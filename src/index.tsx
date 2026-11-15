import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow, SliderField, ToggleField } from '@decky/ui';
import { callable, definePlugin } from '@decky/api';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { FaLayerGroup } from 'react-icons/fa';
import { copyText } from './clipboard';
import { CARD_LANGUAGES, UI_LANGUAGES, tr, type UiLang } from './i18n';
type Settings = {enabled:boolean;visible:boolean;own_deck:boolean;arena:boolean;arena_memory:boolean;font_size:number;panel_width:number;scale:number;opacity:number;x:number;y:number;right_x:number;right_y:number;own_played:boolean;opponent_played:boolean;show_summary:boolean;hide_exhausted:boolean;ui_language:UiLang;card_language:string};
type Status = {lifecycle:string;version:string;settings:Settings;running:boolean;error:string;process:{found?:boolean};power_config:{enabled?:boolean;restart_required?:boolean};decks_config:{enabled?:boolean;restart_required?:boolean};arena_config:{enabled?:boolean;restart_required?:boolean};arena:{memory?:{status?:string}};cards:{count:number;download_state:string;download_phase:string;error:string;language?:string;data_language?:string;cached_languages?:string[];image_batch:{status:string;total:number;success:number;failed:number;skipped:number}}};
const getStatus=callable<[],Status>('status');
const configure=callable<[values:Partial<Settings>],Status>('configure');
const start=callable<[],Status>('start_hud');
const stop=callable<[],Status>('stop_hud');
const clearCache=callable<[],Status>('clear_card_cache');
const retryDatabase=callable<[],Status>('retry_card_database');
const downloadImages=callable<[],Status>('download_missing_images');
const diagnosticText=callable<[],string>('diagnostic_text');
const box={fontSize:13,lineHeight:1.45,padding:'6px 2px',overflowWrap:'anywhere' as const};
function Fold({title,openLabel,closeLabel,children}:{title:string;openLabel:string;closeLabel:string;children:ReactNode}){
 const [open,setOpen]=useState(false);
 return <div style={{margin:'6px 0'}}>
  <ButtonItem layout="below" onClick={()=>setOpen(value=>!value)}>{(open?closeLabel:openLabel)} · {title}</ButtonItem>
  {open&&<div style={box}>{children}</div>}
 </div>;
}
function Content(){
 const [data,setData]=useState<Status>();const [error,setError]=useState('');
 const [busy,setBusy]=useState(false);const [action,setAction]=useState('');
 const [copyState,setCopyState]=useState('');const [manualCopy,setManualCopy]=useState('');
 const revision=useRef(0);const pending=useRef(0);
 const lang=data?.settings.ui_language??'en';
 const t=(key:Parameters<typeof tr>[1],values?:Record<string,string|number>)=>tr(lang,key,values);
 const run=async(job:()=>Promise<Status>)=>{const ticket=++revision.current;pending.current++;try{const result=await job();if(ticket===revision.current){setData(result);setError('');}}catch(e){if(ticket===revision.current)setError(String(e));}finally{pending.current--;}};
 useEffect(()=>{let alive=true;const refresh=()=>{if(pending.current)return;const ticket=revision.current;getStatus().then(d=>{if(alive&&!pending.current&&ticket===revision.current)setData(d);}).catch(e=>{if(alive&&!pending.current&&ticket===revision.current)setError(String(e));});};refresh();const timer=data?.settings.enabled===false&&data.lifecycle==='disabled'?undefined:setInterval(refresh,1000);return()=>{alive=false;clearInterval(timer);};},[data?.settings.enabled,data?.lifecycle]);
 const change=(values:Partial<Settings>)=>run(()=>configure(values));
 const background=async(label:string,job:()=>Promise<Status>)=>{setBusy(true);setAction(label);try{await run(job);}finally{setBusy(false);setAction('');}};
 const copyDiagnostic=async()=>{
  setCopyState(t('copying'));let text='';
  try{text=await diagnosticText();await copyText(text);setCopyState(t('copied'));setManualCopy('');}
  catch(e){setCopyState(t('copyFailed',{error:String(e)}));setManualCopy(text||`Hearthstone HUD Diagnostic\n[Plugin]\nVersion: ${data?.version??'unknown'}\nStatus: ${data?.running?'running':'stopped'}\n[Recent Errors]\nBackend diagnostic retrieval failed; full diagnostic unavailable.`);}
 };
 const downloading=!!data&&(data.cards.download_phase==='prepare'||data.cards.download_phase==='running');
 const batch=data?.cards.image_batch;
 const cardOptions=[{data:'auto',label:t('followUi')},...CARD_LANGUAGES.map(entry=>({data:entry.code,label:entry.label}))];
 const cardSelected=data?.settings.card_language??'auto';
 return <PanelSection title={t('title',{version:data?.version??'…'})}>
 <PanelSectionRow><div style={box}>{data?.running?t('hudOn'):t('hudOff')}{(error||data?.error)&&<div role="alert" style={{color:'#ffbdad'}}>{error||data?.error}</div>}</div></PanelSectionRow>
 {data&&<>
 <DropdownItem label={t('uiLanguage')} rgOptions={UI_LANGUAGES.map(entry=>({data:entry.code,label:entry.label}))} selectedOption={data.settings.ui_language} onChange={option=>change({ui_language:option.data as UiLang})}/>
 <DropdownItem label={t('cardLanguage')} rgOptions={cardOptions} selectedOption={cardSelected} onChange={option=>change({card_language:String(option.data)})}/>
 <PanelSectionRow><div style={box}>{t('cardLanguageNote')}</div></PanelSectionRow>
 <ToggleField label={t('enable')} description={t('enableDesc')} checked={data.settings.enabled} disabled={busy||data.lifecycle==='stopping'||data.lifecycle==='starting'} onChange={enabled=>background(enabled?t('restoring'):t('stopping'),()=>configure({enabled}))}/>
 {action&&<PanelSectionRow><div role="status" style={box}>{action}</div></PanelSectionRow>}
 {data.settings.enabled?<>
 <ToggleField label={t('hud')} checked={data.running&&data.settings.visible} disabled={busy} onChange={enabled=>background(t('applying'),enabled?start:stop)}/>
 <ToggleField label={t('arena')} description={t('arenaDesc')} checked={data.settings.arena&&data.settings.arena_memory} disabled={busy} onChange={enabled=>change({arena:enabled,arena_memory:enabled})}/>
 {data.running&&(data.power_config.restart_required||data.decks_config.restart_required||data.arena_config.restart_required)&&<PanelSectionRow><div role="status" style={box}>{t('logsRestart')}</div></PanelSectionRow>}
 {data.running&&data.process.found&&(!data.decks_config.enabled||!data.arena_config.enabled)&&<PanelSectionRow><div role="alert" style={box}>{t('logsPending')}</div></PanelSectionRow>}
 {data.settings.arena_memory&&data.arena.memory?.status&&<PanelSectionRow><div style={box}>{data.arena.memory.status}</div></PanelSectionRow>}
 {(downloading&&!action)&&<PanelSectionRow><div role="status" style={box}><progress aria-label={t('downloadAria')} style={{width:'100%'}}/>{data.cards.download_state}</div></PanelSectionRow>}
 {!downloading&&!data.cards.count&&<><PanelSectionRow><div role="alert" style={box}>{t('cardsMissing')}</div></PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={()=>run(retryDatabase)}>{t('retry')}</ButtonItem></>}
 <SliderField label={t('fontSize')} value={data.settings.font_size} min={14} max={30} step={1} onChange={font_size=>change({font_size})}/>
 <SliderField label={t('panelWidth')} value={data.settings.panel_width} min={180} max={640} step={10} onChange={panel_width=>change({panel_width})}/>
 <Fold title={t('display')} openLabel={t('expand')} closeLabel={t('collapse')}>
 {(['own_deck','opponent_played','own_played','show_summary','hide_exhausted'] as const).map((key,i)=><ToggleField key={key} label={[t('ownDeck'),t('opponentPlayed'),t('ownPlayed'),t('summary'),t('hideExhausted')][i]} checked={data.settings[key]} onChange={v=>change({[key]:v})}/>)}
 <SliderField label={t('scale')} value={data.settings.scale} min={.5} max={3} step={.1} onChange={scale=>change({scale})}/>
 <SliderField label={t('opacity')} value={data.settings.opacity} min={.1} max={1} step={.05} onChange={opacity=>change({opacity})}/>
 {(['x','y','right_x','right_y'] as const).map((key,i)=><SliderField key={key} label={[t('leftX'),t('leftY'),t('rightX'),t('rightY')][i]} value={data.settings[key]} min={0} max={[1920,1080,1920,1080][i]} step={10} onChange={v=>change({[key]:v})}/>)}
 </Fold>
 <ButtonItem layout="below" disabled={busy||batch?.status==='running'} onClick={()=>run(downloadImages)}>{t('downloadImages')}</ButtonItem>
 {batch?.status==='running'&&<PanelSectionRow><div role="status" style={box}>{t('imageProgress',{done:batch.success+batch.failed+batch.skipped,total:batch.total})}</div></PanelSectionRow>}
 <ButtonItem layout="below" disabled={busy} onClick={()=>background(t('clearCache'),clearCache)}>{t('clearCache')}</ButtonItem>
 <PanelSectionRow><div style={box}>{t('clearNote')}</div></PanelSectionRow>
 </>:<PanelSectionRow><div style={box}>{data.lifecycle==='disabled'?t('disabled'):t('stopping')}</div></PanelSectionRow>}
 <ButtonItem layout="below" onClick={copyDiagnostic}>{t('copyDiagnostic')}</ButtonItem>
 {copyState&&<PanelSectionRow><div role="status" style={box}>{copyState}</div></PanelSectionRow>}
 {manualCopy&&<textarea aria-label={t('manualAria')} readOnly value={manualCopy} onFocus={e=>e.currentTarget.select()} style={{width:'100%',height:180,fontSize:12,userSelect:'text',boxSizing:'border-box'}}/>}
 </>}
 </PanelSection>;
}
export default definePlugin(()=>({name:'Hearthstone HUD',titleView:<div>Hearthstone HUD</div>,content:<Content/>,icon:<FaLayerGroup/>}));
