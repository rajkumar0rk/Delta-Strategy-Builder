import type {FuturesConfig,FuturesCandlePatternConfig,Strategy} from '../types';
import {AdaptiveFuturesEditor} from './AdaptiveFuturesEditor';

const defaults:FuturesConfig={symbol:'BTCUSD',contract_btc:0.001,quantity_lots:1,leverage:5,
 margin_mode:'ISOLATED',maintenance_margin_percent:.25,taker_fee_percent:.05,
 gst_percent:18,slippage_bps:2,tick_size:0.5,slippage_ticks:0,stop_loss_percent:1,take_profit_percent:2,
 funding_mode:'REQUIRE_CSV',margin_tier_mode:'FLAT_RESEARCH'};
export function FuturesSettings({value,onChange}:{value:Strategy;onChange:(s:Strategy)=>void}){
 const f=value.futures||defaults;
 const minutes:Record<Strategy['timeframe'],number>={'5m':5,'10m':10,'15m':15,'30m':30,'1h':60,'4h':240,'1D':1440};
 const entryTimeframes=(Object.keys(minutes) as Strategy['timeframe'][]).filter(tf=>
  minutes[tf]>=minutes[value.timeframe]&&minutes[tf]%minutes[value.timeframe]===0);
 const dedicatedEntry=!!(f.pullback?.enabled||f.adaptive?.enabled||f.candle_pattern?.enabled);
 const setupDefaults={enabled:false,setup_timeframe:'15m' as const,ema_indicator_id:'ema20_15m',
  atr_indicator_id:'atr14_15m',volume_indicator_id:'volumeSMA20_5m',require_touch:true,
  require_confirmation_color:true,require_volume:true,volume_multiplier:1,max_wait_bars:6,
  execution_mode:'CLOSE_CONFIRM_NEXT_OPEN' as const,stop_anchor:'SWING' as const,
  breakout_buffer_ticks:0,trend_fast_ema_id:null as string|null,
  trend_slow_ema_id:null as string|null,trend_close_indicator_id:null as string|null,
  trend_crossover_block_bars:0,cancel_on_trend_invalidation:true,
  swing_lookback_bars:3,stop_buffer_atr:0.1,breakout_buffer_points:0,reward_r_multiple:2,
  size_mode:'RISK_EQUITY' as const,equity_risk_percent:0.5,max_lots:100000,
  max_estimated_risk_multiple:1};
 const ruleDefaults={enabled:false,execution_timeframe:'strategy' as const,stop_mode:'SWING' as const,stop_loss_points:500,swing_lookback_bars:3,
  atr_indicator_id:'atr14_5m',stop_atr_multiple:1.5,stop_buffer_atr:0.1,
  reward_r_multiple:2,take_profit_points:null as number|null,atr_stop_anchor:'SIGNAL_CLOSE' as const,
  trailing_enabled:false,trailing_mode:'ATR' as const,trailing_activation_points:500,trailing_pullback_points:100,trailing_atr_multiple:3,trailing_source:'HIGH_LOW' as const,
  size_mode:'RISK_EQUITY' as const,equity_risk_percent:0.5,
  max_lots:100000,max_estimated_risk_multiple:1};
 const ruleRisk={...ruleDefaults,...f.rule_risk};
 const setRuleRisk=(patch:Partial<typeof ruleRisk>)=>onChange({...value,futures:{...f,
  ...(patch.enabled===true?{stop_loss_percent:null,take_profit_percent:null,
    ...(f.candle_pattern?{candle_pattern:{...pattern,enabled:false}}:{}),
    ...(f.pullback?{pullback:{...f.pullback,enabled:false}}:{}),
    ...(f.adaptive?{adaptive:{...f.adaptive,enabled:false}}:{})}:{} ),
  rule_risk:{...ruleRisk,...patch}}});
 const ruleNumber=(key:keyof typeof ruleDefaults,label:string,min:number,step:number)=>(
  <label key={key}>{label}<input type="number" min={min} step={step}
   value={Number(ruleRisk[key])} onChange={e=>setRuleRisk({[key]:Number(e.target.value)})}/></label>);
 const pullback={...setupDefaults,...f.pullback};
 const setup=(patch:Partial<typeof pullback>)=>onChange({...value,
   ...(patch.enabled===true?{entry_evaluation_timeframe:'strategy' as const}:{}),futures:{...f,
   ...(patch.enabled===true?{stop_loss_percent:null,take_profit_percent:null,
      ...(f.candle_pattern?{candle_pattern:{...pattern,enabled:false}}:{})}:{}),
   pullback:{...pullback,...patch},...(patch.enabled===true&&f.adaptive?{adaptive:{...f.adaptive,enabled:false}}:{}),
   ...(patch.enabled===true?{rule_risk:{...ruleRisk,enabled:false}}:{})}});
 const setupNumber=(key:keyof typeof setupDefaults,label:string,step:string,min:number)=>(
  <label key={key}>{label}<input type="number" step={step} min={min}
   value={Number(pullback[key])} onChange={e=>setup({[key]:Number(e.target.value)})}/></label>);

 const patternDefaults:FuturesCandlePatternConfig={
  enabled:false,entry_candle:4,doji_filter_enabled:true,doji_threshold_percent:10,
  stop_anchor:'PATTERN_HIGHEST_HIGH',stop_loss_points:500,stop_buffer_ticks:0,
  take_profit_mode:'TRAILING_POINTS',activation_points:200,pullback_points:200,
  fixed_target_points:200,trailing_ignore_doji:true,size_mode:'RISK_EQUITY',
  equity_risk_percent:.5,max_lots:100000,max_estimated_risk_multiple:1
 };
 const pattern={...patternDefaults,...f.candle_pattern};
 const setPattern=(patch:Partial<FuturesCandlePatternConfig>)=>{
  const enabled=patch.enabled===true;
  onChange({...value,
   ...(enabled?{market_type:'FUTURES' as const,timeframe:'5m' as const,entry_evaluation_timeframe:'strategy' as const,direction_mode:'PUT' as const,
    put_exit:{mode:'ANY' as const,min_pass:1,conditions:[],groups:[]},
    put_exit_signal_mode:'ORDER_ONLY' as const,
    risk:{...value.risk,max_hold_minutes:null,close_at_session_end:false},
    session:{...value.session,timezone:'Asia/Kolkata',
     blocked_weekdays:[...new Set([...value.session.blocked_weekdays,5,6])].sort()}}:{}),
   futures:{...f,...(enabled?{stop_loss_percent:null,take_profit_percent:null,
    rule_risk:{...ruleRisk,enabled:false},pullback:{...pullback,enabled:false},
    ...(f.adaptive?{adaptive:{...f.adaptive,enabled:false}}:{})}:{}),
    candle_pattern:{...pattern,...patch}}
  });
 };
 const patternNumber=(key:keyof FuturesCandlePatternConfig,label:string,min:number,step:number)=><label key={key}>{label}
  <input type="number" min={min} step={step} value={Number(pattern[key])}
   onChange={e=>setPattern({[key]:Number(e.target.value)})}/></label>;
 const risk=(patch:Record<string,any>)=>onChange({...value,risk:{...value.risk,...patch}});
 const session=(patch:Partial<Strategy['session']>)=>onChange({...value,session:{...value.session,...patch}});
 const windows=value.session.windows?.length?value.session.windows:[{start:'00:00',end:'23:59'}];
 const set=(patch:Partial<FuturesConfig>)=>onChange({...value,futures:{...f,...patch}});
 const number=(name:keyof FuturesConfig,label:string,step:string,min:number)=>(
  <label key={name}>{label}<input type="number" min={min} step={step} value={Number(f[name] ?? 0)}
  onChange={e=>set({[name]:Number(e.target.value)} as Partial<FuturesConfig>)}/></label>
 );
 const optional=(name:'stop_loss_percent'|'take_profit_percent',label:string)=>(
  <label>{label}<input type="number" min="0.01" step="0.1" placeholder="disabled" disabled={ruleRisk.enabled || pullback.enabled || !!f.adaptive?.enabled}
  value={f[name]??''} onChange={e=>set({[name]:e.target.value===''?null:Number(e.target.value)})}/></label>
 );
 return <><section className="card"><h2>BTCUSD perpetual futures research</h2>
 <p>CALL rules become LONG, PUT rules become SHORT. Entries and condition exits are placed at the following candle open. Only one position at a time. No option contracts are required.</p>
 <p>In unified ARCHIVE backtests, missing completed Delta India 1-minute mark, index and funding-rate candles are automatically downloaded once and reused from the data folder. Rate candles are not verified funding settlements: REQUIRE_CSV still needs validated settlement observations; EXCLUDE_WITH_WARNING leaves funding out. No real historical data has been fetched by this upgrade.</p>
 <div className="form-grid">
  <label>Direction<select value={value.direction_mode} onChange={e=>onChange({...value,direction_mode:e.target.value as Strategy['direction_mode']})}><option value="BOTH">LONG + SHORT</option><option value="CALL">LONG only</option><option value="PUT">SHORT only</option></select></label>
  <label>New-entry evaluation timeframe<select
    disabled={dedicatedEntry}
    value={value.entry_evaluation_timeframe??'strategy'}
    onChange={e=>onChange({...value,entry_evaluation_timeframe:e.target.value as Strategy['entry_evaluation_timeframe']})}>
    <option value="strategy">Every strategy candle (legacy)</option>
    {entryTimeframes.map(tf=><option key={tf} value={tf}>{tf} confirmed-candle gate</option>)}
   </select></label>
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
  {number('extra_half_spread_bps','Extra assumed half-spread (bps, no historical BBO)','0.5',0)}
  <label>Daily futures force-exit time (local)<input type="time" value={f.force_exit_time??''}
    onChange={e=>set({force_exit_time:e.target.value||null})}/></label>
   {number('tick_size','Assumed futures price tick ($)','0.5',0.000001)}
   {number('slippage_ticks','Additional adverse execution ticks','1',0)}
  {optional('stop_loss_percent','Price-based stop-loss %')}
  {optional('take_profit_percent','Price-based take-profit %')}
  <label>Funding history<select value={f.funding_mode} onChange={e=>set({funding_mode:e.target.value as FuturesConfig['funding_mode']})}><option value="REQUIRE_CSV">Require historical funding CSV</option><option value="EXCLUDE_WITH_WARNING">Exclude funding (research only)</option></select></label>
 </div>
 <p>New-entry evaluation is independent of protective stop / trailing execution. A higher-timeframe gate evaluates entries once on the first completed strategy candle after the confirmed higher-timeframe close, then fills at the next strategy open. Existing positions, risk exits, and entry lifecycle updates still run every strategy candle. For 1h RSI/SMA on a 5m base, use a 1h EMA(1) close proxy instead of raw 5m close. Dedicated candle-pattern, pullback and adaptive engines use their own entry schedules.</p>
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
 <section className="card"><h2>1H bearish candle pattern + 5M point trailing</h2>
  <p>Opt-in, SHORT-only. Completed UTC 1H candles establish the setup; the next hour opens at the first 5M bar open. Only complete 12-bar hours qualify. Each 5M high tests the fixed 1H stop, and the profit trail updates only after eligible completed 5M closes.</p>
  <label className="switch"><input type="checkbox" checked={pattern.enabled}
    onChange={e=>setPattern({enabled:e.target.checked})}/>Enable bearish continuation pattern</label>
  {pattern.enabled&&<div className="form-grid">
   <label>Entry candle<select value={pattern.entry_candle}
    onChange={e=>setPattern({entry_candle:Number(e.target.value) as 3|4})}>
     <option value={3}>3rd 1H candle open (green, red setup)</option>
     <option value={4}>4th 1H candle open (green, red, red setup)</option>
    </select></label>
   <label>Fixed stop anchor<select value={pattern.stop_anchor}
    onChange={e=>setPattern({stop_anchor:e.target.value as FuturesCandlePatternConfig['stop_anchor']})}>
     <option value="PATTERN_HIGHEST_HIGH">Highest HIGH across setup candles</option>
     <option value="SETUP_CANDLE_HIGH">Last completed setup candle HIGH</option>
     <option value="ENTRY_POINTS">Entry fill + fixed BTC points (SHORT)</option>
    </select></label>
   {pattern.stop_anchor==='ENTRY_POINTS'
    ? patternNumber('stop_loss_points','Initial stop distance above actual SHORT entry (BTC points)',.01,.5)
    : patternNumber('stop_buffer_ticks','Fixed stop buffer in price ticks',0,1)}
   <label className="switch"><input type="checkbox" checked={pattern.doji_filter_enabled}
    onChange={e=>setPattern({doji_filter_enabled:e.target.checked})}/>Reject doji 1H setup candles</label>
   {patternNumber('doji_threshold_percent','Minimum candle body / full range (%)',0,1)}
   <label>Profit-taking mode<select value={pattern.take_profit_mode}
    onChange={e=>setPattern({take_profit_mode:e.target.value as FuturesCandlePatternConfig['take_profit_mode']})}>
     <option value="TRAILING_POINTS">5M confirmed-close point trailing</option>
     <option value="FIXED_POINTS">Fixed BTC price-point target</option>
     <option value="NONE">Fixed 1H stop only</option>
    </select></label>
   {pattern.take_profit_mode==='TRAILING_POINTS'&&<>
    {patternNumber('activation_points','Profit activation distance (BTC points)',.01,.5)}
    {patternNumber('pullback_points','Trailing pullback distance (BTC points)',.01,.5)}
    <label className="switch"><input type="checkbox" checked={pattern.trailing_ignore_doji}
     onChange={e=>setPattern({trailing_ignore_doji:e.target.checked})}/>Skip doji 5M closes for activation and trailing updates</label>
   </>}
   {pattern.take_profit_mode==='FIXED_POINTS'&&patternNumber('fixed_target_points','Fixed take-profit distance (BTC points)',.01,.5)}
   <label>Position sizing<select value={pattern.size_mode}
    onChange={e=>setPattern({size_mode:e.target.value as FuturesCandlePatternConfig['size_mode']})}>
     <option value="RISK_EQUITY">Risk % of available equity</option>
     <option value="FIXED">Fixed whole lots, guarded by estimated risk</option>
    </select></label>
   {patternNumber('equity_risk_percent','Equity risk % per trade',.01,.1)}
   {patternNumber('max_lots','Maximum futures lots',1,1)}
   {patternNumber('max_estimated_risk_multiple','Fixed size estimated-risk allowance',1,.1)}
  </div>}
  <p>Enabling this mode selects FUTURES / SHORT-only / 5M, disables legacy percent exits, rule risk, pullback and adaptive. Configure Monday-Friday and the IST entry window in Futures risk and entry sessions. OHLC stop hits are research proxies, not guaranteed intrabar fills.</p>
 </section>
 <section className="card"><h2>Rule-tree futures dynamic risk</h2>
  <p>Opt-in swing/signal/ATR stops for ordinary CALL=LONG and PUT=SHORT rules, including VWAP strategies. Signal extremes and ATR are frozen at candle close; entry fills at the next open. Size estimates include fees and adverse stop slippage.</p>
  <label className="switch"><input type="checkbox" checked={ruleRisk.enabled}
   onChange={e=>setRuleRisk({enabled:e.target.checked})}/>Enable dynamic stop, R target and risk sizing</label>
  {ruleRisk.enabled&&<div className="form-grid">
   <label>Stop source<select value={ruleRisk.stop_mode} onChange={e=>setRuleRisk({stop_mode:e.target.value as typeof ruleRisk.stop_mode})}>
    <option value="SWING">Swing extreme</option><option value="SIGNAL_CANDLE">Signal candle</option><option value="ATR">ATR distance</option><option value="FIXED_POINTS">Fixed BTCUSD points from entry fill</option></select></label>
   {ruleRisk.stop_mode==='FIXED_POINTS'&&ruleNumber('stop_loss_points','Fixed stop distance (BTCUSD points)',0.5,0.5)}
   {ruleNumber('swing_lookback_bars','Completed candles in stop window',1,1)}
   <label>ATR indicator ID<input value={ruleRisk.atr_indicator_id} onChange={e=>setRuleRisk({atr_indicator_id:e.target.value})}/></label>
   {ruleNumber('stop_atr_multiple','ATR stop distance (ATR mode)',0.01,0.1)}
   {ruleNumber('stop_buffer_atr','Structure stop ATR buffer',0,0.1)}
   <label>ATR stop anchor<select value={ruleRisk.atr_stop_anchor||'SIGNAL_CLOSE'}
     disabled={ruleRisk.stop_mode!=='ATR'}
     onChange={e=>setRuleRisk({atr_stop_anchor:e.target.value as typeof ruleRisk.atr_stop_anchor})}>
     <option value="SIGNAL_CLOSE">Completed signal close (legacy)</option>
     <option value="ENTRY_FILL">Executed entry price</option>
   </select></label>
   <label>Take profit mode<select value={ruleRisk.take_profit_points!=null?'POINTS':ruleRisk.reward_r_multiple!=null?'R_MULTIPLE':'NONE'}
    onChange={e=>{const mode=e.target.value;setRuleRisk({
      reward_r_multiple:mode==='R_MULTIPLE'?2:null,
      take_profit_points:mode==='POINTS'?200:null
    });}}>
    <option value="R_MULTIPLE">Target as R multiple (legacy)</option>
    <option value="POINTS">Fixed BTCUSD price points</option>
    <option value="NONE">No take profit target</option>
   </select></label>
   {ruleRisk.take_profit_points!=null&&<label>Fixed target distance (BTCUSD points)
     <input type="number" min="0.01" step="0.5" value={ruleRisk.take_profit_points}
       onChange={e=>setRuleRisk({take_profit_points:Number(e.target.value)})}/></label>}
   {ruleRisk.take_profit_points==null&&ruleRisk.reward_r_multiple!=null&&<label>Target multiple of entry-stop distance
     <input type="number" min="0.01" step="0.1" value={ruleRisk.reward_r_multiple}
       onChange={e=>setRuleRisk({reward_r_multiple:Number(e.target.value)})}/></label>}
   <label>Protective stop / trailing execution candles<select value={ruleRisk.execution_timeframe??'strategy'}
    onChange={e=>setRuleRisk({execution_timeframe:e.target.value as 'strategy'|'5m'})}>
    <option value="strategy">Strategy timeframe (legacy)</option>
    <option value="5m">5-minute OHLC (also for higher-timeframe entry rules)</option>
   </select></label>
   <p>In 5m mode, entry and condition-exit signals stay on the strategy timeframe. Stops are checked on each 5m OHLC candle; trailing ratchets after a completed 5m candle and applies on the next 5m candle. Missing child candles fail the backtest. Higher-timeframe ATR trails use the last confirmed strategy-candle ATR.</p>
   <label className="switch"><input type="checkbox" checked={ruleRisk.trailing_enabled}
     onChange={e=>setRuleRisk({trailing_enabled:e.target.checked})}/>Enable dynamic trailing stop</label>
   {ruleRisk.trailing_enabled&&<label>Trailing mode<select value={ruleRisk.trailing_mode??'ATR'} onChange={e=>setRuleRisk({trailing_mode:e.target.value as typeof ruleRisk.trailing_mode})}><option value="ATR">Completed ATR (legacy)</option><option value="POINTS">Activate and trail by BTCUSD points</option></select></label>}
   {ruleRisk.trailing_enabled&&<>
    {(ruleRisk.trailing_mode??'ATR')==='POINTS'?<>
     {ruleNumber('trailing_activation_points','Activate after favorable BTCUSD points',0.5,0.5)}
     {ruleNumber('trailing_pullback_points','Trail pullback (BTCUSD points)',0.5,0.5)}
    </>:ruleNumber('trailing_atr_multiple','Trailing stop × completed ATR',0.01,0.25)}
    <label>Trailing reference<select value={ruleRisk.trailing_source}
      onChange={e=>setRuleRisk({trailing_source:e.target.value as typeof ruleRisk.trailing_source})}>
      <option value="HIGH_LOW">Highest high / lowest low</option>
      <option value="CLOSE">Highest / lowest close</option>
    </select></label>
   </>}
   <label>Position size<select value={ruleRisk.size_mode} onChange={e=>setRuleRisk({size_mode:e.target.value as typeof ruleRisk.size_mode})}><option value="RISK_EQUITY">Equity risk (whole lots)</option><option value="FIXED">Fixed lots with risk guard</option></select></label>
   {ruleNumber('equity_risk_percent','Equity risk % per trade',0.01,0.1)}
   {ruleNumber('max_lots','Maximum futures lots',1,1)}
   {ruleNumber('max_estimated_risk_multiple','Fixed size risk guard multiple',1,0.1)}
  </div>}
  </section>
  <section className="card"><h2>Stateful futures trend / pullback / breakout</h2>
 <p>Opt-in: freeze a completed setup candle and simulate either the original next-open confirmation or a stop-market trigger from subsequent 5m OHLC. Stop-market mode uses conservative same-bar ordering; no historical tick sequence or real BBO is available. Set one open position and one pending order at a time.</p>
 <label className="switch"><input type="checkbox" checked={pullback.enabled}
  onChange={e=>setup({enabled:e.target.checked})}/><span>Enable stateful futures pullback engine</span></label>
 {pullback.enabled&&<div className="form-grid">
  <label>Confirmation timeframe<select value={pullback.setup_timeframe}
   onChange={e=>setup({setup_timeframe:e.target.value as typeof pullback.setup_timeframe})}>
   <option value="15m">15m</option><option value="30m">30m</option><option value="1h">1h</option></select></label>
  <label>Setup EMA indicator ID<input value={pullback.ema_indicator_id} onChange={e=>setup({ema_indicator_id:e.target.value})}/></label>
  <label>Setup ATR indicator ID<input value={pullback.atr_indicator_id} onChange={e=>setup({atr_indicator_id:e.target.value})}/></label>
  <label>5m volume SMA indicator ID<input value={pullback.volume_indicator_id} onChange={e=>setup({volume_indicator_id:e.target.value})}/></label>
  <label>Entry execution<select value={pullback.execution_mode}
   onChange={e=>setup({execution_mode:e.target.value as typeof pullback.execution_mode})}>
   <option value="CLOSE_CONFIRM_NEXT_OPEN">Legacy: confirmed 5m close, next 5m open</option>
   <option value="STOP_MARKET_INTRABAR">Stop market: trigger on next 5m OHLC (research proxy)</option></select></label>
  <label>Protective stop anchor<select value={pullback.stop_anchor}
   onChange={e=>setup({stop_anchor:e.target.value as typeof pullback.stop_anchor})}>
   <option value="SWING">Last N completed setup candles swing</option>
   <option value="SIGNAL_CANDLE">Confirmation candle high/low</option></select></label>
  {setupNumber('max_wait_bars','Breakout expiry (5m candles; 6 = two 15m candles)','1',1)}
  {setupNumber('breakout_buffer_ticks','Stop trigger buffer in price ticks (minimum 1)','1',0)}
  {setupNumber('swing_lookback_bars','Swing window (completed setup candles)','1',1)}
  {setupNumber('stop_buffer_atr','Stop buffer × setup ATR','0.05',0)}
  {setupNumber('breakout_buffer_points','Breakout buffer (BTC points)','1',0)}
  {setupNumber('volume_multiplier','Volume must exceed SMA ×','0.1',0)}
  {setupNumber('reward_r_multiple','Target multiple of initial risk (R)','0.25',0.01)}
  <label>Size calculation<select value={pullback.size_mode} onChange={e=>setup({size_mode:e.target.value as typeof pullback.size_mode})}>
   <option value="RISK_EQUITY">Risk % of available equity</option><option value="FIXED">Existing fixed quantity, risk checked</option>
  </select></label>
  {setupNumber('equity_risk_percent','Maximum estimated equity risk %','0.1',0.01)}
  {setupNumber('max_lots','Maximum allowed lots','1',1)}
  {setupNumber('max_estimated_risk_multiple','Fixed-size risk allowance multiplier','0.1',1)}
  <label>1h fast trend EMA ID<input value={pullback.trend_fast_ema_id??''}
    placeholder="ema50_1h" onChange={e=>setup({trend_fast_ema_id:e.target.value||null})}/></label>
  <label>1h slow trend EMA ID<input value={pullback.trend_slow_ema_id??''}
    placeholder="ema200_1h" onChange={e=>setup({trend_slow_ema_id:e.target.value||null})}/></label>
  <label>1h close proxy EMA(1) ID<input value={pullback.trend_close_indicator_id??''}
    placeholder="close_1h" onChange={e=>setup({trend_close_indicator_id:e.target.value||null})}/></label>
  {setupNumber('trend_crossover_block_bars','Exclude recent EMA cross (completed 1h bars; 0 disables)','1',0)}
  <label className="switch"><input type="checkbox" checked={pullback.cancel_on_trend_invalidation}
   onChange={e=>setup({cancel_on_trend_invalidation:e.target.checked})}/>Cancel pending entry if confirmed 1h trend invalidates</label>
  <label className="switch"><input type="checkbox" checked={pullback.require_touch} onChange={e=>setup({require_touch:e.target.checked})}/>Require EMA touch</label>
  <label className="switch"><input type="checkbox" checked={pullback.require_confirmation_color} onChange={e=>setup({require_confirmation_color:e.target.checked})}/>Require confirmation candle direction</label>
  <label className="switch"><input type="checkbox" checked={pullback.require_volume} onChange={e=>setup({require_volume:e.target.checked})}/>Require breakout volume</label>
 </div>}
 <p>Research only: account equity risk is an estimate, not a hard guarantee. Stop gaps, spread, funding, and exchange liquidation can cause larger losses. Configure each indicator ID/timeframe in the indicator builder; the server validates them before running.</p>
 </section>
 <AdaptiveFuturesEditor value={value} onChange={onChange}/>
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
 <p>Entry windows limit new positions. For a 14:00-inclusive / 22:00-exclusive 5m schedule, use 14:00–21:59. Optional futures force-exit uses its own clock (e.g., 23:45) and closes at the corresponding 5m OPEN, without moving protective SL/TP. Legacy session-end and max-hold exits remain optional.</p>
 </section></>
}
