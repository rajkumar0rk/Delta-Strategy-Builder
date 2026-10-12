import {RuleBuilder} from './RuleBuilder';
import type {AlertRule,RuleGroup} from '../types';

export function AlertEditor({value,operands,onChange}:{value:AlertRule[];operands:string[];onChange:(alerts:AlertRule[])=>void}){
 const update=(id:string,change:Partial<AlertRule>)=>onChange(value.map(a=>a.id===id?{...a,...change}:a));
 const add=()=>{let i=1;while(value.some(a=>a.id==='alert_'+i))i++;onChange([...value,{id:'alert_'+i,name:'Alert '+i,message:'Alert '+i+' triggered',enabled:true,direction:'NEUTRAL',trigger_mode:'ON_ENTER',cooldown_bars:0,conditions:{mode:'ALL',min_pass:1,conditions:[],groups:[]}}])};
 return <section className="card">
  <div className="card-head"><div><h2>Strategy alerts</h2><p>Independent alerts use completed candles. Each has its own conditions and message. They appear on the chart without opening a trade or changing P&amp;L.</p></div><button disabled={value.length>=30} onClick={add}>+ Add alert</button></div>
  {value.map(a=><div key={a.id} className="card" style={{marginTop:12}}>
   <div className="form-grid">
    <label>Alert name<input maxLength={100} value={a.name} onChange={e=>update(a.id,{name:e.target.value})}/></label>
    <label>Alert message<input maxLength={500} value={a.message||''} onChange={e=>update(a.id,{message:e.target.value})}/></label>
    <label>Marker position<select value={a.direction} onChange={e=>update(a.id,{direction:e.target.value as AlertRule['direction']})}><option value="CALL">Bullish (below candle)</option><option value="PUT">Bearish (above candle)</option><option value="NEUTRAL">Neutral (above candle)</option></select></label>
    <label>Trigger<select value={a.trigger_mode} onChange={e=>update(a.id,{trigger_mode:e.target.value as AlertRule['trigger_mode']})}><option value="ON_ENTER">When conditions first become true</option><option value="EVERY_BAR">Every passing candle</option></select></label>
    <label>Cooldown candles<input type="number" min={0} max={10000} value={a.cooldown_bars} onChange={e=>update(a.id,{cooldown_bars:Number(e.target.value)})}/></label>
    <label className="switch"><input type="checkbox" checked={a.enabled} onChange={e=>update(a.id,{enabled:e.target.checked})}/><span>Enabled</span></label>
   </div>
   <button className="mini danger" onClick={()=>onChange(value.filter(x=>x.id!==a.id))}>Remove this alert</button>
   <RuleBuilder title={a.name+' conditions'} value={a.conditions} operands={operands} onChange={(conditions:RuleGroup)=>update(a.id,{conditions})} description="Every alert has an independent AND/OR rule tree. Empty trees do not trigger."/>
  </div>)}
 </section>;
}
