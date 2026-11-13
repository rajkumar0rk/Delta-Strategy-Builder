"""Point stop, activation/pullback trail and unlimited lifecycle regression tests."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from app.engine import run_backtest, _cycle_eligible, EntryCycleState
from app.futures_engine import _exit_level
from app.models import BacktestRequest, Condition, EntryBehavior, RuleGroup, StrategyConfig


def _strategy(direction="LONG"):
    s = StrategyConfig(
        market_type="FUTURES", timeframe="5m",
        direction_mode="CALL" if direction == "LONG" else "PUT",
        call_entry=RuleGroup(conditions=[Condition(id="long", left="close", operator="GT", value=1)]),
        put_entry=RuleGroup(conditions=[Condition(id="short", left="close", operator="GT", value=1)]),
        call_entry_lifecycles=[EntryBehavior(id="long-life", max_entries_per_activation=None)],
        put_entry_lifecycles=[EntryBehavior(id="short-life", max_entries_per_activation=None)],
    )
    s.futures.funding_mode = "EXCLUDE_WITH_WARNING"
    s.futures.stop_loss_percent = None
    s.futures.take_profit_percent = None
    s.futures.slippage_bps = 0
    s.futures.taker_fee_percent = 0
    s.risk.max_hold_minutes = None
    cfg = s.futures.rule_risk
    cfg.enabled = True
    cfg.stop_mode = "FIXED_POINTS"
    cfg.stop_loss_points = 500
    cfg.stop_buffer_atr = 0
    cfg.reward_r_multiple = None
    cfg.take_profit_points = None
    cfg.trailing_enabled = True
    cfg.trailing_mode = "POINTS"
    cfg.trailing_activation_points = 500
    cfg.trailing_pullback_points = 100
    cfg.trailing_source = "HIGH_LOW"
    cfg.size_mode = "FIXED"
    cfg.equity_risk_percent = 50
    return s


def _run(tmp_path, monkeypatch, bars, direction="LONG", strategy_timeframe="5m", risk_execution_timeframe="strategy"):
    data = tmp_path / "data" / "sample"
    data.mkdir(parents=True)
    for name, value in (("STRATEGY_LAB_DATA_ROOT", tmp_path / "data"),
                        ("STRATEGY_LAB_RESULT_ROOT", tmp_path / "results"),
                        ("STRATEGY_LAB_CACHE_ROOT", tmp_path / "cache")):
        monkeypatch.setenv(name, str(value))
    dates = pd.date_range("2026-01-01T00:05:00Z", periods=len(bars), freq="5min")
    records = [
        dict(timestamp=ts.isoformat(), open=o, high=h, low=l, close=c, volume=100)
        for ts, (o, h, l, c) in zip(dates, bars)
    ]
    with (data / "underlying_bars.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    s = _strategy(direction)
    s.timeframe = strategy_timeframe
    s.futures.rule_risk.execution_timeframe = risk_execution_timeframe
    return run_backtest(BacktestRequest(
        dataset_id="sample", start=dates[0].isoformat(),
        end=(dates[-1] + pd.Timedelta(minutes=5)).isoformat(), strategy=s))


def test_point_config_is_opt_in_without_atr_and_validates_tick_bounds():
    s = _strategy()
    assert StrategyConfig.model_validate(s.model_dump()).futures.rule_risk.stop_mode == "FIXED_POINTS"
    assert s.futures.rule_risk.trailing_mode == "POINTS"
    old = StrategyConfig().futures.rule_risk
    assert old.stop_mode == "SWING"
    assert old.trailing_mode == "ATR"
    assert EntryBehavior().max_entries_per_activation == 1
    assert EntryBehavior(max_entries_per_activation=None).max_entries_per_activation is None
    s.futures.rule_risk.stop_loss_points = 0.1
    with pytest.raises(ValidationError, match="tick_size"):
        StrategyConfig.model_validate(s.model_dump())
    s.futures.rule_risk.stop_loss_points = 500
    s.futures.rule_risk.trailing_pullback_points = 0.1
    with pytest.raises(ValidationError, match="tick_size"):
        StrategyConfig.model_validate(s.model_dump())


def test_unlimited_state_is_not_exhausted_but_finite_is():
    state = EntryCycleState(active=True, entries=101, start_index=0)
    behavior = EntryBehavior(max_entries_per_activation=None)
    assert _cycle_eligible(102, behavior, state, True)[0]
    limited = EntryBehavior(max_entries_per_activation=100)
    assert _cycle_eligible(102, limited, state, True)[1] == "MAX_ENTRIES_FOR_ACTIVATION"


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
def test_rule_point_stop_and_trail_are_symmetric_and_next_bar_only(tmp_path, monkeypatch, direction):
    entry = 100000
    flat = (entry, entry+40, entry-40, entry)
    bars = [flat for _ in range(24)]
    # Trigger activation with a favorable wick but do not retrospectively
    # execute the new trailing stop inside this very same OHLC candle.
    if direction == "LONG":
        bars[5] = (entry, entry+600, entry-20, entry+40)
        bars[6] = (entry+40, entry+60, entry+490, entry+50)
        # OHLC must be internally consistent; above is rewritten below.
        bars[6] = (entry+500, entry+520, entry+480, entry+500)
    else:
        bars[5] = (entry, entry+20, entry-600, entry-40)
        bars[6] = (entry-500, entry-480, entry-520, entry-500)
    result = _run(tmp_path, monkeypatch, bars, direction)
    assert result["metrics"]["trades"] >= 1
    trade = result["trades"][0]
    assert trade["initial_stop_price"] == (entry-500 if direction=="LONG" else entry+500)
    assert trade["target_price"] is None
    assert trade["exit_reason"] == "TRAILING_STOP"
    assert trade["exit_price"] == (entry+500 if direction=="LONG" else entry-500)


def test_reentry_persists_while_full_entry_tree_remains_true(tmp_path, monkeypatch):
    p = 100000
    bars = [(p, p+20, p-20, p) for _ in range(30)]
    bars[5] = (p, p+30, p-550, p)
    bars[15] = (p, p+30, p-550, p)
    result = _run(tmp_path, monkeypatch, bars)
    assert result["metrics"]["trades"] >= 2
    assert all(t["exit_reason"] == "STOP_LOSS" for t in result["trades"][:2])
    assert all(t["initial_stop_price"] == t["entry_price"]-500 for t in result["trades"][:2])


def test_reference_json_valid():
    path = Path(__file__).resolve().parents[1] / "examples" / "btc-futures-rsi2-sma200-point-trailing.strategy.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    cfg = StrategyConfig.model_validate(doc["strategy"])
    assert doc["schema_version"] == 15
    assert cfg.futures.rule_risk.stop_loss_points == 500
    assert cfg.futures.rule_risk.trailing_activation_points == 500
    assert cfg.futures.rule_risk.trailing_pullback_points == 100
    assert cfg.futures.rule_risk.execution_timeframe == "5m"
    assert cfg.call_entry.mode == "ALL"
    assert cfg.put_entry.mode == "ALL"
    long_rsi, long_sma = cfg.call_entry.conditions
    short_rsi, short_sma = cfg.put_entry.conditions
    assert (long_rsi.left, long_rsi.operator, long_rsi.value) == ("rsi2", "LT", 3)
    assert (short_rsi.left, short_rsi.operator, short_rsi.value) == ("rsi2", "GT", 97)
    assert (long_sma.left, long_sma.operator, long_sma.right) == ("close", "GT", "sma200")
    assert (short_sma.left, short_sma.operator, short_sma.right) == ("close", "LT", "sma200")
    assert cfg.call_entry_lifecycles[0].max_entries_per_activation is None
    assert cfg.put_entry_lifecycles[0].max_entries_per_activation is None


def test_5m_rule_stop_and_trailing_inside_hour(tmp_path, monkeypatch):
    """A 1h entry can trail at 01:20 and stop by 01:25, before 02:00."""
    p = 100000
    bars = [(p, p+20, p-20, p) for _ in range(72)]
    # The first full 1h signal completes at 01:00; trade fills at 01:00.
    bars[15] = (p, p+600, p-20, p+40)       # 01:20: activate stop at 100500
    bars[16] = (p+500, p+520, p+480, p+500) # 01:25: trailing stop touched
    result = _run(tmp_path, monkeypatch, bars, strategy_timeframe="1h",
                  risk_execution_timeframe="5m")
    assert result["metrics"]["trades"] >= 1
    trade = result["trades"][0]
    assert trade["exit_reason"] == "TRAILING_STOP"
    assert trade["initial_stop_price"] == p-500
    assert trade["exit_price"] == p+500
    assert pd.Timestamp(trade["exit_time"]) == pd.Timestamp("2026-01-01T01:25:00Z")
    assert result["futures_research"]["rule_risk_execution_timeframe"] == "5m"


def test_5m_rule_stop_before_hour_close(tmp_path, monkeypatch):
    p = 100000
    bars = [(p, p+20, p-20, p) for _ in range(72)]
    bars[14] = (p, p+20, p-550, p) # 01:15: initial protective stop
    result = _run(tmp_path, monkeypatch, bars, strategy_timeframe="1h",
                  risk_execution_timeframe="5m")
    assert result["metrics"]["trades"] >= 1
    trade = result["trades"][0]
    assert trade["exit_reason"] == "STOP_LOSS"
    assert trade["exit_price"] == p-500
    assert pd.Timestamp(trade["exit_time"]) == pd.Timestamp("2026-01-01T01:15:00Z")


def test_strategy_timeframe_default_stays_legacy(tmp_path, monkeypatch):
    p=100000
    bars=[(p,p+20,p-20,p) for _ in range(72)]
    bars[15]=(p,p+600,p-20,p+40)
    bars[16]=(p+500,p+520,p+480,p+500)
    result=_run(tmp_path, monkeypatch, bars, strategy_timeframe="1h")
    assert result["futures_research"]["rule_risk_execution_timeframe"] == "1h"
    assert all(pd.Timestamp(t["exit_time"]).minute == 0 for t in result["trades"])


def test_missing_5m_child_bars_fail_closed(tmp_path, monkeypatch):
    from app.data_store import DataStore

    original = DataStore.load_bars_many

    def missing_one_five(self, parts, start, end, timeframe="5m", warmup_candles=0):
        frame = original(self, parts, start, end, timeframe, warmup_candles)
        if timeframe == "5m":
            return frame.drop(pd.Timestamp("2026-01-01T01:20:00Z"), errors="ignore")
        return frame

    monkeypatch.setattr(DataStore, "load_bars_many", missing_one_five)
    p = 100000
    bars = [(p, p+20, p-20, p) for _ in range(72)]
    with pytest.raises(ValueError, match="FUTURES_RULE_RISK_5M_GAP"):
        _run(tmp_path, monkeypatch, bars, strategy_timeframe="1h",
             risk_execution_timeframe="5m")
