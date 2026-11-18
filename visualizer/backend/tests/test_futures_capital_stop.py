"""Allocated-capital futures stop regressions: math, priority, schema, backtest."""
from __future__ import annotations

import csv
from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import ValidationError

from app.engine import run_backtest
from app.futures_engine import _capital_stop_level, _exit_level, _slipped
from app.models import (
    BacktestRequest, Condition, EntryBehavior, FuturesCapitalStopConfig,
    FuturesConfig, RuleGroup, StrategyConfig,
)


@pytest.mark.parametrize("direction,expected", [
    ("LONG", 9850.0),
    ("SHORT", 10150.0),
])
def test_fixed_10_usd_15_percent_budget_sets_1_50_net_loss(direction, expected):
    cfg = FuturesConfig(
        stop_loss_percent=None, take_profit_percent=None,
        taker_fee_percent=0, slippage_bps=0, slippage_ticks=0, tick_size=0.5,
    )
    level = _capital_stop_level(10000, direction, 0.01, 0, 0, 1.5, cfg, 0)
    assert level == pytest.approx(expected)
    hit = _exit_level(
        {"entry_price":10000, "direction":direction, "capital_stop_price":level},
        SimpleNamespace(open=10000, high=10200, low=9800), cfg,
    )
    assert hit == ("CAPITAL_STOP_LOSS", expected)


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
def test_fee_gst_and_slippage_count_toward_15_percent_net_limit(direction):
    cfg = FuturesConfig(
        stop_loss_percent=None, take_profit_percent=None,
        taker_fee_percent=0.05, gst_percent=18, slippage_bps=2,
        slippage_ticks=1, tick_size=0.5,
    )
    entry = 10000
    qty = 0.01
    entry_fee = entry * qty * 0.0005 * 1.18
    level = _capital_stop_level(entry, direction, qty, entry_fee, 0, 1.5, cfg, 2)
    assert level is not None
    exit_fill = _slipped(level, direction, False, 2, 0.5, 1)
    sign = 1 if direction == "LONG" else -1
    net = ((exit_fill-entry)*qty*sign - entry_fee
           - exit_fill*qty*cfg.taker_fee_percent/100*(1+cfg.gst_percent/100))
    assert net >= -1.50000001
    assert net < -1.48


def test_existing_stop_wins_when_tighter_and_gap_is_adverse():
    cfg = FuturesConfig(stop_loss_percent=None, take_profit_percent=None)
    long = {"entry_price":10000, "direction":"LONG",
            "stop_price":9900, "capital_stop_price":9850}
    short = {"entry_price":10000, "direction":"SHORT",
             "stop_price":10100, "capital_stop_price":10150}
    assert _exit_level(long, SimpleNamespace(open=10000, low=9800, high=10100), cfg) == ("STOP_LOSS",9900)
    assert _exit_level(short, SimpleNamespace(open=10000, low=9900, high=10200), cfg) == ("STOP_LOSS",10100)
    long["stop_price"] = None
    assert _exit_level(long, SimpleNamespace(open=9800, low=9700, high=10000), cfg) == ("CAPITAL_STOP_LOSS",9800)
    short["stop_price"] = None
    assert _exit_level(short, SimpleNamespace(open=10200, low=9900, high=10300), cfg) == ("CAPITAL_STOP_LOSS",10200)


def test_too_small_capital_budget_rejects_instead_of_fabricating_stop():
    cfg = FuturesConfig(taker_fee_percent=5, gst_percent=18, slippage_bps=2)
    assert _capital_stop_level(10000, "LONG", .01, 5.9, 0, 1.5, cfg, 2) is None
    assert _capital_stop_level(10000, "SHORT", .01, 5.9, 0, 1.5, cfg, 2) is None


def test_schema_defaults_validate_capital_basis_and_old_strategy_compatibility():
    strategy = StrategyConfig(market_type="FUTURES")
    assert not strategy.futures.capital_stop.enabled
    assert strategy.futures.capital_stop.loss_percent == 15
    assert not StrategyConfig().futures.capital_stop.enabled
    for invalid in [
        dict(capital_usd=0), dict(loss_percent=0), dict(loss_percent=101),
        dict(capital_basis="OPTION_PREMIUM"),
    ]:
        with pytest.raises(ValidationError):
            FuturesCapitalStopConfig(**invalid)


def test_futures_engine_exits_10_lots_on_net_1_50_loss(tmp_path, monkeypatch):
    data = tmp_path / "data"
    root = data / "sample"
    root.mkdir(parents=True)
    monkeypatch.setenv("STRATEGY_LAB_DATA_ROOT", str(data))
    monkeypatch.setenv("STRATEGY_LAB_RESULT_ROOT", str(tmp_path / "results"))
    monkeypatch.setenv("STRATEGY_LAB_CACHE_ROOT", str(tmp_path / "cache"))
    times = pd.date_range("2026-01-01T00:00:00Z", periods=20, freq="5min")
    rows = [
        {"timestamp":t.isoformat(), "open":10000, "high":10020,
         "low":9800 if i == 3 else 9990, "close":10005, "volume":100}
        for i,t in enumerate(times)
    ]
    with (root / "underlying_bars.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    strategy = StrategyConfig(
        name="Ten lot capital stop",
        market_type="FUTURES",
        direction_mode="CALL",
        call_entry=RuleGroup(conditions=[
            Condition(id="enter", left="close", operator="GT", value=9990),
        ]),
        call_entry_lifecycles=[EntryBehavior(id="enter-1", delay_bars=0)],
    )
    strategy.futures.quantity_lots = 10
    strategy.futures.leverage = 5
    strategy.futures.taker_fee_percent = 0
    strategy.futures.slippage_bps = 0
    strategy.futures.stop_loss_percent = None
    strategy.futures.take_profit_percent = None
    strategy.futures.funding_mode = "EXCLUDE_WITH_WARNING"
    strategy.futures.capital_stop = FuturesCapitalStopConfig(
        enabled=True, capital_basis="FIXED_USD", capital_usd=10, loss_percent=15,
    )
    strategy.risk.max_hold_minutes = None
    strategy.risk.starting_balance_usd = 100
    result = run_backtest(BacktestRequest(
        dataset_id="sample", start="2026-01-01T00:00:00Z",
        end="2026-01-01T01:40:00Z", strategy=strategy,
    ))
    stopped = [t for t in result["trades"] if t["exit_reason"] == "CAPITAL_STOP_LOSS"]
    assert stopped
    trade = stopped[0]
    assert trade["quantity"] == pytest.approx(.01)
    assert trade["capital_basis_usd"] == pytest.approx(10)
    assert trade["capital_stop_loss_usd"] == pytest.approx(1.5)
    assert trade["net_pnl_usd"] == pytest.approx(-1.5)
    assert result["metrics"]["capital_stop_exits"] >= 1
