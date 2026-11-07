"""Regression checks for 4h indicators and reusable Futures rule ATR trailing."""
from __future__ import annotations
import csv
import json
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from app.engine import run_backtest
from app.indicators import _aggregate_completed, compute_indicators
from app.models import BacktestRequest, Condition, IndicatorInstance, RuleGroup, StrategyConfig


def sample(n=48*5):
    idx=pd.date_range("2026-01-01T00:05:00Z",periods=n,freq="5min")
    return pd.DataFrame({"open":[100+i*.1 for i in range(n)],
        "high":[101+i*.1 for i in range(n)],
        "low":[99+i*.1 for i in range(n)],
        "close":[100.5+i*.1 for i in range(n)],
        "volume":[10.0]*n},index=idx)


def test_four_hour_completeness_and_no_future_leakage():
    raw=sample()
    agg=_aggregate_completed(raw,"5m","4h")
    assert len(agg)==5
    assert agg.index[0]==pd.Timestamp("2026-01-01T04:00:00Z")
    assert all(t.hour%4==0 for t in agg.index)
    missing=_aggregate_completed(raw.drop(raw.index[17]),"5m","4h")
    assert pd.Timestamp("2026-01-01T04:00:00Z") not in missing.index
    inst=IndicatorInstance(id="ema4",kind="EMA",timeframe="4h",params={"period":2})
    out,_=compute_indicators(raw,[inst],"5m")
    cutoff=pd.Timestamp("2026-01-01T11:00:00Z")
    later=raw.copy()
    later.loc[later.index>cutoff,"close"]+=1000
    check,_=compute_indicators(later,[inst],"5m")
    pd.testing.assert_series_equal(out.loc[:cutoff,"ema4"],check.loc[:cutoff,"ema4"])


def test_new_donchian_example_valid_and_old_vwap_mode_retained():
    path=Path(__file__).resolve().parents[1]/"examples"/"btc-futures-4h-donchian-atr-trend.strategy.json"
    payload=json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"]==15 and payload["app"]=="BTC Strategy Lab"
    cfg=StrategyConfig.model_validate(payload["strategy"])
    risk=cfg.futures.rule_risk
    assert risk.enabled and risk.trailing_enabled
    assert risk.stop_mode=="ATR" and risk.atr_stop_anchor=="ENTRY_FILL"
    assert risk.reward_r_multiple is None
    assert cfg.futures.stop_loss_percent is None and cfg.futures.take_profit_percent is None
    assert any(i.kind=="EMA" and i.timeframe=="4h" and i.params["period"]==200 for i in cfg.indicators)
    assert any(i.kind=="DONCHIAN" and i.params["period"]==55 for i in cfg.indicators)
    old_path=path.parent/"btc-futures-vwap-ema11-rule-risk.strategy.json"
    old=StrategyConfig.model_validate(json.loads(old_path.read_text(encoding="utf-8"))["strategy"])
    assert old.futures.rule_risk.enabled
    assert old.futures.rule_risk.reward_r_multiple==2
    assert not old.futures.rule_risk.trailing_enabled


def test_rule_atr_trail_rejects_invalid_dependencies_and_modes():
    path=Path(__file__).resolve().parents[1]/"examples"/"btc-futures-4h-donchian-atr-trend.strategy.json"
    valid=json.loads(path.read_text(encoding="utf-8"))["strategy"]
    import copy
    wrong=copy.deepcopy(valid)
    wrong["indicators"]=[x for x in wrong["indicators"] if x["id"]!="atr14_1h"]
    with pytest.raises(ValidationError,match="ATR indicator"):
        StrategyConfig.model_validate(wrong)
    wrong=copy.deepcopy(valid)
    wrong["futures"]["pullback"]={"enabled":True}
    with pytest.raises(ValidationError,match="cannot be combined"):
        StrategyConfig.model_validate(wrong)
    wrong=copy.deepcopy(valid)
    wrong["futures"]["rule_risk"]["stop_mode"]="SWING"
    with pytest.raises(ValidationError,match="ENTRY_FILL"):
        StrategyConfig.model_validate(wrong)


def test_generic_rule_trailing_executes_without_fixed_target(tmp_path,monkeypatch):
    data=tmp_path/"data"/"sample"
    data.mkdir(parents=True)
    monkeypatch.setenv("STRATEGY_LAB_DATA_ROOT",str(tmp_path/"data"))
    monkeypatch.setenv("STRATEGY_LAB_RESULT_ROOT",str(tmp_path/"results"))
    monkeypatch.setenv("STRATEGY_LAB_CACHE_ROOT",str(tmp_path/"cache"))
    idx=pd.date_range("2026-01-01T00:05:00Z",periods=140,freq="5min")
    rows=[]
    for i,t in enumerate(idx):
        p=10000+(i*3 if i<100 else 300-(i-100)*18)
        rows.append({"timestamp":t.isoformat(),"open":p,"high":p+9,
                     "low":p-9,"close":p+1,"volume":100})
    with (data/"underlying_bars.csv").open("w",newline="",encoding="utf-8") as out:
        w=csv.DictWriter(out,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    s=StrategyConfig(market_type="FUTURES",direction_mode="CALL",timeframe="5m",
        indicators=[IndicatorInstance(id="atr2",kind="ATR",params={"period":2})],
        call_entry=RuleGroup(conditions=[Condition(id="enter",left="close",operator="GT",value=10040)]))
    s.futures.funding_mode="EXCLUDE_WITH_WARNING"
    s.futures.stop_loss_percent=None
    s.futures.take_profit_percent=None
    r=s.futures.rule_risk
    r.enabled=True;r.stop_mode="ATR";r.atr_indicator_id="atr2"
    r.stop_atr_multiple=2;r.stop_buffer_atr=0;r.atr_stop_anchor="ENTRY_FILL"
    r.trailing_enabled=True;r.trailing_atr_multiple=3;r.reward_r_multiple=None
    s.risk.starting_balance_usd=1000
    s.risk.max_hold_minutes=None
    result=run_backtest(BacktestRequest(dataset_id="sample",
        start="2026-01-01T00:05:00Z",end="2026-01-01T11:40:00Z",strategy=s))
    assert result["metrics"]["trades"]>=1
    assert result["futures_research"]["rule_risk_atr_trailing_enabled"]
    for t in result["trades"]:
        assert t["initial_stop_price"] is not None
        assert t["risk_per_lot_usd"]>0
        assert t["quantity"]>0
        assert t["target_price"] is None
        assert t["net_pnl_usd"]==pytest.approx(t["gross_pnl_usd"]-t["fees_usd"]+t["funding_usd"])
    assert any(t["exit_reason"]=="TRAILING_STOP" for t in result["trades"])
