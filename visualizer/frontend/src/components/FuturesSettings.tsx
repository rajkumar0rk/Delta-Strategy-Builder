import type {FuturesConfig,Strategy} from '../types';

const defaults:FuturesConfig={symbol:'BTCUSD',contract_btc:0.001,quantity_lots:1,leverage:5,
 margin_mode:'ISOLATED',maintenance_margin_percent:.25,taker_fee_percent:.05,
 gst_percent:18,slippage_bps:2,tick_size:0.5,slippage_ticks:0,stop_loss_percent:1,take_profit_percent:2,
 funding_mode:'REQUIRE_CSV',margin_tier_mode:'FLAT_RESEARCH'};
export function FuturesSettings({value,onChange}:{value:Strategy;onChange:(s:Strategy)=>void}){
 const f=value.futures||defaults;
 const risk=(patch:Record<string,any>)=>onChange({...value,risk:{...value.risk,...patch}});
 const session=(patch:Partial<Strategy['session']>)=>onChange({...value,session:{...value.session,...patch}});
 const windows=value.session.windows?.length?value.session.windows:[{start:'00:00',end:'23:59'}];
 const set=(patch:Partial<FuturesConfig>)=>onChange({...value,futures:{...f,...patch}});
 const number=(name:keyof FuturesConfig,label:string,step:string,min:number)=>(
  <label key={name}>{label}<input type="number" min={min} step={step} value={Number(f[name] ?? 0)}
  onChange={e=>set({[name]:Number(e.target.value)} as Partial<FuturesConfig>)}/></label>
 );
 const optional=(name:'stop_loss_percent'|'take_profit_percent',label:string)=>(
  <label>{label}<input type="number" min="0.01" step="0.1" placeholder="disabled"
  value={f[name]??''} onChange={e=>set({[name]:e.target.value===''?null:Number(e.target.value)})}/></label>
 );
 return <><section className="card"><h2>BTCUSD perpetual futures research</h2>
 <p>CALL rules become LONG, PUT rules become SHORT. Entries and condition exits are placed at the following candle open. Only one position at a time. No option contracts are required.</p>
 <p>In unified ARCHIVE backtests, missing completed Delta India 1-minute mark, index and funding-rate candles are automatically downloaded once and reused from the data folder. Rate candles are not verified funding settlements: REQUIRE_CSV still needs validated settlement observations; EXCLUDE_WITH_WARNING leaves funding out. No real historical data has been fetched by this upgrade.</p>
 <div className="form-grid">
  <label>Direction<select value={value.direction_mode} onChange={e=>onChange({...value,direction_mode:e.target.value as Strategy['direction_mode']})}><option value="BOTH">LONG + SHORT</option><option value="CALL">LONG only</option><option value="PUT">SHORT only</option></select></label>
  {number('quantity_lots','Quantity (lots of 0.001 BTC)','1',1)}
  {number('leverage','Assumed leverage ×','1',1)}
  <label>Margin tier assumption<select value={f.margin_tier_mode||'FLAT_RESEARCH'} onChange={e=>set({margin_tier_mode:e.target.value as 'FLAT_RESEARCH'|'DELTA_PUBLISHED_SNAPSHOT'})}>
   <option value="FLAT_RESEARCH">Legacy flat-margin research</option>
   <option value="DELTA_PUBLISHED_SNAPSHOT">Current published BTCUSD size-tier snapshot (not historical)</option>
  </select></label>
  <label>Margin mode<select value={f.margin_mode} onChange={e=>set({margin_mode:e.target.value as FuturesConfig['margin_mode']})}><option value="ISOLATED">Isolated (research estimate)</option><option value="CROSS">Cross (research estimate)</option></select></label>
  {number('maintenance_margin_percent','Assumed maintenance margin %','0.05',0.01)}
  {number('taker_fee_percent','Taker fee % per side','0.001',0)}
  {number('gst_percent','GST % on fees','1',0)}
  {number('slippage_bps','Adverse slippage basis points','1',0)}
   {number('tick_size','Assumed futures price tick ($)','0.5',0.000001)}
   {number('slippage_ticks','Additional adverse execution ticks','1',0)}
  {optional('stop_loss_percent','Price-based stop-loss %')}
  {optional('take_profit_percent','Price-based take-profit %')}
  <label>Funding history<select value={f.funding_mode} onChange={e=>set({funding_mode:e.target.value as FuturesConfig['funding_mode']})}><option value="REQUIRE_CSV">Require historical funding CSV</option><option value="EXCLUDE_WITH_WARNING">Exclude funding (research only)</option></select></label>
 </div>
 <div className="form-grid">
  {(['call','put'] as const).map(side=><div key={side}>
   <b>{side==='call'?'LONG':'SHORT'} signal delivery</b>
   {(['entry','exit'] as const).map(kind=>{
    const field=(side+(kind==='entry'?'_signal_mode':'_exit_signal_mode')) as
     'call_signal_mode'|'put_signal_mode'|'call_exit_signal_mode'|'put_exit_signal_mode';
    return <label key={kind}>{kind==='entry'?'Entry':'Exit'}<select value={value[field]||'ORDER_ONLY'}
      onChange={e=>onChange({...value,[field]:e.target.value})}>
      <option value="ORDER_ONLY">Simulate orders</option>
      <option value="ALERT_ONLY">Alert only</option>
      <option value="BOTH">Order + alert</option>
    </select></label>;
   })}
  </div>)}
 </div>
 <div className="warning-box"><b>Accuracy limitations:</b> Futures fills use historical 5m-derived OHLC and assumed slippage, not recorded futures order-book quotes. Funding requires <code>futures_funding.csv</code> with timestamp, symbol and decimal funding_rate. Collateral and liquidation are approximations; no Delta exchange liquidation precision is claimed. Current published snapshot supports size-dependent margins above $100,000 notional; INR conversion, historical collateral tiers, and genuine liquidation remain unmodeled. Pre-8-Sep-2025 minute-by-minute funding is not supported by the 8-hour funding importer. Backtests never place orders.</div>
 </section>
 <section className="card"><h2>Futures risk and entry sessions</h2>
 <div className="form-grid">
  <label>Starting balance (USD)<input type="number" min="1" step="10" value={value.risk.starting_balance_usd} onChange={e=>risk({starting_balance_usd:Number(e.target.value)})}/></label>
  <label>Maximum hold (minutes)<input type="number" min="1" placeholder="No limit" value={value.risk.max_hold_minutes??''} onChange={e=>risk({max_hold_minutes:e.target.value===''?null:Number(e.target.value)})}/></label>
  <label className="switch"><input type="checkbox" checked={!!value.risk.close_at_session_end} onChange={e=>risk({close_at_session_end:e.target.checked})}/><span>Close at session boundary (next candle open)</span></label>
  <label>Daily max trades<input type="number" min="1" value={value.risk.max_trades_per_day??''} placeholder="No limit" onChange={e=>risk({max_trades_per_day:e.target.value===''?null:Number(e.target.value)})}/></label>
  <label>Daily max loss %<input type="number" min="0.01" max="100" step="0.1" value={value.risk.max_daily_loss_percent??''} placeholder="No limit" onChange={e=>risk({max_daily_loss_percent:e.target.value===''?null:Number(e.target.value)})}/></label>
  <label>Daily max consecutive losses<input type="number" min="1" value={value.risk.max_consecutive_losses??''} placeholder="No limit" onChange={e=>risk({max_consecutive_losses:e.target.value===''?null:Number(e.target.value)})}/></label>
  <label>Entry session timezone<input value={value.session.timezone} onChange={e=>session({timezone:e.target.value})}/></label>
 </div>
 <div className="session-window-list">{windows.map((w,i)=><div className="session-window" key={i}>
  <b>Window {i+1}</b>
  <label>Start<input type="time" value={w.start} onChange={e=>{const next=windows.map((x,j)=>j===i?{...x,start:e.target.value}:x);session({windows:next,start:next[0].start,end:next[0].end})}}/></label>
  <label>End<input type="time" value={w.end} onChange={e=>{const next=windows.map((x,j)=>j===i?{...x,end:e.target.value}:x);session({windows:next,start:next[0].start,end:next[0].end})}}/></label>
  <button className="mini danger" disabled={windows.length===1} onClick={()=>{const next=windows.filter((_,j)=>i!==j);session({windows:next,start:next[0].start,end:next[0].end})}}>Remove</button>
 </div>)}</div>
 <button className="mini ghost" onClick={()=>session({windows:[...windows,{start:'00:00',end:'23:59'}]})}>+ Add session window</button>
 <div className="weekdays">{['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map((day,i)=><label key={day}>
  <input type="checkbox" checked={value.session.blocked_weekdays.includes(i)}
   onChange={e=>session({blocked_weekdays:e.target.checked?
    [...value.session.blocked_weekdays,i]:value.session.blocked_weekdays.filter(n=>n!==i)})}/>
  <span>Block {day}</span></label>)}</div>
 <p>Entry windows limit new positions. Existing positions remain protected by their price stop and take profit. Session-end exits and time exits are executed at the following candle open.</p>
 </section></>
}
