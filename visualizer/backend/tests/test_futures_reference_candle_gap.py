"""Regression tests: configurable futures candle stop and next-open gap guards.

This feature is opt-in; legacy rule-risk configurations keep their existing
signal-candle stop and no-limit gap behavior.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models import FuturesRuleRiskConfig, StrategyConfig


def _example() -> StrategyConfig:
    path = (Path(__file__).resolve().parents[1] / "examples"
            / "btc-futures-vwap-ema11-rule-risk.strategy.json")
    return StrategyConfig.model_validate(json.loads(path.read_text())["strategy"])


def test_new_rule_risk_config_defaults_preserve_legacy_behavior():
    risk = FuturesRuleRiskConfig()
    assert risk.stop_candle_offset_bars == 0
    assert risk.max_entry_gap_percent is None
    assert risk.reward_r_multiple == 2
    assert risk.take_profit_points is None


@pytest.mark.parametrize("offset", [0, 1, 2, 3, 200])
def test_reference_candle_stop_offsets_are_configurable(offset):
    risk = FuturesRuleRiskConfig(stop_mode="SIGNAL_CANDLE",
                                  stop_candle_offset_bars=offset,
                                  reward_r_multiple=3)
    assert risk.stop_candle_offset_bars == offset
    assert risk.reward_r_multiple == 3


@pytest.mark.parametrize("config", [
    {"stop_mode": "SWING", "stop_candle_offset_bars": 1},
    {"stop_mode": "ATR", "stop_candle_offset_bars": 1},
    {"stop_mode": "SIGNAL_CANDLE", "stop_candle_offset_bars": -1},
    {"stop_mode": "SIGNAL_CANDLE", "stop_candle_offset_bars": 201},
    {"max_entry_gap_percent": -0.01},
    {"max_entry_gap_percent": 101},
])
def test_invalid_reference_and_gap_values_rejected(config):
    with pytest.raises(ValidationError):
        FuturesRuleRiskConfig.model_validate(config)


@pytest.mark.parametrize("gap", [None, 0.0, 0.1, 0.5, 5.0, 100.0])
def test_gap_limit_round_trips_in_strategy_json(gap):
    s = _example().model_dump()
    s["futures"]["rule_risk"]["stop_mode"] = "SIGNAL_CANDLE"
    s["futures"]["rule_risk"]["stop_candle_offset_bars"] = 1
    s["futures"]["rule_risk"]["max_entry_gap_percent"] = gap
    parsed = StrategyConfig.model_validate(s)
    saved = parsed.model_dump()
    assert saved["futures"]["rule_risk"]["stop_candle_offset_bars"] == 1
    assert saved["futures"]["rule_risk"]["max_entry_gap_percent"] == gap
    assert StrategyConfig.model_validate(saved).futures.rule_risk.reward_r_multiple == 2


def test_reference_candle_example_is_importable_and_uses_3r():
    path = Path(__file__).resolve().parents[1] / "examples" / "btc-futures-1h-previous-candle-3r.strategy.json"
    document = json.loads(path.read_text())
    assert document["schema_version"] == 15
    strategy = StrategyConfig.model_validate(document["strategy"])
    assert strategy.timeframe == "1h"
    assert strategy.futures.rule_risk.enabled
    assert strategy.futures.rule_risk.stop_mode == "SIGNAL_CANDLE"
    assert strategy.futures.rule_risk.stop_candle_offset_bars == 0
    assert strategy.futures.rule_risk.max_entry_gap_percent == 0.5
    assert strategy.futures.rule_risk.reward_r_multiple == 3
    assert strategy.futures.rule_risk.take_profit_points is None
    assert strategy.futures.stop_loss_percent is None
    assert strategy.futures.take_profit_percent is None


def _run_reference_backtest(tmp_path, monkeypatch, *, offset: int, gap_limit, conditional_exit=False, no_time_exit=False, **risk_overrides):
    """End-to-end signal-close snapshot, prior-candle offset and next-open fills."""
    import csv

    import pandas as pd

    from app.engine import run_backtest
    from app.models import BacktestRequest, Condition, RuleGroup

    data = tmp_path / "data" / "sample"
    data.mkdir(parents=True)
    monkeypatch.setenv("STRATEGY_LAB_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("STRATEGY_LAB_RESULT_ROOT", str(tmp_path / "results"))
    monkeypatch.setenv("STRATEGY_LAB_CACHE_ROOT", str(tmp_path / "cache"))
    idx = pd.date_range("2026-01-01T00:05:00Z", periods=140, freq="5min")
    rows = []
    for i, timestamp in enumerate(idx):
        price = 10000 + (i * 3 if i < 100 else 300 - (i - 100) * 18)
        rows.append({"timestamp": timestamp.isoformat(), "open": price,
                     "high": price + 9, "low": price - 9, "close": price + 1,
                     "volume": 100})
    with (data / "underlying_bars.csv").open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    strategy = StrategyConfig(
        market_type="FUTURES", direction_mode="CALL", timeframe="5m",
        call_entry=RuleGroup(conditions=[
            Condition(id="entry", left="close", operator="GT", value=10040)]))
    strategy.futures.funding_mode = "EXCLUDE_WITH_WARNING"
    strategy.futures.stop_loss_percent = None
    strategy.futures.take_profit_percent = None
    strategy.futures.slippage_bps = 0
    strategy.futures.slippage_ticks = 0
    rc = strategy.futures.rule_risk
    rc.enabled = True
    rc.stop_mode = "SIGNAL_CANDLE"
    rc.stop_candle_offset_bars = offset
    rc.stop_buffer_atr = 0
    rc.max_entry_gap_percent = gap_limit
    rc.reward_r_multiple = 3
    for key, val in risk_overrides.items():
        setattr(rc, key, val)
    if conditional_exit:
        strategy.call_exit = RuleGroup(conditions=[
            Condition(id="always-exit", left="close", operator="GT", value=0)])
    strategy.risk.starting_balance_usd = 1000
    strategy.risk.max_daily_loss_percent = None
    if no_time_exit:
        strategy.risk.max_hold_minutes = None
    return run_backtest(BacktestRequest(
        dataset_id="sample", start="2026-01-01T00:05:00Z",
        end="2026-01-01T11:40:00Z", strategy=strategy))


def test_preceding_candle_changes_frozen_stop_and_3r(tmp_path, monkeypatch):
    current = _run_reference_backtest(tmp_path / "current", monkeypatch,
                                      offset=0, gap_limit=None)
    earlier = _run_reference_backtest(tmp_path / "earlier", monkeypatch,
                                      offset=1, gap_limit=None)
    assert current["metrics"]["trades"] >= 1
    assert earlier["metrics"]["trades"] >= 1
    a, b = current["trades"][0], earlier["trades"][0]
    assert a["entry_price"] == b["entry_price"]
    assert a["initial_stop_price"] - b["initial_stop_price"] == pytest.approx(3)
    assert a["target_price"] == pytest.approx(
        a["entry_price"] + 3 * (a["entry_price"] - a["initial_stop_price"]))
    assert b["target_price"] == pytest.approx(
        b["entry_price"] + 3 * (b["entry_price"] - b["initial_stop_price"]))


def test_gap_guard_rejects_next_open_without_affecting_legacy(tmp_path, monkeypatch):
    baseline = _run_reference_backtest(tmp_path / "baseline", monkeypatch,
                                       offset=0, gap_limit=None)
    guarded = _run_reference_backtest(tmp_path / "guarded", monkeypatch,
                                      offset=0, gap_limit=0.01)
    assert baseline["metrics"]["trades"] >= 1
    assert guarded["metrics"]["trades"] == 0


def test_new_stop_distance_cap_rejects_oversized_entries(tmp_path, monkeypatch):
    baseline = _run_reference_backtest(tmp_path / "base", monkeypatch,
                                       offset=0, gap_limit=None)
    capped = _run_reference_backtest(tmp_path / "cap", monkeypatch,
                                     offset=0, gap_limit=None,
                                     max_stop_distance_percent=0.001)
    assert baseline["metrics"]["trades"] >= 1
    assert capped["metrics"]["trades"] == 0


def test_rule_profit_activation_delays_discretionary_exit(tmp_path, monkeypatch):
    eager = _run_reference_backtest(tmp_path / "eager", monkeypatch,
                                     offset=0, gap_limit=None, conditional_exit=True)
    protected = _run_reference_backtest(tmp_path / "protected", monkeypatch,
                                         offset=0, gap_limit=None, conditional_exit=True,
                                         condition_exit_activation_r=0.5)
    assert eager["metrics"]["trades"] >= 1
    assert protected["metrics"]["trades"] >= 1
    assert protected["trades"][0]["holding_minutes"] > eager["trades"][0]["holding_minutes"]


def test_confirmed_close_moves_stop_toward_breakeven(tmp_path, monkeypatch):
    result = _run_reference_backtest(tmp_path / "breakeven", monkeypatch,
                                      offset=0, gap_limit=None,
                                      breakeven_activation_r=1.0,
                                      breakeven_offset_ticks=0,
                                      reward_r_multiple=None, no_time_exit=True)
    assert result["metrics"]["trades"] >= 1
    assert any(t["exit_reason"] == "BREAKEVEN_STOP" for t in result["trades"])
    for t in result["trades"]:
        if t["exit_reason"] == "BREAKEVEN_STOP":
            assert t["stop_price"] >= t["initial_stop_price"]
            assert t["stop_price"] == pytest.approx(t["entry_price"])
