import {useEffect,useMemo,useState} from 'react';
import {api} from '../api';
import type {JobState,Strategy,TrendDiscoveryResult} from '../types';

const f=(v:any,d=2)=>{const n=Number(v);return Number.isFinite(n)?n.toFixed(d):'—'};
const pct=(v:any)=>`${f(v,1)}%`;

type Props={selection:Record<string,any>;start:string;end:string;strategy:Strategy;onStatus:(s:string)=>void};

export function TrendDiscoveryPanel({selection,start,end,strategy,onStatus}:Props){
 const [lookahead,setLookahead]=useState(24);
 const [bigMove,setBigMove]=useState(1.5);
 const [scoreThreshold,setScoreThreshold]=useState(70);
 const [prelude,setPrelude]=useState(12);
 const [separation,setSeparation]=useState(12);
 const [job,setJob]=useState<JobState|null>(null);
 const [jobId,setJobId]=useState<string|null>(null);
 const [result,setResult]=useState<TrendDiscoveryResult|null>(null);
 const running=Boolean(jobId&&job&&['QUEUED','RUNNING','CANCELLING','STARTING'].includes(job.status));

 useEffect(()=>{if(!jobId)return;let alive=true;const tick=async()=>{try{const j=await api.job(jobId);if(!alive)return;setJob(j);if(j.status==='COMPLETE'){setResult(j.result as unknown as TrendDiscoveryResult);setJobId(null);onStatus('V15.1 Big Trend discovery complete.')}else if(j.status==='FAILED'){setJobId(null);onStatus(`Trend discovery failed: ${j.error||j.message}`)}else if(j.status==='CANCELLED'){setJobId(null);onStatus('Trend discovery stopped.')}}catch(e){if(alive){setJobId(null);onStatus(String(e))}}};void tick();const timer=window.setInterval(()=>void tick(),500);return()=>{alive=false;window.clearInterval(timer)}},[jobId,onStatus]);

 const run=async()=>{try{setResult(null);setJob({id:'',status:'QUEUED',message:'Starting…'} as JobState);const x=await api.trendDiscovery({...selection,start,end,strategy,lookahead_bars:lookahead,big_move_percent:bigMove,candidate_score_threshold:scoreThreshold,prelude_bars:prelude,min_separation_bars:separation,max_events:500});setJobId(x.job_id);onStatus('V15.1 trend discovery started.')}catch(e){onStatus(String(e))}};
 const stop=async()=>{if(!jobId)return;try{setJob(await api.stop(jobId))}catch(e){onStatus(String(e))}};
 const top=useMemo(()=>result?.feature_comparison.slice(0,20)||[],[result]);
 const recent=useMemo(()=>result?.events.slice(-20).reverse()||[],[result]);

 return <section className="card trend-discovery">
  <div className="card-head"><div><h2>Big Trend Outcome Discovery</h2><p>Labels historical BIG moves using future price only for research, then compares the indicator/state snapshot that existed before those moves against strong-looking setups that failed to become big trends.</p></div><span className="research-badge">V15.1 · research only</span></div>
  <div className="trend-discovery-controls">
   <label>Forward window <span>candles</span><input type="number" min="2" max="1000" value={lookahead} onChange={e=>setLookahead(Math.max(2,Number(e.target.value)||24))}/></label>
   <label>BIG move ≥ <span>%</span><input type="number" min="0.1" step="0.1" value={bigMove} onChange={e=>setBigMove(Math.max(.1,Number(e.target.value)||1.5))}/></label>
   <label>Fake candidate score ≥ <input type="number" min="0" max="100" step="1" value={scoreThreshold} onChange={e=>setScoreThreshold(Math.max(0,Math.min(100,Number(e.target.value)||0)))}/></label>
   <label>Prelude <span>candles</span><input type="number" min="1" max="500" value={prelude} onChange={e=>setPrelude(Math.max(1,Number(e.target.value)||12))}/></label>
   <label>Event separation <span>candles</span><input type="number" min="1" max="1000" value={separation} onChange={e=>setSeparation(Math.max(1,Number(e.target.value)||12))}/></label>
   <div className="inline"><button className="primary" disabled={running} onClick={()=>void run()}>Analyze big trends</button>{running&&<button className="danger" onClick={()=>void stop()}>■ Stop</button>}</div>
  </div>
  {job&&running&&<div className="trend-discovery-progress"><div><b>{job.stage||job.status}</b><span>{f(job.progress_percent,0)}%</span></div><progress max={100} value={Number(job.progress_percent||0)}/><p>{job.message}</p>{job.next_step&&<small>Next: {job.next_step}</small>}</div>}
  {result&&<>
   <div className="trend-discovery-summary"><div><span>Bars analyzed</span><b>{result.bars_analyzed.toLocaleString()}</b></div><div><span>BIG CALL</span><b className="good">{result.counts.BIG_CALL||0}</b></div><div><span>BIG PUT</span><b className="good">{result.counts.BIG_PUT||0}</b></div><div><span>FAKE CALL</span><b className="bad">{result.counts.FAKE_CALL||0}</b></div><div><span>FAKE PUT</span><b className="bad">{result.counts.FAKE_PUT||0}</b></div></div>
   {result.warnings.map((w,i)=><p className="notice" key={i}>⚠ {w}</p>)}
   <p className="research-note">{result.research_note}</p>
   <div className="trend-discovery-grid">
    <div><h3>Features that separate BIG vs fake</h3>{!top.length?<p className="muted">Not enough BIG and fake samples yet. Widen the date range or adjust the research thresholds.</p>:<div className="table-scroll"><table><thead><tr><th>Side</th><th>Feature</th><th>BIG avg</th><th>Fake avg</th><th>Δ</th><th>Separation</th></tr></thead><tbody>{top.map((r,i)=><tr key={`${r.direction}-${r.feature}-${i}`}><td>{r.direction}</td><td><code>{r.feature}</code></td><td>{f(r.big_mean)}</td><td>{f(r.fake_mean)}</td><td className={r.mean_delta>=0?'good':'bad'}>{f(r.mean_delta)}</td><td>{f(r.standardized_separation)}</td></tr>)}</tbody></table></div>}</div>
    <div><h3>Big Trend Score calibration</h3><div className="table-scroll"><table><thead><tr><th>Side</th><th>Score</th><th>Samples</th><th>BIG hits</th><th>Hit rate</th><th>Avg MFE</th></tr></thead><tbody>{result.score_calibration.map((r,i)=><tr key={`${r.direction}-${r.bucket}-${i}`}><td>{r.direction}</td><td>{r.bucket}</td><td>{r.samples.toLocaleString()}</td><td>{r.big_move_hits}</td><td className={r.hit_rate_percent>=50?'good':''}>{pct(r.hit_rate_percent)}</td><td>{pct(r.average_forward_mfe_percent)}</td></tr>)}</tbody></table></div></div>
   </div>
   <div className="trend-discovery-events"><h3>Recent labeled events</h3><div className="table-scroll"><table><thead><tr><th>UTC</th><th>Label</th><th>Side</th><th>Score</th><th>Phase</th><th>Forward MFE</th><th>Opposite move</th></tr></thead><tbody>{recent.map((e,i)=><tr key={`${e.time}-${e.direction}-${i}`}><td>{e.timestamp.replace('T',' ').slice(0,16)}</td><td><b className={e.label==='BIG'?'good':'bad'}>{e.label}</b></td><td>{e.direction}</td><td>{f(e.score,1)}</td><td>{e.phase}</td><td>{pct(e.future_mfe_percent)}</td><td>{pct(e.future_mae_percent)}</td></tr>)}</tbody></table></div></div>
  </>}
 </section>
}
