"""Opt-in higher-TF completed futures entry gate; existing entry lifecycles reused."""
from __future__ import annotations

import csv

import pandas as pd
import pytest
from pydantic import ValidationError

from app.engine import run_backtest
from app.futures_engine import _entry_evaluation_due
from app.models import BacktestRequest, Condition, EntryBehavior, IndicatorInstance, RuleGroup, StrategyConfig


@pytest.mark.parametrize("timestamp,base,evaluation,expected", [
    ("2026-01-01T01:00:00Z", "5m", "1h", False),
    ("2026-01-01T01:05:00Z", "5m", "1h", True),
    ("2026-01-01T01:10:00Z", "5m", "1h", False),
    ("2026-01-01T02:05:00Z", "5m", "1h", True),
    ("2026-01-01T04:05:00Z", "5m", "4h", True),
    ("2026-01-01T00:05:00Z", "5m", "1D", True),
    ("2026-01-01T12:10:00Z", "10m", "1h", True),
    ("2026-01-01T12:20:00Z", "10m", "1h", False),
    ("2026-01-01T12:30:00Z", "30m", "30m", True),
    ("2026-01-01T12:35:00Z", "5m", "strategy", True),
])
def test_entry_evaluation_utc_alignment(timestamp, base, evaluation, expected):
    assert _entry_evaluation_due(pd.Timestamp(timestamp), base, evaluation) is expected


def test_schema_rejects_shorter_tf_and_specialized_engines():
    assert StrategyConfig(market_type="FUTURES").entry_evaluation_timeframe == "strategy"
    assert StrategyConfig(market_type="FUTURES", timeframe="5m", entry_evaluation_timeframe="1h").entry_evaluation_timeframe == "1h"
    with pytest.raises(ValidationError, match="exact multiple"):
        StrategyConfig(market_type="FUTURES", timeframe="30m", entry_evaluation_timeframe="10m")
    with pytest.raises(ValidationError, match="exact multiple"):
        StrategyConfig(market_type="FUTURES", timeframe="4h", entry_evaluation_timeframe="1h")
    with pytest.raises(ValidationError, match="only for FUTURES"):
        StrategyConfig(market_type="OPTIONS", entry_evaluation_timeframe="1h")
    with pytest.raises(ValidationError, match="specialized futures modes"):
        StrategyConfig(market_type="FUTURES", entry_evaluation_timeframe="1h", futures={"pullback":{"enabled":True}})


def test_hourly_gate_prevents_intrahour_reentries_and_still_exits_on_five_minute_stop(tmp_path, monkeypatch):
    root = tmp_path / "data" / "sample"
    root.mkdir(parents=True)
    for key, path in (("STRATEGY_LAB_DATA_ROOT",tmp_path / "data"),
                      ("STRATEGY_LAB_RESULT_ROOT",tmp_path / "results"),
                      ("STRATEGY_LAB_CACHE_ROOT",tmp_path / "cache")):
        monkeypatch.setenv(key, str(path))
    dates = pd.date_range("2026-01-01T00:05:00Z", periods=43, freq="5min")
    records = []
    for i, ts in enumerate(dates):
        low = 99_400 if i in (17,29) else 99_970
        records.append({"timestamp":ts.isoformat(),"open":100_000,
                        "high":100_030,"low":low,"close":100_000,"volume":100})
    with (root / "underlying_bars.csv").open("w",newline="",encoding="utf-8") as handle:
        w=csv.DictWriter(handle, fieldnames=list(records[0]))
        w.writeheader()
        w.writerows(records)

    strategy = StrategyConfig(
        market_type="FUTURES",timeframe="5m",entry_evaluation_timeframe="1h",
        direction_mode="CALL",
        indicators=[IndicatorInstance(id="close1h",kind="EMA",
                       params={"period":1,"source":"close"},timeframe="1h")],
        call_entry=RuleGroup(conditions=[
            Condition(id="always_after_first_hour",left="close1h",operator="GT",value=1)]),
        call_entry_lifecycles=[EntryBehavior(id="long_repeat",max_entries_per_activation=None)],
    )
    strategy.futures.funding_mode = "EXCLUDE_WITH_WARNING"
    strategy.futures.stop_loss_percent = None
    strategy.futures.take_profit_percent = None
    strategy.futures.slippage_bps = 0
    strategy.futures.taker_fee_percent = 0
    strategy.futures.gst_percent = 0
    strategy.futures.rule_risk.enabled = True
    strategy.futures.rule_risk.stop_mode = "FIXED_POINTS"
    strategy.futures.rule_risk.stop_loss_points = 500
    strategy.futures.rule_risk.stop_buffer_atr = 0
    strategy.futures.rule_risk.trailing_enabled = True
    strategy.futures.rule_risk.trailing_mode = "POINTS"
    strategy.futures.rule_risk.trailing_activation_points = 500
    strategy.futures.rule_risk.trailing_pullback_points = 100
    strategy.futures.rule_risk.execution_timeframe = "5m"
    strategy.futures.rule_risk.reward_r_multiple = None
    strategy.futures.rule_risk.take_profit_points = None
    strategy.futures.rule_risk.size_mode = "FIXED"
    strategy.futures.quantity_lots = 1
    strategy.risk.starting_balance_usd = 1000

    result = run_backtest(BacktestRequest(dataset_id="sample",strategy=strategy,
        start=dates[0].isoformat(),end=(dates[-1]+pd.Timedelta(minutes=5)).isoformat()))
    positions = list(result["trades"])
    if result.get("unresolved_position"):
        positions.append(result["unresolved_position"])
    entry_times = [pd.Timestamp(p["entry_time"]) for p in positions]
    assert entry_times == [pd.Timestamp(t) for t in (
        "2026-01-01T01:05:00Z","2026-01-01T02:05:00Z","2026-01-01T03:05:00Z")]
    assert len(result["trades"]) == 2
    assert all(t["exit_reason"] == "STOP_LOSS" for t in result["trades"])
    assert all(pd.Timestamp(t["exit_time"]).minute == 30 for t in result["trades"])
    assert all(t["initial_stop_price"] == 99_500 for t in result["trades"])
