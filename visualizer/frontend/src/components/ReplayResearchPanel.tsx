import {useEffect,useRef,useState} from 'react';
import {api} from '../api';
import type {JobState,Strategy} from '../types';

type Kind='replay'|'holdout'|'futures-validation'|'futures-parity';
type ResearchProgress={kind:Kind;jobId:string;job:JobState};
const done=['COMPLETE','FAILED','CANCELLED'];
export function ResearchJobProgress({job,onStop}:{job:JobState;onStop:()=>void}){
 const percent=Math.max(0,Math.min(100,Number(job.progress_percent??0)));
 return <div className="research-job-progress" role="status" aria-live="polite">
  <div className="research-job-heading"><strong>{job.stage||job.status}</strong><span>{percent.toFixed(0)}%</span></div>
  <progress value={percent} max={100} aria-label="Research job progress"/>
  <p>{job.message||'Waiting for research progress…'}</p>
  {job.next_step&&<small>Next: {job.next_step}</small>}
  <button className="danger" disabled={done.includes(job.status)||job.status==='CANCELLING'} onClick={onStop}>{job.status==='CANCELLING'?'Stopping…':'■ Stop research'}</button>
 </div>;
}
const num=(value:any)=>{const n=Number(value);return Number.isFinite(n)?n.toFixed(2):'—'};
export function ReplayResearchPanel({strategy,selection,start,end,onStatus}:{strategy:Strategy;selection:any;start:string;end:string;onStatus:(s:string)=>void}){
 const [spread,setSpread]=useState('0,0.5,1,2');
 const [ticks,setTicks]=useState('0,1');
 const [futureBps,setFutureBps]=useState('0,5,10');
 const [feeMultipliers,setFeeMultipliers]=useState('1');
 const [fundMultipliers,setFundMultipliers]=useState('1');
 const [train,setTrain]=useState(.7);
 const [embargo,setEmbargo]=useState(0);
 const [active,setActive]=useState<ResearchProgress|null>(null);
 const [replay,setReplay]=useState<any>(null);
 const [holdout,setHoldout]=useState<any>(null);
 const [validation,setValidation]=useState<any>(null);
 const [parity,setParity]=useState<any>(null);
 const [feedback,setFeedback]=useState('');
 const alive=useRef(true);
 const activeId=useRef<string|null>(null);
 const submitting=useRef(false);
 const generation=useRef(0);
 useEffect(()=>{alive.current=true;return ()=>{alive.current=false;generation.current+=1}},[]);
 async function run(kind:Kind,payload:any){
  if(activeId.current||submitting.current)return;
  submitting.current=true;
  const token=++generation.current;
  try{
   setFeedback('');
   const reply=kind==='replay'?await api.executionReplay(payload):kind==='holdout'?await api.researchHoldout(payload):kind==='futures-validation'?await api.futuresValidation(payload):await api.futuresParityAudit(payload);
   if(!alive.current||generation.current!==token)return;
   const id=reply.job_id;
   activeId.current=id;
   submitting.current=false;
   setActive({kind,jobId:id,job:{id,status:'QUEUED',message:'Queued',stage:'QUEUED',progress_percent:0}});
   for(;;){
    const job=await api.job(id);
    if(!alive.current||generation.current!==token)return;
    setActive({kind,jobId:id,job});
    if(done.includes(job.status)){
     if(job.status==='COMPLETE'){
      if(kind==='replay')setReplay(job.result);
      else if(kind==='holdout')setHoldout(job.result);
      else if(kind==='futures-validation')setValidation(job.result);
      else setParity(job.result);
      setFeedback(kind==='replay'?'Execution replay completed.':'Holdout comparison completed.');
     }else if(job.status==='CANCELLED'){
      setFeedback('Research stopped at a safe checkpoint. Existing results are preserved.');
     }else{throw Error(job.error||job.message||'Research failed')}
     break;
    }
    await new Promise(resolve=>setTimeout(resolve,750));
   }
  }catch(e){
   if(alive.current&&generation.current===token){
    setFeedback(String(e));onStatus(String(e));
   }
  }finally{
   if(generation.current===token){
    submitting.current=false;
    activeId.current=null;
    if(alive.current)setActive(null);
   }
  }
 }
 function replayNow(){
  if(activeId.current||submitting.current)return;
  const parse=(v:string)=>v.split(',').map(x=>Number(x.trim()));
  const hs=parse(spread),ts=parse(ticks);
  if((strategy.market_type!=='FUTURES'&&(hs.some(x=>!Number.isFinite(x)||x<0)||!hs.length))||ts.some(x=>!Number.isInteger(x)||x<0)||!ts.length){
   setFeedback('Use nonnegative half-spreads and integer tick values.');return;
  }

  if(strategy.market_type==='FUTURES'){
   const bps=parse(futureBps),fees=parse(feeMultipliers),funding=parse(fundMultipliers);
   if(!bps.length||!fees.length||!funding.length||bps.some(x=>!Number.isFinite(x)||x<0)||fees.some(x=>!Number.isFinite(x)||x<1)||funding.some(x=>!Number.isFinite(x)||x<0)){
    setFeedback('Futures bps, fee and funding multipliers must be valid nonnegative numbers; fees at least 1.');return;
   }
   void run('replay',{...selection,start,end,strategy,
    extra_futures_slippage_bps:bps,extra_slippage_ticks:ts,
    futures_fee_multipliers:fees,futures_funding_multipliers:funding});return;
  }
  void run('replay',{...selection,start,end,strategy,extra_half_spread_percent:hs,extra_slippage_ticks:ts});
 }
 function auditFutures(){
  if(activeId.current||submitting.current)return;
  void run('futures-parity',{...selection,start,end,strategy,storage_mode:'COMPACT',bar_gap_policy:'REQUIRE'});
 }
 function validateFutures(){
  if(activeId.current||submitting.current)return;
  void run('futures-validation',{...selection,start,end,strategy,train_fraction:train,embargo_bars:embargo,
    stress_extra_slippage_bps:5,stress_fee_multiplier:1.5,bar_gap_policy:'REQUIRE'});
 }
 function holdoutNow(){
  if(activeId.current||submitting.current)return;
  void run('holdout',{...selection,start,end,strategy,train_fraction:train,embargo_bars:embargo});
 }
 async function stop(){
  const id=activeId.current;if(!id)return;
  try{
   const job=await api.stop(id);
   if(!alive.current||activeId.current!==id)return;
   setActive(current=>current?.jobId===id?{...current,job}:current);
  }catch(e){if(alive.current)setFeedback('Stop failed: '+String(e))}
 }
 const running=!!active;
 return <section className="card">
 <h2>V16.2 / V16.3 · Execution replay &amp; robustness</h2>
 <p>{strategy.market_type==='FUTURES'?'Futures OHLC replay: vary adverse execution basis points, ticks, taker fees and recorded funding multipliers. No historical mark price or L1 liquidity is available.':'Research-only, synthetic/unverified BBO. Execution replay reruns decisions under additional adverse bid/ask spread and slippage.'}</p>
 <div className="form-grid">
 {strategy.market_type==='FUTURES'?<>
  <label>Extra futures adverse slippage (bps)<input disabled={running} value={futureBps} onChange={e=>setFutureBps(e.target.value)}/></label>
  <label>Taker-fee multipliers<input disabled={running} value={feeMultipliers} onChange={e=>setFeeMultipliers(e.target.value)}/></label>
  <label>Recorded funding multipliers<input disabled={running} value={fundMultipliers} onChange={e=>setFundMultipliers(e.target.value)}/></label>
 </>:<label>Extra half-spread % scenarios<input disabled={running} value={spread} onChange={e=>setSpread(e.target.value)}/></label>}
 <label>Extra ticks (each side)<input disabled={running} value={ticks} onChange={e=>setTicks(e.target.value)}/></label></div>
 <button disabled={running||!start||!end} onClick={replayNow}>{active?.kind==='replay'?'Running replay…':'Run full execution replay'}</button>
 {active?.kind==='replay'&&<ResearchJobProgress job={active.job} onStop={()=>void stop()}/>}
 {replay&&<div className="table-wrap"><p>{replay.note}</p><table><thead><tr><th>{strategy.market_type==='FUTURES'?'Extra bps':'Half spread +%'}</th><th>Extra ticks</th><th>Trades</th><th>Net $</th><th>Change $</th><th>Unresolved</th></tr></thead><tbody>{(replay.scenarios||[]).map((r:any,i:number)=><tr key={i}><td>{strategy.market_type==='FUTURES'?r.extra_futures_slippage_bps:r.extra_half_spread_percent}</td><td>{r.extra_slippage_ticks}</td><td>{r.trades}</td><td>{num(r.metrics?.net_pnl_usd)}</td><td>{num(r.delta_net_pnl_usd)}</td><td>{r.unresolved_position?'Yes':'No'}</td></tr>)}</tbody></table></div>}
 <h3>Chronological train / unseen holdout</h3>
 <p>Freeze strategy parameters before comparing periods. The test segment never selects parameters using its results.</p>
 <div className="form-grid"><label>Training fraction<select disabled={running} value={train} onChange={e=>setTrain(Number(e.target.value))}><option value={.6}>60%</option><option value={.7}>70%</option><option value={.8}>80%</option></select></label><label>Embargo candles<input disabled={running} type="number" min={0} max={288} value={embargo} onChange={e=>setEmbargo(Number(e.target.value))}/></label></div>
 <button disabled={running||!start||!end} onClick={holdoutNow}>{active?.kind==='holdout'?'Running holdout…':'Run holdout comparison'}</button>
 {active?.kind==='holdout'&&<ResearchJobProgress job={active.job} onStop={()=>void stop()}/>}
 {holdout&&<div className="table-wrap"><p>{holdout.note}</p><table><thead><tr><th>Period</th><th>Dates</th><th>Trades</th><th>Net $</th><th>PF</th></tr></thead><tbody>{(['train','holdout'] as const).map(key=><tr key={key}><td>{key}</td><td>{holdout[key].start.slice(0,10)} to {holdout[key].end.slice(0,10)}</td><td>{holdout[key].metrics.trades}</td><td>{num(holdout[key].metrics.net_pnl_usd)}</td><td>{num(holdout[key].metrics.profit_factor)}</td></tr>)}</tbody></table></div>}
 {strategy.market_type==='FUTURES'&&<div>
 <h3>Milestone 5 · Historical futures validation</h3>
 <p>Freeze the strategy, run the selected historical data with strict gaps, compare training and unseen holdout, then stress holdout with +5 bps adverse slippage and 1.5× fees. Requires real archive coverage; results remain research-only.</p>
 <button disabled={running||!start||!end} onClick={validateFutures}>Run futures validation</button>
 {active?.kind==='futures-validation'&&<ResearchJobProgress job={active.job} onStop={()=>void stop()}/>}
 {validation&&<div className="table-wrap"><p>{validation.note}</p><table><thead><tr><th>Period</th><th>Trades</th><th>Net $</th><th>PF</th><th>Fees $</th><th>Drawdown $</th><th>Net without best $</th><th>Unresolved</th></tr></thead><tbody>{(['train','holdout','holdout_stressed'] as const).map(key=><tr key={key}><td>{key}</td><td>{validation[key]?.trades}</td><td>{num(validation[key]?.net_closed_usd)}</td><td>{num(validation[key]?.profit_factor)}</td><td>{num(validation[key]?.fees_including_gst_usd)}</td><td>{num(validation[key]?.estimated_candle_close_drawdown_usd)}</td><td>{num(validation[key]?.best_trade_removed_net_usd)}</td><td>{validation[key]?.unresolved_position?'Yes':'No'}</td></tr>)}</tbody></table>{validation.warnings?.map((w:string,i:number)=><p key={i} className="research-job-feedback">{w}</p>)}</div>}
 </div>}
 {strategy.market_type==='FUTURES'&&<div>
 <h3>Milestone 6 · Chart/backtest internal parity audit</h3>
 <p>Checks completed-candle chart rules, OHLC entry pricing, fee/P&amp;L arithmetic, positions and markers. Limit chart range to 30,000 candles. This does not prove exchange-executable fills.</p>
 <button disabled={running||!start||!end} onClick={auditFutures}>Audit futures chart parity</button>
 {active?.kind==='futures-parity'&&<ResearchJobProgress job={active.job} onStop={()=>void stop()}/>}
 {parity&&<div><strong>{parity.status}</strong> · {parity.checked_closed_trades} closed trades · {parity.checked_preview_signals} checked chart signals
 {(parity.failures||[]).map((x:string,i:number)=><p key={'fail-'+i} className="research-job-feedback">{x}</p>)}
 {(parity.warnings||[]).map((x:string,i:number)=><p key={'warn-'+i} className="research-job-feedback">{x}</p>)}</div>}
 </div>}
 {feedback&&<p className="research-job-feedback" role="status">{feedback}</p>}
 </section>;
}
