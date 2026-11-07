"""Price-point futures target regression tests.

These tests deliberately keep the legacy R-multiple and no-target paths
unchanged while exercising configurable fixed price-distance targets.
"""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.futures_setups import target_at_points, target_at_r
from app.models import FuturesConfig, FuturesRuleRiskConfig, StrategyConfig


@pytest.mark.parametrize("entry,points,side,tick,expected", [
    (100000.0,200.0,"LONG",0.5,100200.0),
    (100000.0,200.0,"SHORT",0.5,99800.0),
    (100000.0,201.2,"LONG",0.5,100201.0),
    (100000.0,201.2,"SHORT",0.5,99799.0),
    (100000.0,200.0,"LONG",1.0,100200.0),
    (100000.0,200.0,"SHORT",1.0,99800.0),
])
def test_price_points_derive_from_entry_not_stop(entry,points,side,tick,expected):
    assert target_at_points(entry,points,side,tick)==pytest.approx(expected)


def test_invalid_target_distance_fails_closed():
    for direction in ("LONG","SHORT"):
        assert target_at_points(100,0.1,direction,1.0) is None
        assert target_at_points(100,0,direction,0.5) is None
        assert target_at_points(100,200,"SHORT",0.5) is None
    assert target_at_points(100,200,"NO_DIRECTION",0.5) is None


def test_all_three_modes_are_explicit_and_mutually_exclusive():
    default=FuturesRuleRiskConfig()
    assert default.take_profit_points is None
    assert default.reward_r_multiple==2
    assert not default.trailing_enabled
    assert FuturesRuleRiskConfig(reward_r_multiple=None,take_profit_points=None).take_profit_points is None
    assert FuturesRuleRiskConfig(reward_r_multiple=None,take_profit_points=200).take_profit_points==200
    with pytest.raises(ValidationError,match="reward_r_multiple=null"):
        FuturesRuleRiskConfig(reward_r_multiple=2,take_profit_points=200)
    with pytest.raises(ValidationError):
        FuturesRuleRiskConfig(reward_r_multiple=None,take_profit_points=-1)
    with pytest.raises(ValidationError):
        FuturesConfig(rule_risk=FuturesRuleRiskConfig(enabled=True,reward_r_multiple=None,
            take_profit_points=0.1),stop_loss_percent=None,take_profit_percent=None,tick_size=0.5)


def test_donchian_example_has_exactly_200_point_tp_and_preserves_atr_risk():
    examples=Path(__file__).resolve().parents[1]/"examples"
    p=examples/"btc-futures-4h-donchian-atr-trend.strategy.json"
    strategy=StrategyConfig.model_validate(json.loads(p.read_text(encoding="utf-8"))["strategy"])
    c=strategy.futures.rule_risk
    assert c.enabled and c.stop_mode=="ATR"
    assert c.take_profit_points==200 and c.reward_r_multiple is None
    assert c.stop_atr_multiple==2
    assert c.trailing_enabled and c.trailing_atr_multiple==3
    assert c.equity_risk_percent==0.5
    assert strategy.futures.take_profit_percent is None
    assert strategy.futures.stop_loss_percent is None
    assert any(x.timeframe=="4h" for x in strategy.indicators)


def test_existing_vwap_reference_retains_legacy_r_multiple():
    examples=Path(__file__).resolve().parents[1]/"examples"
    p=examples/"btc-futures-vwap-ema11-rule-risk.strategy.json"
    strategy=StrategyConfig.model_validate(json.loads(p.read_text(encoding="utf-8"))["strategy"])
    c=strategy.futures.rule_risk
    assert c.enabled
    assert c.take_profit_points is None
    assert c.reward_r_multiple==2
    assert target_at_r(10000,9900,"LONG",c.reward_r_multiple,0.5)==10200


def test_point_target_execution_stop_priority_long_short():
    from app.futures_engine import _exit_level
    from types import SimpleNamespace
    config=FuturesConfig(stop_loss_percent=None,take_profit_percent=None)
    long={"direction":"LONG","entry_price":1000,"stop_price":950,
          "target_price":target_at_points(1000,200,"LONG",0.5)}
    short={"direction":"SHORT","entry_price":1000,"stop_price":1050,
           "target_price":target_at_points(1000,200,"SHORT",0.5)}
    assert _exit_level(long,SimpleNamespace(open=1000,high=1201,low=990),config)==("TAKE_PROFIT",1200)
    assert _exit_level(short,SimpleNamespace(open=1000,high=1010,low=799),config)==("TAKE_PROFIT",800)
    assert _exit_level(long,SimpleNamespace(open=1190,high=1201,low=900),config)[0]=="STOP_LOSS"
    assert _exit_level(short,SimpleNamespace(open=810,high=1100,low=790),config)[0]=="STOP_LOSS"
