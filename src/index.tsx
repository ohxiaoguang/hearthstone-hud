import { ButtonItem, PanelSection, PanelSectionRow, SliderField, ToggleField } from '@decky/ui';
import { callable, definePlugin } from '@decky/api';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { FaLayerGroup } from 'react-icons/fa';
import { copyText } from './clipboard';
type Settings = {enabled:boolean;visible:boolean;own_deck:boolean;arena:boolean;arena_memory:boolean;font_size:number;panel_width:number;scale:number;opacity:number;x:number;y:number;right_x:number;right_y:number;own_played:boolean;opponent_played:boolean;show_summary:boolean;hide_exhausted:boolean};
type Status = {lifecycle:string;version:string;settings:Settings;running:boolean;error:string;process:{found?:boolean};power_config:{enabled?:boolean;restart_required?:boolean};decks_config:{enabled?:boolean;restart_required?:boolean};arena_config:{enabled?:boolean;restart_required?:boolean};arena:{memory?:{status?:string}};cards:{count:number;download_state:string;error:string;image_batch:{status:string;total:number;success:number;failed:number;skipped:number}}};
const getStatus=callable<[],Status>('status');
const configure=callable<[values:Partial<Settings>],Status>('configure');
const start=callable<[],Status>('start_hud');
const stop=callable<[],Status>('stop_hud');
const clearCache=callable<[],Status>('clear_card_cache');
const retryDatabase=callable<[],Status>('retry_card_database');
const downloadImages=callable<[],Status>('download_missing_images');
const diagnosticText=callable<[],string>('diagnostic_text');
const box={fontSize:13,lineHeight:1.45,padding:'6px 2px',overflowWrap:'anywhere' as const};
function Fold({title,children}:{title:string;children:ReactNode}){
 const [open,setOpen]=useState(false);
 return <div style={{margin:'6px 0'}}>
  <ButtonItem layout="below" onClick={()=>setOpen(value=>!value)}>{open?'收起':'展开'} · {title}</ButtonItem>
  {open&&<div style={box}>{children}</div>}
 </div>;
}
function Content(){
 const [data,setData]=useState<Status>();const [error,setError]=useState('');
 const [busy,setBusy]=useState(false);const [action,setAction]=useState('');
 const [copyState,setCopyState]=useState('');const [manualCopy,setManualCopy]=useState('');
 const revision=useRef(0);const pending=useRef(0);
 const run=async(job:()=>Promise<Status>)=>{const ticket=++revision.current;pending.current++;try{const result=await job();if(ticket===revision.current){setData(result);setError('');}}catch(e){if(ticket===revision.current)setError(String(e));}finally{pending.current--;}};
 useEffect(()=>{let alive=true;const refresh=()=>{if(pending.current)return;const ticket=revision.current;getStatus().then(d=>{if(alive&&!pending.current&&ticket===revision.current)setData(d);}).catch(e=>{if(alive&&!pending.current&&ticket===revision.current)setError(String(e));});};refresh();const timer=data?.settings.enabled===false&&data.lifecycle==='disabled'?undefined:setInterval(refresh,1000);return()=>{alive=false;clearInterval(timer);};},[data?.settings.enabled,data?.lifecycle]);
 const change=(values:Partial<Settings>)=>run(()=>configure(values));
 const background=async(label:string,job:()=>Promise<Status>)=>{setBusy(true);setAction(label);try{await run(job);}finally{setBusy(false);setAction('');}};
 const copyDiagnostic=async()=>{
  setCopyState('正在整理诊断…');let text='';
  try{text=await diagnosticText();await copyText(text);setCopyState('诊断已复制');setManualCopy('');}
  catch(e){setCopyState('复制失败：'+String(e));setManualCopy(text||`Hearthstone HUD Diagnostic\n[Plugin]\nVersion: ${data?.version??'unknown'}\nStatus: ${data?.running?'running':'stopped'}\n[Recent Errors]\nBackend diagnostic retrieval failed; full diagnostic unavailable.`);}
 };
 const downloading=!!data&&(data.cards.download_state==='准备下载'||data.cards.download_state.startsWith('正在下载'));
 const batch=data?.cards.image_batch;
 return <PanelSection title={`炉石记牌器 · ${data?.version??'加载中'}`}>
 <PanelSectionRow><div style={box}>{data?.running?'HUD 已开启':'HUD 已关闭'}{(error||data?.error)&&<div role="alert" style={{color:'#ffbdad'}}>{error||data?.error}</div>}</div></PanelSectionRow>
 {data&&<>
 <ToggleField label="启用插件" description="关闭将停止所有后台功能，保留配置与缓存。" checked={data.settings.enabled} disabled={busy||data.lifecycle==='stopping'||data.lifecycle==='starting'} onChange={enabled=>background(enabled?'正在恢复插件…':'正在停用，等待后台任务退出…',()=>configure({enabled}))}/>
 {action&&<PanelSectionRow><div role="status" style={box}>{action}</div></PanelSectionRow>}
 {data.settings.enabled?<>
 <ToggleField label="启用 HUD" checked={data.running&&data.settings.visible} disabled={busy} onChange={enabled=>background(enabled?'正在开启…':'正在关闭…',enabled?start:stop)}/>
 <ToggleField label="竞技场辅助" description="自动识别候选并显示评分（只读游戏内存）。" checked={data.settings.arena&&data.settings.arena_memory} disabled={busy} onChange={enabled=>change({arena:enabled,arena_memory:enabled})}/>
 {data.running&&(data.power_config.restart_required||data.decks_config.restart_required||data.arena_config.restart_required)&&<PanelSectionRow><div role="status" style={box}>日志已自动启用，请完全退出并重启炉石。</div></PanelSectionRow>}
 {data.running&&data.process.found&&(!data.decks_config.enabled||!data.arena_config.enabled)&&<PanelSectionRow><div role="alert" style={box}>日志设置尚未完成；若持续出现，请复制诊断。</div></PanelSectionRow>}
 {data.settings.arena_memory&&data.arena.memory?.status&&<PanelSectionRow><div style={box}>{data.arena.memory.status}</div></PanelSectionRow>}
 {(downloading&&!action)&&<PanelSectionRow><div role="status" style={box}><progress aria-label="卡牌数据准备进度" style={{width:'100%'}}/>{action||'正在下载卡牌数据，首次使用请稍候…'}</div></PanelSectionRow>}
 {!downloading&&!data.cards.count&&<><PanelSectionRow><div role="alert" style={box}>卡牌数据暂不可用，可以重试下载；HUD 仍可显示卡牌 ID。</div></PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={()=>run(retryDatabase)}>重试下载卡牌数据</ButtonItem></>}
 <SliderField label="卡牌名称字号" value={data.settings.font_size} min={14} max={30} step={1} onChange={font_size=>change({font_size})}/>
 <SliderField label="面板宽度" value={data.settings.panel_width} min={180} max={640} step={10} onChange={panel_width=>change({panel_width})}/>
 <Fold title="显示设置">
 {(['own_deck','opponent_played','own_played','show_summary','hide_exhausted'] as const).map((key,i)=><ToggleField key={key} label={['己方剩余牌库','对手已打出','我方已打出','顶部对局信息','隐藏已耗尽卡牌'][i]} checked={data.settings[key]} onChange={v=>change({[key]:v})}/>)}
 <SliderField label="整体缩放" value={data.settings.scale} min={.5} max={3} step={.1} onChange={scale=>change({scale})}/>
 <SliderField label="面板不透明度" value={data.settings.opacity} min={.1} max={1} step={.05} onChange={opacity=>change({opacity})}/>
 {(['x','y','right_x','right_y'] as const).map((key,i)=><SliderField key={key} label={['左侧横向位置','左侧纵向位置','右侧横向位置','右侧纵向位置'][i]} value={data.settings[key]} min={0} max={[1920,1080,1920,1080][i]} step={10} onChange={v=>change({[key]:v})}/>)}
 </Fold>
 <ButtonItem layout="below" disabled={busy||batch?.status==='running'} onClick={()=>run(downloadImages)}>下载缺失卡图</ButtonItem>
 {batch?.status==='running'&&<PanelSectionRow><div role="status" style={box}>卡图下载中 · {batch.success+batch.failed+batch.skipped}/{batch.total}</div></PanelSectionRow>}
 <ButtonItem layout="below" disabled={busy} onClick={()=>background('正在清理卡牌数据…',clearCache)}>清理并重新下载卡牌数据</ButtonItem>
 <PanelSectionRow><div style={box}>清理缓存的 JSON 和图片后自动重新下载，保留显示设置和原始导入文件。卡图按当前牌组与候选下载。</div></PanelSectionRow>
 </>:<PanelSectionRow><div style={box}>{data.lifecycle==='disabled'?'插件已停用，后台任务已停止。重新开启可恢复之前的设置。':'正在停止后台任务，请稍候…'}</div></PanelSectionRow>}
 <ButtonItem layout="below" onClick={copyDiagnostic}>复制诊断</ButtonItem>
 {copyState&&<PanelSectionRow><div role="status" style={box}>{copyState}</div></PanelSectionRow>}
 {manualCopy&&<textarea aria-label="手动复制诊断文本" readOnly value={manualCopy} onFocus={e=>e.currentTarget.select()} style={{width:'100%',height:180,fontSize:12,userSelect:'text',boxSizing:'border-box'}}/>}
 </>}
 </PanelSection>;
}
export default definePlugin(()=>({name:'Hearthstone HUD',titleView:<div>Hearthstone HUD</div>,content:<Content/>,icon:<FaLayerGroup/>}));
