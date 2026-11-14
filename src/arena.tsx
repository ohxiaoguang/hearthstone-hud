import { ButtonItem, TextField } from '@decky/ui';
import { callable } from '@decky/api';
import { useState } from 'react';
export type ArenaCard={id:string;name:string;cost:number|null;image:string;image_data?:string;score:number|null;tier:string;rating_label:string;best:boolean;round?:number;source?:string;conflict?:boolean;hero_row?:boolean;class_name?:string;hero_stats?:{winrate:number;games:number;rank:number;of:number}|null;package?:{id:string;name:string;cost:number|null;image:string}[]};
export type ArenaView={stage:string;slot:string;source:string;show_count:boolean;source_note:string;association:string;log_conflict?:boolean;class_ratings?:{source:string;captured_at:string;error:string};memory?:{enabled:boolean;found:boolean;pid:number|null;status:string;code:string;candidate_count:number;last_error:string;error:string};deck_id:string;phase:string;round:number;mode:string;class_name:string;count:number;count_exact:boolean;drafting:boolean;exact:boolean;picks:ArenaCard[];redraft_picks:ArenaCard[];candidates:ArenaCard[];offer_round:number|null;unresolved_choices:number;overflow_choices:number;conflicts:number;error:string;ratings:{source:string;captured_at:string;entries:number;error:string}};
const search=callable<[query:string],ArenaCard[]>('arena_search');
const setOffer=callable<[id:string,phase:string,ordinal:number,ids:string[]],ArenaView>('arena_set_offer');
const clearOffer=callable<[],ArenaView>('arena_clear_offer');
const manualPick=callable<[id:string,phase:string,ordinal:number,cid:string],ArenaView>('arena_manual_pick');
export function ArenaEditor({data,onUpdate}:{data:ArenaView;onUpdate:(v:ArenaView)=>void}){
 const [query,setQuery]=useState('');const [results,setResults]=useState<ArenaCard[]>([]);const [slots,setSlots]=useState<(ArenaCard|null)[]>([null,null,null]);
 const [slot,setSlot]=useState(0);const [busy,setBusy]=useState(false);const [error,setError]=useState('');
 const [context,setContext]=useState('');const [manual,setManual]=useState<ArenaCard|null>(null);
 const key=`${data.deck_id}/${data.phase}/${data.round}`;
 const heroStage=data.stage==='hero_selection'||data.stage==='hero_power_selection';
 const ratingError=heroStage?data.class_ratings?.error:data.ratings.error;
 const run=async(job:()=>Promise<void>)=>{setBusy(true);setError('');try{await job();}catch(e){setError(String(e));}finally{setBusy(false);}};
 const choose=(card:ArenaCard)=>{
   const next=context===key?[...slots]:[null,null,null];next[slot]=card;setSlots(next);setContext(key);setManual(card);
 };
 const current=context===key?slots:[null,null,null];
 return <div style={{fontSize:13,lineHeight:1.5}}>
  <div>{heroStage?(data.stage==='hero_selection'?'竞技场 · 英雄选择':'竞技场 · 英雄技能选择'):`${data.class_name} · ${data.mode||'未发现选牌'}`}{!heroStage&&(data.show_count?` · 日志已选 ${data.count}/30${!data.count_exact?'（份数待确认）':''}`:' · 已选数量等待日志确认')}</div>
  <div>竞技场 ID：{data.deck_id||'未发现'} · 下一轮：{data.round}</div>
  <div>{data.source==='memory'?'候选来源：只读内存自动识别。实际选牌仍由日志确认。':'候选牌录入：手动录入三张牌。实际选牌：日志自动识别，失败时手动补录。'}</div>
  <div>{data.source_note}</div>
  {heroStage?<div>职业统计：{data.class_ratings?.source||'暂无评分'} · 快照 {data.class_ratings?.captured_at||'不可用'}</div>:<div>评分：{data.ratings.source} · 快照 {data.ratings.captured_at||'不可用'} · {data.ratings.entries} 条；仅比较已有评分，不代表未知牌较弱。</div>}
  {(data.error||ratingError)&&<div role="alert">{data.error||ratingError}</div>}
  {data.overflow_choices>0&&<div role="alert">选牌日志超过30条，超出部分未加入牌组；请等待 Decks.log 最终定义确认。</div>}
  {data.unresolved_choices>0&&<div>有 {data.unresolved_choices} 条选择等待卡牌数据库确认类型，暂不计数。</div>}
  {data.conflicts>0&&<div role="alert">{data.conflicts} 轮手动记录与日志不同，已采用日志确认，没有重复加牌。</div>}
  {!heroStage&&<>
  <TextField label="简体中文名称或 Card ID" value={query} onChange={e=>setQuery(e.target.value)}/>
  <ButtonItem disabled={busy} onClick={()=>run(async()=>setResults(await search(query)))}>查找卡牌</ButtonItem>
  <div>选择要填写的槽位，再点搜索结果；也可把搜索结果用于实际选择补录。</div>
  {current.map((card,i)=><ButtonItem key={i} onClick={()=>setSlot(i)}>{slot===i?'正在填写 · ':''}候选 {i+1}：{card?.name||'未录入'}</ButtonItem>)}
  {results.map(card=><ButtonItem key={card.id} onClick={()=>choose(card)}>{card.name} · {card.id} · {card.cost??'?'} 费 · {card.rating_label}</ButtonItem>)}
  <ButtonItem disabled={busy||!data.drafting||current.some(c=>!c)} onClick={()=>run(async()=>onUpdate(await setOffer(data.deck_id,data.phase,data.round,current.map(c=>c!.id))))}>提交本轮三张候选（不加入牌组）</ButtonItem>
  <ButtonItem disabled={busy} onClick={()=>run(async()=>{onUpdate(await clearOffer());setSlots([null,null,null]);setContext('');})}>清空候选并重新录入</ButtonItem>
  </>}
  {data.candidates.map((card,i)=><div key={i} style={{padding:6,margin:'4px 0',border:card.best?'2px solid #ffdc78':'1px solid #666',position:'relative'}}>
   {card.image_data?<img src={card.image_data} alt={card.name} style={{width:'100%',height:52,objectFit:'cover'}}/>:<div>卡图等待缓存／下载</div>}
   <div>{card.best?(card.hero_row?'★ 已知胜率最高 · ':'★ 已知评分最高 · '):''}{card.hero_row?card.class_name:card.name}{!card.hero_row&&` · ${card.cost??'?'} 费`} · {card.rating_label} {card.tier}</div>
   {card.package&&card.package.length>0&&<div>附带卡牌（仅预览）：{card.package.map(c=>c.name).join('、')}</div>}
   {!heroStage&&<ButtonItem disabled={busy||!data.offer_round} onClick={()=>run(async()=>onUpdate(await manualPick(data.deck_id,data.phase,data.offer_round!,card.id)))}>日志未识别时，补录本轮实际选中此牌</ButtonItem>}
  </div>)}
  {!heroStage&&<>
  <div>不录候选也可补录：先在搜索结果选中一张，再确认。当前：{context===key?manual?.name||'未选择':'未选择'}。</div>
  <ButtonItem disabled={busy||!data.drafting||context!==key||!manual} onClick={()=>run(async()=>{onUpdate(await manualPick(data.deck_id,data.phase,data.round,manual!.id));setManual(null);})}>补录第 {data.round} 轮实际选择（一张）</ButtonItem>
  </>}
  {error&&<div role="alert">{error}</div>}
  {!heroStage&&<>
  <div>已选牌（{data.exact?'Decks.log 最终精确牌组':'按实际选择顺序；日志列表恢复时份数未确认'}）：</div>
  {data.picks.map((card,i)=><div key={i}>{i+1}. {card.name} · {card.rating_label} {card.source==='manual'?'（手动，待日志核对）':''}</div>)}
  {data.redraft_picks.length>0&&<div>重选操作（不追加到旧牌组，等待最终 Decks.log）：{data.redraft_picks.map((r,i)=><div key={i}>{i+1}. {r.name} · {r.rating_label}</div>)}</div>}
  </>}
 </div>;
}
