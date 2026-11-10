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
    invalid["direction_mode"] = "BOTH"
    with pytest.raises(ValidationError, match="SHORT-only"):
        StrategyConfig.model_validate(invalid)
