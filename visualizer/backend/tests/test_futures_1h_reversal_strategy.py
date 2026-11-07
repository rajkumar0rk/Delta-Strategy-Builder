"""1h bearish-structure-to-bullish-reversal strategy rule regression.

All comparisons use completed candles. This test intentionally does not
simulate or claim executable futures fills.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from app.indicators import compute_indicators
from app.models import StrategyConfig
from app.rules import evaluate_group

EXAMPLE = (Path(__file__).resolve().parents[1] / "examples"
           / "btc-futures-1h-bullish-reversal-structure-exit.strategy.json")


def strategy() -> StrategyConfig:
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 15
    return StrategyConfig.model_validate(raw["strategy"])


def _bar(open_, high, low, close):
    assert low <= min(open_, close) <= max(open_, close) <= high
    return {"open": open_, "high": high, "low": low,
            "close": close, "volume": 100}


def _evaluate(current, *, old=None, down=None, after=None):
    s = strategy()
    candles = [
        old or _bar(110, 112, 102, 105),
        down or _bar(105, 108, 90, 95),
        current,
    ]
    if after is not None:
        candles.append(after)
    index = pd.date_range("2026-10-01T01:00:00Z", periods=len(candles), freq="1h")
    frame = pd.DataFrame(candles, index=index)
    computed, _ = compute_indicators(frame, s.indicators, "1h")
    return s, computed


def test_reversal_strategy_schema_and_exit_configuration():
    s = strategy()
    assert s.market_type == "FUTURES"
    assert s.timeframe == "1h" and s.direction_mode == "CALL"
    assert s.call_entry.configured() and not s.put_entry.configured()
    assert s.call_exit.configured() and s.call_exit.mode == "ANY"
    rr = s.futures.rule_risk
    assert rr.enabled and rr.stop_mode == "SIGNAL_CANDLE"
    assert rr.stop_candle_offset_bars == 0
    assert rr.reward_r_multiple is None and rr.take_profit_points is None
    assert rr.trailing_enabled is False
    assert s.futures.stop_loss_percent is None
    assert s.futures.take_profit_percent is None


@pytest.mark.parametrize("current", [
    _bar(94, 109, 93, 107),   # entire prior bearish body engulfed
    _bar(98, 105, 95, 99),    # 10% body, bullish doji, improving close
    _bar(97, 101, 92, 100),   # lower-wick hammer with improving close
])
def test_engulf_doji_hammer_can_enter_after_downtrend(current):
    s, frame = _evaluate(current)
    assert evaluate_group(frame, 2, s.call_entry)["passed"]


def test_ordinary_bullish_candle_is_not_reversal():
    s, frame = _evaluate(_bar(97, 103, 95, 100))
    assert not evaluate_group(frame, 2, s.call_entry)["passed"]


def test_downtrend_structure_is_mandatory():
    s, frame = _evaluate(
        _bar(94, 109, 93, 107),
        down=_bar(105, 115, 90, 95),  # higher high invalidates downtrend setup
    )
    assert not evaluate_group(frame, 2, s.call_entry)["passed"]


def test_previous_candle_must_be_red_even_if_structural_levels_decline():
    s, frame = _evaluate(
        _bar(98, 105, 95, 99),
        down=_bar(94, 108, 90, 95),  # green candle despite lower highs/lows
    )
    assert not evaluate_group(frame, 2, s.call_entry)["passed"]


def test_missing_previous_candles_cannot_enter():
    s = strategy()
    frame = pd.DataFrame([_bar(94, 109, 93, 107)], index=pd.date_range(
        "2026-10-01T01:00:00Z", periods=1, freq="1h"))
    computed, _ = compute_indicators(frame, s.indicators, "1h")
    assert not evaluate_group(computed, 0, s.call_entry)["passed"]


def test_long_exit_only_when_any_ascending_condition_fails():
    signal = _bar(94, 109, 93, 107)
    progressing = _bar(109, 115, 95, 111)
    s, frame = _evaluate(signal, after=progressing)
    assert not evaluate_group(frame, 3, s.call_exit)["passed"]

    # Each individually breaks ONE of the three higher-high,
    # close-above-previous-open or higher-low conditions.
    failures = [
        _bar(108, 109, 95, 108),     # high NOT greater than preceding high
        _bar(94, 110, 93.5, 94),     # close NOT greater than preceding open
        _bar(108, 115, 93, 109),     # low NOT greater than preceding low
    ]
    for candle in failures:
        _, checked = _evaluate(signal, after=candle)
        assert evaluate_group(checked, 3, s.call_exit)["passed"]
