"""Arena presentation where the game's DraftDeck is the only card source.

Candidates stay a read-only preview. Nothing here reads Arena.log, so repeated
"Client chooses" lines cannot change the selected list, and each snapshot
replaces the previous deck instead of being merged into it. Selected cards are
ordered by mana cost, then by name, so the panel is stable while drafting.
"""
import re
from .arena import CLASS_NAMES,HERO_CLASSES
from .arena_memory import DECK_UNREADABLE

# Diagnostic codes that mean the read itself failed, as opposed to a successful
# poll that simply found no active draft.
READ_FAILURES=('read_error','not_ready','incompatible','permission_denied','not_running','mono_missing')


def hero_class(cards,cid):
    cls=cards.by_id.get(cid,{}).get('cardClass','')
    match=re.match(r'^HERO_(\d{2})',cid or '')
    return cls or (HERO_CLASSES.get(int(match[1]),'') if match else '')


def mana_order(row):
    """Lowest cost first, unknown cost last, ties by name then id."""
    cost=row.get('cost');known=isinstance(cost,int)
    return (0 if known else 1,cost if known else 0,(row.get('name') or '').casefold(),row.get('id') or '')


class ArenaPreview:
    """Memory-only arena view with the last good deck per arena.

    The deck is replaced, never appended to: a snapshot is the whole selection.
    A failed read keeps the previous deck for the same process and arena, but
    marks it stale so the HUD cannot present it as current.
    """

    def __init__(self,class_ratings):
        self.class_ratings=class_ratings
        self.reset()

    def reset(self):
        self.identity=None;self.deck=();self.hero='';self.deck_id='';self.mode='';self.stale=False

    def feed(self,state,diagnostic):
        """Adopt one snapshot. No cross-snapshot accumulation happens here."""
        if diagnostic.get('code') in ('not_running','disabled'):
            # The game is gone or the opt-in was withdrawn: drop the old deck.
            self.reset();return
        identity=(diagnostic.get('pid'),diagnostic.get('process_instance'))
        if any(identity):
            if self.identity is not None and identity!=self.identity:
                # Game restarted: nothing read from the old process may survive.
                self.reset();self.identity=identity
            elif self.identity is None:self.identity=identity
        if state is None:
            # Keep the last deck. Only a failed read makes it uncertain: a good
            # poll that finds no active draft (finished deck, between rounds)
            # leaves the flag alone so the hint cannot stick.
            if self.deck and (diagnostic.get('error') or diagnostic.get('stale_read') or
                              diagnostic.get('code') in READ_FAILURES):self.stale=True
            return
        if state.mode:self.mode=state.mode
        if state.slot in ('HERO','HERO_POWER'):
            # Hero selection opens a new draft: no card has been picked yet.
            self.deck=();self.hero='';self.deck_id='';self.stale=False;return
        if state.deck_id and state.deck_id!=self.deck_id:
            # Another arena: drop the old deck before adopting the new snapshot.
            self.deck=();self.hero='';self.deck_id=state.deck_id;self.stale=True
        if not state.deck_object or state.deck_reason in DECK_UNREADABLE:
            # Unreadable deck: keep the previous selection, but mark it stale.
            self.stale=True;return
        self.deck=state.deck
        self.hero=state.hero or self.hero
        self.stale=False

    def _row(self,cards,ratings,cls,cid):
        rating=ratings.get(cls,cid)
        return dict(cards.info(cid),rating=rating,score=rating['score'] if rating else None,
                    rating_label=str(rating['score']) if rating else '暂无评分',
                    tier=rating['tier'] if rating else '',best=False)

    def _candidates(self,cards,ratings,cls,state):
        rows=[]
        for choice in state.choices:
            row=dict(cards.info(choice.card_id),rating=None,score=None,best=False,tier='',rating_label='暂无评分',
                     package=[cards.info(cid) for cid in choice.package],hero_row=state.slot=='HERO')
            if state.slot=='HERO':
                hero_cls=hero_class(cards,choice.card_id);stats=self.class_ratings.get(state.underground,hero_cls)
                row.update(class_id=hero_cls,class_name=CLASS_NAMES.get(hero_cls,'职业未知'),hero_stats=stats)
                if stats:row.update(score=stats['winrate']*100,rating_label=f"{stats['winrate']*100:.1f}%",
                                    tier=f"排名 {stats['rank']}/{stats['of']} · {stats['games']} 场")
            elif state.slot=='CARD':
                rating=ratings.get(cls,choice.card_id)
                if rating:row.update(rating=rating,score=rating['score'],rating_label=str(rating['score']),tier=rating['tier'])
                if choice.package:row['tier']+=f" · 附带 {len(choice.package)} 张"
            rows.append(row)
        scores=[r['score'] for r in rows if r['score'] is not None]
        ranks=[r['hero_stats']['rank'] for r in rows if r.get('hero_stats')]
        for row in rows:
            row['best']=(bool(ranks) and bool(row.get('hero_stats')) and row['hero_stats']['rank']==min(ranks)) if state.slot=='HERO' \
                        else bool(scores) and row['score']==max(scores)
        return rows

    def view(self,cards,ratings,state,diagnostic):
        """Build the arena view from the memory snapshot only."""
        self.feed(state,diagnostic)
        cls=hero_class(cards,self.hero)
        picks=[self._row(cards,ratings,cls,cid) for cid in self.deck]
        picks.sort(key=mana_order)
        stage='none';slot='CARD';drafting=False;candidates=[]
        if state is not None:
            slot=state.slot
            stage={'HERO':'hero_selection','HERO_POWER':'hero_power_selection',
                   'CARD':'redrafting' if state.mode=='REDRAFTING' else 'card_selection'}.get(slot,'none')
            drafting=slot=='CARD' and state.mode in ('DRAFTING','REDRAFTING')
            if len(state.choices)==3:candidates=self._candidates(cards,ratings,cls,state)
        count=len(picks)
        return dict(stage=stage,slot=slot,source='memory',
                    show_count=bool(picks) or (state is not None and slot=='CARD' and not self.stale),
                    source_note='候选与已选牌都来自只读内存；已选牌按费用排序，候选不计入',
                    deck_id=self.deck_id,phase=('draft:'+self.deck_id) if self.deck_id else '',round=0,
                    mode=self.mode,class_name=CLASS_NAMES.get(cls,'职业未识别'),
                    count=count,count_exact=not self.stale,drafting=drafting,exact=False,
                    picks=picks,redraft_picks=[],candidates=candidates,deck_stale=bool(self.stale),
                    ratings=ratings.metadata(),class_ratings=self.class_ratings.metadata(),memory=diagnostic)
