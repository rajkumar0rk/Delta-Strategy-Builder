"""Completed 1h candle patterns and next-5m protective point trailing."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import ValidationError

from app.futures_candle_pattern import completed_hour_patterns, update_short_point_trail
from app.models import FuturesCandlePatternConfig, StrategyConfig


def hourly_frame(specs):
    """Build 12 contiguous closed five-minute candles for each UTC hour."""
    rows = []
    start = pd.Timestamp("2026-11-09T01:00:00Z")
    for hour, (opened, high, low, closed) in enumerate(specs):
        for j in range(12):
            current = opened + (closed - opened) * j / 12
            following = opened + (closed - opened) * (j + 1) / 12
            rows.append((start + pd.Timedelta(hours=hour, minutes=5 * (j + 1)),
                         current, high, low, following))
    return pd.DataFrame(
        rows, columns=["timestamp", "open", "high", "low", "close"]
    ).set_index("timestamp")


SETUP = [(1000, 1060, 990, 1040),
         (1040, 1050, 970, 980),
         (980, 1000, 940, 950)]


def test_fourth_hour_short_arms_only_at_completed_third_hour():
    frame = hourly_frame(SETUP)
    config = FuturesCandlePatternConfig(enabled=True)
    signals = completed_hour_patterns(frame, config, 0.5)
    assert list(signals) == [35]
    assert signals[35]["stop_price"] == 1060
    assert signals[35]["setup_highs"] == [1060, 1050, 1000]
    assert signals[35]["take_profit_points"] is None
    assert signals[35]["setup_time"] == "2026-11-09T04:00:00+00:00"


def test_third_candle_and_last_setup_stop_are_configurable():
    frame = hourly_frame(SETUP)
    config = FuturesCandlePatternConfig(
        enabled=True, entry_candle=3, stop_anchor="SETUP_CANDLE_HIGH",
        stop_buffer_ticks=2,
    )
    signals = completed_hour_patterns(frame, config, 0.5)
    assert 23 in signals
    assert signals[23]["stop_price"] == 1051
    assert 35 not in signals


def test_incomplete_hour_breaks_pattern_without_lookahead():
    frame = hourly_frame(SETUP).drop(
        pd.Timestamp("2026-11-09T02:25:00Z")
    )
    assert completed_hour_patterns(frame, FuturesCandlePatternConfig(), 0.5) == {}


def test_doji_setup_is_rejected_with_configurable_filter():
    frame = hourly_frame([(1000, 1060, 990, 1040),
                          (1040, 1050, 970, 980),
                          (980, 1050, 940, 979)])
    assert completed_hour_patterns(
        frame, FuturesCandlePatternConfig(doji_threshold_percent=10), 0.5
    ) == {}
    assert 35 in completed_hour_patterns(
        frame, FuturesCandlePatternConfig(doji_filter_enabled=False), 0.5
    )


def bar(opened, high, low, close):
    return SimpleNamespace(open=opened, high=high, low=low, close=close)


def test_short_trailing_activation_floor_and_monotonic_next_bar_update():
    cfg = FuturesCandlePatternConfig(enabled=True)
    pos = {"entry_price": 100000., "stop_price": 100500., "direction": "SHORT",
           "pattern_profit_active": False, "trailing_active": False}
    assert update_short_point_trail(pos, bar(100000, 100100, 99800, 99801), cfg, .5) is None
    assert update_short_point_trail(pos, bar(100000, 100100, 99800, 99800), cfg, .5) == "PATTERN_TRAIL_ACTIVATED"
    assert pos["stop_price"] == 99800
    assert update_short_point_trail(pos, bar(99800, 99800, 99700, 99700), cfg, .5) is None
    assert pos["stop_price"] == 99800
    assert update_short_point_trail(pos, bar(99700, 99700, 99500, 99500), cfg, .5) == "PATTERN_TRAIL_RATCHET"
    assert pos["stop_price"] == 99700
    assert update_short_point_trail(pos, bar(99500, 99900, 99500, 99800), cfg, .5) is None
    assert pos["stop_price"] == 99700


def test_five_minute_doji_does_not_activate_or_update_trail():
    cfg = FuturesCandlePatternConfig(enabled=True, doji_threshold_percent=10)
    pos = {"entry_price": 100000., "stop_price": 100500.}
    assert update_short_point_trail(pos, bar(99805, 100000, 99500, 99800), cfg, .5) is None
    assert pos.get("pattern_profit_active") is None
    pos["pattern_profit_active"] = True
    pos["stop_price"] = 99800
    assert update_short_point_trail(pos, bar(99505, 99800, 99200, 99500), cfg, .5) is None
    assert pos["stop_price"] == 99800


def test_strategy_schema_rejects_mixed_modes_and_accepts_reference_json():
    path = Path(__file__).resolve().parents[1] / "examples" / (
        "btc-futures-1h-bearish-4th-candle-5m-200-point-trail.strategy.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    strategy = StrategyConfig.model_validate(payload["strategy"])
    assert payload["schema_version"] == 15
    assert strategy.futures.candle_pattern.enabled
    assert strategy.session.blocked_weekdays == [5, 6]
    assert strategy.futures.candle_pattern.entry_candle == 4
    invalid = strategy.model_dump()
    invalid["futures"]["rule_risk"]["enabled"] = True
    with pytest.raises(ValidationError, match="exclusive"):
        StrategyConfig.model_validate(invalid)
    invalid = strategy.model_dump()
    invalid["timeframe"] = "1h"
    with pytest.raises(ValidationError, match="5m execution"):
        StrategyConfig.model_validate(invalid)
    invalid = strategy.model_dump()
    invalid["put_exit"] = {"mode":"ANY","conditions":[{"id":"unexpected","left":"close","operator":"GT","value":0}]}
    with pytest.raises(ValidationError, match="dedicated 5m exits"):
        StrategyConfig.model_validate(invalid)
    invalid = strategy.model_dump()
    invalid["direction_mode"] = "BOTH"
    with pytest.raises(ValidationError, match="SHORT-only"):
        StrategyConfig.model_validate(invalid)


def test_integrated_hourly_entry_five_minute_trail_and_gap_model(tmp_path, monkeypatch):
    """Real Futures backtest uses next-hour open, 5m HIGH and frozen stop."""
    import csv
    from app.engine import run_backtest
    from app.models import BacktestRequest

    root = tmp_path / "data" / "sample"
    root.mkdir(parents=True)
    monkeypatch.setenv("STRATEGY_LAB_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("STRATEGY_LAB_RESULT_ROOT", str(tmp_path / "results"))
    monkeypatch.setenv("STRATEGY_LAB_CACHE_ROOT", str(tmp_path / "cache"))

    history = hourly_frame(SETUP)
    future = pd.DataFrame([
        ("2026-11-09T04:05:00Z", 950, 958, 920, 928),
        ("2026-11-09T04:10:00Z", 928, 928, 895, 900),
        ("2026-11-09T04:15:00Z", 900, 925, 897, 915),
    ], columns=["timestamp", "open", "high", "low", "close"]).set_index("timestamp")
    future.index = pd.to_datetime(future.index, utc=True)
    history = pd.concat([history, future]).sort_index()
    with (root / "underlying_bars.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["timestamp", "open", "high", "low", "close", "volume"]
        )
        writer.writeheader()
        for timestamp, row in history.iterrows():
            writer.writerow({"timestamp": timestamp.isoformat(),
                             **{k: float(row[k]) for k in ["open", "high", "low", "close"]},
                             "volume": 100})

    path = Path(__file__).resolve().parents[1] / "examples" / (
        "btc-futures-1h-bearish-4th-candle-5m-200-point-trail.strategy.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))["strategy"]
    payload["futures"]["candle_pattern"]["activation_points"] = 20
    payload["futures"]["candle_pattern"]["pullback_points"] = 20
    payload["risk"]["starting_balance_usd"] = 1000
    payload["futures"]["slippage_bps"] = 0
    strategy = StrategyConfig.model_validate(payload)
    result = run_backtest(BacktestRequest(
        dataset_id="sample", start="2026-11-09T01:05:00Z",
        end="2026-11-09T04:20:00Z", strategy=strategy
    ))
    assert result["metrics"]["trades"] == 1
    trade = result["trades"][0]
    assert trade["direction"] == "SHORT"
    assert trade["entry_time"] == "2026-11-09T04:00:00+00:00"
    assert trade["initial_stop_price"] == 1060
    assert trade["exit_reason"] == "PATTERN_TRAILING_STOP"
    assert trade["exit_price"] == pytest.approx(920)
    assert trade["exit_time"] == "2026-11-09T04:15:00+00:00"
    assert result["metrics"]["cash_reconciliation_residual_usd"] == pytest.approx(0)
    assert result["futures_research"]["candle_pattern_enabled"]


def test_third_hour_entry_points_stop_is_deferred_until_execution_fill():
    frame=hourly_frame(SETUP[:2])
    cfg=FuturesCandlePatternConfig(enabled=True,entry_candle=3,
        stop_anchor="ENTRY_POINTS",stop_loss_points=500,
        activation_points=1000,pullback_points=100)
    signals=completed_hour_patterns(frame,cfg,.5)
    assert list(signals)==[23]
    assert signals[23]["stop_price"] is None
    assert signals[23]["take_profit_points"] is None


def test_entry_point_stop_and_1000_100_trailing_through_backtest(tmp_path,monkeypatch):
    import csv
    from app.engine import run_backtest
    from app.models import BacktestRequest

    root=tmp_path/"data"/"sample"
    root.mkdir(parents=True)
    monkeypatch.setenv("STRATEGY_LAB_DATA_ROOT",str(tmp_path/"data"))
    monkeypatch.setenv("STRATEGY_LAB_RESULT_ROOT",str(tmp_path/"results"))
    monkeypatch.setenv("STRATEGY_LAB_CACHE_ROOT",str(tmp_path/"cache"))
    # 1H C1 green, C2 red and C2 closes under C1 low.
    # Third hour opens at 99500, reaches activation on 5m eligible close,
    # next bar may tighten the protective stop to completed close + 100.
    setup=hourly_frame([
        (100000,100500,99800,100200),
        (100200,100300,99300,99500),
    ])
    later=pd.DataFrame([
        ("2026-11-09T03:05:00Z",99500,99510,98400,98500),
        ("2026-11-09T03:10:00Z",98450,98480,98100,98200),
        ("2026-11-09T03:15:00Z",98200,98300,98150,98250),
    ],columns=["timestamp","open","high","low","close"]).set_index("timestamp")
    later.index=pd.to_datetime(later.index,utc=True)
    rows=pd.concat([setup,later])
    with (root/"underlying_bars.csv").open("w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=["timestamp","open","high","low","close","volume"])
        writer.writeheader()
        for ts,row in rows.iterrows():
            writer.writerow({"timestamp":ts.isoformat(),"open":float(row.open),
                "high":float(row.high),"low":float(row.low),"close":float(row.close),"volume":100})
    example=Path(__file__).resolve().parents[1]/"examples"/(
        "btc-futures-1h-c3-stop500-activation1000-pullback100.strategy.json")
    j=json.loads(example.read_text(encoding="utf-8"))
    assert j["schema_version"]==15
    assert j["strategy"]["timeframe"]=="5m"
    cfg=StrategyConfig.model_validate(j["strategy"])
    assert cfg.futures.candle_pattern.entry_candle==3
    assert cfg.futures.candle_pattern.stop_loss_points==500
    assert cfg.session.blocked_weekdays==[5,6]
    cfg.futures.slippage_bps=0
    cfg.risk.starting_balance_usd=10000
    result=run_backtest(BacktestRequest(
        dataset_id="sample",
        start="2026-11-09T01:05:00Z",
        end="2026-11-09T03:20:00Z",
        strategy=cfg,
    ))
    assert result["metrics"]["trades"]==1
    trade=result["trades"][0]
    assert trade["entry_time"]=="2026-11-09T03:00:00+00:00"
    assert trade["entry_price"]==99500
    assert trade["initial_stop_price"]==100000
    assert trade["exit_reason"]=="PATTERN_TRAILING_STOP"
    assert trade["exit_price"]==98300
    assert trade["exit_time"]=="2026-11-09T03:15:00+00:00"
    assert result["metrics"]["cash_reconciliation_residual_usd"]==pytest.approx(0)
    assert result["futures_research"]["candle_pattern_config"]["stop_loss_points"]==500


def test_fixed_entry_point_stop_validates_tick_compatibility():
    import copy
    sample_path=Path(__file__).resolve().parents[1]/"examples"/(
        "btc-futures-1h-c3-stop500-activation1000-pullback100.strategy.json")
    data=json.loads(sample_path.read_text(encoding="utf-8"))["strategy"]
    bad=copy.deepcopy(data)
    bad["futures"]["candle_pattern"]["stop_loss_points"]=.1
    with pytest.raises(ValidationError,match="stop_loss_points"):
        StrategyConfig.model_validate(bad)
    old=FuturesCandlePatternConfig()
    assert old.stop_anchor=="PATTERN_HIGHEST_HIGH"
