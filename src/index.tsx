import {
  ButtonItem, DialogButton, DropdownItem, PanelSection, PanelSectionRow,
  SliderField, ToggleField,
} from '@decky/ui';
import { callable, definePlugin } from '@decky/api';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { FaLayerGroup } from 'react-icons/fa';
import { copyText } from './clipboard';
import { UI_LANGUAGES, tr, type UiLang } from './i18n';

type Settings = {enabled:boolean;visible:boolean;own_deck:boolean;arena:boolean;arena_memory:boolean;font_size:number;panel_width:number;scale:number;preview_scale:number;opacity:number;x:number;y:number;right_x:number;right_y:number;own_played:boolean;opponent_played:boolean;secret_hints:boolean;show_summary:boolean;hide_exhausted:boolean;ui_language:UiLang;arena_data_auto_update:boolean};
type Database = {code:string;active:boolean;exists:boolean;bytes:number;updated:number};
type Batch = {status:string;total:number;success:number;failed:number;missing?:number;skipped:number;retried?:number;done?:number;locale?:string};
type Cards = {count:number;download_state:string;download_phase:string;error:string;language?:string;data_language?:string;
  databases?:Record<string,Database>;image_usage?:{cached:number;bytes:number;total:number;downloading:boolean};image_batch:Batch};
type ArenaResult = 'idle'|'checking'|'downloading'|'unchanged'|'updated'|'failed';
type ArenaSnapshot = {source:string;captured_at:string};
type ArenaData = {last_checked:number;running:boolean;
  results:Record<'arena_ratings.json'|'arena_class_ratings.json',ArenaResult>;
  cards:ArenaSnapshot;classes:ArenaSnapshot & {dates:Partial<Record<'arena'|'arena-underground',string>>}};
type Status = {lifecycle:string;version:string;repository?:string;settings:Settings;running:boolean;error:string;
  process:{found?:boolean};power_config:{enabled?:boolean;restart_required?:boolean};
  decks_config:{enabled?:boolean;restart_required?:boolean};arena_config:{enabled?:boolean;restart_required?:boolean};
  full_card_resources?:{cached:number;bytes:number;total:number;locale:string;batch:Batch;last_error:string};
  arena:{memory?:{status?:string}};cards:Cards;arena_data:ArenaData};

const getStatus=callable<[],Status>('status');
const configure=callable<[values:Partial<Settings>],Status>('configure');
const checkArenaData=callable<[],Status>('check_arena_data');
const start=callable<[],Status>('start_hud');
const stop=callable<[],Status>('stop_hud');
const retryDatabase=callable<[],Status>('retry_card_database');
const downloadAllImages=callable<[],Status>('download_all_images');
const clearImages=callable<[],Status>('clear_card_images');
const cancelImageDownload=callable<[],Status>('cancel_image_download');
const downloadAllFullImages=callable<[],Status>('download_all_full_card_images');
const cancelFullDownload=callable<[],Status>('cancel_full_card_download');
const clearFullImages=callable<[],Status>('clear_full_card_images');
const clearDatabase=callable<[locale:string],Status>('clear_card_database');
const diagnosticText=callable<[],string>('diagnostic_text');

const UPDATE_URL='https://github.com/ohxiaoguang/hearthstone-hud/releases/latest/download/hearthstone-hud.zip';

const box={fontSize:13,lineHeight:1.45,padding:'6px 2px',overflowWrap:'anywhere' as const};
const row={display:'flex',alignItems:'center',gap:'8px',flexWrap:'wrap' as const,fontSize:12,lineHeight:1.5,padding:'4px 2px'};

function Fold({title,openLabel,closeLabel,children}:{title:string;openLabel:string;closeLabel:string;children:ReactNode}){
 const [open,setOpen]=useState(false);
 return <div style={{margin:'6px 0'}}>
  <ButtonItem layout="below" onClick={()=>setOpen(value=>!value)}>{(open?closeLabel:openLabel)} · {title}</ButtonItem>
  {open&&<div style={box}>{children}</div>}
 </div>;
}
function SmallButton({children,onClick,disabled}:{children:ReactNode;onClick:()=>void;disabled?:boolean}){
 return <DialogButton disabled={disabled} onClick={onClick}
   style={{width:'auto',minWidth:0,padding:'6px 14px',fontSize:12,lineHeight:1.2}}>{children}</DialogButton>;
}
function size(bytes:number){
 if(!bytes)return '0 B';
 if(bytes<1024)return `${bytes} B`;
 if(bytes<1024*1024)return `${(bytes/1024).toFixed(0)} KB`;
 return `${(bytes/1024/1024).toFixed(1)} MB`;
}

const arenaResultKey:Record<ArenaResult,string>={
 idle:'arenaDataIdle',checking:'arenaDataChecking',downloading:'arenaDataDownloading',
 unchanged:'arenaDataUnchanged',updated:'arenaDataUpdated',failed:'arenaDataFailed',
};

function ArenaDataPanel({data,lang,automatic,busy,onToggle,onCheck}:{
 data:ArenaData;lang:UiLang;automatic:boolean;busy:boolean;onToggle:(enabled:boolean)=>void;onCheck:()=>void;
}){
 const t=(key:string)=>tr(lang,key);
 const format=(value?:string|number)=>{
  if(!value)return '—';
  const date=new Date(typeof value==='number'?value*1000:value);
  return Number.isNaN(date.getTime())?'—':date.toLocaleString(lang,{dateStyle:'medium',timeStyle:'short'});
 };
 return <Fold title={t('arenaData')} openLabel={t('expand')} closeLabel={t('collapse')}>
  <ToggleField label={t('arenaDataAuto')} checked={automatic} disabled={busy} onChange={onToggle}/>
  <div style={box}>
   <strong>{t('arenaCardRatings')}</strong>
   <div>{data.cards.source || '—'}</div>
   <div>{t('arenaDataCaptured')} · {format(data.cards.captured_at)}</div>
  </div>
  <div style={box}>
   <strong>{t('arenaClassRatings')}</strong>
   <div>{data.classes.source || '—'}</div>
   <div>{t('arenaNormal')} · {format(data.classes.dates.arena)}</div>
   <div>{t('arenaUnderground')} · {format(data.classes.dates['arena-underground'])}</div>
  </div>
  <div role="status" style={box}>
   <div>{t('arenaDataLastCheck')} · {format(data.last_checked)}</div>
   {data.running&&<progress aria-label={t('arenaDataChecking')} style={{width:'100%'}}/>}
   <div>{t('arenaCardRatings')} · {t(arenaResultKey[data.results['arena_ratings.json']])}</div>
   <div>{t('arenaClassRatings')} · {t(arenaResultKey[data.results['arena_class_ratings.json']])}</div>
  </div>
  <ButtonItem layout="below" disabled={busy||data.running} onClick={onCheck}>{t('arenaDataCheckNow')}</ButtonItem>
 </Fold>;
}

type Confirm={kind:'database';code:string}|{kind:'images'}|{kind:'fullImages'}|null;

function Content(){
 const [data,setData]=useState<Status>();const [error,setError]=useState('');
 const [busy,setBusy]=useState(false);const [action,setAction]=useState('');
 const [copyState,setCopyState]=useState('');const [manualCopy,setManualCopy]=useState('');
 const [updateCopyState,setUpdateCopyState]=useState('');
 const [confirm,setConfirm]=useState<Confirm>(null);
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
 const copyUpdateLink=async()=>{
  try{await copyText(UPDATE_URL);setUpdateCopyState(t('updateLinkCopied'));}
  catch(e){setUpdateCopyState(t('copyFailed',{error:String(e)}));}
 };
 const cards=data?.cards;const databases=cards?.databases??{};const usage=cards?.image_usage;const batch=cards?.image_batch;
 const full=data?.full_card_resources;const fullBatch=full?.batch;const fullBatchRunning=fullBatch?.status==='running';
 const done=Math.min(batch?.total??0,(batch?.success??0)+(batch?.failed??0)+(batch?.missing??0)+(batch?.skipped??0));
 const downloading=cards?.download_phase==='prepare'||cards?.download_phase==='running';
 const batchRunning=batch?.status==='running';
 const databaseLabel=(code:string)=>code==='enUS'?t('databaseEnglish'):t('databaseChinese');
 const databaseState=(info:Database)=>{
  if(info.exists)return info.active?t('databaseActive'):t('databaseReady');
  return info.active&&downloading?t('databasePending'):t('databaseMissing');
 };
 const finishConfirm=async()=>{
  const job=confirm;
  setConfirm(null);
  if(!job)return;
  if(job.kind==='database')await background(t('applying'),()=>clearDatabase(job.code));
  else await background(t('applying'),job.kind==='fullImages'?clearFullImages:clearImages);
 };
 return <PanelSection title={t('title',{version:data?.version??'…'})}>
 <PanelSectionRow><div style={box}>{data?.running?t('hudOn'):t('hudOff')}{(error||data?.error)&&<div role="alert" style={{color:'#ffbdad'}}>{error||data?.error}</div>}</div></PanelSectionRow>
 {data&&<>
 <DropdownItem label={t('languageOptions')} rgOptions={UI_LANGUAGES.map(entry=>({data:entry.code,label:entry.label}))} selectedOption={data.settings.ui_language} onChange={option=>change({ui_language:option.data as UiLang})}/>
 <PanelSectionRow><div style={box}>{t('languageNote')}</div></PanelSectionRow>
 <ToggleField label={t('enable')} description={t('enableDesc')} checked={data.settings.enabled} disabled={busy||data.lifecycle==='stopping'||data.lifecycle==='starting'} onChange={enabled=>background(enabled?t('restoring'):t('stopping'),()=>configure({enabled}))}/>
 {action&&<PanelSectionRow><div role="status" style={box}>{action}</div></PanelSectionRow>}
 {data.settings.enabled?<>
 <ToggleField label={t('hud')} checked={data.running&&data.settings.visible} disabled={busy} onChange={enabled=>background(t('applying'),enabled?start:stop)}/>
 <ToggleField label={t('arena')} description={t('arenaDesc')} checked={data.settings.arena&&data.settings.arena_memory} disabled={busy} onChange={enabled=>change({arena:enabled,arena_memory:enabled})}/>
 {data.arena_data&&<ArenaDataPanel data={data.arena_data} lang={lang} automatic={data.settings.arena_data_auto_update}
   busy={busy} onToggle={arena_data_auto_update=>change({arena_data_auto_update})} onCheck={()=>run(checkArenaData)}/>}
 {data.running&&(data.power_config.restart_required||data.decks_config.restart_required||data.arena_config.restart_required)&&<PanelSectionRow><div role="status" style={box}>{t('logsRestart')}</div></PanelSectionRow>}
 {data.running&&data.process.found&&(!data.decks_config.enabled||!data.arena_config.enabled)&&<PanelSectionRow><div role="alert" style={box}>{t('logsPending')}</div></PanelSectionRow>}
 {data.settings.arena_memory&&data.arena.memory?.status&&<PanelSectionRow><div style={box}>{data.arena.memory.status}</div></PanelSectionRow>}
 {(downloading&&!action)&&<PanelSectionRow><div role="status" style={box}><progress aria-label={t('downloadAria')} style={{width:'100%'}}/>{cards?.download_state}</div></PanelSectionRow>}
 {!downloading&&!cards?.count&&<><PanelSectionRow><div role="alert" style={box}>{t('cardsMissing')}</div></PanelSectionRow><ButtonItem layout="below" disabled={busy} onClick={()=>run(retryDatabase)}>{t('retry')}</ButtonItem></>}
 <Fold title={t('display')} openLabel={t('expand')} closeLabel={t('collapse')}>
 <SliderField label={t('fontSize')} value={data.settings.font_size} min={14} max={30} step={1} onChange={font_size=>change({font_size})}/>
 <SliderField label={t('panelWidth')} value={data.settings.panel_width} min={180} max={640} step={10} onChange={panel_width=>change({panel_width})}/>
 <SliderField label={t('scale')} value={data.settings.scale} min={.5} max={3} step={.1} onChange={scale=>change({scale})}/>
 <SliderField label={t('previewScale')} value={data.settings.preview_scale??1} min={.5} max={2} step={.1} onChange={preview_scale=>change({preview_scale})}/>
 <PanelSectionRow><div style={box}>{t('previewScaleNote')}</div></PanelSectionRow>
 <SliderField label={t('opacity')} value={data.settings.opacity} min={.1} max={1} step={.05} onChange={opacity=>change({opacity})}/>
 {(['own_deck','opponent_played','own_played','secret_hints','show_summary','hide_exhausted'] as const).map((key,i)=><ToggleField key={key} label={[t('ownDeck'),t('opponentPlayed'),t('ownPlayed'),t('secretHints'),t('summary'),t('hideExhausted')][i]} checked={data.settings[key]} onChange={v=>change({[key]:v})}/>)}
 {(['x','y','right_x','right_y'] as const).map((key,i)=><SliderField key={key} label={[t('leftX'),t('leftY'),t('rightX'),t('rightY')][i]} value={data.settings[key]} min={0} max={[1920,1080,1920,1080][i]} step={10} onChange={v=>change({[key]:v})}/>)}
 </Fold>
 <Fold title={t('resources')} openLabel={t('expand')} closeLabel={t('collapse')}>
 <div style={{fontWeight:600,padding:'4px 2px'}}>{t('databases')}</div>
 {(['enUS','zhCN'] as const).map(code=>{
  const info=databases[code];if(!info)return null;
  return <div key={code} style={row}>
   <span style={{flex:'1 1 140px'}}>{databaseLabel(code)}</span>
   <span style={{opacity:.8}}>{info.exists?size(info.bytes):'—'}</span>
   <span style={{opacity:.8}}>{databaseState(info)}</span>
   <SmallButton disabled={busy||!info.exists} onClick={()=>setConfirm({kind:'database',code})}>{t('delete')}</SmallButton>
  </div>;
 })}
 <div style={{fontWeight:600,padding:'8px 2px 4px'}}>{t('images')}</div>
 <div style={row}>
  <span style={{flex:'1 1 160px'}}>{t('imagesCached',{cached:usage?.cached??0,total:usage?.total??0})}</span>
  <span style={{opacity:.8}}>{t('imagesOnDisk',{size:size(usage?.bytes??0)})}</span>
 </div>
 {batchRunning&&<PanelSectionRow><div role="status" style={box}>
  <progress aria-label={t('downloadAria')} value={batch?.total?done/batch.total:0} style={{width:'100%'}}/>
  {t('imageBatchRunning',{done,total:batch?.total??0,failed:batch?.failed??0,missing:batch?.missing??0,retried:batch?.retried??0})}
  <div style={{marginTop:'6px'}}><SmallButton disabled={busy} onClick={()=>background(t('applying'),cancelImageDownload)}>{t('cancel')}</SmallButton></div>
 </div></PanelSectionRow>}
 {batch?.status==='complete'&&<PanelSectionRow><div role="status" style={box}>
  {t('imageBatchDone',{total:batch?.total??0,success:batch?.success??0,failed:batch?.failed??0,missing:batch?.missing??0,skipped:batch?.skipped??0})}
 </div></PanelSectionRow>}
 <PanelSectionRow><div style={row}>
  <SmallButton disabled={busy||batchRunning||!cards?.count} onClick={()=>background(t('applying'),downloadAllImages)}>{t('downloadAllImages')}</SmallButton>
  <SmallButton disabled={busy||batchRunning||!(usage?.cached??0)} onClick={()=>setConfirm({kind:'images'})}>{t('clearImages')}</SmallButton>
 </div></PanelSectionRow>
 <PanelSectionRow><div style={box}>{t('imagesNote')}</div></PanelSectionRow>
 <div style={{fontWeight:600,padding:'8px 2px 4px'}}>{t('fullImages')} · {full?.locale??cards?.language}</div>
 <div style={row}>
  <span style={{flex:'1 1 160px'}}>{t('imagesCached',{cached:full?.cached??0,total:full?.total??0})}</span>
  <span style={{opacity:.8}}>{t('imagesOnDisk',{size:size(full?.bytes??0)})}</span>
 </div>
 {fullBatchRunning&&<PanelSectionRow><div role="status" style={box}>
  <progress aria-label={t('fullDownloadAria')} value={fullBatch?.total?(fullBatch.done??0)/fullBatch.total:0} style={{width:'100%'}}/>
  {t('fullBatchRunning',{done:fullBatch?.done??0,total:fullBatch?.total??0,failed:fullBatch?.failed??0,missing:fullBatch?.missing??0,retried:fullBatch?.retried??0})}
  <div style={{marginTop:'6px'}}><SmallButton disabled={busy} onClick={()=>background(t('applying'),cancelFullDownload)}>{t('cancel')}</SmallButton></div>
 </div></PanelSectionRow>}
 {fullBatch?.status==='complete'&&<PanelSectionRow><div role="status" style={box}>
  {t('fullBatchDone',{total:fullBatch.total,success:fullBatch.success,failed:fullBatch.failed,missing:fullBatch.missing??0,skipped:fullBatch.skipped})}
 </div></PanelSectionRow>}
 {fullBatch?.status==='cancelled'&&<PanelSectionRow><div role="status" style={box}>{t('fullBatchCancelled')}</div></PanelSectionRow>}
 {(fullBatch?.failed??0)>0&&full?.last_error&&<PanelSectionRow><div role="alert" style={box}>{full.last_error}</div></PanelSectionRow>}
 <PanelSectionRow><div style={row}>
  <SmallButton disabled={busy||fullBatchRunning||!cards?.count} onClick={()=>background(t('applying'),downloadAllFullImages)}>{t('downloadAllFullImages')}</SmallButton>
  <SmallButton disabled={busy||fullBatchRunning||!(full?.bytes??0)} onClick={()=>setConfirm({kind:'fullImages'})}>{t('clearFullImages')}</SmallButton>
 </div></PanelSectionRow>
 <PanelSectionRow><div style={box}>{t('fullImagesNote')}</div></PanelSectionRow>
 </Fold>
 <Fold title={t('about')} openLabel={t('expand')} closeLabel={t('collapse')}>
 <PanelSectionRow><div style={box}>
  <div>{t('aboutBody')}</div>
  <div style={{marginTop:'6px'}}>{t('version',{version:data?.version??'—'})}</div>
  <div style={{marginTop:'4px'}}>{t('repository')}: {data?.repository??'https://github.com/ohxiaoguang/hearthstone-hud'}</div>
 </div></PanelSectionRow>
 </Fold>
 </>:<PanelSectionRow><div style={box}>{data.lifecycle==='disabled'?t('disabled'):t('stopping')}</div></PanelSectionRow>}
 <PanelSectionRow><div style={{...row,flexWrap:'nowrap'}}>
  <SmallButton onClick={copyDiagnostic}>{t('copyDiagnostic')}</SmallButton>
  <SmallButton onClick={copyUpdateLink}>{t('copyUpdateLink')}</SmallButton>
 </div></PanelSectionRow>
 {updateCopyState&&<PanelSectionRow><div role="status" style={box}>{updateCopyState}</div></PanelSectionRow>}
 {copyState&&<PanelSectionRow><div role="status" style={box}>{copyState}</div></PanelSectionRow>}
 {manualCopy&&<textarea aria-label={t('manualAria')} readOnly value={manualCopy} onFocus={e=>e.currentTarget.select()} style={{width:'100%',height:180,fontSize:12,userSelect:'text',boxSizing:'border-box'}}/>}
 </>}
 {confirm&&<PanelSectionRow><div role="alertdialog" style={box}>
  <div>{confirm.kind==='database'?t('confirmDeleteDatabase',{language:databaseLabel(confirm.code)}):t(confirm.kind==='fullImages'?'confirmClearFullImages':'confirmClearImages')}</div>
  <div style={{marginTop:'4px',opacity:.8}}>{confirm.kind==='database'?t('confirmDeleteDatabaseBody'):t(confirm.kind==='fullImages'?'confirmClearFullImagesBody':'confirmClearImagesBody')}</div>
  <div style={{...row,marginTop:'8px'}}>
   <SmallButton disabled={busy} onClick={finishConfirm}>{confirm.kind==='database'?t('delete'):t(confirm.kind==='fullImages'?'clearFullImages':'clearImages')}</SmallButton>
   <SmallButton disabled={busy} onClick={()=>setConfirm(null)}>{t('cancel')}</SmallButton>
  </div>
 </div></PanelSectionRow>}
 </PanelSection>;
}
export default definePlugin(()=>({name:'Hearthstone HUD',titleView:<div>Hearthstone HUD</div>,content:<Content/>,icon:<FaLayerGroup/>}));
