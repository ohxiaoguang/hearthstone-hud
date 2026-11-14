import { ButtonItem, PanelSection, PanelSectionRow, TextField, SliderField, ToggleField } from '@decky/ui';
import { callable, definePlugin } from '@decky/api';
import { useEffect, useState, type ReactNode } from 'react';
import { FaLayerGroup } from 'react-icons/fa';
import { copyText } from './clipboard';
import { ArenaEditor, type ArenaView } from './arena';
type Settings = {game_dir:string;proton_prefix:string;log_dir:string;display:string;x:number;y:number;scale:number;opacity:number;visible:boolean;own_deck:boolean;opponent_deck:boolean;opponent_hand:boolean;arena:boolean;right_x:number;right_y:number;card_images:boolean;image_tls_verify:boolean;database_tls_verify:boolean;own_played:boolean;opponent_played:boolean;show_summary:boolean;panel_width:number;hide_exhausted:boolean;chinese_names:boolean};
type ImportResult = {found:number;imported:number;skipped:number;format_errors:number;invalid_ids:number;other_failures:number;errors:string[]};
type Status = {arena:ArenaView;arena_log_status:string;arena_config:{enabled?:boolean;restart_required?:boolean};storage:{runtime:string;database:string;images:string;manual_images:string;retained_on_uninstall:boolean};version:string;settings:Settings;running:boolean;error:string;log_path:string;parse_errors:number;gamescope_status:string;
  cards:{count:number;state:string;download_state:string;source:string;updated:number;error:string;image_error:string;images_pending:number;image_cache:{manual:number;automatic:number};image_batch:{status:string;total:number;success:number;failed:number;skipped:number};image_import:ImportResult|null};
  process:{found?:boolean;prefix?:string;pid?:number};power_config:{exists?:boolean;enabled?:boolean;restart_required?:boolean};log_status:string;decks_config:{enabled?:boolean;restart_required?:boolean};match_status:string;identity_status:string;deck_status:string;decks_log_status:string};
const getStatus = callable<[],Status>('status');
const configure = callable<[values:Partial<Settings>],Status>('configure');
const start = callable<[],Status>('start_hud');
const stop = callable<[],Status>('stop_hud');
const enableArena = callable<[],Status>('enable_arena_logging');
const enableDecks = callable<[],Status>('enable_decks_logging');
const importDatabase = callable<[path:string],Status>('import_card_database');
const retryDatabase = callable<[],Status>('retry_card_database');
const downloadImages = callable<[],Status>('download_missing_images');
const importImages = callable<[path:string],Status>('import_card_images');
const diagnosticText = callable<[],string>('diagnostic_text');
const box = {fontSize:13,lineHeight:1.45,padding:'4px 2px',overflowWrap:'anywhere' as const};
function Datum({label,children}:{label:string;children:ReactNode}) {return <div style={{display:'flex',gap:8,marginBottom:3}}><span style={{opacity:.65,minWidth:76}}>{label}</span><span style={{minWidth:0,flex:1}}>{children}</span></div>;}
function Fold({title,children}:{title:string;children:ReactNode}) {
 const [open,setOpen]=useState(false);
 return <div style={{margin:'6px 0'}}>
  <ButtonItem layout="below" onClick={()=>setOpen(value=>!value)}>{open?'收起':'展开'} · {title}</ButtonItem>
  {open&&<div style={box}>{children}</div>}
 </div>;
}
function PathField({label,value,save}:{label:string;value:string;save:(value:string)=>void}){
 const [draft,setDraft]=useState(value);
 return <TextField label={label} value={draft} onChange={e=>setDraft(e.target.value)} onBlur={()=>{if(draft!==value)save(draft);}}/>;
}
function Content(){
 const [data,setData]=useState<Status>();const [error,setError]=useState('');
 const [importPath,setImportPath]=useState('/home/deck/Downloads/cards-zhCN.json');
 const [zipPath,setZipPath]=useState('/home/deck/Downloads/cards-images.zip');
 const [busy,setBusy]=useState(false);const [copyState,setCopyState]=useState('');
 const [manualCopy,setManualCopy]=useState('');
 const run=async(job:()=>Promise<Status>)=>{try{setData(await job());setError('');}catch(e){setError(String(e));}};
 useEffect(()=>{let alive=true;const refresh=()=>{getStatus().then(d=>{if(alive)setData(d);}).catch(e=>{if(alive)setError(String(e));});};refresh();const timer=setInterval(refresh,2000);return()=>{alive=false;clearInterval(timer);};},[]);
 const change=(values:Partial<Settings>)=>run(()=>configure(values));
 const background=async(job:()=>Promise<Status>)=>{setBusy(true);try{await run(job);}finally{setBusy(false);}};
 const copyDiagnostic=async()=>{
   setCopyState('正在整理诊断…');let text='';
   try {text=await diagnosticText();const method=await copyText(text);setCopyState(`已复制诊断（${method}）`);setManualCopy('');}
   catch(e){setCopyState('复制失败：'+String(e));setManualCopy(text||`Hearthstone HUD Diagnostic\n[Plugin]\nVersion: ${data?.version??'unknown'}\nStatus: ${data?.running?'running':'stopped'}\n[Recent Errors]\nBackend diagnostic retrieval failed; full diagnostic unavailable.`);}
 };
 const batch=data?.cards.image_batch;
 const imported=data?.cards.image_import;
 return <PanelSection title={`炉石记牌器 · ${data?.version??'加载中'}`}>
 <PanelSectionRow><div style={box}>{data?.running?'HUD 正在运行':'HUD 已停止'}{(error||data?.error)&&<div role="alert" style={{color:'#ffbdad'}}>{error||data?.error}</div>}</div></PanelSectionRow>
 <ButtonItem onClick={()=>run(data?.running?stop:start)}>{data?.running?'停止 HUD':'启动记牌 HUD'}</ButtonItem>
 {data && <>
 <ToggleField label="显示 HUD" checked={data.settings.visible} onChange={visible=>change({visible})}/>
 <PanelSection title="日志与卡牌数据">
 <div style={box}>
 <Datum label="日志">{data.log_status}</Datum><Datum label="对局">{data.match_status}</Datum><Datum label="双方身份">{data.identity_status}</Datum>
 <Datum label="初始牌组">{data.deck_status}</Datum><Datum label="中文数据库">{data.cards.state} · {data.cards.count} 张</Datum>
 {(data.power_config.restart_required||data.decks_config.restart_required||data.arena_config.restart_required)&&<div role="alert" style={{color:'#ffd38a'}}>配置已更新，请完全退出并重启炉石。</div>}
 </div>
 <ButtonItem onClick={copyDiagnostic}>复制诊断</ButtonItem>
 {copyState&&<div role="status" style={box}>{copyState}</div>}
 {manualCopy&&<textarea aria-label="手动复制诊断文本" readOnly value={manualCopy} onFocus={e=>e.currentTarget.select()} style={{width:'100%',height:180,fontSize:12,userSelect:'text',boxSizing:'border-box'}}/>}
 <Fold title="日志详情与 Decks 配置">
 <Datum label="游戏进程">{data.process.found?`PID ${data.process.pid??'未知'}`:'未发现'}</Datum>
 <Datum label="Proton">{data.process.prefix||'未发现'}</Datum><Datum label="Gamescope">{data.gamescope_status}</Datum>
 <Datum label="Power.log">{data.log_path||'未生成'} · 解析错误 {data.parse_errors}</Datum>
 <Datum label="Decks.log">{data.decks_log_status}</Datum><Datum label="Decks 配置">{data.decks_config.enabled?'已启用':'未启用'}</Datum>
 <ButtonItem disabled={data.decks_config.enabled} onClick={()=>run(enableDecks)}>备份并启用 Decks 日志</ButtonItem>
 </Fold>
 <Fold title="竞技场选牌与静态评分">
 <ToggleField label="显示竞技场 HUD（仅选牌时）" checked={data.settings.arena} onChange={arena=>change({arena})}/>
 <Datum label="Arena.log">{data.arena_log_status}</Datum><Datum label="Arena 配置">{data.arena_config.enabled?'已启用':'未启用'}</Datum>
 <ButtonItem disabled={data.arena_config.enabled} onClick={()=>run(enableArena)}>备份并启用 Arena 日志</ButtonItem>
 <div style={box}>修改后请完全退出并重启炉石。不会自动修改 Arena 节。需先发现竞技场 ID，再录入本轮候选或补录实际选择。</div>
 <ArenaEditor data={data.arena} onUpdate={arena=>setData(value=>value?{...value,arena}:value)}/>
 </Fold>
 <Fold title="数据库更新与离线导入">
 <Datum label="缓存文件">{data.storage.database}</Datum>
 <Datum label="来源">{data.cards.source}</Datum><Datum label="更新时间">{data.cards.updated?new Date(data.cards.updated*1000).toLocaleString():'尚无'}</Datum>
 <Datum label="下载状态">{data.cards.download_state}</Datum>{data.cards.error&&<div role="alert">{data.cards.error.slice(0,300)}</div>}
 <ToggleField label="数据库 SSL 证书校验" checked={data.settings.database_tls_verify} onChange={database_tls_verify=>change({database_tls_verify})}/>
 {!data.settings.database_tls_verify&&<div style={box}>测试模式：数据库下载跳过证书校验，仍校验 JSON 内容和数量。可打开开关恢复证书校验。</div>}
 <ButtonItem disabled={busy} onClick={()=>background(retryDatabase)}>重试下载卡牌数据库</ButtonItem>
 <TextField label="离线 zhCN JSON 路径" value={importPath} onChange={e=>setImportPath(e.target.value)}/>
 <ButtonItem disabled={busy} onClick={()=>background(()=>importDatabase(importPath))}>校验并导入离线数据库</ButtonItem>
 </Fold>
 <Fold title="卡图下载与手动导入">
 <ToggleField label="卡图 SSL 证书校验" checked={data.settings.image_tls_verify} onChange={image_tls_verify=>change({image_tls_verify})}/>
 {!data.settings.image_tls_verify&&<div style={box}>测试模式：卡图下载跳过证书校验。可随时打开上方开关恢复。</div>}
 <Datum label="卡图目录">{data.storage.images}</Datum><Datum label="手动卡图">{data.storage.manual_images}</Datum>
 <div style={box}>正常卸载插件会保留此数据目录；下载/导入源文件也不会删除。</div>
 <Datum label="缓存">手动 {data.cards.image_cache.manual} / 自动 {data.cards.image_cache.automatic}</Datum>
 <Datum label="下载进度">{batch?.status==='running'?'后台下载中':batch?.status==='complete'?'本批已完成':'尚未开始'} · {(batch?.success??0)+(batch?.failed??0)+(batch?.skipped??0)}/{batch?.total??0}</Datum>
 <Datum label="结果">成功 {batch?.success??0} · 失败 {batch?.failed??0} · 跳过 {batch?.skipped??0}</Datum>
 <Datum label="待下载">{data.cards.images_pending}</Datum>
 {data.cards.image_error&&<div role="alert">最近失败：{data.cards.image_error.slice(0,200)}</div>}
 <ButtonItem disabled={batch?.status==='running'} onClick={()=>run(downloadImages)}>下载缺失卡图</ButtonItem>
 <TextField label="平铺 CardID.png ZIP 路径" value={zipPath} onChange={e=>setZipPath(e.target.value)}/>
 <ButtonItem disabled={busy} onClick={()=>background(()=>importImages(zipPath))}>校验并导入卡图</ButtonItem>
 {imported&&<div role="status">发现 {imported.found} · 导入 {imported.imported} · 已存在 {imported.skipped} · 格式错误 {imported.format_errors} · 非法 ID {imported.invalid_ids} · 其他失败 {imported.other_failures}{imported.errors.map((s,i)=><div key={i}>{s}</div>)}</div>}
 </Fold>
 </PanelSection>
 <Fold title="HUD 布局与显示设置">
 <div style={box}>右侧只放己方剩余牌库。左侧两个出牌面板可独立开关，同时开启时上下各占一半；只开一个时占满左侧。</div>
 {(['game_dir','log_dir','display'] as const).map((key,i)=><PathField key={key} label={['游戏目录（自动发现备用）','日志目录或 Power.log','X11 DISPLAY（重启 HUD 生效）'][i]} value={data.settings[key]} save={value=>change({[key]:value})}/>)}
 {(['x','y','scale','opacity','right_x','right_y','panel_width'] as const).map((key,i)=><SliderField key={key} label={['左侧出牌横向位置','左侧出牌纵向位置','缩放','面板不透明度','右侧牌库横向位置','右侧牌库纵向位置','面板宽度（随缩放）'][i]} value={data.settings[key]} min={[0,0,.5,.1,0,0,180][i]} max={[1920,1080,3,1,1920,1080,640][i]} step={[10,10,.1,.05,10,10,10][i]} onChange={v=>change({[key]:v})}/>)}
 {(['own_deck','opponent_played','own_played','show_summary','hide_exhausted','opponent_hand','card_images','chinese_names'] as const).map((key,i)=><ToggleField key={key} label={['右侧己方剩余牌库','左侧对手已打出','左侧我方已打出','显示顶部信息','隐藏已耗尽原牌（关闭则置灰）','顶部对手手牌数量','卡图背景','简体中文名称'][i]} checked={data.settings[key]} onChange={v=>change({[key]:v})}/>)}
 </Fold>
 </>}
 </PanelSection>;
}
export default definePlugin(()=>({name:'Hearthstone HUD',titleView:<div>Hearthstone HUD</div>,content:<Content/>,icon:<FaLayerGroup/>}));
