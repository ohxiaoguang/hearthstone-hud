# Adapted from justfaked/hs-decktracker-linux@649534be99f35cb499ed2fae371625bd04b95b1d
# Copyright (c) 2026 justfaked. MIT: licenses/hs-decktracker-linux-MIT.txt.
"""Bounded DraftDisplay/DraftManager snapshots; never confirms logged picks."""
from dataclasses import dataclass, field
from .mono_memory import T_CLASS,T_GENERICINST,T_OBJECT,T_VALUETYPE,T_I4,T_I8,T_BOOLEAN,Mono, Obj, Process, MemoryReadError, UnsupportedLayout, MonoMissing, NotReady, Cancelled, MissingField
from .proton import discover_process
from .images import valid_id

DRAFT_MODES=('INVALID','NO_ACTIVE_DRAFT','DRAFTING','ACTIVE_DRAFT_DECK','IN_REWARDS','REDRAFTING')
SLOT_TYPES=('NONE','CARD','HERO','HERO_POWER')
MAX_DECK_COPIES=40  # 30 picks plus room for a torn/duplicated read; never used as card data.

@dataclass(frozen=True)
class DraftChoice:
    card_id: str
    package: tuple = ()

@dataclass(frozen=True)
class DraftState:
    mode: str
    slot: str
    underground: bool
    choices: tuple
    deck_id: str = ''
    hero: str = ''
    deck: tuple = ()
    wins: int = 0
    losses: int = 0
    # Read-only evidence about the deck object itself; never card data.
    # The reader always sets these explicitly; the defaults only describe a
    # hand-built state, so "assume present" keeps synthetic states usable.
    deck_object: bool = True
    deck_slots: int = 0
    deck_reason: str = ''


def card_id(value,empty=False):
    if value in (None,'') and empty:return ''
    if not isinstance(value,str) or not valid_id(value):raise UnsupportedLayout('invalid managed Card ID')
    return value


def enum(value,items):
    if type(value) is not int or not 0<=value<len(items):raise UnsupportedLayout('unknown draft enum')
    return items[value]


class HearthstoneMemory:
    def __init__(self,stop=None,process_factory=None,finder=None,mono_factory=Mono):
        self.stop=stop;self.factory=process_factory or (lambda pid:Process(pid,stop=stop))
        self.finder=finder or discover_process;self.mono_factory=mono_factory
        self.process=None;self.mono=None;self.identity=None;self.pid=None;self.observed_identity=None

    def close(self):
        process,self.process=self.process,None
        self.mono=None;self.identity=None
        if process is not None:process.close()

    def connect(self):
        found=self.finder();self.pid=found.get('pid') if found.get('found') else None
        if self.pid is None:
            self.close();return False
        identity=(self.pid,found.get('instance',''));self.observed_identity=identity
        if identity!=self.identity or self.mono is None:
            self.close()
            try:
                self.process=self.factory(self.pid)
                # PID reuse while opening must not attach to an unrelated process.
                check=self.finder()
                if not check.get('found') or (check.get('pid'),check.get('instance',''))!=identity:raise ProcessLookupError('game process changed during attach')
                self.mono=self.mono_factory(self.process);self.identity=identity
                self._validate_schema()
            except BaseException:
                self.close();raise
        else:
            self.process.begin_poll();self.process.refresh_maps()
        return True

    def _validate_schema(self):
        refs={T_CLASS,T_GENERICINST,T_OBJECT};enums={T_I4,T_VALUETYPE}
        schemas={
            'DraftDisplay':{'s_instance':(refs,True),'m_currentMode':(enums,False),'m_choices':(refs,False)},
            'DraftManager':{'m_undergroundActive':({T_BOOLEAN},False),
                'm_currentSlotType':(enums,False),'m_currentUndergroundSlotType':(enums,False),
                'm_wins':({T_I4},False),'m_losses':({T_I4},False),'m_undergroundWins':({T_I4},False),'m_undergroundLosses':({T_I4},False),
                'm_draftDeck':(refs,False),'m_undergroundDraftDeck':(refs,False)},
            'Hearthstone.HearthstoneJobs':{'s_dependencyBuilder':(refs,True)}}
        for name,expected in schemas.items():
            fields=self.mono.fields(self.mono.find_class(name))
            for field,(types,static) in expected.items():
                actual=fields.get(field)
                if actual is None or actual.type not in types or actual.static!=static:raise UnsupportedLayout('layout signature mismatch: '+name+'.'+field)

    def _manager(self):
        builders=self.mono.static('Hearthstone.HearthstoneJobs','s_dependencyBuilder')
        if builders is None:raise NotReady('service builder not initialized')
        objects=builders.list_objects(64)
        if not objects:raise NotReady('service builder empty')
        entries=objects[0]['m_serviceLocator']['m_services']['_entries']
        if entries is None:raise NotReady('service registry not initialized')
        for i in range(entries.length):
            addr=entries.element_addr(i,24)
            if self.process.i32(addr)<0:continue
            ref=self.process.ptr(addr+16)
            if not ref:continue
            info=Obj(self.mono,ref)
            if info['<ServiceTypeName>k__BackingField']=='DraftManager':
                manager=info['<Service>k__BackingField']
                if manager is None:raise NotReady('DraftManager not initialized')
                if manager.class_name!='DraftManager':raise UnsupportedLayout('wrong service object type')
                return manager
        raise NotReady('DraftManager service unavailable')

    def _deck_cards(self,deck):
        """Deck copies in slot order: List<m_slots>, each with m_cardId and m_count.

        m_count is the per-premium-variant copy list in the shipped layout
        (upstream sums it); a plain int is accepted and reported. Nothing is
        synthesised: an unreadable slot stops the read with a reason code.
        """
        self.deck_meta=dict(slots=0,reason='')
        try:
            slots=deck['m_slots']
        except MissingField:
            self.deck_meta['reason']='no_slots_field';return []
        if slots is None:
            self.deck_meta['reason']='no_slots_null';return []
        entries=slots.list_objects(100);self.deck_meta['slots']=len(entries)
        cards=[];int_counts=0
        for entry in entries:
            cid=entry.get('m_cardId')
            if cid is None:
                self.deck_meta['reason']='slot_without_card_id';return []
            if not isinstance(cid,str) or not valid_id(cid):
                self.deck_meta['reason']='slot_invalid_card_id';return []
            counts=entry.get('m_count')
            if counts is None:copies=[]
            elif type(counts) is int:copies=[counts];int_counts+=1
            else:
                try:copies=counts.list_ints(16)
                except UnsupportedLayout:
                    self.deck_meta['reason']='count_layout';return []
            if any(type(n) is not int or not 0<=n<=30 for n in copies):
                self.deck_meta['reason']='count_range';return []
            total=sum(copies)
            if len(cards)+total>MAX_DECK_COPIES:
                self.deck_meta['reason']='deck_overflow';return []
            cards.extend([cid]*total)
        if int_counts:self.deck_meta['reason']='int_count'
        elif not cards:self.deck_meta['reason']='empty'
        return cards

    def draft_state(self):
        display=self.mono.static('DraftDisplay','s_instance')
        if display is None:return None
        if display.class_name!='DraftDisplay':raise UnsupportedLayout('wrong DraftDisplay instance')
        mode=enum(display['m_currentMode'],DRAFT_MODES)
        if mode not in ('DRAFTING','REDRAFTING'):return None
        manager=self._manager()
        underground=manager['m_undergroundActive']
        if type(underground) is not bool:raise UnsupportedLayout('invalid underground flag')
        prefix='m_currentUnderground' if underground else 'm_current'
        slot=enum(manager[prefix+'SlotType'],SLOT_TYPES)
        options=display['m_choices'];choices=[]
        for choice in options.list_objects(3) if options else []:
            package=choice.get('m_packageCardIds')
            choices.append(DraftChoice(card_id(choice['m_cardID']),tuple(card_id(c) for c in package.list_strings(30)) if package else ()))
        # A torn/partial update must not publish one or two old candidates.
        if len(choices)!=3:choices=[]
        wins=manager['m_undergroundWins' if underground else 'm_wins']
        losses=manager['m_undergroundLosses' if underground else 'm_losses']
        if type(wins) is not int or type(losses) is not int or not 0<=wins<=50 or not 0<=losses<=20:raise UnsupportedLayout('implausible arena record')
        deck=manager['m_undergroundDraftDeck' if underground else 'm_draftDeck']
        deck_id='';hero='';cards=[];slots=0;reason='no_deck_object'
        if deck is not None:
            number=deck.get('ID')
            if type(number) is not int or not 0<=number<2**63:raise UnsupportedLayout('invalid deck ID')
            deck_id=str(number) if number else '';hero=card_id(deck.get('<HeroCardID>k__BackingField'),True)
            self.deck_meta=dict(slots=0,reason='')
            cards=self._deck_cards(deck)
            slots=self.deck_meta['slots'];reason=self.deck_meta['reason']
        # Re-read selection identity to reject concurrent mode/choice transitions.
        check_options=display['m_choices']
        if manager['m_undergroundActive']!=underground or display['m_currentMode']!=DRAFT_MODES.index(mode) or (check_options.addr if check_options else 0)!=(options.addr if options else 0) or manager[prefix+'SlotType']!=SLOT_TYPES.index(slot):
            raise NotReady('draft changed during snapshot')
        current_deck=manager['m_undergroundDraftDeck' if underground else 'm_draftDeck']
        if (current_deck.addr if current_deck else 0)!=(deck.addr if deck else 0):raise NotReady('arena deck changed during snapshot')
        if deck is not None and (deck['ID']!=number or card_id(deck['<HeroCardID>k__BackingField'],True)!=hero):raise NotReady('arena identity changed during snapshot')
        if deck is not None and self._deck_cards(deck)!=cards:raise NotReady('draft deck changed during snapshot')
        if options and choices:
            if [c['m_cardID'] for c in options.list_objects(3)]!=[c.card_id for c in choices]:raise NotReady('choices changed during snapshot')
        return DraftState(mode,slot,underground,tuple(choices),deck_id,hero,tuple(cards),wins,losses,
                          deck is not None,slots,reason)

    def poll(self):
        try:
            if not self.connect():return None,dict(code='not_running',status='Hearthstone 未运行',pid=None,error='')
            state=self.draft_state()
            stage=state.slot if state and state.choices else ''
            code={'HERO':'hero_selection','CARD':'card_selection','HERO_POWER':'hero_power_selection'}.get(stage,'reading')
            message={'hero_selection':'英雄选择识别成功','card_selection':'卡牌选择识别成功','hero_power_selection':'英雄技能选择识别成功'}.get(code,'正在读取；当前无完整候选')
            return state,dict(code=code,status=message,pid=self.pid,error='',profile='Unity 6000.3 x64 / Assembly-CSharp',unity_version='.'.join(map(str,self.mono.version)),process_instance=str(self.identity),
                              deck_object=bool(state and state.deck_object),deck_slots=int(state.deck_slots) if state else 0,
                              deck_parsed=len(state.deck) if state else 0,deck_reason=(state.deck_reason if state else ''))
        except Cancelled:
            self.close();return None,dict(code='disabled',status='内存读取未开启',pid=None,error='')
        except (OSError,MemoryReadError,UnicodeError,KeyError,TypeError,ValueError,AttributeError) as exc:
            code=('permission_denied' if isinstance(exc,PermissionError) else 'not_running' if isinstance(exc,ProcessLookupError) else
                  'mono_missing' if isinstance(exc,MonoMissing) else 'not_ready' if isinstance(exc,NotReady) else
                  'incompatible' if isinstance(exc,(UnsupportedLayout,UnicodeError,KeyError,TypeError,ValueError,AttributeError)) else 'read_error')
            status={'permission_denied':'权限不足；未修改系统权限','not_running':'游戏进程已退出或重启','mono_missing':'找到进程但没有 Mono',
                    'not_ready':'Mono / 选牌对象尚未就绪','incompatible':'Mono 版本或结构不兼容','read_error':'内存读取失败'}[code]
            pid=self.pid;self.close()
            return None,dict(code=code,status=status,pid=pid,error=str(exc)[:300],process_instance=str(self.observed_identity))
