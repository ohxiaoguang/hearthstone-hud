"""Evidence-based card views on top of the MIT PowerParser.

Decks.log headers/deck-code format follow hs-decktracker-linux/decks.py.
Never infer an opponent's unknown card identity or use played cards as a deck.
"""
from . import i18n
from collections import Counter, OrderedDict, deque
from datetime import datetime
import re
from .power import (PowerParser, POWER_PREFIX, RE_TAG, RE_FULL_CREATE, RE_FULL_UPDATE,
                    RE_SHOW, RE_CHANGE, RE_GAME_ENTITY, RE_PLAYER, RE_BRACKET_ID)
from .deckstring import decode

LINE = re.compile(r'^[A-Z] (\d\d:\d\d:\d\d\.\d+) (.*)$')


class DeckLog:
    def __init__(self):
        self.pending = False
        self.candidates = []
        self.errors = 0
        self.metadata = {}
        self.header = {}

    def feed(self, ts, payload):
        text = payload.strip()
        if text.startswith(('Finding Game With Deck:', 'Starting Arena Game With Deck:')):
            self.pending = True
            self.header = dict(arena=text.startswith('Starting Arena'))
        elif self.pending and text.startswith('### '):
            self.header['name'] = text[4:].strip()[:256]
        elif self.pending and text.startswith('# Deck ID:'):
            self.header['deck_id'] = text.split(':',1)[1].strip()[:128]
        elif self.pending and text.startswith('AAE'):
            try:
                definition = decode(text)
                if 0 < sum(definition.cards.values()) <= 100:
                    self.candidates.append((ts, definition.cards))
                    self.metadata[ts] = dict(self.header,code=text,cards=dict(definition.cards),time=ts)
                    self.metadata = {t:m for t,m in self.metadata.items() if t in [x[0] for x in self.candidates[-32:]]}
                    self.candidates = self.candidates[-32:]
            except (ValueError, IndexError):
                self.errors += 1
            self.pending = False
        elif self.pending and not text.startswith('#'):
            self.pending = False

    def record_for_game(self,start,previous=None):
        eligible=[t for t,_ in self.candidates if t <= start and (previous is None or t > previous)]
        return self.metadata.get(max(eligible),{}) if eligible else {}

    def for_game(self, start, previous=None):
        eligible = [(t,d) for t,d in self.candidates if t <= start and (previous is None or t > previous)]
        return dict(max(eligible,key=lambda pair:pair[0])[1]) if eligible else {}


class Tracker(PowerParser):
    def __init__(self, decks=None, arena=None):
        super().__init__()
        self.decks = decks or DeckLog()
        self.arena = arena
        self.initial_dbf = {}
        self.drawn = set()
        self.used = []
        self.public = set()
        self.recent = OrderedDict()
        self._line_entity_id = None
        self.accepted = 0
        self.failures = 0
        self.recent_errors = deque(maxlen=10)
        self.previous_start = None

    def _create_game(self):
        previous = self.game
        super()._create_game()
        if not self.game.resumed_from:
            self.previous_start = previous.start if previous else None
            self.initial_dbf = self.decks.for_game(self.game.start, previous.start if previous else None)
            self.drawn = set()
            self.used = []
            self.public = set()

    def _set_tag(self, ent, tag, value):
        old = ent.zone
        # Snapshot event evidence before later reveals/transforms/controller changes.
        if tag == 'ZONE' and old == 'HAND' and value in ('PLAY','SECRET') and self._reset_depth is None and not (self.game.resumed_from and self.game.setup):
            self.used.append(dict(entity_id=ent.id, card_id=ent.card_id,
                player_id=ent.controller, turn=(self.game.turn+1)//2,
                game_turn=self.game.turn, order=len(self.used)+1,
                **self._provenance(ent, ent.controller)))
        if tag == 'ZONE' and old == 'DECK' and value == 'HAND':
            self.drawn.add(ent.id)
        super()._set_tag(ent,tag,value)

    def _provenance(self, ent, player_id):
        """Only evidence identifies a generator. False starting != generated."""
        original = bool(ent.in_starting_deck and ent.owner == player_id)
        foreign = bool(ent.owner and ent.owner != player_id)
        source_id = ent.creation_source
        for tag in ('CREATOR', 'DISPLAYED_CREATOR', 'COPIED_FROM_ENTITY_ID'):
            value = ent.tags.get(tag, '')
            if value.isdigit() and int(value):
                source_id = int(value)
                break
        source = self.game.entities.get(source_id)
        generated = bool(not original and not foreign and source_id)
        transformed = bool(original and ent.card_id and ent.card_id != ent.known_id)
        copied = bool(ent.tags.get('COPIED_FROM_ENTITY_ID','').isdigit() and int(ent.tags['COPIED_FROM_ENTITY_ID']))
        origin = ('opponent' if foreign else 'transformed' if transformed else 'starting' if original else 'copied' if copied else
                  'generated' if generated else 'non_initial' if ent.in_starting_deck is False else 'unknown')
        label = i18n.t('track.origin_'+origin)
        returned = bool(ent.arrival and ent.arrival.origin in ('PLAY', 'SECRET', 'GRAVEYARD'))
        return dict(in_starting_deck=original, starting_card_id=ent.known_id if original else '',
                    transformed=transformed, generated=generated, foreign=foreign,
                    origin=origin, origin_label=label, returned=returned,
                    shuffled_in=bool(ent.entered_deck and not original),
                    source_entity_id=source_id, source_card_id=(ent.creation_source_card_id if source_id == ent.creation_source else source.card_id if source else ''),
                    source_known=bool(source_id))

    def _played(self, cards, player_id):
        rows = []
        for event in self.used:
            if event['player_id'] != player_id:
                continue
            cid = event['card_id']
            rows.append(dict(cards.info(cid), **event, count=1,
                             source_name=cards.info(event['source_card_id'])['name'] if event['source_card_id'] else ''))
        return rows

    def _record_context(self, payload):
        """Indented tag lines belong to the preceding entity record, including
        when that record itself is a replay duplicate. No parser mutation here.
        """
        if not payload.startswith(POWER_PREFIX):
            return False
        body = payload[len(POWER_PREFIX):].strip()
        if RE_TAG.fullmatch(body):
            return True
        self._line_entity_id = None
        for pattern in (RE_FULL_CREATE, RE_GAME_ENTITY, RE_PLAYER):
            match = pattern.match(body)
            if match:
                self._line_entity_id = int(match[1])
                return False
        for pattern in (RE_FULL_UPDATE, RE_SHOW, RE_CHANGE):
            match = pattern.match(body)
            if match:
                ref = match[1].removeprefix('Entity=')
                bracket = RE_BRACKET_ID.search(ref) if ref.startswith('[') else None
                if ref.isdigit() or bracket:
                    self._line_entity_id = int(ref if ref.isdigit() else bracket[1])
                return False
        return False

    def feed_line(self, raw, day=None):
        match = LINE.match(raw)
        if not match:
            return False
        stamp,payload = match.groups()
        inline_tag = self._record_context(payload)
        # Different entities routinely have identical timestamp + indented tag
        # text. Dedup must include their record context, not discard legal tags.
        key = (raw, self._line_entity_id if inline_tag else None)
        if key in self.recent:
            return False
        self.recent[key] = None
        if len(self.recent)>8192:
            self.recent.popitem(last=False)
        if inline_tag and self.game:
            self._current = self.game.entities.get(self._line_entity_id)
        try:
            ts = datetime.fromisoformat((day or datetime.now().date()).isoformat()+'T'+stamp[:15])
            if payload.startswith(('GameState.DebugPrintPower()', 'GameState.DebugPrintGame()')):
                self.feed(ts,payload)
                self.accepted += 1
                if self.game and 'CHANGE_ENTITY' not in payload:
                    for event in self.used:
                        ent = self.game.entities.get(event['entity_id'])
                        if not event['card_id'] and not event.get('identity_lost') and ent and ent.card_id:
                            event['card_id'] = ent.card_id
                elif self.game:
                    for event in self.used:
                        ent = self.game.entities.get(event['entity_id'])
                        if not event['card_id'] and ent and ent.card_id:
                            event['identity_lost'] = True
                if self.game and self.game.opponent:
                    for e in self.game.entities.values():
                        if e.controller==self.game.opponent.player_id and e.card_id and e.tags.get('CARDTYPE') not in ('HERO','HERO_POWER','PLAYER','GAME') and not e.card_id.startswith('HERO_'):
                            self.public.add((e.id,e.card_id))
            return True
        except (ValueError,KeyError,TypeError,IndexError) as exc:
            self.recent_errors.append(type(exc).__name__+': '+str(exc)[:200]+' | '+payload[:160])
            self.failures += 1
            return False

    def _secret_view(self, cards, opponent):
        game = self.game
        active = []
        for ent in game.entities.values():
            if ent.controller != opponent.player_id or ent.zone != 'SECRET':
                continue
            # Quests and other public objectives can occupy the same zone.
            if any(ent.tags.get(tag) == '1' for tag in ('QUEST', 'SIDE_QUEST', 'QUESTLINE', 'OBJECTIVE')):
                continue
            card = cards.by_id.get(ent.card_id)
            if ent.tags.get('SECRET') != '1' and card and cards.has_mechanics and 'SECRET' not in card.get('mechanics', ()):
                continue
            active.append(dict(cards.info(ent.card_id), entity_id=ent.id))

        if not active:
            return {}
        candidates = []
        unknown = sum(not row['id'] for row in active)
        title = i18n.t('hud.secrets', count=len(active))
        empty_label = ''
        if unknown:
            cls = game.hero_class(opponent) or cards.by_id.get(game.hero_card(opponent), {}).get('cardClass')
            candidates = [cards.info(cid) for cid in cards.secrets_by_class.get(cls, ())]
            title += i18n.t('hud.secret_unknown', count=unknown)
            if candidates:
                title += '\n' + i18n.t('hud.secret_unfiltered')
            else:
                empty_label = i18n.t('hud.secret_no_candidates' if cls else 'hud.secret_no_class')
        return dict(secrets=active, secret_candidates=candidates, secret_title=title, secret_empty=empty_label)

    def view(self, cards, secret_hints=True):
        game = self.game
        result = dict(turn=0, own=[], own_added=[], own_played=[], opponent=[], opponent_seen=[],
                      opponent_played=[], opponent_hand=None, opponent_deck=None, secrets=[], secret_candidates=[])
        if game is None or game.complete:
            return dict(result, status='waiting', own_label=i18n.t('track.waiting_new'))
        if game.game_type.startswith(('GT_BATTLEGROUNDS','GT_MERCENARIES')):
            return dict(result, status='unsupported', own_label=i18n.t('track.unsupported'))
        # Cross-file buffers can expose a queue-time deck block after CREATE_GAME.
        # Bind only a deck timestamped before this game, after the previous one.
        if not self.initial_dbf:
            self.initial_dbf = self.decks.for_game(game.start,self.previous_start)
        if self.arena is not None and game.game_type in ('GT_ARENA','GT_UNDERGROUND_ARENA'):
            self.initial_dbf = self.arena.definition_for_game(datetime.fromisoformat(game.key))
        me,opp = game.friendly,game.opponent
        result.update(status='playing' if me and opp else 'identifying',turn=(game.turn+1)//2,
                      own_label=i18n.t('track.deck_unknown'),
                      own_class=game.hero_class(me) if me else '',opponent_class=game.hero_class(opp) if opp else '')
        if not me or not opp:
            return result
        entities=list(game.entities.values())
        if secret_hints and not (game.result(me) or game.result(opp)):
            result.update(self._secret_view(cards, opp))
        # CardID came from a logged FULL/SHOW/CHANGE event. Never fill unknown IDs.
        for e in entities:
            if e.controller==opp.player_id and e.card_id and e.tags.get('CARDTYPE') not in ('HERO','HERO_POWER','PLAYER','GAME') and not e.card_id.startswith('HERO_'):
                self.public.add((e.id,e.card_id))
        revealed = Counter(card_id for _,card_id in self.public)
        result['opponent_seen']=[dict(cards.info(c),count=n) for c,n in revealed.items()]
        result['opponent']=result['opponent_seen']  # Backwards-compatible public view.
        result['own_played']=self._played(cards,me.player_id)
        result['opponent_played']=self._played(cards,opp.player_id)
        result['opponent_hand']=game.count_zone(opp,'HAND')
        # Zone counts are entity counts from the log, not inferred card identities.
        result['opponent_deck']=game.count_zone(opp,'DECK') if any(e.in_starting_deck and e.owner==opp.player_id for e in entities) else None
        mine=[e for e in entities if e.owner==me.player_id and e.in_starting_deck]
        # Distinct dbf IDs can map to the same card ID; preserve counts.
        starting=Counter()
        for dbf,n in self.initial_dbf.items(): starting[cards.id_for_dbf(dbf)]+=n
        departed=Counter(e.known_id for e in mine if (e.zone!='DECK' or e.controller!=me.player_id) and e.known_id)
        accounted=Counter(e.known_id for e in mine if e.known_id)
        missing=max(0,sum(starting.values())-len(mine))
        unidentified_departures=sum(1 for e in mine if not e.known_id and (e.zone!='DECK' or e.controller!=me.player_id))
        unknown_extras=sum(1 for e in entities if e.controller==me.player_id and e.zone=='DECK' and not e.in_starting_deck and not e.card_id)
        known_current=Counter(e.card_id for e in entities if e.controller==me.player_id and e.zone=='DECK' and e.card_id)
        transformed=Counter(e.known_id for e in mine if e.zone=='DECK' and e.controller==me.player_id and e.card_id and e.card_id!=e.known_id)
        drawn=Counter(e.known_id for e in mine if e.id in self.drawn and e.known_id)
        used=Counter(e['card_id'] for e in self.used if e['player_id']==me.player_id and e['in_starting_deck'])
        record=self.decks.record_for_game(game.start,self.previous_start)
        result['deck_name']=record.get('name','') if record.get('cards')==self.initial_dbf and not record.get('arena') and game.game_type not in ('GT_ARENA','GT_UNDERGROUND_ARENA') else ''
        if game.game_type in ('GT_ARENA','GT_UNDERGROUND_ARENA'):
            result['deck_name']=i18n.t('hud.arena_deck',hero=i18n.class_label(result['own_class'],'arena.class_unknown'))
        result['own_label']=i18n.t('track.deck_full') if starting else i18n.t('track.deck_partial')
        # Without a deck definition, show only confirmed starting entities. Never
        # use arbitrary visible cards or plays to manufacture a deck definition.
        original_ids = starting.keys() if starting else accounted.keys()
        for cid in original_ids:
            initial=starting.get(cid) if starting and cid in starting else None
            uncertain_slots=min(max(0,(initial or 0)-accounted[cid]),missing+unidentified_departures)
            exact=initial is not None and not cid.startswith('dbf:') and not uncertain_slots and accounted[cid]<=initial
            remaining=max(0,(initial or 0)-departed[cid]-transformed[cid]) if exact else None
            lower=sum(1 for e in mine if e.zone=='DECK' and e.controller==me.player_id and e.card_id==cid and e.known_id==cid)
            reason=(i18n.t('count.exact') if exact else
                    i18n.t('count.start_unknown') if not starting else
                    i18n.t('count.unmapped') if cid.startswith('dbf:') else
                    i18n.t('count.uncertain') if uncertain_slots else
                    i18n.t('count.over') if accounted[cid]>(initial or 0) else
                    i18n.t('count.not_initial'))
            self_row=dict(cards.info(cid),initial=initial,
                remaining=remaining,known_in_deck=lower,remaining_lower_bound=lower if remaining is None and lower>0 else None,
                count_confidence='exact' if exact else 'lower_bound' if lower>0 else 'unknown',count_reason=reason,
                drawn=drawn[cid],used=used[cid],count=remaining if remaining is not None else lower)
            result['own'].append(self_row)
        # A separate current-zone projection, grouped by provenance, not CardID
        # alone. Transformed starting entities no longer represent their original
        # slot's identity, so the replacement lives here too.
        added = {}
        for ent in entities:
            if ent.controller != me.player_id or ent.zone != 'DECK':
                continue
            original = ent.in_starting_deck and ent.owner == me.player_id
            if original and (not ent.card_id or ent.card_id == ent.known_id):
                continue
            provenance = self._provenance(ent, me.player_id)
            if original:
                provenance.update(origin='transformed',origin_label=i18n.t('track.origin_transformed'))
            key = (ent.card_id, provenance['origin'], provenance['source_entity_id'])
            if key not in added:
                added[key] = dict(cards.info(ent.card_id), **provenance,
                    initial=None, remaining=0, count=0, count_confidence='exact',
                    known_in_deck=0, count_reason=i18n.t('count.zone'))
            added[key]['remaining'] += 1
            added[key]['count'] += 1
            added[key]['known_in_deck'] += 1
        result['own_added'] = list(added.values())
        for key in ('own','own_added','opponent'):
            result[key].sort(key=lambda r:(r['cost'] if isinstance(r['cost'],int) else 99,r['name']))
            result[key]=result[key][:256]
        result['count_evidence']=dict(
            friendly_id=me.player_id,opponent_id=opp.player_id,entities_total=len(entities),
            expected_initial=sum(starting.values()),starting_seen=len(mine),missing_initial=missing,
            own_deck_entities=game.count_zone(me,'DECK'),known_own_deck=sum(known_current.values()),
            unknown_generated_deck=unknown_extras,unknown_initial_departures=unidentified_departures,
            unmapped_initial_rows=sum(c.startswith('dbf:') for c in starting),
            controller_unset=sum(e.controller==0 for e in entities),
            bracket_hydrations=self.bracket_hydrations,deduplication='entity_record_context')
        result['own_deck']=game.count_zone(me,'DECK')
        result['own_remaining']=(sum(r['remaining'] for r in result['own'])+sum(r['remaining'] for r in result['own_added'])
                                 if starting and all(r['remaining'] is not None for r in result['own']) else None)
        result['opponent_unknown']=sum(not e['card_id'] for e in result['opponent_played'])
        return result
