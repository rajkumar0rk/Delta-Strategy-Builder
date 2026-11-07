import {describe,expect,it} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {defaultStrategy} from '../defaults';
import {FuturesSettings} from './FuturesSettings';
import {Results} from './Results';
import type {BacktestResult} from '../types';

describe('BTCUSD perpetual futures market editor',()=>{
 it('keeps existing strategy files defaulting to OPTIONS',()=>{
  expect(defaultStrategy().market_type).toBe('OPTIONS');
 });
 it('shows futures contract sizing, leverage, costs, funding and margin risk controls',()=>{
  const s=defaultStrategy();s.market_type='FUTURES';
  const html=renderToStaticMarkup(<FuturesSettings value={s} onChange={()=>{}}/>);
  for(const field of ['LONG + SHORT','Quantity (lots of 0.001 BTC)',
     'Assumed leverage','Isolated','Cross','Taker fee','GST','Adverse slippage',
     'Funding history','Require historical funding CSV','automatically downloaded once','not verified funding settlements','Starting balance',
     'Daily max loss','Maximum hold','session boundary','Add session window']){
    expect(html).toContain(field);
  }
  expect(html).not.toContain('SELL collateral &amp; leverage');
 });
 it('separates regular missing BTC archive downloads from optional futures observations',()=>{
   // The choice is owned by App (BacktestRequest), not FuturesConfig.
   const s=defaultStrategy();s.market_type='FUTURES';
   expect(s.futures?.funding_mode).toBe('REQUIRE_CSV');
   const html=renderToStaticMarkup(<FuturesSettings value={s} onChange={()=>{}}/>);
   expect(html).toContain('Funding history');
   expect(html).not.toContain('auto_sync_futures_observations');
 });
 it('shows configurable prior-entry candle stop and gap controls',()=>{
  const s=defaultStrategy();s.market_type='FUTURES';
  s.futures={...s.futures!,rule_risk:{
   enabled:true,stop_mode:'SIGNAL_CANDLE',swing_lookback_bars:1,
   atr_indicator_id:'atr14_5m',stop_atr_multiple:1.5,stop_buffer_atr:0,
   reward_r_multiple:3,take_profit_points:null,
   stop_candle_offset_bars:0,max_entry_gap_percent:0.5,
   size_mode:'RISK_EQUITY',equity_risk_percent:1,max_lots:100000,
   max_estimated_risk_multiple:1}};
  const html=renderToStaticMarkup(<FuturesSettings value={s} onChange={()=>{}}/>);
  expect(html).toContain('Stop candle reference');
  expect(html).toContain('Signal candle (previous candle at entry)');
  expect(html).toContain('Max next-open gap from signal close');
  expect(html).toContain('Target multiple of entry-stop distance');
 });
 it('shows the configurable futures stop guards and confirmed-close profit controls',()=>{
   const s=defaultStrategy();s.market_type='FUTURES';
   s.futures={...s.futures!,rule_risk:{
    enabled:true,stop_mode:'SWING',swing_lookback_bars:2,stop_candle_offset_bars:0,
    max_entry_gap_percent:0.5,max_stop_distance_percent:1.0,max_stop_distance_atr:3.0,
    condition_exit_activation_r:0.5,breakeven_activation_r:1.0,breakeven_offset_ticks:0,
    atr_indicator_id:'atr14_1h',stop_atr_multiple:1.5,stop_buffer_atr:0,
    reward_r_multiple:null,take_profit_points:null,
    size_mode:'RISK_EQUITY',equity_risk_percent:0.5,max_lots:100000,
    max_estimated_risk_multiple:1}};
   const html=renderToStaticMarkup(<FuturesSettings value={s} onChange={()=>{}}/>);
   for(const text of ['Max initial stop distance (% of fill)',
     'Max initial stop distance (× frozen ATR)','Condition exit activation',
     'Move stop to breakeven','Breakeven stop offset'])
     expect(html).toContain(text);
 });
 it('clearly labels simulated futures fills in result report',()=>{
  const s=defaultStrategy();s.market_type='FUTURES';
  const result:BacktestResult={run_id:'test',result_dir:'test',storage_mode:'COMPACT',strategy:s,
    start:'2026-01-01T00:00:00Z',end:'2026-01-02T00:00:00Z',
    decision_count:0,trades:[],markers:[],equity_curve:[],metrics:{trades:0,wins:0,losses:0,win_rate_percent:0,
      gross_pnl_usd:0,net_pnl_usd:0,fees_usd:0,gst_usd:0,
      profit_factor:null,return_percent:0,max_closed_trade_drawdown_usd:0,
      max_closed_trade_drawdown_percent:0,avg_mfe_percent:0,avg_mae_percent:0,
      funding_usd:0,estimated_margin_breaches:0,ambiguous_intrabar_stop_target:0}
  };
  const html=renderToStaticMarkup(<Results r={result}/>);
  expect(html).toContain('FUTURES OHLC RESEARCH ONLY');
  expect(html).toContain('funding');
  expect(html).not.toContain('Delta option trading cost model');
 });
});
