"""Regression coverage for confirmed 1h BTC Futures reversal v2.

Only completed-bar, bounded-offset indicator/rule logic is used here.
Separate engine tests validate next-open execution, protective stop and sizing.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from app.indicators import compute_indicators
from app.models import FuturesRuleRiskConfig, StrategyConfig
from app.rules import evaluate_group

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "btc-futures-1h-bullish-reversal-confirmed-v2.strategy.json"


def _strategy():
    payload=json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert payload["schema_version"]==15 and payload["app"]=="BTC Strategy Lab"
    return StrategyConfig.model_validate(payload["strategy"])


def _bar(op, hi, lo, cl):
    assert lo<=min(op,cl)<=max(op,cl)<=hi
    return {"open":op,"high":hi,"low":lo,"close":cl,"volume":100.0}


DOWNTREND = [
    _bar(125,128,118,120), _bar(120,124,114,116),
    _bar(116,120,110,112), _bar(112,116,106,108),
    _bar(108,112,102,104), _bar(104,108,98,100),
]
ENGULF = _bar(99,107,97,105)
DOJI = _bar(100,104,99,100.5)
HAMMER = _bar(100,103,95,102)
CONFIRM_DOJI = _bar(100.5,107,100,105)
CONFIRM_HAMMER = _bar(102,106,101,105)


def _signal(candles):
    s=_strategy()
    idx=pd.date_range("2026-01-01T01:00:00Z", periods=len(candles), freq="1h")
    data=pd.DataFrame(candles,index=idx)
    frame,_=compute_indicators(data,s.indicators,"1h")
    return s,frame


def test_v2_config_is_safe_and_original_strategy_remains():
    s=_strategy()
    assert s.market_type=="FUTURES" and s.timeframe=="1h"
    assert s.direction_mode=="CALL" and s.call_entry.configured()
    assert s.call_exit.configured() and not s.put_entry.configured()
    r=s.futures.rule_risk
    assert r.enabled and r.stop_mode=="SWING" and r.swing_lookback_bars==2
    assert r.max_stop_distance_percent==1.0 and r.max_stop_distance_atr==3.0
    assert r.condition_exit_activation_r==0.5 and r.breakeven_activation_r==1
    assert r.reward_r_multiple is None and r.take_profit_points is None
    assert not r.trailing_enabled and s.futures.stop_loss_percent is None
    assert s.futures.take_profit_percent is None
    old=EXAMPLE.with_name("btc-futures-1h-bullish-reversal-structure-exit.strategy.json")
    previous=StrategyConfig.model_validate(json.loads(old.read_text(encoding="utf-8"))["strategy"])
    assert previous.futures.rule_risk.stop_mode=="SIGNAL_CANDLE"


@pytest.mark.parametrize("bars,should_pass", [
    (DOWNTREND+[ENGULF],True),
    (DOWNTREND+[DOJI,CONFIRM_DOJI],True),
    (DOWNTREND+[HAMMER,CONFIRM_HAMMER],True),
    (DOWNTREND+[DOJI],False),  # doji needs a subsequent breakout
    (DOWNTREND+[HAMMER],False), # hammer needs a subsequent breakout
    (DOWNTREND+[DOJI,_bar(100.5,104,99.5,103)],False),
    (DOWNTREND+[HAMMER,_bar(102,103.5,101,103)],False),
])
def test_confirmation_entry_paths(bars,should_pass):
    s,frame=_signal(bars)
    assert evaluate_group(frame,len(frame)-1,s.call_entry)["passed"] is should_pass


def test_three_descending_high_low_pairs_required():
    broken=DOWNTREND.copy()
    broken[3]=_bar(112,125,106,108)  # previous structure has a higher high
    s,frame=_signal(broken+[ENGULF])
    assert not evaluate_group(frame,len(frame)-1,s.call_entry)["passed"]


def test_bearish_close_count_and_prior_setup_candle_required():
    broken=DOWNTREND.copy()
    broken[4]=_bar(103,112,102,108) # non-red within the required sequence
    broken[5]=_bar(99,108,98,104)   # green latest setup candle
    s,frame=_signal(broken+[ENGULF])
    assert not evaluate_group(frame,len(frame)-1,s.call_entry)["passed"]


def test_no_future_candles_can_make_unconfirmed_doji_pass():
    s,frame=_signal(DOWNTREND+[DOJI])
    before=evaluate_group(frame,len(frame)-1,s.call_entry)["passed"]
    _,extended=_signal(DOWNTREND+[DOJI,CONFIRM_DOJI])
    preserved=evaluate_group(extended,len(frame)-1,s.call_entry)["passed"]
    assert before is False and preserved is False


def test_single_non_higher_high_is_not_an_exit():
    s=_strategy()
    bars=DOWNTREND+[ENGULF,_bar(105,107,98,106)]
    _,frame=_signal(bars)
    assert not evaluate_group(frame,len(frame)-1,s.call_exit)["passed"]


def test_close_below_previous_low_is_an_exit():
    s=_strategy()
    bars=DOWNTREND+[ENGULF,_bar(102,108,95,96)]
    _,frame=_signal(bars)
    assert evaluate_group(frame,len(frame)-1,s.call_exit)["passed"]


def test_two_consecutive_lower_highs_and_lows_exit_without_close_breakdown():
    s=_strategy()
    candles=DOWNTREND+[
        _bar(103,116,102,110), _bar(106,115,101,109),
        _bar(105,114,100,108)]
    _,frame=_signal(candles)
    assert evaluate_group(frame,len(frame)-1,s.call_exit)["passed"]


@pytest.mark.parametrize("bad",[
    {"max_stop_distance_percent":0},
    {"max_stop_distance_atr":0},
    {"condition_exit_activation_r":-1},
    {"breakeven_activation_r":0},
    {"breakeven_offset_ticks":-1},
    {"breakeven_offset_ticks":1},
])
def test_risk_config_rejects_invalid_values(bad):
    with pytest.raises(ValidationError):
        FuturesRuleRiskConfig.model_validate(bad)



def test_atr_width_cap_must_have_matching_confirmed_atr_indicator():
    data=_strategy().model_dump()
    data["indicators"]=[i for i in data["indicators"] if i["id"]!="atr14_1h"]
    with pytest.raises(ValidationError,match="ATR indicator"):
        StrategyConfig.model_validate(data)


def test_v2_settings_round_trip_without_loss():
    s=_strategy()
    parsed=StrategyConfig.model_validate(s.model_dump(mode="json"))
    assert parsed.futures.rule_risk.max_stop_distance_percent==1.0
    assert parsed.futures.rule_risk.max_stop_distance_atr==3.0
    assert parsed.futures.rule_risk.condition_exit_activation_r==0.5
    assert parsed.futures.rule_risk.breakeven_activation_r==1.0
    assert parsed.futures.rule_risk.breakeven_offset_ticks==0


def test_legacy_defaults_preserved_on_import():
    cfg=FuturesRuleRiskConfig()
    assert cfg.max_stop_distance_percent is None
    assert cfg.max_stop_distance_atr is None
    assert cfg.condition_exit_activation_r==0
    assert cfg.breakeven_activation_r is None
    assert cfg.breakeven_offset_ticks==0
