import {describe, expect, it} from 'vitest';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {RiskOptions} from './components/RiskOptions';
import {defaultStrategy} from './defaults';

describe('options underlying signal-candle stop UI',()=>{
  it('shows buffer, trigger and timeframe for the new mode',()=>{
    const strategy=defaultStrategy();
    strategy.risk.stop_loss={
      mode:'UNDERLYING_SIGNAL_CANDLE',value:15,
      signal_candle_trigger:'WICK',
      signal_candle_execution_timeframe:'5m',
      signal_candle_buffer_points:25
    };
    const html=renderToStaticMarkup(createElement(RiskOptions,{value:strategy,onChange:()=>{}}));
    expect(html).toContain('Stop buffer (BTC points)');
    expect(html).toContain('Monitoring candle');
    expect(html).toContain('5-minute candle');
    expect(html).not.toContain('Stop value');
  });
  it('preserves existing option premium stop as default',()=>{
    const strategy=defaultStrategy();
    const html=renderToStaticMarkup(createElement(RiskOptions,{value:strategy,onChange:()=>{}}));
    expect(html).toContain('Stop value');
    expect(html).not.toContain('Stop buffer (BTC points)');
  });
});
