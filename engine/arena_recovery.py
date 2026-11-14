"""Reconcile whole-deck snapshots with confirmed events without inventing order.

Memory rows are an unordered multiset. Log records remain owned by Arena.
Only deltas observed after an anchor can cover later log events, so repeated
Card IDs never consume an unrelated copy from the initial recovered history.
"""
from collections import Counter
from .images import valid_id


class ArenaRecovery:
    def __init__(self):
        self.reset()

    def reset(self):
        self.context=None;self.candidate=None;self.observed=0;self.snapshot=None
        self.covered=set();self.known=set();self.pending={};self.credit=Counter()
        self.note='';self.hero=''

    @staticmethod
    def records(arena):
        return arena.records('draft:'+arena.deck_id)

    @staticmethod
    def key(record):
        return (record['round'],record['card_id'],record['source'])

    def observe(self,arena,state,diagnostic):
        if state is None:
            self.credit.clear();return
        if not state or state.mode not in ('DRAFTING','REDRAFTING') or state.slot!='CARD':return
        if not state.deck_id or not state.deck_id.isdecimal() or not 0<len(state.deck)<=30:return
        if any(not valid_id(cid) or arena._kind(cid) in ('hero','power') for cid in state.deck):return
        if arena.deck_id and arena.deck_id!=state.deck_id:return
        identity=(diagnostic.get('pid'),diagnostic.get('process_instance'),arena.session,state.deck_id,state.mode,arena.phase,id(arena.cards.by_id))
        if identity!=self.context:
            self.reset();self.context=identity
        observed=diagnostic.get('observed_at',0)
        if observed<=self.observed:return
        self.observed=observed;self.hero=state.hero
        cards=Counter(state.deck)
        fingerprint=tuple(sorted(cards.items()))
        # Two independent polls, not two renders of one snapshot.
        if self.candidate!=fingerprint:
            self.candidate=fingerprint;return
        records=self.records(arena)
        if self.snapshot is None:
            self.snapshot=cards
            available=Counter(cards)
            for record in records:
                key=self.key(record);cid=record['card_id'];self.known.add(key)
                if available[cid]:self.covered.add(key);available[cid]-=1
                elif state.mode!='REDRAFTING':self.pending[key]=cid
        elif state.mode=='REDRAFTING' or any(cards[cid]<n for cid,n in self.snapshot.items()):
            # Redraft replaces a multiset; operations must not append to it.
            self.snapshot=cards;self.covered=set();self.pending={};self.credit=Counter()
            available=Counter(cards)
            for record in records:
                key=self.key(record);cid=record['card_id'];self.known.add(key)
                if available[cid]:self.covered.add(key);available[cid]-=1
            self.note='重选历史按当前牌组恢复，不追加重选操作' if state.mode=='REDRAFTING' else '内存牌组发生替换，已重新核对历史'
        elif cards!=self.snapshot:
            delta=cards-self.snapshot
            for key,cid in list(self.pending.items()):
                if delta[cid]:delta[cid]-=1;self.covered.add(key);del self.pending[key]
            self.snapshot=cards;self.credit+=delta

    def merge(self,arena,base):
        base['history_picks']=[];base['recovery_source']='logs'
        if self.snapshot is None or not self.context:return base
        if base['exact'] and (self.context[4]!='REDRAFTING' or (arena.mode=='REDRAFTING' and base.get('exact_phase')==arena.phase)):return base
        if arena.deck_id!=self.context[3]:return base
        records=self.records(arena)
        # Rewinds/reconciliation can replace a record at an existing ordinal.
        keys={self.key(r) for r in records}
        if not self.known.issubset(keys):
            self.reset();return base
        for record in records:
            key=self.key(record);cid=record['card_id']
            if key in self.known:continue
            self.known.add(key)
            if self.context[4]=='REDRAFTING':continue
            if self.credit[cid]>0:
                self.credit[cid]-=1;self.covered.add(key)
            else:self.pending[key]=cid
        available=Counter(self.snapshot);confirmed=[]
        for record in records:
            key=self.key(record);cid=record['card_id']
            if key in self.covered and available[cid]>0:
                available[cid]-=1;confirmed.append(dict(arena.rated(cid),**record))
            elif key in self.pending:
                confirmed.append(dict(arena.rated(cid),**record))
        history=[dict(arena.rated(cid),source='memory_history',round=0,order_known=False) for cid in sorted(available) for _ in range(available[cid])]
        base.update(picks=confirmed,history_picks=history,count=len(confirmed)+len(history),
                    exact=False,count_exact=not self.pending,recovery_source='memory_and_logs',recovery_note=self.note or '历史牌组来自只读内存，选择顺序未知')
        return base
