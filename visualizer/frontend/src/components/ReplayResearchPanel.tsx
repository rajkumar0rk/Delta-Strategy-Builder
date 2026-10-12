import {useState} from 'react';
import {api} from '../api';
import type {Strategy} from '../types';

async function wait(id:string,onStatus:(message:string)=>void){
 for(;;){
  await new Promise(r=>setTimeout(r,750));
  const result=await api.job(id);onStatus(result.message||result.status);
  if(result.status==='COMPLETE')return result.result as any;
  if(result.status==='FAILED'||result.status==='CANCELLED')throw new Error(result.error||result.message||result.status);
 }
}
const num=(value:any)=>{const n=Number(value);return Number.isFinite(n)?n.toFixed(2):'—'};
export function ReplayResearchPanel({strategy,selection,start,end,onStatus}:{strategy:Strategy;selection:any;start:string;end:string;onStatus:(s:string)=>void}){
 const [spread,setSpread]=useState('0,0.5,1,2');
 const [ticks,setTicks]=useState('0,1');
 const [train,setTrain]=useState(.7);
 const [embargo,setEmbargo]=useState(0);
 const [working,setWorking]=useState(false);
 const [replay,setReplay]=useState<any>(null);
 const [holdout,setHoldout]=useState<any>(null);
 const parse=(value:string)=>value.split(',').map(x=>Number(x.trim()));
 const simulate=async()=>{try{setWorking(true);const hs=parse(spread),ts=parse(ticks);if(!hs.length||!ts.length||hs.some(x=>!Number.isFinite(x)||x<0)||ts.some(x=>!Number.isInteger(x)||x<0))throw Error('Use nonnegative numeric half-spreads and integer tick counts');const {job_id}=await api.executionReplay({...selection,start,end,strategy,extra_half_spread_percent:hs,extra_slippage_ticks:ts});setReplay(await wait(job_id,onStatus))}catch(e){onStatus(String(e))}finally{setWorking(false)}};
 const validate=async()=>{try{setWorking(true);const {job_id}=await api.researchHoldout({...selection,start,end,strategy,train_fraction:train,embargo_bars:embargo});setHoldout(await wait(job_id,onStatus))}catch(e){onStatus(String(e))}finally{setWorking(false)}};
 return <section className="card"><h2>V16.2 / V16.3 · Execution replay &amp; robustness</h2>
 <p>Research-only, synthetic/unverified BBO. Execution replay reruns all strategy decisions under additional adverse bid/ask spread and slippage. No historical L1 depth or fill probability is invented.</p>
 <div className="form-grid"><label>Extra half-spread % scenarios<input value={spread} onChange={e=>setSpread(e.target.value)}/></label><label>Extra ticks (each side)<input value={ticks} onChange={e=>setTicks(e.target.value)}/></label></div>
 <button disabled={working||!start||!end} onClick={()=>void simulate()}>{working?'Running…':'Run full execution replay'}</button>
 {replay&&<div className="table-wrap"><p>{replay.note}</p><table><thead><tr><th>Half spread +%</th><th>Extra ticks</th><th>Trades</th><th>Net $</th><th>Change $</th><th>Unresolved</th></tr></thead><tbody>{(replay.scenarios||[]).map((r:any,i:number)=><tr key={i}><td>{r.extra_half_spread_percent}</td><td>{r.extra_slippage_ticks}</td><td>{r.trades}</td><td>{num(r.metrics?.net_pnl_usd)}</td><td>{num(r.delta_net_pnl_usd)}</td><td>{r.unresolved_position?'Yes':'No'}</td></tr>)}</tbody></table></div>}
 <h3>Chronological train / unseen holdout</h3><p>Freeze strategy parameters before comparing periods. The test segment never selects parameters using its results.</p>
 <div className="form-grid"><label>Training fraction<select value={train} onChange={e=>setTrain(Number(e.target.value))}><option value={.6}>60%</option><option value={.7}>70%</option><option value={.8}>80%</option></select></label><label>Embargo candles<input type="number" min={0} max={288} value={embargo} onChange={e=>setEmbargo(Number(e.target.value))}/></label></div>
 <button disabled={working||!start||!end} onClick={()=>void validate()}>{working?'Running…':'Run holdout comparison'}</button>
 {holdout&&<div className="table-wrap"><p>{holdout.note}</p><table><thead><tr><th>Period</th><th>Dates</th><th>Trades</th><th>Net $</th><th>PF</th></tr></thead><tbody>{(['train','holdout'] as const).map(key=><tr key={key}><td>{key}</td><td>{holdout[key].start.slice(0,10)} to {holdout[key].end.slice(0,10)}</td><td>{holdout[key].metrics.trades}</td><td>{num(holdout[key].metrics.net_pnl_usd)}</td><td>{num(holdout[key].metrics.profit_factor)}</td></tr>)}</tbody></table></div>}
 </section>
}
