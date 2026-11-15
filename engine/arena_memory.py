# Adapted from justfaked/hs-decktracker-linux@649534be99f35cb499ed2fae371625bd04b95b1d
# Copyright (c) 2026 justfaked. MIT: licenses/hs-decktracker-linux-MIT.txt.
"""Bounded DraftDisplay/DraftManager snapshots; never confirms logged picks."""
from dataclasses import dataclass, field
import time
from .mono_memory import T_CLASS,T_GENERICINST,T_OBJECT,T_VALUETYPE,T_I4,T_I8,T_BOOLEAN,Mono, Obj, Process, MemoryReadError, UnsupportedLayout, MonoMissing, NotReady, Cancelled, MissingField
from . import i18n
from .proton import discover_process
from .images import valid_id

DRAFT_MODES=('INVALID','NO_ACTIVE_DRAFT','DRAFTING','ACTIVE_DRAFT_DECK','IN_REWARDS','REDRAFTING')
SLOT_TYPES=('NONE','CARD','HERO','HERO_POWER')
MAX_DECK_COPIES=40  # 30 picks plus room for a torn/duplicated read; never used as card data.
# A deck read that produced no cards for one of these reasons must not be
# mistaken for "the draft has no picks yet".
DECK_UNREADABLE=('no_slots_field','no_slots_null','slot_layout','slot_without_card_id',
                 'slot_invalid_card_id','no_card_id_field','no_count_field','count_layout',
                 'count_range','deck_overflow','deck_id_invalid')


def wall_clock():
    """The single place the stable-snapshot timestamp comes from."""
    return time.time()

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
    deck_note: str = ''


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
        self.deck_meta=dict(slots=0,reason='no_deck_object',notes=[])
        self.snapshot_start=0;self.snapshot_wall=0

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

    def _note(self,name):
        notes=self.deck_meta.setdefault('notes',[])
        if name not in notes:notes.append(name)

    def _deck_cards(self,deck):
        """Deck copies in slot order: List<m_slots>, each with m_cardId and m_count.

        m_count is the per-premium-variant copy list in the shipped layout
        (upstream sums it); a plain int is accepted and a null list means "no
        copies from this slot", as upstream's ``if counts else []``. Nothing is
        synthesised: any unreadable slot abandons the whole read with a reason,
        so a partial deck can never be published.
        """
        self.deck_meta=dict(slots=0,reason='',notes=[])
        try:
            slots=deck['m_slots']
        except MissingField:
            self.deck_meta['reason']='no_slots_field';return []
        if slots is None:
            self.deck_meta['reason']='no_slots_null';return []
        try:
            entries=slots.list_objects(100)
        except UnsupportedLayout:
            self.deck_meta['reason']='slot_layout';return []
        self.deck_meta['slots']=len(entries)
        cards=[]
        for entry in entries:
            try:
                cid=entry['m_cardId']
            except MissingField:
                self.deck_meta['reason']='no_card_id_field';return []
            if cid is None:
                self.deck_meta['reason']='slot_without_card_id';return []
            if not isinstance(cid,str) or not valid_id(cid):
                self.deck_meta['reason']='slot_invalid_card_id';return []
            try:
                counts=entry['m_count']
            except MissingField:
                self.deck_meta['reason']='no_count_field';return []
            if counts is None:
                copies=[];self._note('null_count')
            elif type(counts) is int:
                copies=[counts];self._note('int_count')
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
        if not cards:self.deck_meta['reason']='empty'
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
        # The deck lives in its own object: a broken deck must not take the three
        # candidates down with it. Only layout problems are contained here; a
        # closed process, permission failure, cancellation or a low-level read
        # error still propagates from the Mono reader.
        deck_id='';hero='';cards=[];meta=dict(slots=0,reason='no_deck_object',notes=[]);number=None;deck_read=False
        start=0;settled=0
        if deck is not None:
            try:
                number=deck.get('ID')
                if type(number) is not int or not 0<=number<2**63:raise UnsupportedLayout('invalid deck ID')
            except UnsupportedLayout:
                deck_id='';hero='';cards=[];meta=dict(slots=0,reason='deck_id_invalid',notes=[])
            else:
                deck_id=str(number) if number else ''
                try:hero=card_id(deck.get('<HeroCardID>k__BackingField'),True)
                except UnsupportedLayout:hero=''
                # Lower bound: taken immediately before the content is read, so a
                # pick already in the deck keeps its timestamp below the window.
                start=wall_clock()
                try:
                    cards=self._deck_cards(deck);meta=self.deck_meta;deck_read=True
                except UnsupportedLayout:
                    cards=[];meta=dict(slots=0,reason='slot_layout',notes=[])
        # Re-read selection identity to reject concurrent mode/choice transitions.
        check_options=display['m_choices']
        if manager['m_undergroundActive']!=underground or display['m_currentMode']!=DRAFT_MODES.index(mode) or (check_options.addr if check_options else 0)!=(options.addr if options else 0) or manager[prefix+'SlotType']!=SLOT_TYPES.index(slot):
            raise NotReady('draft changed during snapshot')
        current_deck=manager['m_undergroundDraftDeck' if underground else 'm_draftDeck']
        if (current_deck.addr if current_deck else 0)!=(deck.addr if deck else 0):raise NotReady('arena deck changed during snapshot')
        if deck is not None and deck_read:
            try:second_hero=card_id(deck.get('<HeroCardID>k__BackingField'),True)
            except UnsupportedLayout:second_hero=hero
            if deck.get('ID')!=number or second_hero!=hero:raise NotReady('arena identity changed during snapshot')
            second=self._deck_cards(deck)
            # The published read owns the diagnostics; the verification read
            # must not replace its reason with its own.
            self.deck_meta=meta
            if second!=cards:raise NotReady('draft deck changed during snapshot')
            # Upper bound of the deck content: after this instant a new pick can
            # only be missing from `cards`. A pick between the bounds may or may
            # not be included, so it is never classified by guesswork.
            settled=wall_clock()
        elif deck is not None:
            settled=start
        if options and choices:
            if [c['m_cardID'] for c in options.list_objects(3)]!=[c.card_id for c in choices]:raise NotReady('choices changed during snapshot')
        self.snapshot_start=start
        self.snapshot_wall=max(start,settled) if deck is not None else 0
        return DraftState(mode,slot,underground,tuple(choices),deck_id,hero,tuple(cards),wins,losses,
                          deck is not None,meta['slots'],meta['reason'],','.join(meta.get('notes') or ()))

    def poll(self):
        try:
            if not self.connect():return None,dict(code='not_running',status=i18n.t('mem.not_running'),pid=None,error='')
            state=self.draft_state()
            stage=state.slot if state and state.choices else ''
            code={'HERO':'hero_selection','CARD':'card_selection','HERO_POWER':'hero_power_selection'}.get(stage,'reading')
            message={'hero_selection':i18n.t('mem.hero'),'card_selection':i18n.t('mem.card'),
                     'hero_power_selection':i18n.t('mem.hero_power')}.get(code,i18n.t('mem.reading'))
            return state,dict(code=code,status=message,pid=self.pid,error='',profile='Unity 6000.3 x64 / Assembly-CSharp',unity_version='.'.join(map(str,self.mono.version)),process_instance=str(self.identity),
                              deck_object=bool(state and state.deck_object),deck_slots=int(state.deck_slots) if state else 0,
                              deck_parsed=len(state.deck) if state else 0,deck_reason=(state.deck_reason if state else ''),
                              deck_note=(state.deck_note if state else ''),observed_start=(self.snapshot_start if state else 0),
                              observed_wall=(self.snapshot_wall if state else 0))
        except Cancelled:
            self.close();return None,dict(code='disabled',status=i18n.t('mem.disabled'),pid=None,error='')
        except (OSError,MemoryReadError,UnicodeError,KeyError,TypeError,ValueError,AttributeError) as exc:
            code=('permission_denied' if isinstance(exc,PermissionError) else 'not_running' if isinstance(exc,ProcessLookupError) else
                  'mono_missing' if isinstance(exc,MonoMissing) else 'not_ready' if isinstance(exc,NotReady) else
                  'incompatible' if isinstance(exc,(UnsupportedLayout,UnicodeError,KeyError,TypeError,ValueError,AttributeError)) else 'read_error')
            status={'permission_denied':i18n.t('mem.permission'),'not_running':i18n.t('mem.exited'),'mono_missing':i18n.t('mem.no_mono'),
                    'not_ready':i18n.t('mem.not_ready'),'incompatible':i18n.t('mem.incompatible'),'read_error':i18n.t('mem.failed')}[code]
            pid=self.pid;self.close()
            return None,dict(code=code,status=status,pid=pid,error=str(exc)[:300],process_instance=str(self.observed_identity))
