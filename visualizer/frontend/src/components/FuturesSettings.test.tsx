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
 it('configures a separate opt-in confirmed higher timeframe for new futures entries',()=>{
   const s=defaultStrategy();s.market_type='FUTURES';s.timeframe='5m';
   s.entry_evaluation_timeframe='1h';
   const html=renderToStaticMarkup(<FuturesSettings value={s} onChange={()=>{}}/>);
   expect(html).toContain('New-entry evaluation timeframe');
   expect(html).toContain('1h confirmed-candle gate');
   expect(html).toContain('4h confirmed-candle gate');
   expect(html).toContain('Every strategy candle (legacy)');
   expect(html).toContain('entry lifecycle updates still run');
 });
 it('separates regular missing BTC archive downloads from optional futures observations',()=>{
   // The choice is owned by App (BacktestRequest), not FuturesConfig.
   const s=defaultStrategy();s.market_type='FUTURES';
   expect(s.futures?.funding_mode).toBe('REQUIRE_CSV');
   const html=renderToStaticMarkup(<FuturesSettings value={s} onChange={()=>{}}/>);
   expect(html).toContain('Funding history');
   expect(html).not.toContain('auto_sync_futures_observations');
 });
 it('renders the imported capital-based stop without silently discarding it',()=>{
  const s=defaultStrategy();s.market_type='FUTURES';
  s.futures={...s.futures!,capital_stop:{
   enabled:true,capital_basis:'FIXED_USD',capital_usd:10,loss_percent:15}};
  const html=renderToStaticMarkup(<FuturesSettings value={s} onChange={()=>{}}/>);
  for(const token of ['Futures allocated-capital stop','Fixed allocated USD',
     'Estimated initial margin per position','Available account balance at entry',
     'Allocated capital (USD)','Max net loss','15%','$1.50','Maximum hold']){
   expect(html).toContain(token);
  }
 });
 it('shows the dedicated confirmed-1h first EMA20 touch and reference 2R configuration',()=>{
  const s=defaultStrategy();s.market_type='FUTURES';
  s.futures={...s.futures!,supertrend_ema_first_touch:{
   enabled:true,supertrend_indicator_id:'supertrend_1h',
   ema_indicator_id:'ema20_1h',reward_r_multiple:2}};
  const html=renderToStaticMarkup(<FuturesSettings value={s} onChange={()=>{}}/>);
  expect(html).toContain('1H Supertrend');
  expect(html).toContain('Enable Supertrend entry');
  expect(html).toContain('supertrend_1h');
  expect(html).toContain('ema20_1h');
  expect(html).toContain('NEXT 5M open');
  expect(html).toContain('not 1-minute');
 });
 it('shows 200-point trailing for the Supertrend EMA20 first touch without fixed TP',()=>{
  const s=defaultStrategy();s.market_type='FUTURES';s.timeframe='5m';
  s.futures={...s.futures!,supertrend_ema_first_touch:{
   enabled:true,supertrend_indicator_id:'supertrend_1h',
   ema_indicator_id:'ema20_1h',exit_mode:'POINT_TRAIL',trailing_distance_points:200}};
  const html=renderToStaticMarkup(<FuturesSettings value={s} onChange={()=>{}}/>);
  expect(html).toContain('200-point trailing');
  expect(html).toContain('Trailing distance (BTCUSD points)');
  expect(html).toContain('value="200"');
  expect(html).toContain('No fixed TP');
  expect(html).not.toContain('1H ATR indicator ID');
 });
 it('renders breakout and profit-activated trailing from imported strategy',()=>{
  const s=defaultStrategy();s.market_type='FUTURES';
  s.futures={...s.futures!,supertrend_ema_first_touch:{
   enabled:true,supertrend_indicator_id:'supertrend_1h',
   ema_indicator_id:'ema20_1h',entry_mode:'BREAKOUT_OR_REJECTION',
   breakout_lookback_bars:12,swing_stop_lookback_bars:12,require_ema_slope:true,
   exit_mode:'ACTIVATED_POINT_TRAIL',trailing_activation_points:500,trailing_distance_points:200}};
  const html=renderToStaticMarkup(<FuturesSettings value={s} onChange={()=>{}}/>);
  for(const field of ['12-candle breakout','BREAKOUT_OR_REJECTION',
    'Breakout lookback (completed 5M bars)','Swing stop lookback',
    'Trailing activate after favorable BTCUSD points','value="500"',
    'Trailing distance (BTCUSD points)','value="200"']){
   expect(html).toContain(field);
  }
  expect(html).not.toContain('1H ATR indicator ID');
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
