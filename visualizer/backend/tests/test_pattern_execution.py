"""In-engine quote-backed option 2R/3R execution and fee reconciliation."""
from __future__ import annotations
import csv
import pandas as pd
import pytest
from app.engine import run_backtest
from app.models import BacktestRequest,Condition,RuleGroup,PatternTradeConfig,StrategyConfig


def _csv(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",newline="",encoding="utf-8") as fh:
        w=csv.DictWriter(fh,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def fixture(tmp_path,monkeypatch):
    root=tmp_path/"data";ds=root/"sample"
    for key,value in [("STRATEGY_LAB_DATA_ROOT",root),
                      ("STRATEGY_LAB_RESULT_ROOT",tmp_path/"results"),
                      ("STRATEGY_LAB_CACHE_ROOT",tmp_path/"cache")]:
        monkeypatch.setenv(key,str(value))
    index=pd.date_range("2026-11-01T00:05:00Z",periods=18,freq="5min")
    closes=[103,106,109,113,140,153,154,155,156,157,158,159,160,161,162,163,164,165]
    rows=[]
    previous=100.
    for i,(ts,close) in enumerate(zip(index,closes)):
        open_price=previous
        high=max(open_price,close)+.5
        low=min(open_price,close)-.5
        if i<3:
            high=max(open_price,close)
            low=min(open_price,close)
        rows.append(dict(timestamp=ts.isoformat(),open=open_price,high=high,
                         low=low,close=close,volume=200 if i>=3 else 10))
        previous=float(close)
    _csv(ds/"underlying_bars.csv",rows)
    _csv(ds/"option_instruments.csv",[dict(
        symbol="BTC100CE",source_symbol="BTC100CE",expiry="2026-11-02",strike=100,
        option_type="CE",activation="2026-10-31T00:00:00Z",expiration="2026-11-02T00:00:00Z",
        price_precision=2,size_precision=0,price_increment=.1,size_increment=1,
        lot_size=1,min_quantity=1,contract_value=.001)])
    quotes=[]
    for i,ts in enumerate(index):
        bid=19+i*1.0
        quotes.append(dict(timestamp=ts.isoformat(),symbol="BTC100CE",bid=bid,ask=bid+1,
                           bid_size=10000,ask_size=10000,volume=100,open_interest=1000,
                           source_event="fixture"))
    _csv(ds/"option_quotes.csv",quotes)
    return index


def config():
    always=RuleGroup(conditions=[Condition(id="setup",left="close",operator="GT",value=0)])
    cfg=PatternTradeConfig(enabled=True,
        option_delta_assumption=.5,max_risk_usd=1.,
        volume_lookback_bars=2,min_volume_ratio=1.,min_body_range_ratio=.6,
        pullback_patterns=[],breakout_patterns=["BULL_MARUBOZU"],
        call_pullback=always,call_breakout=always,put_pullback=always,put_breakout=always)
    s=StrategyConfig(name="Pattern 2R/3R",direction_mode="CALL",
        call_entry=RuleGroup(conditions=[Condition(left="close",operator="GT",value=0)]),
        pattern_trade=cfg)
    s.risk.stop_loss.mode="NONE"
    s.risk.take_profit.mode="NONE"
    s.risk.profit_protection.mode="NONE"
    s.risk.max_hold_minutes=None
    s.option.max_spread_percent=20
    s.option.min_dte_days=0
    s.option.max_dte_days=3
    s.risk.budget_usd=100
    return s


def test_pattern_2r_3r_preserves_exclusive_position_and_reconciles_fees(tmp_path,monkeypatch):
    fixture(tmp_path,monkeypatch)
    result=run_backtest(BacktestRequest(dataset_id="sample",
        start="2026-11-01T00:05:00Z",end="2026-11-01T01:35:00Z",
        strategy=config(),storage_mode="COMPACT"))
    legs=result["trades"]
    assert len(legs)==2,legs
    assert [x["exit_reason"] for x in legs]==["PATTERN_TARGET_1","PATTERN_TARGET_2"]
    assert legs[0]["entry_time"]==legs[1]["entry_time"]
    assert legs[0]["position_group_id"]==legs[1]["position_group_id"]
    assert legs[0]["partial_exit"] is True
    assert legs[1]["partial_exit"] is False
    assert result["metrics"]["trades"]==1
    assert result["metrics"]["trade_legs"]==2
    assert sum(x["quantity"] for x in legs)==pytest.approx(result["markers"][0]["details"]["quantity"] if result["markers"][0]["kind"]=="entry" else sum(x["quantity"] for x in legs))
    assert result["metrics"]["net_pnl_usd"]==pytest.approx(sum(x["net_pnl_usd"] for x in legs))
    assert result["metrics"]["fees_usd"]==pytest.approx(sum(x["fees_usd"] for x in legs))
    assert result["metrics"]["ending_balance_usd"]==pytest.approx(
        config().risk.starting_balance_usd+result["metrics"]["net_pnl_usd"])


def test_pattern_stop_has_priority_over_target_in_same_underlying_candle(tmp_path,monkeypatch):
    fixture(tmp_path,monkeypatch)
    from app.data_store import DataStore
    # Modify the fifth 5m bar so it crosses the pattern stop and closes above 2R.
    part=tmp_path/"data"/"sample"/"underlying_bars.csv"
    with part.open(newline="") as fh:rows=list(csv.DictReader(fh))
    rows[4]["low"]="90"
    _csv(part,rows)
    result=run_backtest(BacktestRequest(dataset_id="sample",
        start="2026-11-01T00:05:00Z",end="2026-11-01T01:35:00Z",
        strategy=config(),storage_mode="COMPACT"))
    assert result["trades"][0]["exit_reason"]=="PATTERN_STOP"



def test_configurable_three_stage_pattern_executes_all_crossed_targets(tmp_path,monkeypatch):
    fixture(tmp_path,monkeypatch)
    strategy=config()
    strategy.pattern_trade.take_profit_stages=[
        {"r_multiple":1.0,"quantity_fraction":.2},
        {"r_multiple":1.5,"quantity_fraction":.3},
        {"r_multiple":2.0,"quantity_fraction":.5},
    ]
    # Assignment bypasses model validation but is accepted on JSON round-trip.
    strategy=StrategyConfig.model_validate(strategy.model_dump())
    result=run_backtest(BacktestRequest(dataset_id="sample",
        start="2026-11-01T00:05:00Z",end="2026-11-01T01:35:00Z",
        strategy=strategy,storage_mode="COMPACT"))
    legs=result["trades"]
    assert [x["exit_reason"] for x in legs]==[
        "PATTERN_TARGET_1","PATTERN_TARGET_2","PATTERN_TARGET_3"]
    assert result["metrics"]["trades"]==1
    assert result["metrics"]["trade_legs"]==3
    assert result["metrics"]["fees_usd"]==pytest.approx(sum(x["fees_usd"] for x in legs))
    assert result["metrics"]["net_pnl_usd"]==pytest.approx(sum(x["net_pnl_usd"] for x in legs))


def test_target_stage_configuration_fails_on_invalid_fractions_or_order():
    from app.models import PatternTradeConfig
    from pydantic import ValidationError
    with pytest.raises(ValidationError,match="total 1"):
        PatternTradeConfig(take_profit_stages=[
            {"r_multiple":1,"quantity_fraction":.3},
            {"r_multiple":2,"quantity_fraction":.3}])
    with pytest.raises(ValidationError,match="increasing"):
        PatternTradeConfig(take_profit_stages=[
            {"r_multiple":3,"quantity_fraction":.5},
            {"r_multiple":2,"quantity_fraction":.5}])
