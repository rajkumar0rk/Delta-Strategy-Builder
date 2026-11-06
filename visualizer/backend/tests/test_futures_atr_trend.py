"""Regression tests for opt-in trend ATR risk and 4h candles."""
from __future__ import annotations

import csv
import pandas as pd
import pytest
from pydantic import ValidationError

from app.indicators import _aggregate_completed, compute_indicators
from app.models import BacktestRequest, Condition, FuturesConfig, IndicatorInstance, RuleGroup, StrategyConfig
from app.engine import run_backtest
from app.futures_engine import _exit_level
from app.futures_setups import risk_sized_lots


def _frame(n=48*5):
    index=pd.date_range("2026-01-01T00:05:00Z",periods=n,freq="5min")
    return pd.DataFrame({
        "open":[100+i*.1 for i in range(n)],
        "high":[101+i*.1 for i in range(n)],
        "low":[99+i*.1 for i in range(n)],
        "close":[100.5+i*.1 for i in range(n)],
        "volume":[10.0]*n,
    },index=index)


def test_four_hour_completed_only_and_no_lookahead():
    raw=_frame()
    bars=_aggregate_completed(raw,"5m","4h")
    assert len(bars)==5
    assert all(t.hour%4==0 and t.minute==0 for t in bars.index)
    assert bars.index[0]==pd.Timestamp("2026-01-01T04:00:00Z")
    missing=_aggregate_completed(raw.drop(raw.index[17]),"5m","4h")
    assert pd.Timestamp("2026-01-01T04:00:00Z") not in missing.index
    instance=IndicatorInstance(id="ema4h",kind="EMA",timeframe="4h",params={"period":2})
    result,_=compute_indicators(raw,[instance],"5m")
    cutoff=pd.Timestamp("2026-01-01T11:00:00Z")
    future=raw.copy()
    future.loc[future.index>cutoff,"close"]+=10000
    check,_=compute_indicators(future,[instance],"5m")
    pd.testing.assert_series_equal(result.loc[:cutoff,"ema4h"],check.loc[:cutoff,"ema4h"])


def test_trend_risk_requires_matching_atr_and_nonlegacy_stops():
    atr=IndicatorInstance(id="atr14",kind="ATR",timeframe="strategy",params={"period":14})
    trend={"enabled":True,"atr_indicator_id":"atr14"}
    base={"market_type":"FUTURES","timeframe":"1h","indicators":[atr],
          "futures":{"trend_risk":trend,"stop_loss_percent":None,"take_profit_percent":None}}
    assert StrategyConfig.model_validate(base).futures.trend_risk.enabled
    with pytest.raises(ValidationError,match="Disable fixed-percent"):
        StrategyConfig.model_validate({**base,"futures":{**base["futures"],"stop_loss_percent":1}})
    with pytest.raises(ValidationError,match="non-chart-only"):
        StrategyConfig.model_validate({**base,"indicators":[atr.model_copy(update={"chart_only":True})]})
    with pytest.raises(ValidationError,match="mutually exclusive|not pullback"):
        StrategyConfig.model_validate({**base,"futures":{**base["futures"],"pullback":{"enabled":True}}})
    with pytest.raises(ValidationError,match="non-chart-only"):
        StrategyConfig.model_validate({**base,"indicators":[atr.model_copy(update={"timeframe":"4h"})]})


def test_shared_risk_sizing_rejects_unaffordable_and_small_lots():
    from app.models import FuturesTrendRiskConfig
    cfg=FuturesConfig(stop_loss_percent=None,take_profit_percent=None)
    risk=FuturesTrendRiskConfig(enabled=True)
    lots,reason,per_lot=risk_sized_lots(10000,9800,"LONG",1000,cfg,risk)
    assert lots>0 and not reason and per_lot>0
    assert lots*per_lot<=5.0+1e-9
    risk.equity_risk_percent=.001
    lots,reason,_=risk_sized_lots(10000,9800,"LONG",1000,cfg,risk)
    assert lots==0 and reason=="RISK_BUDGET_BELOW_MIN_LOT"


def test_trend_stop_overrides_legacy_nulls_and_gap_worsens_fill():
    cfg=FuturesConfig(stop_loss_percent=None,take_profit_percent=None)
    long={"direction":"LONG","entry_price":100,"stop_price":95}
    bar=type("Bar",(),{"open":93,"high":103,"low":90})()
    assert _exit_level(long,bar,cfg)==("STOP_LOSS",93)
    short={"direction":"SHORT","entry_price":100,"stop_price":105}
    bar=type("Bar",(),{"open":107,"high":110,"low":95})()
    assert _exit_level(short,bar,cfg)==("STOP_LOSS",107)


def test_directional_trend_atr_mode_runs_without_options(tmp_path,monkeypatch):
    data=tmp_path/"data"
    data.mkdir()
    directory=data/"sample"
    directory.mkdir()
    rows=[]
    index=pd.date_range("2026-01-01T00:05:00Z",periods=12*36,freq="5min")
    for i,t in enumerate(index):
        price=10000+i*2
        rows.append({"timestamp":t.isoformat(),"open":price,
                     "high":price+15,"low":price-15,"close":price+1,"volume":100})
    with (directory/"underlying_bars.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    monkeypatch.setenv("STRATEGY_LAB_DATA_ROOT",str(data))
    monkeypatch.setenv("STRATEGY_LAB_RESULT_ROOT",str(tmp_path/"results"))
    monkeypatch.setenv("STRATEGY_LAB_CACHE_ROOT",str(tmp_path/"cache"))
    strategy=StrategyConfig(
        name="ATR trend regression",market_type="FUTURES",timeframe="1h",direction_mode="CALL",
        indicators=[IndicatorInstance(id="atr2",kind="ATR",params={"period":2})],
        call_entry=RuleGroup(conditions=[Condition(id="entry",left="close",operator="GT",value=10050)]))
    strategy.futures.funding_mode="EXCLUDE_WITH_WARNING"
    strategy.futures.stop_loss_percent=None
    strategy.futures.take_profit_percent=None
    strategy.futures.trend_risk.enabled=True
    strategy.futures.trend_risk.atr_indicator_id="atr2"
    strategy.futures.trend_risk.max_lots=100000
    strategy.risk.starting_balance_usd=5000
    strategy.session.windows=[]
    result=run_backtest(BacktestRequest(
        dataset_id="sample",start="2026-01-01T00:05:00Z",
        end="2026-01-02T12:00:00Z",strategy=strategy,warmup_candles=2))
    assert result["futures_research"]["trend_risk_enabled"] is True
    assert result["metrics"]["trades"]>=1 or result["unresolved_position"] is not None
    for trade in result["trades"]:
        assert trade["initial_stop_price"] is not None
        assert trade["risk_per_lot_usd"]>0
        assert trade["quantity"]>0
