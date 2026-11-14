"""Evidence-based card views on top of the MIT PowerParser.

Decks.log headers/deck-code format follow hs-decktracker-linux/decks.py.
Never infer an opponent's unknown card identity or use played cards as a deck.
"""
from collections import Counter, OrderedDict
from datetime import datetime
import re
from .power import PowerParser
from .deckstring import decode

LINE = re.compile(r'^[A-Z] (\d\d:\d\d:\d\d\.\d+) (.*)$')


class DeckLog:
    def __init__(self):
        self.pending = False
        self.candidates = []
        self.errors = 0

    def feed(self, ts, payload):
        text = payload.strip()
        if text.startswith(('Finding Game With Deck:', 'Starting Arena Game With Deck:')):
            self.pending = True
        elif self.pending and text.startswith('AAE'):
            try:
                definition = decode(text)
                if 0 < sum(definition.cards.values()) <= 100:
                    self.candidates.append((ts, definition.cards))
                    self.candidates = self.candidates[-32:]
            except (ValueError, IndexError):
                self.errors += 1
            self.pending = False
        elif self.pending and not text.startswith('#'):
            self.pending = False

    def for_game(self, start, previous=None):
        eligible = [(t,d) for t,d in self.candidates if t <= start and (previous is None or t > previous)]
        return dict(max(eligible,key=lambda pair:pair[0])[1]) if eligible else {}


class Tracker(PowerParser):
    def __init__(self, decks=None):
        super().__init__()
        self.decks = decks or DeckLog()
        self.initial_dbf = {}
        self.drawn = set()
        self.used = []
        self.public = set()
        self.recent = OrderedDict()
        self.accepted = 0
        self.failures = 0

    def _create_game(self):
        previous = self.game
        super()._create_game()
        if not self.game.resumed_from:
            self.initial_dbf = self.decks.for_game(self.game.start, previous.start if previous else None)
            self.drawn = set()
            self.used = []
            self.public = set()

    def _set_tag(self, ent, tag, value):
        old = ent.zone
        # Capture the actual card at play time, not its identity after a transform.
        if tag == 'ZONE' and old == 'HAND' and value in ('PLAY','SECRET') and self._reset_depth is None and not (self.game.resumed_from and self.game.setup):
            self.used.append((ent.id,ent.card_id,ent.controller))
        if tag == 'ZONE' and old == 'DECK' and value == 'HAND':
            self.drawn.add(ent.id)
        super()._set_tag(ent,tag,value)

    def feed_line(self, raw, day=None):
        match = LINE.match(raw)
        if not match:
            return False
        # Exact timestamp+payload repeats are duplicates; identical actions with
        # different timestamps remain distinct. Bounded for long sessions.
        if raw in self.recent:
            return False
        self.recent[raw] = None
        if len(self.recent)>8192:
            self.recent.popitem(last=False)
        stamp,payload = match.groups()
        try:
            ts = datetime.fromisoformat((day or datetime.now().date()).isoformat()+'T'+stamp[:15])
            if payload.startswith(('GameState.DebugPrintPower()', 'GameState.DebugPrintGame()')):
                self.feed(ts,payload)
                self.accepted += 1
                if self.game and self.game.opponent:
                    for e in self.game.entities.values():
                        if e.controller==self.game.opponent.player_id and e.card_id and e.tags.get('CARDTYPE') not in ('HERO','HERO_POWER','PLAYER','GAME') and not e.card_id.startswith('HERO_'):
                            self.public.add((e.id,e.card_id))
            return True
        except (ValueError,KeyError,TypeError,IndexError):
            self.failures += 1
            return False

    def view(self, cards):
        game = self.game
        if game is None or game.complete:
            return dict(status='waiting',turn=0,own=[],opponent=[],own_label='等待新对局',opponent_hand=None,opponent_deck=None)
        if game.game_type.startswith(('GT_BATTLEGROUNDS','GT_MERCENARIES')):
            return dict(status='unsupported',turn=0,own=[],opponent=[],own_label='不支持的游戏模式',opponent_hand=None,opponent_deck=None)
        me,opp = game.friendly,game.opponent
        result = dict(status='playing' if me and opp else 'identifying',turn=(game.turn+1)//2,
                      own=[],opponent=[],own_label='牌组未知',opponent_hand=None,opponent_deck=None,
                      own_class=game.hero_class(me) if me else '',opponent_class=game.hero_class(opp) if opp else '')
        if not me or not opp:
            return result
        entities=list(game.entities.values())
        # CardID came from a logged FULL/SHOW/CHANGE event. Never fill unknown IDs.
        for e in entities:
            if e.controller==opp.player_id and e.card_id and e.tags.get('CARDTYPE') not in ('HERO','HERO_POWER','PLAYER','GAME') and not e.card_id.startswith('HERO_'):
                self.public.add((e.id,e.card_id))
        revealed = Counter(card_id for _,card_id in self.public)
        result['opponent']=[dict(cards.info(c),count=n) for c,n in revealed.items()]
        result['opponent_hand']=game.count_zone(opp,'HAND')
        # Zone counts are entity counts from the log, not inferred card identities.
        result['opponent_deck']=game.count_zone(opp,'DECK') if any(e.in_starting_deck and e.owner==opp.player_id for e in entities) else None
        mine=[e for e in entities if e.owner==me.player_id and e.in_starting_deck]
        # Distinct dbf IDs can map to the same card ID; preserve counts.
        starting=Counter()
        for dbf,n in self.initial_dbf.items(): starting[cards.id_for_dbf(dbf)]+=n
        departed=Counter(e.known_id for e in mine if (e.zone!='DECK' or e.controller!=me.player_id) and e.known_id)
        uncertain=any(c.startswith('dbf:') for c in starting) or any(c not in starting for c in departed) or len(mine)!=sum(starting.values()) or any(not e.known_id for e in mine if e.zone!='DECK' or e.controller!=me.player_id)
        known_current=Counter(e.card_id for e in entities if e.controller==me.player_id and e.zone=='DECK' and e.card_id)
        extras=Counter(e.card_id for e in entities if e.controller==me.player_id and e.zone=='DECK' and e.card_id and not e.in_starting_deck)
        transformed=Counter(e.known_id for e in mine if e.zone=='DECK' and e.card_id and e.card_id!=e.known_id)
        drawn=Counter(e.known_id for e in mine if e.id in self.drawn and e.known_id)
        used=Counter(c or game.entities[eid].card_id for eid,c,pid in self.used if pid==me.player_id and eid in game.entities)
        result['own_label']='完整初始牌组（Decks.log）' if starting else '部分已知；完整牌组未知'
        visible_own={e.card_id for e in entities if e.controller==me.player_id and e.card_id and not e.card_id.startswith('HERO_') and e.tags.get('CARDTYPE') not in ('HERO','HERO_POWER','PLAYER','GAME')}
        for cid in starting.keys()|known_current.keys()|departed.keys()|used.keys()|visible_own:
            remaining = max(0,starting[cid]-departed[cid]-transformed[cid])+extras[cid] if starting and not uncertain else None
            # A transformed starting entity remains in deck under its new ID.
            remaining = (remaining or 0)+sum(1 for e in mine if e.zone=='DECK' and e.controller==me.player_id and e.card_id==cid and e.card_id!=e.known_id) if remaining is not None else None
            result['own'].append(dict(cards.info(cid),initial=starting[cid] if starting else None,
                remaining=remaining,known_in_deck=known_current[cid],drawn=drawn[cid],used=used[cid],count=remaining if remaining is not None else known_current[cid]))
        for key in ('own','opponent'):
            result[key].sort(key=lambda r:(r['cost'] if isinstance(r['cost'],int) else 99,r['name']))
            result[key]=result[key][:256]
        result['own_deck']=game.count_zone(me,'DECK')
        unknown_used={eid for eid,c,pid in self.used if pid==opp.player_id and not c and eid in game.entities and not game.entities[eid].card_id}
        result['opponent_unknown']=len(unknown_used)
        if unknown_used:
            result['opponent'].append(dict(id='',name='未知卡牌（已使用）',cost=None,image='',count=len(unknown_used)))
        return result
