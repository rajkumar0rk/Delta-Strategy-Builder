import {useEffect,useState} from 'react';
import {api} from '../api';
import type {LiveMonitorStatus,LiveSignal} from '../types';

function chatGptPrompt(s:LiveSignal):string {
 return [
  'Review this BTC options breakout candidate for a $100 Delta Exchange India account.',
  'This is preliminary Binance BTCUSDT futures screening, NOT a buy signal.',
  'Recheck current market context and obtain VERIFIED LIVE Delta India BTC option chain bid/ask,',
  'expiry, available sizes, spread, minimum quantity/increment, fees and GST.',
  'Reject a trade if any executable option quote, affordability or risk information is unavailable.',
  'Evaluate continuation strength, reversal risk, entry price, invalidation and maximum affordable loss.',
  'Answer BUY CALL / BUY PUT / WAIT with precise checked times; do not execute orders.',
  'Candidate data:',
  JSON.stringify(s, null, 2),
 ].join('\n');
}

export function LiveMonitor() {
 const [data,setData]=useState<LiveMonitorStatus|null>(null);
 const [error,setError]=useState('');
 const [busy,setBusy]=useState(false);
 const [copyStatus,setCopyStatus]=useState('');
 const refresh=async()=>{try{setData(await api.liveMonitorStatus());setError('')}catch(e){setError(String(e))}};
 useEffect(()=>{void refresh();const timer=setInterval(()=>void refresh(),15000);return()=>clearInterval(timer)},[]);
 const act=async(kind:'start'|'stop'|'check')=>{
  setBusy(true);
  try{setData(await api.liveMonitorAction(kind));setError('')}catch(e){setError(String(e))}
  finally{setBusy(false)}
 };
 const copy=async(s:LiveSignal)=>{
  try{await navigator.clipboard.writeText(chatGptPrompt(s));setCopyStatus('Review prompt copied; paste into ChatGPT Plus.')}
  catch(e){setCopyStatus('Clipboard unavailable: '+String(e))}
 };
 return <section className="card" style={{marginTop:14}}>
  <div className="card-head">
   <div><h2>Live BTC Monitor · Gemini Free API</h2>
    <p>5-minute screening · completed candles · alert-only · no live order execution</p></div>
   <span style={{color:data?.running?'#62d6a4':'#8f9db2'}}>{data?.running?'● Running':'○ Stopped'}</span>
  </div>
  <div className="strategy-actions" style={{margin:'12px 0'}}>
   <button disabled={busy||!data||data.running||!data.gemini_configured} onClick={()=>void act('start')}>Start monitor</button>
   <button disabled={busy||!data?.running} onClick={()=>void act('stop')}>Stop</button>
   <button disabled={busy} onClick={()=>void act('check')}>Check once</button>
   <button className="ghost" disabled={busy} onClick={()=>void refresh()}>Refresh</button>
  </div>
  {error&&<p style={{color:'#ff9a9f'}}>Request failed: {error}</p>}
  {data&&<div style={{display:'grid',gap:9}}>
   <p>Gemini API key: {data.gemini_configured?'Configured':'Missing'} · Model: {data.gemini_model} · Telegram: {data.telegram_configured?'Configured':'Not configured'}</p>
   <p>Last check (UTC): {data.last_checked_utc||'Never'} · Cadence: {data.interval_minutes} minutes</p>
   {data.last_error&&<p style={{color:'#ff9a9f'}}>Latest check failed: {data.last_error}</p>}
   {data.last_screen&&<div className="card" style={{margin:0}}>
    <b>Latest: {data.last_screen.state}</b> · {data.last_screen.direction||'No breakout'} · BTC ${data.last_screen.latest_completed_5m_close}
    <p>15m candle close: {data.last_screen.candle_close_utc} · RSI: {data.last_screen.rsi_15m} · Volume: {data.last_screen.volume_ratio}×</p>
    <p>{data.last_screen.explanation} · This does not validate any executable Delta option.</p>
    {data.last_screen.ai&&<p>Gemini: {data.last_screen.ai.verdict} — {data.last_screen.ai.reason}</p>}
   </div>}
   <h2>Review candidates (current backend session)</h2>
   {!data.signals.length?<p>No candidate alerts yet.</p>:data.signals.map((s,i)=><div className="card" key={s.candle_id+'-'+i} style={{margin:0}}>
    <b>{s.direction} · MANUAL REVIEW ONLY</b>
    <p>{s.candle_close_utc} · Breakout ${s.breakout_level} · {s.ai?.model}: {s.ai?.reason}</p>
    <p>Telegram: {s.telegram_delivery||'Not attempted'}</p>
    <button onClick={()=>void copy(s)}>Copy ChatGPT Plus review prompt</button>
   </div>)}
   {copyStatus&&<p>{copyStatus}</p>}
   <p>All candidates are non-actionable until a separate review checks real Delta India option bid/ask, expiry, fees and budget. This worker runs only while the backend stays online. Historical backtests are unchanged.</p>
  </div>}
 </section>;
}
