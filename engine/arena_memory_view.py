"""Presentation-only merge. Never mutates Arena log history or pick counts."""
import time
from .arena import HERO_CLASSES, CLASS_NAMES
import re


def hero_class(cards,cid):
    cls=cards.by_id.get(cid,{}).get('cardClass','')
    match=re.match(r'^HERO_(\d{2})',cid or '')
    return cls or (HERO_CLASSES.get(int(match[1]),'') if match else '')


class ArenaPreview:
    def __init__(self,class_ratings):
        self.class_ratings=class_ratings;self.context=None;self.cutoff=0;self.barrier=False

    def view(self,arena,state,diagnostic):
        base=arena.view();context=(arena.session,base['deck_id'],base['phase'],base['mode'])
        if self.context is not None and context!=self.context:
            self.cutoff=time.monotonic();self.barrier=True
        self.context=context
        base.update(stage='redrafting' if base['mode']=='REDRAFTING' else 'drafting' if base['drafting'] else 'none',
                    slot='CARD',source='manual',show_count=True,memory=diagnostic,class_ratings=self.class_ratings.metadata(),
                    association='logs',source_note='候选手动录入；实际选择由日志或补录确认')
        valid=bool(state and state.mode in ('DRAFTING','REDRAFTING') and len(state.choices)==3 and state.slot in ('HERO','CARD','HERO_POWER'))
        if valid and diagnostic.get('observed_at',0)<=self.cutoff:valid=False
        if valid and self.barrier and base['deck_id'] and state.slot!='HERO':
            if state.deck_id!=base['deck_id'] or (base['mode']=='REDRAFTING' and state.mode!='REDRAFTING'):valid=False
            else:self.barrier=False
        if not valid:
            # A healthy memory read says the screen changed: don't resurrect the
            # previous manual/auto offer. Permission failures retain log-only UI.
            if diagnostic.get('enabled') and diagnostic.get('code') in ('reading','not_running','hero_selection','card_selection','hero_power_selection'):
                base['candidates']=[]
                if diagnostic.get('code')=='not_running' or (diagnostic.get('code')=='reading' and state is None):
                    base['stage']='none';base['drafting']=False
                    base['source_note']='当前没有可确认的选牌画面；保留日志历史'
            return base
        stage={'HERO':'hero_selection','CARD':'redrafting' if state.mode=='REDRAFTING' else 'card_selection','HERO_POWER':'hero_power_selection'}[state.slot]
        matched=bool(base['deck_id'] and state.deck_id==base['deck_id'] and state.slot!='HERO')
        formal=base['cls'] if matched else ''
        temporary=hero_class(arena.cards,state.hero)
        conflict=bool(matched and formal and temporary and formal!=temporary)
        cls=formal or temporary
        rows=[]
        for choice in state.choices:
            row=dict(arena.cards.info(choice.card_id),rating=None,score=None,best=False,tier='',rating_label='暂无评分',
                     package=[arena.cards.info(cid) for cid in choice.package],hero_row=state.slot=='HERO')
            if state.slot=='HERO':
                hero_cls=hero_class(arena.cards,choice.card_id);stats=self.class_ratings.get(state.underground,hero_cls)
                row.update(class_id=hero_cls,class_name=CLASS_NAMES.get(hero_cls,'职业未知'),hero_stats=stats)
                if stats:row.update(score=stats['winrate']*100,rating_label=f"{stats['winrate']*100:.1f}%",tier=f"排名 {stats['rank']}/{stats['of']} · {stats['games']} 场")
            elif state.slot=='CARD':
                rating=arena.ratings.get(cls,choice.card_id)
                if rating:row.update(rating=rating,score=rating['score'],rating_label=str(rating['score']),tier=rating['tier'])
                if choice.package:row['tier']+=f" · 附带 {len(choice.package)} 张"
            rows.append(row)
        scores=[r['score'] for r in rows if r['score'] is not None]
        hero_ranks=[r['hero_stats']['rank'] for r in rows if r.get('hero_stats')]
        for row in rows:
            row['best']=(bool(hero_ranks) and bool(row.get('hero_stats')) and row['hero_stats']['rank']==min(hero_ranks)) if state.slot=='HERO' else bool(scores) and row['score']==max(scores)
        base.update(stage=stage,slot=state.slot,source='memory',offer_round=base['round'] if matched and base['drafting'] and state.slot=='CARD' else None,candidates=rows,mode=state.mode,
                    underground=state.underground,show_count=matched,association='matched' if matched else 'preview_only',
                    temporary_hero=state.hero,temporary_class=CLASS_NAMES.get(temporary,''),
                    memory_deck_id=state.deck_id,memory_deck_size=len(state.deck),wins=state.wins,losses=state.losses,
                    source_note='只读内存候选预览；不计入已选牌组',log_conflict=conflict)
        if conflict:base['source_note']='内存职业与日志冲突；保留正式日志职业及其评分，不改历史'
        if not matched:
            base['picks']=[];base['redraft_picks']=[]
            if cls:base['class_name']=CLASS_NAMES.get(cls,'职业未知')
        return base
