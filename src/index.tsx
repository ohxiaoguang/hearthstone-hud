import { ButtonItem, PanelSection, PanelSectionRow, TextField, SliderField, ToggleField } from '@decky/ui';
import { callable, definePlugin } from '@decky/api';
import { useEffect, useState } from 'react';
import { FaLayerGroup } from 'react-icons/fa';
type Settings = {game_dir:string;proton_prefix:string;log_dir:string;display:string;x:number;y:number;scale:number;opacity:number;visible:boolean;own_deck:boolean;opponent_deck:boolean;opponent_hand:boolean;arena:boolean;right_x:number;right_y:number;card_images:boolean;chinese_names:boolean};
type Status = {gamescope_running:boolean;settings:Settings;running:boolean;error:string;diagnostic:unknown;log_path:string;parse_errors:number;arena:string;visibility:string;gamescope_status:string;logs:unknown;cards:{count:number;state:string;download_state:string;source:string;updated:number;error:string};tracking:unknown;process:{found?:boolean;prefix?:string;pid?:number};power_config:{exists?:boolean;enabled?:boolean;restart_required?:boolean;path?:string;state?:string};log_status:string;decks_config:{enabled?:boolean;restart_required?:boolean;state?:string};match_status:string;identity_status:string;deck_status:string;decks_log_status:string};
const status = callable<[],Status>('status');
const configure = callable<[values:Partial<Settings>],Status>('configure');
const start = callable<[],Status>('start_hud');
const stop = callable<[],Status>('stop_hud');
const enableDecks = callable<[],Status>('enable_decks_logging');
const importDatabase = callable<[path:string],Status>('import_card_database');
const retryDatabase = callable<[],Status>('retry_card_database');
function PathField({label,value,save}:{label:string;value:string;save:(value:string)=>void}){
 const [draft,setDraft]=useState(value);
 return <TextField label={label} value={draft} onChange={e=>setDraft(e.target.value)} onBlur={()=>{if(draft!==value)save(draft);}}/>;
}
function Content(){
 const [data,setData]=useState<Status>();const [error,setError]=useState('');
 const [importPath,setImportPath]=useState('/home/deck/Downloads/cards-zhCN.json');
 const [dbBusy,setDbBusy]=useState(false);
 const run=async(job:()=>Promise<Status>)=>{try{setData(await job());setError('');}catch(e){setError(String(e));}};
 useEffect(()=>{let alive=true;const refresh=()=>{status().then(d=>{if(alive)setData(d);}).catch(e=>{if(alive)setError(String(e));});};refresh();const timer=setInterval(refresh,2000);return()=>{alive=false;clearInterval(timer);};},[]);
 const change=(values:Partial<Settings>)=>run(()=>configure(values));
 const databaseJob=async(job:()=>Promise<Status>)=>{setDbBusy(true);try{await run(job);}finally{setDbBusy(false);}};
 return <PanelSection title="炉石记牌器 · v0.2.2">
 <PanelSectionRow><div>{data?.running?'HUD 进程运行中':'HUD 已停止'}<br/>{error||data?.error}</div></PanelSectionRow>
 <ButtonItem onClick={()=>run(start)}>启动记牌 HUD</ButtonItem>
 <ButtonItem onClick={()=>run(stop)}>停止并退出</ButtonItem>
 {data && <>
 <PanelSection title="日志与卡牌数据">
 <div style={{fontSize:12}}>{data.log_status}<br/>{data.match_status}；{data.identity_status}<br/>{data.deck_status}<br/>{data.decks_log_status}<br/>Decks 配置：{data.decks_config.enabled?'已启用':'未启用'}<br/>{data.cards.state}（{data.cards.count} 张）<br/>{data.cards.download_state}<br/>来源：{data.cards.source}<br/>缓存更新：{data.cards.updated?new Date(data.cards.updated*1000).toLocaleString():'尚无'}<br/>{data.cards.error}</div>
 <ButtonItem disabled={data.decks_config.enabled} onClick={()=>run(enableDecks)}>备份并启用 Decks 日志</ButtonItem>
 <ButtonItem disabled={dbBusy} onClick={()=>databaseJob(retryDatabase)}>重试下载卡牌数据库</ButtonItem>
 <TextField label="离线 zhCN JSON 绝对路径" value={importPath} onChange={e=>setImportPath(e.target.value)}/>
 <ButtonItem disabled={dbBusy} onClick={()=>databaseJob(()=>importDatabase(importPath))}>校验并导入离线数据库</ButtonItem>
 </PanelSection>
 <ToggleField label="显示 HUD" checked={data.settings.visible} onChange={visible=>change({visible})}/>
 {(['game_dir','log_dir','display'] as const).map((key,i)=><PathField key={key} label={['游戏目录（自动发现失败时备用）','日志目录或 Power.log（空白自动检测）','X11 DISPLAY（重启 HUD 生效）'][i]} value={data.settings[key]} save={value=>change({[key]:value})}/>)}
 {(['x','y','scale','opacity','right_x','right_y'] as const).map((key,i)=><SliderField key={key} label={['左侧横向位置','左侧纵向位置','缩放','面板不透明度','右侧横向位置','右侧纵向位置'][i]} value={data.settings[key]} min={[0,0,.5,.1,0,0][i]} max={[1920,1080,3,1,1920,1080][i]} step={[10,10,.1,.05,10,10][i]} onChange={v=>change({[key]:v})}/>)}
 {(['own_deck','opponent_deck','opponent_hand','card_images','chinese_names'] as const).map((key,i)=><ToggleField key={key} label={['左侧己方牌库','右侧对手公开卡牌','对手手牌数量','卡牌缩略图','简体中文名称'][i]} checked={data.settings[key]} onChange={v=>change({[key]:v})}/>)}
 <PanelSection title="诊断"><div style={{fontSize:12,overflowWrap:'anywhere'}}>Gamescope 进程：{data.gamescope_status}<br/>游戏进程：{data.process.found?`已发现 PID ${data.process.pid??'未知'}`:'未发现'}<br/>当前 Proton 前缀：{data.process.prefix||'未发现'}<br/>log.config：{data.power_config.exists?'存在':'不存在'}；Power：{data.power_config.enabled?'已启用':'未启用'}<br/>日志状态：{data.log_status}<br/>{(data.power_config.restart_required||data.decks_config.restart_required)?'请完全退出并重新启动炉石，以加载新配置。':''}<br/>Power.log：{data.log_path||'尚未生成'}<br/>{data.visibility}<br/>{data.arena}<br/>解析错误：{data.parse_errors}<pre style={{whiteSpace:'pre-wrap'}}>{JSON.stringify({render:data.diagnostic,logs:data.logs,process:data.process,power_config:data.power_config,decks_config:data.decks_config,cards:data.cards},null,2)}</pre></div></PanelSection>
 </>}
 </PanelSection>;
}
export default definePlugin(()=>({name:'Hearthstone HUD',titleView:<div>Hearthstone HUD</div>,content:<Content/>,icon:<FaLayerGroup/>}));
