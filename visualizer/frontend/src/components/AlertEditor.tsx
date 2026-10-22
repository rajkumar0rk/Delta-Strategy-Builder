import type {AlertRule,AlertSource,Strategy,Condition,RuleGroup} from '../types';
const choices:[AlertSource,string,keyof Strategy][]=[
 ['CALL_ENTRY','CALL entry','call_entry'],['PUT_ENTRY','PUT entry','put_entry'],
 ['CALL_EXIT','CALL exit','call_exit'],['PUT_EXIT','PUT exit','put_exit'],
 ['NO_TRADE','Shared NO TRADE','no_trade'],['CALL_NO_TRADE','CALL NO TRADE','call_no_trade'],['PUT_NO_TRADE','PUT NO TRADE','put_no_trade'],
];
function descendants(group:RuleGroup):Condition[]{return [...group.conditions,...group.groups.flatMap(descendants)]}
export function AlertEditor({value,strategy,operands=[],onChange}:{value:AlertRule[];strategy:Strategy;operands?:string[];onChange:(alerts:AlertRule[])=>void}){
 const update=(id:string,change:Partial<AlertRule>)=>onChange(value.map(a=>a.id===id?{...a,...change}:a));
 const add=()=>{let i=1;while(value.some(a=>a.id==='alert_'+i))i++;onChange([...value,{id:'alert_'+i,name:'Alert '+i,message:'Alert '+i+' triggered',enabled:true,direction:'NEUTRAL',trigger_mode:'ON_ENTER',cooldown_bars:0,source:'CALL_ENTRY',condition_id:null,conditions:{mode:'ALL',min_pass:1,conditions:[],groups:[]}}])};
 return <section className="card"><div className="card-head"><div><h2>Strategy warning alerts</h2><p>Reuse existing entry, exit or no-trade conditions. Each warning has its own message, trigger and enabled switch; no second condition builder.</p></div><button disabled={value.length>=30} onClick={add}>+ Add warning alert</button></div>
 {value.map(a=>{const source=a.source||'LEGACY_CUSTOM';const key=choices.find(x=>x[0]===source)?.[2];const rule=key?strategy[key] as RuleGroup:null;const conditions=rule?descendants(rule):[];return <div key={a.id} className="card" style={{marginTop:12}}>
 <div className="form-grid">
 <label>Name<input maxLength={100} value={a.name} onChange={e=>update(a.id,{name:e.target.value})}/></label>
 <label>Message<input maxLength={500} value={a.message||''} onChange={e=>update(a.id,{message:e.target.value})}/></label>
 <label>Existing rule<select value={source} onChange={e=>update(a.id,{source:e.target.value as AlertSource,condition_id:null})}>{choices.map(([id,label])=><option value={id} key={id}>{label}</option>)}{source==='LEGACY_CUSTOM'&&<option value="LEGACY_CUSTOM">Imported legacy custom rules</option>}</select></label>
 {rule&&<label>Signal source<select value={a.condition_id||''} onChange={e=>update(a.id,{condition_id:e.target.value||null})}><option value="">Whole existing rule group</option>{conditions.filter(c=>!!c.id).map(c=><option value={c.id} key={c.id}>{c.id}: {c.left} {c.operator} {c.right??c.value}</option>)}</select></label>}
 <label>Marker<select value={a.direction} onChange={e=>update(a.id,{direction:e.target.value as AlertRule['direction']})}><option value="CALL">Bullish (below)</option><option value="PUT">Bearish (above)</option><option value="NEUTRAL">Neutral</option></select></label>
 <label>Trigger<select value={a.trigger_mode} onChange={e=>update(a.id,{trigger_mode:e.target.value as AlertRule['trigger_mode']})}><option value="ON_ENTER">First true candle</option><option value="EVERY_BAR">Every passing candle</option></select></label>
 <label>Rearm when value changes<select value={a.reset_operand||''} onChange={e=>update(a.id,{reset_operand:e.target.value||null})}><option value="">Keep normal transition / cooldown</option>{operands.map(o=><option key={o} value={o}>{o}</option>)}</select></label>
 <label>Cooldown candles<input type="number" min={0} max={10000} value={a.cooldown_bars} onChange={e=>update(a.id,{cooldown_bars:Number(e.target.value)})}/></label>
 <label className="switch"><input type="checkbox" checked={a.enabled} onChange={e=>update(a.id,{enabled:e.target.checked})}/><span>Enabled</span></label>
 </div>
 {source==='LEGACY_CUSTOM'&&<p>Imported legacy alert conditions remain supported. You can switch to any current strategy rule.</p>}
 {rule&&!rule.conditions.length&&!rule.groups.length&&<p>No conditions in this strategy rule yet; it will not trigger.</p>}
 <button className="mini danger" onClick={()=>onChange(value.filter(x=>x.id!==a.id))}>Remove warning</button>
 </div>})}</section>;
}

