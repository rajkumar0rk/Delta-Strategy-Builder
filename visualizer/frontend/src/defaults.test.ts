import { describe, expect, it } from 'vitest';
import { behavior, cond, defaultStrategy, group } from './defaults';

describe('new strategy defaults', () => {
  it('starts with separate BUY CALL/PUT entries and independent lifecycles', () => {
    const strategy = defaultStrategy();
    expect(strategy.timeframe).toBe('5m');
    expect(strategy.direction_mode).toBe('BOTH');
    expect(strategy.position_policy).toBe('EXCLUSIVE');
    expect(strategy.call_action).toBe('BUY');
    expect(strategy.put_action).toBe('BUY');
    expect(strategy.call_entry.conditions.length).toBeGreaterThan(0);
    expect(strategy.put_entry.conditions.length).toBeGreaterThan(0);
    expect(strategy.call_entry_lifecycles).toHaveLength(1);
    expect(strategy.put_entry_lifecycles).toHaveLength(1);
    expect(strategy.call_entry_lifecycles[0].id).not.toBe(strategy.put_entry_lifecycles[0].id);
  });

  it('does not accidentally enable NO TRADE gates or higher-timeframe lookahead', () => {
    const strategy = defaultStrategy();
    for (const gate of [strategy.no_trade, strategy.call_no_trade, strategy.put_no_trade]) {
      expect(gate.conditions).toHaveLength(0);
      expect(gate.groups).toHaveLength(0);
    }
    expect(strategy.indicators.every(ind => ind.timeframe == null || ind.timeframe === 'strategy')).toBe(true);
    expect(strategy.indicators.every(ind => ind.chart_only === false)).toBe(true);
  });

  it('keeps contract validity and trading budget checks enabled', () => {
    const strategy = defaultStrategy();
    expect(strategy.risk.enforce_trade_budget_strict).toBe(true);
    expect(strategy.risk.enforce_cash).toBe(true);
    expect(strategy.risk.starting_balance_usd).toBeGreaterThan(0);
    expect(strategy.execution.fee_model).toBe('DELTA_OPTIONS');
    expect(strategy.execution.option_notional_fee_rate_percent).toBe(0.01);
    expect(strategy.execution.premium_fee_cap_percent).toBe(3.5);
    expect(strategy.execution.gst_percent).toBe(18);
  });

  it('returns fresh nested objects on each call', () => {
    const first = defaultStrategy();
    const second = defaultStrategy();
    first.indicators[0].params.period = 999;
    first.call_entry.conditions[0].left = 'changed';
    first.call_entry_lifecycles[0].name = 'changed';
    first.session.windows[0].start = '10:00';
    expect(second.indicators[0].params.period).toBe(9);
    expect(second.call_entry.conditions[0].left).toBe('ema9');
    expect(second.call_entry_lifecycles[0].name).not.toBe('changed');
    expect(second.session.windows[0].start).toBe('00:00');
  });

  it('creates unique condition identifiers across CALL and PUT rules', () => {
    const strategy = defaultStrategy();
    const conditions = [
      ...strategy.call_entry.conditions,
      ...strategy.put_entry.conditions,
      ...strategy.call_exit.conditions,
      ...strategy.put_exit.conditions,
    ];
    expect(new Set(conditions.map(c => c.id)).size).toBe(conditions.length);
    expect(conditions.every(c => /^[A-Za-z][A-Za-z0-9_-]*$/.test(c.id))).toBe(true);
  });
});

describe('rule and lifecycle constructors', () => {
  it('does not share condition arrays or behavior objects by default', () => {
    const a = group();
    const b = group();
    a.conditions.push(cond());
    expect(b.conditions).toHaveLength(0);
    const call = behavior('CALL');
    const put = behavior('PUT');
    expect(call.id).not.toBe(put.id);
    expect(call.trigger_condition_id).toBeNull();
    expect(put.trigger_condition_id).toBeNull();
  });
});
