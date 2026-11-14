"""Reconcile whole-deck snapshots with confirmed events without inventing order.

Memory rows are an unordered multiset. Log records remain owned by Arena.
Only deltas observed after an anchor can cover later log events, so repeated
Card IDs never consume an unrelated copy from the initial recovered history.

The anchor is the lower bound of the stable memory read: a record stamped at or
before it is a pick the snapshot already contains (the log may have delivered it
late), so it consumes a snapshot copy. A record stamped after the read's *upper*
bound is a later pick and is counted separately, even when the Card ID repeats.
A record stamped inside the read window, or one without a trustworthy timestamp,
cannot be ordered against the snapshot: it is never guessed either way, it is
counted separately and flagged so the count stays visibly inexact. Every early
exit records a reason code so the HUD can say why nothing was recovered.
"""
from collections import Counter
import time
from .arena_memory import DECK_UNREADABLE
from .images import valid_id

REASONS={
    'idle':'尚未读取到选牌画面',
    'no_state':'本次未取得内存快照（未运行/未就绪/读取失败）',
    'mode':'当前不是竞技场选牌模式',
    'slot':'当前不是卡牌选择槽位',
    'no_deck':'DraftManager 没有可用的 DraftDeck 对象',
    'no_deck_id':'内存牌组没有有效的竞技场 ID',
    'deck_overflow':'内存牌组数量异常（超过 40 张），不采用',
    'deck_unreadable':'内存牌组结构无法解析，本局不采用牌组数据',
    'deck_empty':'内存牌组尚未包含已选卡牌',
    'deck_invalid':'内存牌组含英雄/英雄技能或非法卡牌 ID',
    'id_mismatch':'内存竞技场 ID 与日志竞技场 ID 不一致',
    'waiting_second_read':'等待第二个一致的内存快照',
    'anchored':'快照已建立，等待合并',
    'recovered':'已从内存牌组恢复历史牌',
    'exact_deck':'已有当前阶段的最终牌组，无需内存恢复',
    'log_rewind':'日志记录被重写，等待重新核对',
    'no_snapshot':'尚未建立快照',
}


class ArenaRecovery:
    def __init__(self,clock=None):
        self.clock=clock or time.time
        self.reset()

    def reset(self):
        self.context=None;self.candidate=None;self.observed=0;self.snapshot=None
        self.covered=set();self.known=set();self.pending={};self.credit=Counter()
        self.note='';self.hero='';self.anchor=None;self.settled=None
        self.reason='idle';self.parsed=0;self.slots=0;self.deck_object=False;self.merged=0;self.recovered=0
        self.uncertain=set();self.deck_reason='';self.deck_note=''

    @staticmethod
    def records(arena):
        return arena.timed_records('draft:'+arena.deck_id)

    @staticmethod
    def key(record):
        # A manual fallback replaced by a log line keeps round and card: the
        # mapping stays valid, and only a real rewind invalidates it.
        return (record['round'],record['card_id'])

    def observe(self,arena,state,diagnostic):
        reason=self._observe(arena,state,diagnostic)
        if state is not None:
            self.parsed=len(state.deck);self.slots=state.deck_slots;self.deck_object=state.deck_object
            self.deck_reason=state.deck_reason;self.deck_note=state.deck_note
        elif reason=='no_state':
            self.parsed=0;self.slots=0;self.deck_object=False;self.deck_reason='';self.deck_note=''
        if reason:self.reason=reason

    def _observe(self,arena,state,diagnostic):
        if state is None:
            self.credit.clear();return 'no_state'
        if state.mode not in ('DRAFTING','REDRAFTING'):return 'mode'
        if state.slot!='CARD':return 'slot'
        if not state.deck_object:return 'no_deck'
        if not state.deck_id or not state.deck_id.isdecimal():return 'no_deck_id'
        if state.deck_reason=='deck_overflow' or len(state.deck)>40:return 'deck_overflow'
        if not state.deck:return 'deck_unreadable' if state.deck_reason in DECK_UNREADABLE else 'deck_empty'
        if any(not valid_id(cid) or arena._kind(cid) in ('hero','power') for cid in state.deck):return 'deck_invalid'
        if arena.deck_id and arena.deck_id!=state.deck_id:return 'id_mismatch'
        identity=(diagnostic.get('pid'),diagnostic.get('process_instance'),arena.session,state.deck_id,state.mode,arena.phase,id(arena.cards.by_id))
        if identity!=self.context:
            self.reset();self.context=identity
        observed=diagnostic.get('observed_at',0)
        if observed<=self.observed:return self.reason or 'waiting_second_read'
        self.observed=observed;self.hero=state.hero
        cards=Counter(state.deck)
        fingerprint=tuple(sorted(cards.items()))
        # Two independent polls, not two renders of one snapshot.
        if self.candidate!=fingerprint:
            self.candidate=fingerprint;return 'waiting_second_read'
        records=self.records(arena)
        # Lower and upper bounds of the deck read. The anchor is the lower bound,
        # never a log timestamp: a pick after the read must not borrow a copy. A
        # record inside (anchor, settled] is unordered and never guessed.
        base=diagnostic.get('observed_start') or diagnostic.get('observed_wall') or self.clock()
        settled=max(base,diagnostic.get('observed_wall') or base)
        if self.snapshot is None:
            self.snapshot=cards;self.known=set();self.covered=set();self.pending={};self.credit=Counter();self.uncertain=set()
            self.anchor=base;self.settled=settled
            available=Counter(cards)
            for ts,record in records:
                key=self.key(record);cid=record['card_id'];self.known.add(key)
                if self._historical(ts) and available[cid]:
                    self.covered.add(key);available[cid]-=1
                elif state.mode!='REDRAFTING':
                    self.pending[key]=cid
                    if self._unordered(ts):self.uncertain.add(key)
            return 'anchored'
        if state.mode=='REDRAFTING' or any(cards[cid]<n for cid,n in self.snapshot.items()):
            # Redraft replaces a multiset; operations must not append to it.
            self.snapshot=cards;self.covered=set();self.pending={};self.credit=Counter();self.uncertain=set()
            self.anchor=base;self.settled=settled
            available=Counter(cards)
            for ts,record in records:
                key=self.key(record);cid=record['card_id'];self.known.add(key)
                if self._historical(ts) and available[cid]:self.covered.add(key);available[cid]-=1
                elif state.mode!='REDRAFTING':
                    self.pending[key]=cid
                    if self._unordered(ts):self.uncertain.add(key)
            self.note='重选历史按当前牌组恢复，不追加重选操作' if state.mode=='REDRAFTING' else '内存牌组发生替换，已重新核对历史'
            return None
        if cards!=self.snapshot:
            delta=cards-self.snapshot
            for key,cid in list(self.pending.items()):
                if delta[cid]:delta[cid]-=1;self.covered.add(key);del self.pending[key];self.uncertain.discard(key)
            self.snapshot=cards;self.credit+=delta
            return None
        return 'anchored'

    def _historical(self,ts):
        return ts is not None and self.anchor is not None and ts.timestamp()<=self.anchor

    def _unordered(self,ts):
        """No trustworthy timestamp, or one inside the read window."""
        if ts is None:return True
        if self.anchor is None:return False
        return self.anchor<ts.timestamp()<=(self.settled if self.settled is not None else self.anchor)

    def merge(self,arena,base):
        base['history_picks']=[];base['recovery_source']='logs'
        self.merged+=1;self.recovered=0
        if self.snapshot is None:
            # Keep the observe() reason: it says exactly why nothing was anchored.
            return base
        if not self.context:return base
        if base['exact'] and (self.context[4]!='REDRAFTING' or (arena.mode=='REDRAFTING' and base.get('exact_phase')==arena.phase)):
            self.reason='exact_deck';return base
        if arena.deck_id!=self.context[3]:
            self.reset();self.reason='id_mismatch';return base
        timed=self.records(arena)
        if not self.known.issubset({self.key(record) for _,record in timed}):
            self.reset();self.reason='log_rewind';return base
        remaining=Counter(self.snapshot);covered=set();pending={};credit=Counter(self.credit)
        uncertain=set(self.uncertain);confirmed=[]
        for ts,record in timed:
            key=self.key(record);cid=record['card_id'];fresh=key not in self.known
            self.known.add(key)
            row=dict(arena.rated(cid),**record)
            if not fresh:
                if key in self.pending:pending[key]=cid;confirmed.append(row)
                elif key not in self.covered:continue
                elif remaining[cid]>0:remaining[cid]-=1;covered.add(key);confirmed.append(row)
                else:pending[key]=cid;confirmed.append(row)
                continue
            if self.context[4]=='REDRAFTING':continue
            # At or before the anchor: a pick the snapshot already contains, even
            # if the log only delivered it now.
            if self._historical(ts) and remaining[cid]>0:
                remaining[cid]-=1;covered.add(key);confirmed.append(row)
            elif self._unordered(ts):
                # Inside the read window: counting it as history could hide a new
                # pick, so keep it separate and keep the count visibly inexact.
                pending[key]=cid;uncertain.add(key);confirmed.append(row)
            elif credit[cid]>0:
                credit[cid]-=1;covered.add(key)
                if remaining[cid]>0:remaining[cid]-=1
                confirmed.append(row)
            else:pending[key]=cid;confirmed.append(row)
        self.covered,self.pending,self.credit=covered,pending,credit
        self.uncertain=uncertain
        history=[dict(arena.rated(cid),source='memory_history',round=0,order_known=False) for cid in sorted(remaining) for _ in range(remaining[cid])]
        self.recovered=len(history)
        base.update(picks=confirmed,history_picks=history,count=len(confirmed)+len(history),
                    exact=False,count_exact=not self.pending and not self.uncertain,recovery_source='memory_and_logs',
                    recovery_note=self.note or ('部分日志落在快照读取窗口内或缺少时间戳，已单独计数但份数待确认'
                                                if self.uncertain else '历史牌组来自只读内存，选择顺序未知'))
        self.reason='recovered'
        return base

    def status(self):
        """Read-only evidence for the diagnostic panel.

        merge_executed only says merge() ran; executed means a snapshot existed
        and history was actually produced, so the two cannot disagree.
        """
        return dict(merge_executed=self.merged>0,executed=bool(self.snapshot) and self.recovered>0,
                    snapshot=self.snapshot is not None,recovered=self.recovered,
                    pending=len(self.pending),covered=len(self.covered),uncertain=len(self.uncertain),slots=self.slots,
                    deck_object=self.deck_object,deck_parsed=self.parsed,
                    deck_reason=self.deck_reason,deck_note=self.deck_note,
                    snapshot_size=sum(self.snapshot.values()) if self.snapshot else 0,
                    read_start=self.anchor or 0,read_settled=self.settled or 0,
                    reason=self.reason,reason_text=REASONS.get(self.reason,self.reason))
