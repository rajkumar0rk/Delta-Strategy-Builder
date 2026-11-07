"""Regression coverage for opt-in rule-tree Futures risk and VWAP sessions."""
from __future__ import annotations

import csv
import json

import pandas as pd
import pytest
from pydantic import ValidationError

from app.engine import run_backtest
from app.indicators import compute_indicators
from app.models import BacktestRequest, IndicatorInstance, StrategyConfig


def _bars():
    idx = pd.date_range("2026-01-01T00:05:00Z", periods=90, freq="5min")
    close = [100.0] * 30 + [96.0] * 20 + [106.0] * 40
    return pd.DataFrame({
        "open": close, "high": [v + 0.5 for v in close],
        "low": [v - 0.5 for v in close],
        "close": close, "volume": [100.0] * len(close),
    }, index=idx)


def _example():
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "examples" / "btc-futures-vwap-ema11-rule-risk.strategy.json"
    obj = json.loads(p.read_text(encoding="utf-8"))
    assert obj["schema_version"] == 15 and obj["app"] == "BTC Strategy Lab"
    return StrategyConfig.model_validate(obj["strategy"])


def test_reference_strategy_is_importable():
    s = _example()
    assert s.market_type == "FUTURES" and s.futures.rule_risk.enabled
    assert s.futures.stop_loss_percent is None and s.futures.take_profit_percent is None


def test_vwap_reset_uses_completed_candle_open_not_its_close():
    frame = _bars().iloc[:7]
    # Open timestamps: 00:00, 00:05, 00:10...
    conf = IndicatorInstance(id="v", kind="VWAP", params={
        "reset_mode": "CUSTOM_SESSION_OPEN", "timezone": "Etc/UTC",
        "reset_time": "00:10", "price_source": "close",
    })
    output, _ = compute_indicators(frame, [conf])
    # 00:15 timestamp belongs to the new 00:10-open session.
    assert output["v"].iloc[2] == pytest.approx(float(frame.close.iloc[2]))


@pytest.mark.parametrize("bad_params", [
    {"reset_time": "25:00"}, {"timezone": "Mars/Olympus"},
    {"price_source": "future_close"}, {"unknown_key": "test"},
])
def test_bad_vwap_configuration_rejected(bad_params):
    with pytest.raises(ValidationError):
        IndicatorInstance(id="v", kind="VWAP", params=bad_params)


def test_generic_risk_mode_rejects_conflicting_protective_modes():
    s = _example().model_dump()
    s["futures"]["pullback"]["enabled"] = True
    with pytest.raises(ValidationError, match="cannot be combined"):
        StrategyConfig.model_validate(s)
    s["futures"]["pullback"]["enabled"] = False
    s["futures"]["stop_loss_percent"] = 1.0
    with pytest.raises(ValidationError, match="fixed-percent"):
        StrategyConfig.model_validate(s)


def test_generic_risk_requires_actual_non_chart_atr():
    s = _example().model_dump()
    s["indicators"] = [x for x in s["indicators"] if x["id"] != "atr14_5m"]
    with pytest.raises(ValidationError, match="ATR indicator"):
        StrategyConfig.model_validate(s)


def test_rule_risk_futures_full_engine_accounting(tmp_path, monkeypatch):
    root = tmp_path / "data"
    directory = root / "sample"
    directory.mkdir(parents=True)
    monkeypatch.setenv("STRATEGY_LAB_DATA_ROOT", str(root))
    monkeypatch.setenv("STRATEGY_LAB_RESULT_ROOT", str(tmp_path / "results"))
    monkeypatch.setenv("STRATEGY_LAB_CACHE_ROOT", str(tmp_path / "cache"))
    rows = [{"timestamp": t.isoformat(), **{key: float(bar[key]) for key in ("open", "high", "low", "close", "volume")}}
            for t, bar in _bars().iterrows()]
    with (directory / "underlying_bars.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    strategy = _example()
    strategy.risk.max_daily_loss_percent = None
    request = BacktestRequest(
        dataset_id="sample", start="2026-01-01T00:05:00Z",
        end="2026-01-01T07:30:00Z", strategy=strategy)
    result = run_backtest(request)
    assert result["reliability"]["grade"] == "RESEARCH_ONLY"
    assert result["metrics"]["trades"] >= 1
    for trade in result["trades"]:
        assert trade["fees_usd"] == pytest.approx(trade["entry_fee_usd"] + trade["exit_fee_usd"])
        assert trade["net_pnl_usd"] == pytest.approx(trade["gross_pnl_usd"] - trade["fees_usd"] + trade["funding_usd"])
        assert trade["quantity"] > 0
