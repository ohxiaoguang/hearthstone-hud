"""Log-only arena state. Formats studied in hs-decktracker-linux decks.py (MIT).
Candidates are a preview; only confirmed round records affect draft picks.
"""
from collections import Counter, OrderedDict
from datetime import datetime
import re
from .arena_ratings import ArenaRatings
from .deckstring import decode

DECK=re.compile(r'Draft Deck ID: (\d+), Hero Card = (\S+)')
NEW=re.compile(r'Got new draft deck with ID: (\d+)')
REDRAFT=re.compile(r'Got new redraft deck with ID: (\d+)')
CARD=re.compile(r'Draft deck contains card (\S+)')
PICK=re.compile(r'Client chooses: .* \((\S+)\)$')
MODE=re.compile(r'SetDraftMode - (\S+)')
DECK_ID=re.compile(r'# Deck ID: (\d+)')
HERO_CLASSES=dict(zip(range(1,12),('WARRIOR','SHAMAN','ROGUE','PALADIN','HUNTER','DRUID','WARLOCK','MAGE','PRIEST','DEMONHUNTER','DEATHKNIGHT')))
CLASS_NAMES=dict(zip(HERO_CLASSES.values(),('战士','萨满','潜行者','圣骑士','猎人','德鲁伊','术士','法师','牧师','恶魔猎手','死亡骑士')))
CARD_TYPES={'MINION','SPELL','WEAPON','LOCATION'}

class Arena:
    def __init__(self,cards,ratings=None,manual=None,clock=None):
        self.cards=cards;self.ratings=ratings or ArenaRatings();self.clock=clock or datetime.now
        self.manual={}
        for record in (manual or [])[-256:]:
            try:
                key=(str(record['session']),str(record['deck_id']),str(record['phase']),int(record['round']))
                if 1<=key[3]<=100 and isinstance(record['card_id'],str):self.manual[key]=dict(card_id=record['card_id'],confirmed_at=record.get('confirmed_at',''))
            except (KeyError,TypeError,ValueError):pass
        self.session='';self.reset_stream()

    def reset_stream(self):
        self.identity_source=''
        self.exact_phase=''
        self.deck_id='';self.hero='';self.mode='';self.phase='';self.redraft_id='';self.fresh_draft=False
        self.listed=[];self.listing=False;self.raw_choices={};self.phase_decks={}
        self.offer=[];self.offer_round=None;self.seen=OrderedDict();self.errors=0
        self.exact_dbf={};self.exact_history=[];self.runs=[];self.deck_runs=[];self.known_ids=set();self.pending=None
        self.last_error=''

    def set_session(self,session):
        if session!=self.session:self.session=session;self.reset_stream()

    def _new(self,deck_id,ts,mode='DRAFTING',record=True):
        self.identity_source='log'
        self.exact_phase=''
        self.deck_id=deck_id;self.hero='';self.mode=mode;self.phase='draft:'+deck_id;self.redraft_id='';self.fresh_draft=mode=='DRAFTING';self.last_error=''
        self.offer=[];self.offer_round=None;self.listed=[];self.exact_dbf={}
        self.raw_choices.setdefault(self.phase,[]);self.phase_decks[self.phase]=deck_id
        self.known_ids.add(deck_id)
        if record:self.runs.append((ts,deck_id));self.runs=self.runs[-64:]

    @property
    def drafting(self):return self.mode in ('DRAFTING','REDRAFTING')

    def attach_memory_deck(self,deck_id,hero,mode):
        """Identity proof only; never inserts memory cards into raw_choices."""
        if (not self.deck_id or (not self.drafting and self.deck_id!=deck_id)) and deck_id.isdecimal() and mode in ('DRAFTING','REDRAFTING'):
            self._new(deck_id,self.clock(),mode,record=True)
            self.fresh_draft=False
            self.identity_source='memory'
            self.hero=hero

    def _kind(self,cid):
        typ=self.cards.by_id.get(cid,{}).get('type')
        if typ=='HERO_POWER' or (cid.startswith('HERO_') and 'bp' in cid.lower()):return 'power'
        if typ=='HERO' or cid.startswith('HERO_'):return 'hero'
        return 'card' if typ in CARD_TYPES else 'unknown'

    def feed(self,ts,text):
        text=text.strip();key=(ts.isoformat(),text)
        # Choice events at different timestamps are distinct, including same ID.
        if key in self.seen:return
        self.seen[key]=None
        if len(self.seen)>8192:self.seen.popitem(last=False)
        if m:=DECK.search(text):
            if self.deck_id!=m[1]:self._new(m[1],ts,mode='UNKNOWN')
            self.hero=m[2];self.identity_source='log';self.listed=[];self.listing=True;return
        if self.listing and (m:=CARD.search(text)):
            if len(self.listed)<100:self.listed.append(m[1])
            return
        self.listing=False
        if m:=NEW.search(text):
            self._new(m[1],ts)
        elif m:=REDRAFT.search(text):
            # Temporary redraft ID is not the base deck ID used by Finished Editing.
            if not self.deck_id:self.last_error='重选日志缺少原竞技场 ID';return
            self.redraft_id=m[1];self.phase='redraft:'+m[1];self.mode='REDRAFTING'
            self.phase_decks[self.phase]=self.deck_id;self.raw_choices.setdefault(self.phase,[])
            self.offer=[];self.offer_round=None
        elif m:=MODE.search(text):
            self.mode=m[1]
            if self.mode=='REDRAFTING':
                self.phase='';self.redraft_id='';self.offer=[];self.offer_round=None
        elif self.drafting and self.deck_id and (m:=PICK.search(text)):
            cid=m[1];kind=self._kind(cid)
            if kind=='hero':self.hero=cid;self.identity_source='log';return
            if kind=='power':return
            if not self.phase:self.last_error='等待重选 ID，未将选择追加到原牌组';return
            choices=self.raw_choices.setdefault(self.phase,[])
            if len(choices)<100:choices.append((ts,cid))
            # Log confirmation resolves or overrides a manual record at its ordinal.
            if self.offer_round and self.offer_round in self._automatic(self.phase):
                self.offer=[];self.offer_round=None

    def _manual_phase(self,phase):
        deck_id=self.phase_decks.get(phase,self.deck_id)
        return {k[3]:r for k,r in self.manual.items() if k[:3]==(self.session,deck_id,phase) and self._kind(r['card_id'])=='card'}

    def _automatic_entries(self,phase):
        # Client chooses has no explicit ordinal. Source timestamps distinguish a
        # delayed confirmation from the *next* round after a manual fallback.
        manual=self._manual_phase(phase);result={};cursor=0
        for ts,cid in self.raw_choices.get(phase,[]):
            if self._kind(cid)!='card':continue
            ordinal=cursor+1
            while ordinal in manual:
                try:confirmed=datetime.fromisoformat(manual[ordinal]['confirmed_at'])
                except (TypeError,ValueError):break
                if ts<=confirmed:break
                ordinal+=1
            if ordinal>(30 if phase.startswith('draft:') else 100):break
            result[ordinal]=(cid,ts);cursor=ordinal
        return result

    def _automatic(self,phase):
        return {ordinal:cid for ordinal,(cid,_) in self._automatic_entries(phase).items()}

    def records(self,phase=None):
        phase=self.phase if phase is None else phase
        auto=self._automatic(phase);manual=self._manual_phase(phase);result=[]
        for ordinal in sorted(auto.keys()|manual.keys()):
            logged=auto.get(ordinal);fallback=manual.get(ordinal,{}).get('card_id')
            result.append(dict(card_id=logged or fallback,round=ordinal,source='log' if logged else 'manual',
                               reconciled=bool(logged and fallback),conflict=bool(logged and fallback and logged!=fallback)))
        return result

    def next_round(self):return max((p['round'] for p in self.records()),default=0)+1

    def timed_records(self,phase=None):
        """Same ordinals as records(), each with the confirmation timestamp.

        Recovery needs the time to tell a *historical* pick that the log only
        delivered late apart from a pick made after the memory snapshot.
        """
        phase=self.phase if phase is None else phase
        auto=self._automatic_entries(phase);manual=self._manual_phase(phase);out=[]
        for ordinal in sorted(auto.keys()|manual.keys()):
            logged=auto.get(ordinal);fallback=manual.get(ordinal,{})
            if logged:cid,ts=logged
            else:
                cid=fallback.get('card_id');ts=None
                try:ts=datetime.fromisoformat(fallback.get('confirmed_at',''))
                except (TypeError,ValueError):pass
            manual_id=fallback.get('card_id')
            out.append((ts,dict(card_id=cid or manual_id,round=ordinal,source='log' if logged else 'manual',
                                reconciled=bool(logged and manual_id),conflict=bool(logged and manual_id and cid!=manual_id))))
        return out

    def context(self):return dict(deck_id=self.deck_id,phase=self.phase,round=self.next_round())

    def _check_context(self,deck_id,phase):
        if not self.drafting or not self.deck_id or not self.phase:raise ValueError('先等待 Arena.log 识别竞技场及选牌阶段')
        if deck_id!=self.deck_id or phase!=self.phase:raise ValueError('竞技场或选牌阶段已变化，请刷新后重试')

    def set_offer(self,deck_id,phase,ordinal,ids):
        self._check_context(deck_id,phase)
        if type(ordinal) is not int or ordinal!=self.next_round():raise ValueError('选牌轮次已变化，请重新录入')
        if not isinstance(ids,list) or len(ids)!=3 or any(not isinstance(cid,str) or self._kind(cid)!='card' for cid in ids):raise ValueError('请选择三张已知卡牌；英雄和英雄技能不能作为卡牌候选')
        self.offer=list(ids);self.offer_round=ordinal

    def clear_offer(self):self.offer=[];self.offer_round=None

    def manual_pick(self,deck_id,phase,ordinal,cid):
        self._check_context(deck_id,phase)
        if type(ordinal) is not int or not 1<=ordinal<=30:raise ValueError('补录序号必须为 1–30')
        if not isinstance(cid,str) or self._kind(cid)!='card':raise ValueError('请选择已知卡牌，不能补录英雄或英雄技能')
        key=(self.session,deck_id,phase,ordinal);auto=self._automatic(phase)
        if ordinal in auto:
            if auto[ordinal]!=cid:raise ValueError('该轮已有不同的日志确认，不能用手动记录覆盖')
            return  # Idempotent response to a delayed QAM action.
        if ordinal>self.next_round():raise ValueError('不能跳过选牌序号')
        self.manual[key]=dict(card_id=cid,confirmed_at=self.clock().isoformat())
        if len(self.manual)>256:self.manual.pop(next(iter(self.manual)))
        self.clear_offer()

    def export_manual(self):
        return [dict(zip(('session','deck_id','phase','round'),key),**record) for key,record in self.manual.items()]

    def reset_decks(self):
        self.exact_phase=''
        self.pending=None;self.exact_history=[];self.exact_dbf={};self.deck_runs=[]
        self.known_ids={deck_id for _,deck_id in self.runs}

    def feed_decks(self,ts,text):
        text=text.strip()
        if text.startswith(('Starting Arena Game With Deck:','Finished Editing Deck:','Finding Game With Deck:')):
            self.pending=dict(header=text,deck_id='');return
        if self.pending is None:return
        if m:=DECK_ID.match(text):self.pending['deck_id']=m[1];return
        if text.startswith('#'):return
        pending=self.pending;self.pending=None
        if not text.startswith('AAE'):return
        deck_id=pending['deck_id'];starting=pending['header'].startswith('Starting Arena')
        if not deck_id or (not starting and (not pending['header'].startswith('Finished Editing') or deck_id not in self.known_ids)):return
        try:
            definition=decode(text)
            if sum(definition.cards.values())!=30 or any(type(n) is not int or not 0<n<=30 for n in definition.cards.values()):raise ValueError('竞技场最终牌组必须为 30 张')
        except (ValueError,IndexError) as exc:
            self.errors+=1;self.last_error=str(exc);return
        if starting:
            self.known_ids.add(deck_id);self.deck_runs.append((ts,deck_id));self.deck_runs=self.deck_runs[-64:]
            if not self.deck_id:self._new(deck_id,ts,'ACTIVE_DRAFT_DECK',record=False)
        self.last_error=''
        self.exact_history.append((ts,deck_id,dict(definition.cards)));self.exact_history=self.exact_history[-64:]
        if deck_id==self.deck_id:
            self.exact_phase=self.phase
            self.exact_dbf=dict(definition.cards)
            if definition.heroes:
                hero=self.cards.id_for_dbf(definition.heroes[0])
                if not hero.startswith('dbf:'):self.hero=hero

    def definition_for_game(self,start):
        runs=[(t,i) for t,i in self.runs+self.deck_runs if t<=start]
        if not runs:return {}
        _,deck_id=max(runs,key=lambda r:r[0])
        eligible=[(t,d) for t,i,d in self.exact_history if i==deck_id and t<=start]
        return dict(max(eligible,key=lambda r:r[0])[1]) if eligible else {}

    def class_id(self):
        cls=self.cards.by_id.get(self.hero,{}).get('cardClass','')
        m=re.match(r'^HERO_(\d{2})',self.hero)
        return cls or (HERO_CLASSES.get(int(m[1]),'') if m else '')

    def rated(self,cid):
        rating=self.ratings.get(self.class_id(),cid)
        return dict(self.cards.info(cid),rating=rating,score=rating['score'] if rating else None,
                    rating_label=str(rating['score']) if rating else '暂无评分',tier=rating['tier'] if rating else '',best=False)

    def search(self,query):
        if not isinstance(query,str) or len(query)>100:raise ValueError('搜索文字过长')
        q=query.strip().casefold()
        if not q:return []
        ids=[cid for cid,c in self.cards.by_id.items() if self._kind(cid)=='card' and (q in cid.casefold() or q in c.get('name','').casefold())]
        ids.sort(key=lambda cid:(cid.casefold()!=q,self.cards.by_id[cid].get('name','')!=query,cid))
        return [self.rated(cid) for cid in ids[:12]]

    def view(self):
        cls=self.class_id();rows=[]
        draft_phase='draft:'+self.deck_id
        original=self.records(draft_phase)
        if self.exact_dbf:
            final=Counter()
            for dbf,n in self.exact_dbf.items():final[self.cards.id_for_dbf(dbf)]+=n
            # Preserve chosen order where cards survived; append unobserved/package copies.
            history=original+[p for phase,deck in self.phase_decks.items() if deck==self.deck_id and phase.startswith('redraft:') for p in self.records(phase)]
            for p in history:
                if final[p['card_id']]>0:rows.append(dict(self.rated(p['card_id']),**p));final[p['card_id']]-=1
            for cid in final.elements():rows.append(dict(self.rated(cid),source='final_deck',round=0))
        else:
            rows=[dict(self.rated(p['card_id']),**p) for p in original]
            if not rows:rows=[dict(self.rated(cid),source='listing_unconfirmed',round=0) for cid in self.listed if self._kind(cid)=='card']
        redraft=[dict(self.rated(p['card_id']),**p) for p in self.records() ] if self.mode=='REDRAFTING' else []
        offer=[self.rated(cid) for cid in self.offer]
        scores=[r['score'] for r in offer if r['score'] is not None]
        for row in offer:row['best']=bool(scores) and row['score']==max(scores)
        overflow=max(0,sum(self._kind(cid)=='card' for _,cid in self.raw_choices.get(draft_phase,[]))-30)
        unresolved=sum(self._kind(cid)=='unknown' for phase,values in self.raw_choices.items() if self.phase_decks.get(phase)==self.deck_id for _,cid in values)
        return dict(**self.context(),mode=self.mode,hero=self.hero,identity_source=self.identity_source,cls=cls,class_name=CLASS_NAMES.get(cls,'职业未识别'),
            drafting=self.drafting,count=len(rows),count_exact=bool(self.exact_dbf) or (self.fresh_draft and not unresolved and not overflow),
            picks=rows,redraft_picks=redraft,candidates=offer,offer_round=self.offer_round,
            exact=bool(self.exact_dbf),exact_phase=self.exact_phase,unresolved_choices=unresolved,overflow_choices=overflow,ratings=self.ratings.metadata(),
            conflicts=sum(p.get('conflict',False) for phase in self.raw_choices if self.phase_decks.get(phase)==self.deck_id for p in self.records(phase)),
            error=self.last_error,parse_errors=self.errors)
