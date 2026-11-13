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


def test_long_or_exit():
    cfg = load_strategy()
    assert cfg.call_exit.mode == "ANY"
    assert len(cfg.call_exit.conditions) == 2
    rsi, ema = cfg.call_exit.conditions
    assert (rsi.left, rsi.operator, rsi.value) == ("rsi2", "GTE", 70)
    assert (ema.left, ema.operator, ema.right) == ("close", "LT", "ema20")
    frame = pd.DataFrame([
        {"rsi2": 69.0, "close": 101.0, "ema20": 100.0},
        {"rsi2": 70.0, "close": 101.0, "ema20": 100.0},
        {"rsi2": 69.0, "close": 99.0, "ema20": 100.0},
        {"rsi2": 70.0, "close": 99.0, "ema20": 100.0},
    ])
    assert not evaluate_group(frame, 0, cfg.call_exit)["passed"]
    for i in (1, 2, 3):
        assert evaluate_group(frame, i, cfg.call_exit)["passed"]


def test_short_or_exit():
    cfg = load_strategy()
    assert cfg.put_exit.mode == "ANY"
    assert len(cfg.put_exit.conditions) == 2
    rsi, ema = cfg.put_exit.conditions
    assert (rsi.left, rsi.operator, rsi.value) == ("rsi2", "LTE", 30)
    assert (ema.left, ema.operator, ema.right) == ("close", "GT", "ema20")
    frame = pd.DataFrame([
        {"rsi2": 31.0, "close": 99.0, "ema20": 100.0},
        {"rsi2": 30.0, "close": 99.0, "ema20": 100.0},
        {"rsi2": 31.0, "close": 101.0, "ema20": 100.0},
        {"rsi2": 30.0, "close": 101.0, "ema20": 100.0},
    ])
    assert not evaluate_group(frame, 0, cfg.put_exit)["passed"]
    for i in (1, 2, 3):
        assert evaluate_group(frame, i, cfg.put_exit)["passed"]


def test_one_hour_completed_signal_exits_next_hour_open(tmp_path, monkeypatch):
    """Integration: 5m source -> complete 1h RSI/SMA/EMA -> condition exit."""
    root = tmp_path / "data"
    sample = root / "sample"
    sample.mkdir(parents=True)
    monkeypatch.setenv("STRATEGY_LAB_DATA_ROOT", str(root))
    monkeypatch.setenv("STRATEGY_LAB_RESULT_ROOT", str(tmp_path / "results"))
    monkeypatch.setenv("STRATEGY_LAB_CACHE_ROOT", str(tmp_path / "cache"))
    hours = 221
    # A long-established uptrend keeps price above SMA200 and EMA20
    # even as RSI(2) becomes oversold after 12 small declining hours.
    # Two later larger hourly declines confirm the actual EMA20/structure
    # exit without reaching the entry's 500-point protective stop.
    hourly = [100000.0 + i * 2 for i in range(hours)]
    hourly[201] = hourly[200] + 480
    for hour in range(202, 214):
        hourly[hour] = hourly[hour - 1] - 2
    for hour in range(214, hours):
        hourly[hour] = hourly[hour - 1] - 125
    origin = pd.Timestamp("2026-01-01T00:00:00Z")
    rows = []
    for hour, price in enumerate(hourly):
        previous = hourly[hour - 1] if hour else price
        for minute in range(1, 13):
            close_ts = origin + pd.Timedelta(hours=hour, minutes=minute * 5)
            opened = previous + (price - previous) * (minute - 1) / 12
            closed = previous + (price - previous) * minute / 12
            rows.append({
                "timestamp": close_ts.isoformat(),
                "open": opened, "high": max(opened, closed) + 0.1,
                "low": min(opened, closed) - 0.1, "close": closed, "volume": 100,
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
    long_rsi, long_trend, long_ema = cfg.call_entry.conditions
    short_rsi, short_trend, short_ema = cfg.put_entry.conditions
    assert (long_rsi.left, long_rsi.operator, long_rsi.value) == ("rsi2", "LT", 3)
    assert (short_rsi.left, short_rsi.operator, short_rsi.value) == ("rsi2", "GT", 97)
    assert (long_trend.left, long_trend.operator, long_trend.right) == ("close", "GT", "sma200")
    assert (short_trend.left, short_trend.operator, short_trend.right) == ("close", "LT", "sma200")
    assert (long_ema.left, long_ema.operator, long_ema.right) == ("close", "GT", "ema20")
    assert (short_ema.left, short_ema.operator, short_ema.right) == ("close", "LT", "ema20")


def test_ema20_entry_gate_is_directional_and_uses_completed_1h_close():
    cfg = load_strategy()
    assert cfg.timeframe == "1h"
    long_ema = cfg.call_entry.conditions[-1]
    short_ema = cfg.put_entry.conditions[-1]
    assert (long_ema.id, long_ema.left, long_ema.operator, long_ema.right) == (
        "long_above_ema20", "close", "GT", "ema20")
    assert (short_ema.id, short_ema.left, short_ema.operator, short_ema.right) == (
        "short_below_ema20", "close", "LT", "ema20")
    # Every entry rule is an ALL-group condition, so this gate is mandatory.
    assert cfg.call_entry.mode == cfg.put_entry.mode == "ALL"
    assert len(cfg.call_entry.conditions) == len(cfg.put_entry.conditions) == 3
    from app.rules import evaluate_group
    import pandas as pd
    # RSI and SMA permit LONG, but the EMA gate rejects a close below EMA20.
    long_frame = pd.DataFrame([{"rsi2": 2.0, "close": 101.0, "sma200": 100.0, "ema20": 102.0}])
    assert not evaluate_group(long_frame, 0, cfg.call_entry)["passed"]
    long_frame.loc[0, "ema20"] = 100.5
    assert evaluate_group(long_frame, 0, cfg.call_entry)["passed"]
    # RSI and SMA permit SHORT, but the EMA gate rejects a close above EMA20.
    short_frame = pd.DataFrame([{"rsi2": 98.0, "close": 99.0, "sma200": 100.0, "ema20": 98.0}])
    assert not evaluate_group(short_frame, 0, cfg.put_entry)["passed"]
    short_frame.loc[0, "ema20"] = 99.5
    assert evaluate_group(short_frame, 0, cfg.put_entry)["passed"]
