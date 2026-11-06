import {describe,it,expect} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {defaultStrategy} from '../defaults';
import {RiskOptions} from './RiskOptions';

describe('opt-in options underlying ATR stop and shared signals',()=>{
 it('is visible for options without altering legacy saved defaults',()=>{
  const strategy=defaultStrategy();
  expect(strategy.options_pullback).toBeUndefined();
  const html=renderToStaticMarkup(<RiskOptions value={strategy} onChange={()=>{}}/>);
  expect(html).toContain('Opt-in underlying stop-market pullback');
  expect(html).toContain('quote');
  expect(html).toContain('forced exit time');
  expect(html).toContain('Enable quote-backed options stop-market research');
 });
 it('exposes BTC pending-order, risk and trend settings in options mode',()=>{
  const strategy=defaultStrategy();
  strategy.options_pullback={
    enabled:true,execution_mode:'STOP_MARKET_INTRABAR',
    stop_anchor:'SIGNAL_CANDLE',setup_timeframe:'15m',
    ema_indicator_id:'ema20_15m',atr_indicator_id:'atr14_15m',
    volume_indicator_id:'volumeSMA20_5m',
    require_touch:true,require_confirmation_color:true,require_volume:false,
    volume_multiplier:1,max_wait_bars:6,swing_lookback_bars:3,
    stop_buffer_atr:0.1,breakout_buffer_points:0,breakout_buffer_ticks:1,
    reward_r_multiple:2,size_mode:'RISK_EQUITY',
    equity_risk_percent:0.5,max_lots:10000,max_estimated_risk_multiple:1,
    trend_crossover_block_bars:3,cancel_on_trend_invalidation:true,
    trend_fast_ema_id:'ema50_1h',trend_slow_ema_id:'ema200_1h',
    trend_close_indicator_id:'close_1h',underlying_tick_size:0.5,
  };
  strategy.options_force_exit_time='23:45';
  const html=renderToStaticMarkup(<RiskOptions value={strategy} onChange={()=>{}}/>);
  for (const label of ['Entry breakout buffer ticks','Stop buffer','Underlying BTC reward multiple',
                       'Maximum premium-risk equity','Recent completed 1h crosses to block',
                       'Cancel pending on trend invalidation','23:45']) {
    expect(html).toContain(label);
  }
 });
 it('does not show option-only controls when in futures market mode',()=>{
  const strategy=defaultStrategy();
  strategy.market_type='FUTURES';
  const html=renderToStaticMarkup(<RiskOptions value={strategy} onChange={()=>{}}/>);
  expect(html).not.toContain('Opt-in underlying stop-market pullback');
 });
});
