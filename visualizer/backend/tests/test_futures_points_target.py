"""Fixed BTCUSD price-point targets for opt-in rule-risk Futures."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.futures_setups import target_at_points
from app.models import FuturesRuleRiskConfig, StrategyConfig


@pytest.mark.parametrize("direction,entry,points,tick,expected", [
    ("LONG",100000.0,200.0,0.5,100200.0),
    ("SHORT",100000.0,200.0,0.5,99800.0),
    ("LONG",100000.1,200.0,0.5,100200.0),
    ("SHORT",100000.1,200.0,0.5,99800.5),
])
def test_point_target_uses_executed_entry_and_conservative_tick(direction,entry,points,tick,expected):
    assert target_at_points(entry,points,direction,tick)==expected


@pytest.mark.parametrize("direction,entry,points,tick", [
    ("SHORT",50.0,200.0,0.5),
    ("LONG",100.0,0.05,0.5),
    ("SHORT",100.0,0.05,0.5),
    ("LONG",100.0,0.0,0.5),
])
def test_point_target_rejects_invalid_prices(direction,entry,points,tick):
    assert target_at_points(entry,points,direction,tick) is None


def test_fixed_points_and_r_target_cannot_compete():
    with pytest.raises(ValidationError,match="reward_r_multiple=null"):
        FuturesRuleRiskConfig.model_validate({"enabled":True,"take_profit_points":200})
    valid=FuturesRuleRiskConfig.model_validate({"enabled":True,"take_profit_points":200,"reward_r_multiple":None})
    assert valid.take_profit_points==200
    old=FuturesRuleRiskConfig()
    assert old.take_profit_points is None
    assert old.reward_r_multiple==2.0


def test_reference_example_is_importable_and_has_200_point_target():
    root=Path(__file__).resolve().parents[1]/"examples"
    path=root/"btc-futures-4h-donchian-atr-trend.strategy.json"
    doc=json.loads(path.read_text(encoding="utf-8"))
    s=StrategyConfig.model_validate(doc["strategy"])
    assert doc["schema_version"]==15
    assert s.futures.rule_risk.take_profit_points==200
    assert s.futures.rule_risk.reward_r_multiple is None
    assert s.futures.rule_risk.trailing_enabled
    assert s.futures.rule_risk.atr_stop_anchor=="ENTRY_FILL"
    legacy=json.loads((root/"btc-futures-vwap-ema11-rule-risk.strategy.json").read_text(encoding="utf-8"))
    previous=StrategyConfig.model_validate(legacy["strategy"])
    assert previous.futures.rule_risk.reward_r_multiple==2
    assert previous.futures.rule_risk.take_profit_points is None
