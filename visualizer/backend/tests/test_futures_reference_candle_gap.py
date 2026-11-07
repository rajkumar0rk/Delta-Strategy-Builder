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
