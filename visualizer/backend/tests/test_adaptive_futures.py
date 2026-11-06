"""AMRS closed-candle regime, breakout, retest, trailing and schema checks."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from app.adaptive_futures import AdaptiveBreakoutPlanner, trail_stop
from app.models import AdaptiveFuturesConfig, StrategyConfig


def _frame(kind="trend"):
    idx = pd.date_range("2026-01-01T00:05:00Z", periods=48, freq="5min")
    frame = pd.DataFrame(
        dict(open=[100.0]*len(idx), high=[102.0]*len(idx),
             low=[99.0]*len(idx), close=[100.0]*len(idx),
             volume=[100.0]*len(idx)), index=idx)
    # Two fully completed 1h observations and then one 15m breakout.
    frame.loc[idx[24:27], "high"] = 111.0
    frame.loc[idx[24:27], "close"] = 110.0
    frame.loc[idx[24:27], "open"] = 100.0
    frame["amrs_ema50_1h"] = 200.0
    frame["amrs_ema200_1h"] = 100.0
    frame["amrs_close_1h"] = 205.0
    frame["amrs_adx_1h.adx"] = 30.0 if kind=="trend" else 16.0
    frame["amrs_adx_1h.plus_di"] = 30.0
    frame["amrs_adx_1h.minus_di"] = 10.0
    frame["amrs_atr_percentile_1h"] = 50.0 if kind=="trend" else 10.0
    frame["amrs_donchian_15m.upper"] = 105.0
    frame["amrs_donchian_15m.lower"] = 95.0
    frame["amrs_atr_15m"] = 2.0
    frame["amrs_volume_ratio_15m"] = 1.8
    return frame


def _config():
    cfg = AdaptiveFuturesConfig()
    cfg.regime.require_ema_slope = False
    cfg.compression.require_retest = True
    return cfg


def test_adaptive_strategy_reference_imports_and_rejects_missing_dependencies():
    path=Path(__file__).resolve().parents[1]/"examples"/"btc-futures-adaptive-regimes-v1.strategy.json"
    strategy=StrategyConfig.model_validate(json.loads(path.read_text())["strategy"])
    assert strategy.futures.adaptive.enabled
    assert strategy.futures.pullback.enabled is False
    assert strategy.futures.stop_loss_percent is None
    assert strategy.futures.take_profit_percent is None
    assert strategy.futures.adaptive.regime.confirmations==2
    assert strategy.timeframe=="5m"
    missing=strategy.model_dump()
    missing["indicators"]=[i for i in missing["indicators"] if i["id"]!="amrs_adx_1h"]
    with pytest.raises(ValidationError,match="AMRS requires"):
        StrategyConfig.model_validate(missing)


def test_new_schema_is_opt_in_and_existing_futures_unchanged():
    old=StrategyConfig(market_type="FUTURES")
    assert old.futures.adaptive.enabled is False
    assert old.futures.stop_loss_percent==1
    assert old.futures.take_profit_percent==2
    with pytest.raises(ValidationError,match="AMRS uses its own ATR stops"):
        StrategyConfig.model_validate({"market_type":"FUTURES","futures":{"adaptive":{"enabled":True}}})


def test_1h_regime_persistence_before_breakout_and_no_same_bar_lookahead():
    cfg=_config()
    frame=_frame()
    planner=AdaptiveBreakoutPlanner(frame,cfg)
    found=[]
    for idx,(ts,row) in enumerate(frame.iterrows()):
        planner.step(idx,ts,row)
        if planner.new_setups:
            found.append((ts,dict(planner.new_setups)))
    assert planner.regime=="TREND_UP"
    assert any(event[0]==frame.index[26] for event in found)
    assert all(event[0]>=frame.index[23] for event in found)
    assert all("SHORT" not in payload for _,payload in found)
    assert found[0][1]["LONG"]["module"]=="TREND"


def test_compression_waits_for_subsequent_15m_retest_then_arms():
    cfg=_config()
    frame=_frame("compression")
    # Completed breakout at 02:15 followed by a later candle that
    # touches the frozen level and closes above it.
    frame.loc[frame.index[27:30],["open","high","low","close"]]=[108,109,104,107]
    planner=AdaptiveBreakoutPlanner(frame,cfg)
    seen=[]
    for i,(ts,row) in enumerate(frame.iterrows()):
        planner.step(i,ts,row)
        if planner.new_setups:
            seen.append((ts,dict(planner.new_setups)))
    assert planner.regime=="COMPRESSION"
    assert seen and seen[0][0]==frame.index[29]
    assert seen[0][1]["LONG"]["module"]=="COMPRESSION"


def test_volatile_1h_regime_forces_no_trade_without_waiting_confirmation():
    cfg=_config()
    frame=_frame()
    planner=AdaptiveBreakoutPlanner(frame,cfg)
    for i,(ts,row) in enumerate(frame.iterrows()):
        if ts >= pd.Timestamp("2026-01-01T02:00:00Z"):
            row=row.copy()
            row["amrs_atr_percentile_1h"]=99
        planner.step(i,ts,row)
    assert planner.regime=="EXTREME_VOLATILITY"
    assert not planner.new_setups


def test_stop_trails_only_in_profitable_direction_and_never_loosened():
    cfg=_config().trailing
    long=dict(direction="LONG",entry_price=100.0,stop_price=95.0,
              initial_r=5.0,adaptive_module="TREND",favorable_close=100)
    bar=pd.Series({"close":112.0,"amrs_atr_15m":2.0})
    assert trail_stop(long,bar,cfg,0.5)==108.0
    assert trail_stop(long,pd.Series({"close":101.0,"amrs_atr_15m":8.0}),
                      cfg,0.5) is None
    assert long["stop_price"]==108.0
    short=dict(direction="SHORT",entry_price=100.0,stop_price=105.0,
               initial_r=5.0,adaptive_module="COMPRESSION",favorable_close=100)
    assert trail_stop(short,pd.Series({"close":88.0,"amrs_atr_15m":2.0}),
                      cfg,0.5)==92.0
    assert trail_stop(short,pd.Series({"close":99.0,"amrs_atr_15m":10.0}),
                      cfg,0.5) is None
    assert short["stop_price"]==92.0
