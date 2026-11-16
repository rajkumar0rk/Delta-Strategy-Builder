"""Causal native Supertrend and importable futures research seed."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.indicators import CATALOG, compute_indicators
from app.models import Condition, IndicatorInstance, StrategyConfig
from app.rules import evaluate_condition

EXAMPLE = (
    Path(__file__).resolve().parents[1] / "examples" /
    "btc-futures-1h-supertrend-4h-ema200-adx-atr.strategy.json"
)


def sample_bars(closes, freq="1h"):
    close = pd.Series(closes, index=pd.date_range("2026-01-01T01:00:00Z", periods=len(closes), freq=freq), dtype=float)
    return pd.DataFrame({
        "open": close, "high": close + 1, "low": close - 1,
        "close": close, "volume": 100.0,
    }, index=close.index)


def test_supertrend_ready_bands_and_single_bar_flip_signals():
    assert "SUPERTREND" in CATALOG
    frame = sample_bars([100.0] * 18 + [120.0] * 12 + [80.0] * 12)
    calc, meta = compute_indicators(frame, [
        IndicatorInstance(id="st", kind="SUPERTREND", params={"atr_period": 10, "multiplier": 3.0})
    ], "1h")
    assert calc["st.direction"].iloc[:9].isna().all()
    assert calc["st.direction"].iloc[9] == -1
    assert calc["st.bullish_flip"].iloc[9] == 0
    assert int(calc["st.bullish_flip"].fillna(0).sum()) == 1
    assert int(calc["st.bearish_flip"].fillna(0).sum()) == 1
    assert (calc.loc[calc["st.direction"] == 1, "st.line"] == calc.loc[calc["st.direction"] == 1, "st.lower"]).all()
    assert (calc.loc[calc["st.direction"] == -1, "st.line"] == calc.loc[calc["st.direction"] == -1, "st.upper"]).all()
    assert [x["key"] for x in meta] == ["st.line"]
    up = Condition(id="up",left="st.bullish_flip",operator="GT",value=0.5)
    down = Condition(id="down",left="st.bearish_flip",operator="GT",value=0.5)
    assert sum(evaluate_condition(calc, i, up)["passed"] for i in range(len(calc))) == 1
    assert sum(evaluate_condition(calc, i, down)["passed"] for i in range(len(calc))) == 1


def test_supertrend_does_not_revise_past_and_4h_waits_for_close():
    # A 5m base with complete clock-anchored 4h candles, and one future
    # price shock: snapshots at/before the cutoff must not change.
    frame = sample_bars(
        [100.0] * (48 * 12) + [130.0] * (48 * 12) + [80.0] * (48 * 12),
        freq="5min",
    )
    instances = [
        IndicatorInstance(id="st",kind="SUPERTREND",params={"atr_period":3,"multiplier":1.5},timeframe="4h")
    ]
    before, _ = compute_indicators(frame, instances, "5m")
    changed = frame.copy()
    cutoff = frame.index[48 * 12 - 1]
    later = changed.index > cutoff
    for field in ("open", "high", "low", "close"):
        changed.loc[later, field] += 200
    after, _ = compute_indicators(changed, instances, "5m")
    for operand in ("st.line", "st.direction", "st.bullish_flip", "st.bearish_flip"):
        pd.testing.assert_series_equal(before.loc[:cutoff, operand], after.loc[:cutoff, operand])
    assert before["st.direction"].iloc[:47].isna().all()


def test_futures_supertrend_example_schema_and_risk():
    payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 15
    assert payload["app"] == "BTC Strategy Lab"
    strategy = StrategyConfig.model_validate(payload["strategy"])
    assert strategy.market_type == "FUTURES" and strategy.timeframe == "1h"
    assert strategy.position_policy == "EXCLUSIVE"
    assert strategy.session.blocked_weekdays == [5, 6]
    assert strategy.futures.funding_mode == "EXCLUDE_WITH_WARNING"
    ids = {i.id:i for i in strategy.indicators}
    assert ids["supertrend_1h"].kind == "SUPERTREND"
    assert ids["supertrend_1h"].params == {"atr_period":10,"multiplier":3}
    assert ids["ema200_4h"].timeframe == "4h"
    assert all(not x.chart_only for x in strategy.indicators)
    assert strategy.call_entry.conditions[0].left == "supertrend_1h.bullish_flip"
    assert strategy.put_entry.conditions[0].left == "supertrend_1h.bearish_flip"
    assert strategy.call_exit.conditions[0].left == "supertrend_1h.bearish_flip"
    assert strategy.put_exit.conditions[0].left == "supertrend_1h.bullish_flip"
    assert strategy.call_entry_lifecycles[0].max_entries_per_activation == 1
    assert strategy.put_entry_lifecycles[0].max_entries_per_activation == 1
    risk = strategy.futures.rule_risk
    assert risk.enabled and risk.execution_timeframe == "5m"
    assert risk.stop_mode == "ATR" and risk.atr_indicator_id == "atr14_1h"
    assert risk.atr_stop_anchor == "ENTRY_FILL"
    assert risk.stop_atr_multiple == 2 and risk.trailing_atr_multiple == 3
    assert risk.trailing_enabled and risk.trailing_mode == "ATR"
    assert risk.reward_r_multiple is None and risk.take_profit_points is None
