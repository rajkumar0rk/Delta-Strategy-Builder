import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { RiskOptions } from './components/RiskOptions';
import { defaultStrategy } from './defaults';

describe('configurable underlying signal-candle stop settings', () => {
  it('shows trigger, timeframe and buffer controls when signal-candle mode is selected', () => {
    const strategy = defaultStrategy();
    strategy.risk.stop_loss = {
      mode: 'UNDERLYING_SIGNAL_CANDLE',
      value: 15,
      signal_candle_trigger: 'CLOSE',
      signal_candle_execution_timeframe: '5m',
      signal_candle_buffer_points: 25,
    };
    const html = renderToStaticMarkup(createElement(RiskOptions, {
      value: strategy,
      onChange: () => {},
    }));
    expect(html).toContain('Stop trigger');
    expect(html).toContain('Stop monitor timeframe');
    expect(html).toContain('Signal-candle buffer (BTC points)');
    expect(html).toContain('5-minute candle');
    expect(html).toContain('25');
    expect(html).not.toContain('Stop value');
  });

  it('preserves old premium stop UI unless signal-candle mode is explicitly enabled', () => {
    const strategy = defaultStrategy();
    expect(strategy.risk.stop_loss.mode).toBe('OPTION_PERCENT');
    const html = renderToStaticMarkup(createElement(RiskOptions, {
      value: strategy,
      onChange: () => {},
    }));
    expect(html).toContain('Stop value');
    expect(html).not.toContain('Signal-candle buffer (BTC points)');
    expect(html).not.toContain('Stop monitor timeframe');
  });
});
