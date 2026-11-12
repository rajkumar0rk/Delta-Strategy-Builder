"""1H RSI(2) + SMA200 reusable EMA20/price-action exit regression tests."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd

from app.engine import run_backtest
from app.models import BacktestRequest, StrategyConfig
from app.rules import evaluate_group


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "btc-futures-rsi2-sma200-1h-ema20-structure-exit.strategy.json"


def load_strategy():
    doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert doc["schema_version"] == 15 and doc["app"] == "BTC Strategy Lab"
    return StrategyConfig.model_validate(doc["strategy"])


def test_one_hour_sample_uses_existing_rule_exit_and_no_trailing():
    cfg = load_strategy()
    assert cfg.market_type == "FUTURES"
    assert cfg.timeframe == "1h"
    assert cfg.direction_mode == "BOTH"
    assert cfg.position_policy == "EXCLUSIVE"
    assert cfg.futures.rule_risk.stop_mode == "FIXED_POINTS"
    assert cfg.futures.rule_risk.stop_loss_points == 500
    assert cfg.futures.rule_risk.trailing_enabled is False
    assert cfg.futures.rule_risk.reward_r_multiple is None
    assert cfg.futures.rule_risk.take_profit_points is None
    assert cfg.futures.take_profit_percent is None
    assert cfg.futures.stop_loss_percent is None
    assert cfg.risk.max_hold_minutes is None
    assert cfg.call_entry_lifecycles[0].max_entries_per_activation is None
    assert cfg.put_entry_lifecycles[0].max_entries_per_activation is None
    assert {x.id for x in cfg.indicators} == {"rsi2", "sma200", "ema20"}
    assert all(x.timeframe == "strategy" for x in cfg.indicators)
    assert cfg.futures.funding_mode == "EXCLUDE_WITH_WARNING"


def test_long_exit_requires_two_closes_below_ema_and_prior_low_break():
    cfg = load_strategy()
    frame = pd.DataFrame([
        {"close": 101, "low": 100, "high": 102, "ema20": 100},
        {"close": 98, "low": 97, "high": 101, "ema20": 100},
        {"close": 96, "low": 95, "high": 99, "ema20": 99},
    ])
    assert evaluate_group(frame, 2, cfg.call_exit)["passed"]
    assert not evaluate_group(frame, 1, cfg.call_exit)["passed"]
    # No structural close beneath the prior candle's low.
    frame.loc[2, "close"] = 98
    assert not evaluate_group(frame, 2, cfg.call_exit)["passed"]
    frame.loc[2, "close"] = 96
    # Previous hour did not close beneath EMA20.
    frame.loc[1, "close"] = 101
    assert not evaluate_group(frame, 2, cfg.call_exit)["passed"]


def test_short_exit_requires_two_closes_above_ema_and_prior_high_break():
    cfg = load_strategy()
    frame = pd.DataFrame([
        {"close": 99, "low": 98, "high": 101, "ema20": 100},
        {"close": 102, "low": 100, "high": 103, "ema20": 101},
        {"close": 105, "low": 101, "high": 106, "ema20": 102},
    ])
    assert evaluate_group(frame, 2, cfg.put_exit)["passed"]
    assert not evaluate_group(frame, 1, cfg.put_exit)["passed"]
    frame.loc[2, "close"] = 103
    assert not evaluate_group(frame, 2, cfg.put_exit)["passed"]
    frame.loc[2, "close"] = 105
    frame.loc[1, "close"] = 100
    assert not evaluate_group(frame, 2, cfg.put_exit)["passed"]


def test_one_hour_completed_signal_exits_next_hour_open(tmp_path, monkeypatch):
    """Integration: 5m source -> complete 1h RSI/SMA/EMA -> condition exit."""
    root = tmp_path / "data"
    sample = root / "sample"
    sample.mkdir(parents=True)
    monkeypatch.setenv("STRATEGY_LAB_DATA_ROOT", str(root))
    monkeypatch.setenv("STRATEGY_LAB_RESULT_ROOT", str(tmp_path / "results"))
    monkeypatch.setenv("STRATEGY_LAB_CACHE_ROOT", str(tmp_path / "cache"))
    hours = 211
    hourly = [100000 + i for i in range(hours)]
    hourly[206] = 100150
    hourly[207] = 100100
    hourly[208] = 100100
    hourly[209] = 100100
    hourly[210] = 100100
    origin = pd.Timestamp("2026-01-01T00:00:00Z")
    rows = []
    for hour, price in enumerate(hourly):
        for minute in range(1, 13):
            close_ts = origin + pd.Timedelta(hours=hour, minutes=minute * 5)
            rows.append({
                "timestamp": close_ts.isoformat(),
                "open": float(price), "high": float(price) + 0.1,
                "low": float(price) - 0.1, "close": float(price), "volume": 100,
            })
    with (sample / "underlying_bars.csv").open("w", newline="", encoding="utf-8") as handle:
        w = csv.DictWriter(handle, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    cfg = load_strategy()
    # Close strictly by the rule: a 500-point emergency stop must not be hit.
    result = run_backtest(BacktestRequest(
        dataset_id="sample",
        start=(origin + pd.Timedelta(hours=199)).isoformat(),
        end=(origin + pd.Timedelta(hours=hours)).isoformat(),
        strategy=cfg,
    ))
    assert any(t["exit_reason"] == "CONDITION_EXIT" and t["direction"] == "LONG"
               for t in result["trades"])
    assert all(t["exit_reason"] != "TRAILING_STOP" for t in result["trades"])
    for trade in result["trades"]:
        expected_sl = trade["entry_price"] - 500 if trade["direction"] == "LONG" else trade["entry_price"] + 500
        assert trade["initial_stop_price"] == expected_sl


def test_rsi2_reversal_thresholds_and_sma_trend_filters():
    cfg = load_strategy()
    long_rsi, long_trend = cfg.call_entry.conditions
    short_rsi, short_trend = cfg.put_entry.conditions
    assert (long_rsi.left, long_rsi.operator, long_rsi.value) == ("rsi2", "LT", 3)
    assert (short_rsi.left, short_rsi.operator, short_rsi.value) == ("rsi2", "GT", 97)
    assert (long_trend.left, long_trend.operator, long_trend.right) == ("close", "GT", "sma200")
    assert (short_trend.left, short_trend.operator, short_trend.right) == ("close", "LT", "sma200")
