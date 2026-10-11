import type {Condition,EntryBehavior,RuleGroup} from '../types';

function flatten(g:RuleGroup):Condition[]{return [...g.conditions,...g.groups.flatMap(flatten)]}
function label(c:Condition){const rhs=c.right??c.value??'';const extra=['GT_BY_POINTS','LT_BY_POINTS','GT_BY_PERCENT','LT_BY_PERCENT'].includes(c.operator)?` margin ${c.value}`:'';return `${c.left} ${c.operator} ${rhs}${extra}`}
function nextId(side:'CALL'|'PUT',items:EntryBehavior[]){let n=items.length+1;let id=`${side.toLowerCase()}-life-${n}`;while(items.some(x=>x.id===id)){n++;id=`${side.toLowerCase()}-life-${n}`}return id}
function fresh(side:'CALL'|'PUT',items:EntryBehavior[]):EntryBehavior{const id=nextId(side,items);return {id,name:`${side} lifecycle ${items.length+1}`,enabled:true,trigger_condition_id:null,delay_bars:0,max_wait_bars:null,max_entries_per_activation:1,cooldown_bars:0}}

export function EntryBehaviorEditor({side,group,value,onChange}:{side:'CALL'|'PUT';group:RuleGroup;value:EntryBehavior[];onChange:(x:EntryBehavior[])=>void}){
 const items=flatten(group).filter(c=>c.id);
 const patch=(index:number,next:Partial<EntryBehavior>)=>onChange(value.map((x,i)=>i===index?{...x,...next}:x));
 const move=(index:number,delta:number)=>{const target=index+delta;if(target<0||target>=value.length)return;const next=[...value];[next[index],next[target]]=[next[target],next[index]];onChange(next)};
 return <section className="card entry-behavior lifecycle-section"><div className="card-head"><div><h2>{side} entry lifecycles</h2><p>Multiple independent setup lifecycles can arm from different conditions. The first ready lifecycle in this list gets priority when the full {side} entry tree passes.</p></div><div className="inline"><span className="exclusive-badge">EXCLUSIVE position</span><button className="mini" onClick={()=>onChange([...value,fresh(side,value)])}>+ lifecycle</button></div></div>
 <div className="lifecycle-list">{value.map((life,index)=><div className={`lifecycle-card ${life.enabled?'':'lifecycle-disabled'}`} key={life.id}>
  <div className="lifecycle-title"><label className="life-enabled"><input type="checkbox" checked={life.enabled} onChange={e=>patch(index,{enabled:e.target.checked})}/><span>{life.enabled?'Enabled':'Disabled'}</span></label><input className="life-name" value={life.name} onChange={e=>patch(index,{name:e.target.value})}/><code>#{life.id}</code><div className="inline"><button className="mini ghost" disabled={index===0} onClick={()=>move(index,-1)}>↑</button><button className="mini ghost" disabled={index===value.length-1} onClick={()=>move(index,1)}>↓</button><button className="mini danger" disabled={value.length===1} onClick={()=>onChange(value.filter((_,i)=>i!==index))}>Remove</button></div></div>
  <div className="form-grid lifecycle-grid aligned-form">
   <label>Activation trigger<select value={life.trigger_condition_id??''} onChange={e=>patch(index,{trigger_condition_id:e.target.value||null})}><option value="">Entire {side} entry group</option>{items.map(c=><option key={c.id} value={c.id}>#{c.id} · {label(c)}</option>)}</select><small>The lifecycle arms when this condition becomes true.</small></label>
   <label>Minimum wait (candles)<input type="number" min="0" max="500" value={life.delay_bars} onChange={e=>patch(index,{delay_bars:Number(e.target.value)})}/><small>0 = the full entry tree may execute on the trigger candle.</small></label>
   <label>Wait up to (candles)<input type="number" min={life.delay_bars} max="5000" placeholder="Unlimited" value={life.max_wait_bars??''} onChange={e=>patch(index,{max_wait_bars:e.target.value===''?null:Number(e.target.value)})}/><small>Example: trigger A now, wait up to 3 candles for condition B/full entry tree. Blank = no expiry while trigger stays true.</small></label>
   <label>Max buys per activation<input type="number" min="1" max="100" value={life.max_entries_per_activation} onChange={e=>patch(index,{max_entries_per_activation:Number(e.target.value)})}/><small>Successful entries allowed before this lifecycle must rearm.</small></label>
   <label>Cooldown after buy (candles)<input type="number" min="0" max="5000" value={life.cooldown_bars} onChange={e=>patch(index,{cooldown_bars:Number(e.target.value)})}/><small>Minimum completed candles before another buy from this same lifecycle.</small></label>
  </div>
  <div className="lifecycle-example"><b>Flow:</b> arm on <em>{life.trigger_condition_id?`#${life.trigger_condition_id}`:`the full ${side} entry group`}</em> → wait at least <em>{life.delay_bars}</em> candle(s){life.max_wait_bars!=null?<> → full entry must become true by age <em>{life.max_wait_bars}</em></>:<> → no maximum wait</>} → recheck every {side} entry condition → buy. If the window expires, this lifecycle waits for its trigger to become false before rearming.</div>
 </div>)}</div>
 </section>
}
