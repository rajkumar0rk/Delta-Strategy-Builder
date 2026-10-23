import type {IndicatorDefinition,IndicatorInstance} from '../types';

function move<T>(items:T[],index:number,delta:number){const next=[...items];const to=index+delta;if(to<0||to>=next.length)return items;[next[index],next[to]]=[next[to],next[index]];return next}
const timeframes=['strategy','5m','10m','15m','30m','1h'] as const;

export function IndicatorManager({catalog,value,onChange}:{catalog:IndicatorDefinition[];value:IndicatorInstance[];onChange:(x:IndicatorInstance[])=>void}){
 const add=(d:IndicatorDefinition)=>{let base=d.kind.toLowerCase().replace(/_/g,'');let id=base;let i=2;while(value.some(x=>x.id===id))id=`${base}${i++}`;const params:Record<string,number|string>={};Object.entries(d.params).forEach(([k,p])=>params[k]=p.default);onChange([...value,{id,kind:d.kind,params,visible:true,chart_only:true,timeframe:'strategy'}])};
 const def=(kind:string)=>catalog.find(x=>x.kind===kind);
 return <section className="card"><div className="card-head"><div><h2>Indicators & chart order</h2><p>↑/↓ changes pane/legend order. V14 indicators can run on the strategy timeframe or a higher completed timeframe such as 1h. Chart-only indicators stay visual and cannot affect strategy decisions.</p></div><select onChange={e=>{const d=def(e.target.value);if(d)add(d);e.currentTarget.value=''}} defaultValue=""><option value="" disabled>+ Add indicator</option>{catalog.map(d=><option key={d.kind} value={d.kind}>{d.category} · {d.label}</option>)}</select></div>
 <div className="indicator-list">{value.map((x,idx)=>{const d=def(x.kind);return <div className="indicator-row" key={`${x.id}-${idx}`}>
  <div className="move-buttons"><button className="mini ghost" disabled={idx===0} onClick={()=>onChange(move(value,idx,-1))}>↑</button><button className="mini ghost" disabled={idx===value.length-1} onClick={()=>onChange(move(value,idx,1))}>↓</button></div>
  <label className="switch"><input type="checkbox" checked={x.visible} onChange={e=>onChange(value.map((v,i)=>i===idx?{...v,visible:e.target.checked}:v))}/><span>show</span></label>
  <label className="switch strategy-switch"><input type="checkbox" checked={x.chart_only} onChange={e=>onChange(value.map((v,i)=>i===idx?{...v,chart_only:e.target.checked}:v))}/><span>chart only</span></label>
  <input className="id-input" value={x.id} onChange={e=>onChange(value.map((v,i)=>i===idx?{...v,id:e.target.value}:v))}/><strong>{d?.label||x.kind}</strong>
  <label className="param"><span>timeframe</span><select value={x.timeframe||'strategy'} onChange={e=>onChange(value.map((v,i)=>i===idx?{...v,timeframe:e.target.value as IndicatorInstance['timeframe']}:v))}>{timeframes.map(tf=><option key={tf} value={tf}>{tf==='strategy'?'strategy TF':tf}</option>)}</select></label>
  {d&&Object.entries(d.params).filter(([k])=>{
   if(x.kind!=='DAY_LEVELS')return true;
   const mode=x.params.day_boundary_mode||'CALENDAR';
   if(k==='timezone')return mode==='CALENDAR';
   if(k==='symbol')return mode==='SYMBOL_SESSION';
   if(['session_timezone','session_open','session_close','session_weekdays'].includes(k))return mode==='CUSTOM_SESSION';
   return true;
  }).map(([k,p])=><label key={k} className={`param ${p.type==='text'?'param-wide':''}`}><span>{k}</span>{p.type==='select'?<select value={String(x.params[k]??p.default)} onChange={e=>onChange(value.map((v,i)=>i===idx?{...v,params:{...v.params,[k]:e.target.value}}:v))}>{p.options?.map(o=><option key={o}>{o}</option>)}</select>:p.type==='text'?<input type="text" value={String(x.params[k]??p.default)} onChange={e=>onChange(value.map((v,i)=>i===idx?{...v,params:{...v.params,[k]:e.target.value}}:v))}/>:<input type="number" min={p.min} max={p.max} step={p.type==='float'?'0.1':'1'} value={Number(x.params[k]??p.default)} onChange={e=>onChange(value.map((v,i)=>i===idx?{...v,params:{...v.params,[k]:Number(e.target.value)}}:v))}/>}</label>)}
  {x.kind==='DAY_LEVELS'&&<p>{(x.params.day_boundary_mode||'CALENDAR')==='SYMBOL_SESSION'
    ?'BTCUSD trades 24/7; its configured 00:00 UTC rollover is a chart convention, not a Delta exchange open/close or option expiry.'
    :(x.params.day_boundary_mode||'CALENDAR')==='CUSTOM_SESSION'
      ?'Custom sessions use open/close HH:MM in the selected timezone (equal times = 24 hours); weekdays: Monday=0 through Sunday=6. Closed hours are excluded, and previous session skips configured closed weekdays.'
      :'Calendar day uses midnight in the chosen timezone (legacy IST behavior).'}
    {' '}Daily ranges use complete 5m history; swings must be confirmed by the next session start. Older swings search earlier completed sessions; missing history leaves gaps. Warning distance is in BTC points. Disable chart only for alert rules.</p>}
  <button className="danger ghost" onClick={()=>onChange(value.filter((_,i)=>i!==idx))}>Remove</button>
 </div>})}</div></section>
}

