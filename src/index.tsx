import { ButtonItem, PanelSection, PanelSectionRow, TextField, SliderField, ToggleField } from '@decky/ui';
import { callable, definePlugin } from '@decky/api';
import { useEffect, useState } from 'react';
import { FaLayerGroup } from 'react-icons/fa';
type Settings = {game_dir:string;proton_prefix:string;log_dir:string;display:string;x:number;y:number;scale:number;opacity:number;visible:boolean;own_deck:boolean;opponent_deck:boolean;opponent_hand:boolean;arena:boolean};
type Status = {gamescope_running:boolean;settings:Settings;running:boolean;error:string;diagnostic:unknown;log_path:string;parse_errors:number;arena:string;visibility:string};
const status = callable<[],Status>('status');
const configure = callable<[values:Partial<Settings>],Status>('configure');
const start = callable<[],Status>('start_hud');
const stop = callable<[],Status>('stop_hud');
function PathField({label,value,save}:{label:string;value:string;save:(value:string)=>void}){
 const [draft,setDraft]=useState(value);
 return <TextField label={label} value={draft} onChange={e=>setDraft(e.target.value)} onBlur={()=>{if(draft!==value)save(draft);}}/>;
}
function Content(){
 const [data,setData]=useState<Status>();const [error,setError]=useState('');
 const run=async(job:()=>Promise<Status>)=>{try{setData(await job());setError('');}catch(e){setError(String(e));}};
 useEffect(()=>{let alive=true;const refresh=()=>{status().then(d=>{if(alive)setData(d);}).catch(e=>{if(alive)setError(String(e));});};refresh();const timer=setInterval(refresh,2000);return()=>{alive=false;clearInterval(timer);};},[]);
 const change=(values:Partial<Settings>)=>run(()=>configure(values));
 return <PanelSection title="炉石记牌器 · 实机验证版">
 <PanelSectionRow><div>{data?.running?'HUD 进程运行中':'HUD 已停止'}<br/>{error||data?.error}</div></PanelSectionRow>
 <ButtonItem onClick={()=>run(start)}>启动测试 HUD</ButtonItem>
 <ButtonItem onClick={()=>run(stop)}>停止并退出</ButtonItem>
 {data && <>
 <ToggleField label="显示 HUD" checked={data.settings.visible} onChange={visible=>change({visible})}/>
 {(['game_dir','proton_prefix','log_dir','display'] as const).map((key,i)=><PathField key={key} label={['游戏安装目录','Proton 前缀','日志目录（空白自动检测）','X11 DISPLAY（重启 HUD 生效）'][i]} value={data.settings[key]} save={value=>change({[key]:value})}/>)}
 {(['x','y','scale','opacity'] as const).map((key,i)=><SliderField key={key} label={['横向位置','纵向位置','缩放','背景透明度'][i]} value={data.settings[key]} min={[0,0,.5,.1][i]} max={[1920,1080,3,1][i]} step={[10,10,.1,.05][i]} onChange={v=>change({[key]:v})}/>)}
 {(['own_deck','opponent_deck','opponent_hand','arena'] as const).map((key,i)=><ToggleField key={key} label={['己方牌库数量','对手牌库数量','对手手牌数量','竞技场评分（尚未接入）'][i]} checked={data.settings[key]} onChange={v=>change({[key]:v})}/>)}
 <PanelSection title="诊断"><div style={{fontSize:12,overflowWrap:'anywhere'}}>Gamescope 进程：{data.gamescope_running?'已检测到':'未检测到'}<br/>日志：{data.log_path||'未发现'}<br/>{data.visibility}<br/>{data.arena}<br/>解析错误：{data.parse_errors}<pre style={{whiteSpace:'pre-wrap'}}>{JSON.stringify(data.diagnostic,null,2)}</pre></div></PanelSection>
 </>}
 </PanelSection>;
}
export default definePlugin(()=>({name:'Hearthstone HUD',titleView:<div>Hearthstone HUD</div>,content:<Content/>,icon:<FaLayerGroup/>}));
