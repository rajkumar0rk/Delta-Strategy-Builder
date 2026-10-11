import {useMemo,useState} from 'react';
import type {ChartPayload,ConditionState,Strategy} from '../types';

type DetectorState='NO TREND'|'DEVELOPING'|'STRONG'|'EXTENDED';
type Row={time:number;direction:'CALL'|'PUT';score:number;threshold:number;state:DetectorState;phase:string;extension:number|null;noTrade:boolean;retestReady:boolean;barsSinceBreakout:number|null;falseBreakout:boolean};

const fmt=(n:number|null|undefined,d=1)=>n==null||!Number.isFinite(Number(n))?'—':Number(n).toFixed(d);

export function BigTrendDetector({payload,strategy}:{payload:ChartPayload|null;strategy:Strategy}){
 const [extendedAtr,setExtendedAtr]=useState(2.0);
 const rows=useMemo<Row[]>(()=>{
  if(!payload?.condition_states?.length)return[];
  const over=payload.series.find(s=>s.kind==='OVEREXTENSION'&&s.output==='abs_distance_atr');
  const overMap=new Map<number,number>((over?.values||[]).map(v=>[v.time,v.value]));
  const classify=(s:ConditionState):Row=>{
   const callEnabled=strategy.direction_mode!=='PUT';const putEnabled=strategy.direction_mode!=='CALL';
   const callScore=callEnabled?Number(s.call_big_trend_score??s.call_score??0):-1;
   const putScore=putEnabled?Number(s.put_big_trend_score??s.put_score??0):-1;
   const direction:("CALL"|"PUT")=putScore>callScore?'PUT':'CALL';
   const score=Math.max(0,direction==='CALL'?callScore:putScore);
   const cfg=direction==='CALL'?strategy.call_big_trend_score:strategy.put_big_trend_score;
   const threshold=cfg.enabled?Number(cfg.threshold):70;
   const extension=overMap.get(s.time)??null;
   let state:DetectorState='NO TREND';
   if(score>=threshold)state='STRONG';
   else if(score>=Math.max(35,threshold*.55))state='DEVELOPING';
   if(state==='STRONG'&&extension!=null&&Math.abs(extension)>=extendedAtr)state='EXTENDED';
   const phase=direction==='CALL'?(s.call_trend_phase||'COMPRESSION'):(s.put_trend_phase||'COMPRESSION');const retestReady=direction==='CALL'?Boolean(s.call_retest_ready):Boolean(s.put_retest_ready);const barsSinceBreakout=direction==='CALL'?(s.call_bars_since_breakout??null):(s.put_bars_since_breakout??null);const falseBreakout=direction==='CALL'?Boolean(s.call_false_breakout):Boolean(s.put_false_breakout);const noTrade=Boolean(s.no_trade_active||(direction==='CALL'?s.call_no_trade_active:s.put_no_trade_active));return{time:s.time,direction,score,threshold,state,phase,extension,noTrade,retestReady,barsSinceBreakout,falseBreakout};
  };
  return payload.condition_states.map(classify);
 },[payload,strategy,extendedAtr]);
 const latest=rows.at(-1);
 const counts=useMemo(()=>rows.reduce((a,r)=>(a[r.state]=(a[r.state]||0)+1,a),{} as Record<DetectorState,number>),[rows]);
 const transitions=useMemo(()=>{const out:Row[]=[];for(const r of rows){if(!out.length||out[out.length-1].state!==r.state||out[out.length-1].direction!==r.direction)out.push(r)}return out.slice(-12).reverse()},[rows]);
 if(!payload)return null;
 return <section className="card trend-detector"><div className="card-head"><div><h2>Big Trend Detector</h2><p>V15.1 shows both the score diagnosis and the stateful trend phase. Breakout/retest status is computed from remembered levels without moving signals backward in time.</p></div><label>Extended at ≥ ATR<input type="number" min="0.1" step="0.1" value={extendedAtr} onChange={e=>setExtendedAtr(Math.max(.1,Number(e.target.value)||2))}/></label></div>
  <div className="detector-current">
   <div className={`detector-badge detector-${(latest?.state||'NO TREND').toLowerCase().replace(' ','-')}`}><span>{latest?.direction||'—'}</span><b>{latest?.state||'NO DATA'}</b></div>
   <div><span>Current score</span><b>{fmt(latest?.score)} / 100</b></div><div><span>Trend phase</span><b>{latest?.phase||'—'}</b></div><div><span>Bars since breakout</span><b>{fmt(latest?.barsSinceBreakout,0)}</b></div><div><span>Retest</span><b className={latest?.retestReady?'good':''}>{latest?.retestReady?'READY':'waiting'}</b></div><div><span>False breakout</span><b className={latest?.falseBreakout?'bad':'good'}>{latest?.falseBreakout?'YES':'no'}</b></div><div><span>EMA distance / ATR</span><b>{fmt(latest?.extension,2)}</b></div><div><span>No-trade</span><b className={latest?.noTrade?'bad':'good'}>{latest?.noTrade?'ACTIVE':'clear'}</b></div>
  </div>
  <div className="detector-distribution">{(['NO TREND','DEVELOPING','STRONG','EXTENDED'] as DetectorState[]).map(k=><div key={k}><span>{k}</span><b>{(counts[k]||0).toLocaleString()}</b><small>{rows.length?((counts[k]||0)/rows.length*100).toFixed(1):'0.0'}%</small></div>)}</div>
  {!!transitions.length&&<div className="detector-transitions"><h3>Recent regime changes</h3>{transitions.map((r,i)=><div key={`${r.time}-${i}`}><time>{new Date(r.time*1000).toLocaleString()}</time><span>{r.direction}</span><b className={`state-${r.state.toLowerCase().replace(' ','-')}`}>{r.state}</b><strong>{fmt(r.score)}</strong></div>)}</div>}
 </section>
}
