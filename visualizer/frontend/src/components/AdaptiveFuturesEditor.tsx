import type {AdaptiveFuturesConfig,AdaptiveRegimeConfig,AdaptiveBreakoutModule,AdaptiveTrailingStop,Strategy} from '../types';

const moduleDefault:AdaptiveBreakoutModule={enabled:true,setup_timeframe:'15m',
 donchian_id:'amrs_donchian_15m',atr_id:'amrs_atr_15m',volume_ratio_id:'amrs_volume_ratio_15m',
 volume_ratio_min:1.2,stop_lookback_bars:3,stop_atr_multiple:1.5,
 breakout_buffer_points:0,require_confirmation_color:true,require_retest:false,
 retest_max_wait_bars:12,retest_tolerance_atr:.25,reward_r_multiple:3};
const defaults:AdaptiveFuturesConfig={enabled:false,regime:{
 timeframe:'1h',fast_ema_id:'amrs_ema50_1h',slow_ema_id:'amrs_ema200_1h',
 close_ema_id:'amrs_close_1h',adx_id:'amrs_adx_1h',atr_percentile_id:'amrs_atr_percentile_1h',
 adx_trend_min:25,adx_range_max:20,atr_compression_max:30,atr_extreme_min:90,
 confirmations:2,compression_grace_hours:2,ema_slope_bars:2,require_ema_slope:true},
 trend:{...moduleDefault},compression:{...moduleDefault,volume_ratio_min:1.5,require_retest:true},
 trailing:{enabled:true,atr_id:'amrs_atr_15m',activation_r:2,atr_multiple:2,update_mode:'PRIOR_COMPLETED_BAR'},
 execution_mode:'STOP_MARKET_INTRABAR',breakout_buffer_ticks:1,breakout_buffer_points:0,
 max_wait_bars:3,cancel_on_trend_invalidation:true,
 size_mode:'RISK_EQUITY',equity_risk_percent:.5,max_lots:100000,
 max_estimated_risk_multiple:1,reward_r_multiple:3};

export function AdaptiveFuturesEditor({value,onChange}:{value:Strategy;onChange:(strategy:Strategy)=>void}){
 const current=value.futures?.adaptive;
 const adaptive:AdaptiveFuturesConfig={...defaults,...current,
  regime:{...defaults.regime,...current?.regime},
  trend:{...defaults.trend,...current?.trend},
  compression:{...defaults.compression,...current?.compression},
  trailing:{...defaults.trailing,...current?.trailing}};
 const update=(patch:Partial<AdaptiveFuturesConfig>)=>{
  const next={...adaptive,...patch};
  onChange({...value,futures:{...value.futures!,adaptive:next,
   ...(next.enabled?{...(value.futures?.pullback?
      {pullback:{...value.futures.pullback,enabled:false}}:{}),
    stop_loss_percent:null,take_profit_percent:null}: {})}});
 };
 const regime=(patch:Partial<AdaptiveRegimeConfig>)=>update({regime:{...adaptive.regime,...patch}});
 const moduleUpdate=(kind:'trend'|'compression',patch:Partial<AdaptiveBreakoutModule>)=>
  update({[kind]:{...adaptive[kind],...patch}});
 const trailing=(patch:Partial<AdaptiveTrailingStop>)=>update({trailing:{...adaptive.trailing,...patch}});
 const num=(label:string,v:number,onValue:(n:number)=>void,min=0,step=.1)=>
  <label>{label}<input type="number" min={min} step={step} value={v}
   onChange={e=>onValue(Number(e.target.value))}/></label>;
 const str=(label:string,v:string,onValue:(s:string)=>void)=>
  <label>{label}<input value={v} onChange={e=>onValue(e.target.value)}/></label>;
 const check=(label:string,v:boolean,onValue:(b:boolean)=>void)=>
  <label className="switch"><input type="checkbox" checked={v}
   onChange={e=>onValue(e.target.checked)}/><span>{label}</span></label>;
 const moduleEditor=(kind:'trend'|'compression')=>{
  const m=adaptive[kind];
  return <div key={kind}><h3>{kind==='trend'?'Trend continuation':'Compression breakout + retest'}</h3>
   <div className="form-grid">
    {check('Enabled',m.enabled,n=>moduleUpdate(kind,{enabled:n}))}
    {str('Donchian (15m) indicator ID',m.donchian_id,n=>moduleUpdate(kind,{donchian_id:n}))}
    {str('ATR (15m) indicator ID',m.atr_id,n=>moduleUpdate(kind,{atr_id:n}))}
    {str('Volume ratio (15m) indicator ID',m.volume_ratio_id,n=>moduleUpdate(kind,{volume_ratio_id:n}))}
    {num('Minimum volume ratio',m.volume_ratio_min,n=>moduleUpdate(kind,{volume_ratio_min:n}))}
    {num('Swing lookback (15m candles)',m.stop_lookback_bars,n=>moduleUpdate(kind,{stop_lookback_bars:n}),1,1)}
    {num('Structure stop buffer × ATR',m.stop_atr_multiple,n=>moduleUpdate(kind,{stop_atr_multiple:n}),.1)}
    {num('Breakout buffer (BTC points)',m.breakout_buffer_points,n=>moduleUpdate(kind,{breakout_buffer_points:n}))}
    {check('Require breakout candle color',m.require_confirmation_color,n=>moduleUpdate(kind,{require_confirmation_color:n}))}
    {check('Require completed 15m retest',m.require_retest,n=>moduleUpdate(kind,{require_retest:n}))}
    {num('Retest expiry (5m bars)',m.retest_max_wait_bars,n=>moduleUpdate(kind,{retest_max_wait_bars:n}),1,1)}
    {num('Retest tolerance × ATR',m.retest_tolerance_atr,n=>moduleUpdate(kind,{retest_tolerance_atr:n}))}
    {num('Target multiple (R)',m.reward_r_multiple,n=>moduleUpdate(kind,{reward_r_multiple:n}),.1)}
   </div></div>;
 };
 return <section className="card"><h2>Adaptive market-regime Futures (AMRS)</h2>
  <p>Optional regime router: two confirmed 1h states, separate trend/compression
  breakout modules, completed 15m retest, structure/ATR stops and a trailing stop
  updated only from the prior completed bar. Enable with the matching non-chart-only
  indicator IDs. Legacy Futures strategies stay unchanged.</p>
  {check('Enable AMRS (disables legacy pullback / percent stops)',adaptive.enabled,n=>update({enabled:n}))}
  {adaptive.enabled&&<>
   <h3>1h market regime</h3>
   <div className="form-grid">
    {str('Fast EMA indicator',adaptive.regime.fast_ema_id,n=>regime({fast_ema_id:n}))}
    {str('Slow EMA indicator',adaptive.regime.slow_ema_id,n=>regime({slow_ema_id:n}))}
    {str('1h close proxy EMA(1)',adaptive.regime.close_ema_id,n=>regime({close_ema_id:n}))}
    {str('1h ADX_DMI indicator',adaptive.regime.adx_id,n=>regime({adx_id:n}))}
    {str('1h ATR_PERCENTILE indicator',adaptive.regime.atr_percentile_id,n=>regime({atr_percentile_id:n}))}
    {num('Trend ADX ≥',adaptive.regime.adx_trend_min,n=>regime({adx_trend_min:n}))}
    {num('Range ADX <',adaptive.regime.adx_range_max,n=>regime({adx_range_max:n}))}
    {num('Compression ATR percentile ≤',adaptive.regime.atr_compression_max,n=>regime({atr_compression_max:n}))}
    {num('Extreme ATR percentile ≥',adaptive.regime.atr_extreme_min,n=>regime({atr_extreme_min:n}))}
    {num('Regime confirmations (1h candles)',adaptive.regime.confirmations,n=>regime({confirmations:n}),1,1)}
    {num('EMA slope lookback (1h bars)',adaptive.regime.ema_slope_bars,n=>regime({ema_slope_bars:n}),1,1)}
    {check('Require correct EMA slope',adaptive.regime.require_ema_slope,n=>regime({require_ema_slope:n}))}
   </div>
   {moduleEditor('trend')}
   {moduleEditor('compression')}
   <h3>Trailing stop and trade sizing</h3>
   <div className="form-grid">
    {check('ATR trailing enabled',adaptive.trailing.enabled,n=>trailing({enabled:n}))}
    {str('Trailing ATR indicator ID',adaptive.trailing.atr_id,n=>trailing({atr_id:n}))}
    {num('Activate trailing after R',adaptive.trailing.activation_r,n=>trailing({activation_r:n}),.1)}
    {num('Trailing distance × ATR',adaptive.trailing.atr_multiple,n=>trailing({atr_multiple:n}),.1)}
    {num('Entry order expiry (5m bars)',adaptive.max_wait_bars,n=>update({max_wait_bars:n}),1,1)}
    {num('Breakout buffer ticks',adaptive.breakout_buffer_ticks,n=>update({breakout_buffer_ticks:n}),1,1)}
    {num('Breakout buffer BTC points',adaptive.breakout_buffer_points,n=>update({breakout_buffer_points:n}))}
    {num('Estimated risk per trade %',adaptive.equity_risk_percent,n=>update({equity_risk_percent:n}),.01)}
    {num('Maximum whole lots',adaptive.max_lots,n=>update({max_lots:n}),1,1)}
    {check('Cancel pending orders on regime change',adaptive.cancel_on_trend_invalidation,n=>update({cancel_on_trend_invalidation:n}))}
   </div>
  </>}
  <p>Research only. A single pending stop is simulated with 5m OHLC, not exchange ticks.
  Trailing stops cannot guarantee the configured risk in a gap or liquidation.</p>
 </section>;
}
