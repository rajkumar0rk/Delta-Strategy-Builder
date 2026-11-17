from types import SimpleNamespace

import pandas as pd
import pytest

from app.engine import _exit_blocks_candle, _executable_exit_price, _quantity, _select_option, _stop_reason
from app.models import ExecutionConfig, ExecutionSafetyCaps, StrategyConfig


def strategy():
    s = StrategyConfig()
    s.risk.quantity = 10
    s.risk.enforce_trade_budget_strict = False
    s.risk.enforce_cash = True
    s.execution.safety_caps = ExecutionSafetyCaps(max_spread_percent=3, per_trade_premium_usd=10, account_budget_usd=100)
    return s


@pytest.mark.parametrize('exit_time,blocked', [
    ('2026-11-14T06:50:00Z', False),
    ('2026-11-14T06:50:00.000001Z', True),
    ('2026-11-14T06:55:00Z', True),
    ('2026-11-14T12:20:00.000001+05:30', True),
])
def test_actual_exit_fill_blocks_its_completed_candle(exit_time, blocked):
    assert _exit_blocks_candle(pd.Timestamp('2026-11-14T06:55:00Z'), pd.Timestamp(exit_time), 5) is blocked
    assert not _exit_blocks_candle(pd.Timestamp('2026-11-14T07:00:00Z'), pd.Timestamp(exit_time), 5)


@pytest.mark.parametrize('action,bid,ask,fill', [('SELL', 114.8, 114.9, 115.9), ('BUY', 85.1, 85.2, 84.1)])
def test_option_stop_uses_quote_but_realized_exit_keeps_slippage(action, bid, ask, fill):
    s = strategy()
    s.execution.slippage_ticks = 1
    s.risk.stop_loss.mode = 'OPTION_PERCENT'
    s.risk.stop_loss.value = 15
    s.risk.take_profit.mode = 'NONE'
    s.risk.profit_protection.mode = 'NONE'
    pos = SimpleNamespace(action=action, entry_price=100, spec={'price_increment': 1}, peak_return=0., worst_return=0.)
    quote = {'bid': bid, 'ask': ask}
    assert _stop_reason(pos, quote, s)[0] is None
    assert _executable_exit_price(pos, quote, s) == pytest.approx(fill)
    quote['ask' if action == 'SELL' else 'bid'] = 115 if action == 'SELL' else 85
    assert _stop_reason(pos, quote, s)[0] == 'STOP_LOSS'


def test_json_safety_caps_limit_premium_and_cash_even_without_strict_budget():
    s = strategy()
    spec = {'contract_value': .001, 'size_increment': 1, 'min_quantity': 1}
    assert _quantity(s, spec, 100, 60000, 100)[0] == 10
    s.execution.safety_caps.per_trade_premium_usd = .5
    assert _quantity(s, spec, 100, 60000, 100)[2] == 'PER_TRADE_PREMIUM_LIMIT'
    s.execution.safety_caps.per_trade_premium_usd = 10
    s.execution.safety_caps.account_budget_usd = .5
    assert _quantity(s, spec, 100, 60000, 100)[2] == 'INSUFFICIENT_CASH'
    with pytest.raises(ValueError):
        ExecutionConfig(safety_caps={'max_spread_percent': 0})


def test_selection_checks_json_spread_cap_and_each_quotes_session():
    s = strategy()
    s.session.timezone = 'UTC'
    s.session.windows = []
    s.session.start = s.session.end = '06:55'
    s.session.blocked_weekdays = []
    s.option.max_spread_percent = 5
    s.option.min_dte_days = 1.3
    s.option.max_dte_days = 3
    at = pd.Timestamp('2026-11-14T06:55:00Z')
    inst = pd.DataFrame([
        dict(symbol='first', strike=60000, option_type='CE', activation=at-pd.Timedelta(days=1), expiration=at+pd.Timedelta(days=2)),
        dict(symbol='second', strike=60000, option_type='CE', activation=at-pd.Timedelta(days=1), expiration=at+pd.Timedelta(days=3)),
    ])
    class Store:
        def first_quote_many(self, parts, symbol, start, delay):
            return dict(timestamp=(at if symbol=='first' else at+pd.Timedelta(seconds=60)).isoformat(), bid=98 if symbol=='first' else 99.9, ask=102 if symbol=='first' else 100)
    spec, q, why = _select_option(Store(), [], inst, at, 60000, 'CALL', s)
    assert spec is None and q is None
    assert why == 'ENTRY_QUOTE_OUTSIDE_SESSION'


def test_backtest_does_not_reenter_the_candle_containing_a_late_exit_fill(tmp_path, monkeypatch):
    from app.engine import run_backtest
    from app.models import BacktestRequest, Condition, EntryBehavior, RuleGroup
    from test_v161_correctness_hardening import _csv, _seed, _strategy
    root = _seed(tmp_path, monkeypatch, expiration='2026-01-03T00:00:00Z')
    s = _strategy()
    s.call_entry = RuleGroup(conditions=[Condition(id='enter', left='close', operator='GT', value=0)])
    s.call_exit = RuleGroup(conditions=[Condition(id='exit', left='close', operator='GT', value=0)])
    s.call_entry_lifecycles = [EntryBehavior(id='repeat', delay_bars=0, max_entries_per_activation=None, cooldown_bars=0)]
    quotes = [dict(timestamp=(ts+pd.Timedelta(seconds=3)).isoformat(), symbol='BTC100CE', bid=10, ask=10.1,
                   bid_size=100, ask_size=100, volume=100, open_interest=100, source_event='fixture')
              for ts in pd.date_range('2026-01-01T00:00:00Z', periods=8, freq='5min')]
    _csv(root/'sample/option_quotes.csv', quotes)
    result = run_backtest(BacktestRequest(dataset_id='sample', start='2026-01-01T00:00:00Z', end='2026-01-01T00:35:00Z', strategy=s))
    trades = result['trades']
    assert len(trades) >= 2
    for previous, current in zip(trades, trades[1:]):
        assert pd.Timestamp(current['entry_time']) > pd.Timestamp(previous['exit_time']).ceil('5min')
