"""Regression: existing 15M futures strategies may reference completed 1H ATR."""
from __future__ import annotations

import copy

import pandas as pd
import pytest
from pydantic import ValidationError

from app.indicators import compute_indicators
from app.models import IndicatorInstance, StrategyConfig


def v6b_risk_fixture():
    """V6B's previously rejected ATR setup; no entry-rule modifications."""
    return {
        "name": "BTCUSD Futures | V6B 15M Breakout After 1H EMA20 Pullback",
        "market_type": "FUTURES",
        "timeframe": "15m",
        "direction_mode": "BOTH",
        "position_policy": "EXCLUSIVE",
        "indicators": [
            {
                "id": "atr14_1h",
                "kind": "ATR",
                "timeframe": "1h",
                "chart_only": False,
                "visible": True,
                "params": {"period": 14},
            }
        ],
        "futures": {
            "stop_loss_percent": None,
            "take_profit_percent": None,
            "funding_mode": "EXCLUDE_WITH_WARNING",
            "rule_risk": {
                "enabled": True,
                "execution_timeframe": "5m",
                "stop_mode": "ATR",
                "atr_indicator_id": "atr14_1h",
                "stop_atr_multiple": 3.0,
                "atr_stop_anchor": "ENTRY_FILL",
                "trailing_enabled": False,
                "reward_r_multiple": None,
                "take_profit_points": None,
            },
        },
    }


def test_v6b_15m_1h_atr_now_imports_without_rewriting_risk():
    strategy = StrategyConfig.model_validate(v6b_risk_fixture())
    assert strategy.timeframe == "15m"
    assert strategy.indicators[0].timeframe == "1h"
    assert strategy.futures.rule_risk.atr_indicator_id == "atr14_1h"
    assert strategy.futures.rule_risk.stop_atr_multiple == 3.0
    assert strategy.futures.rule_risk.execution_timeframe == "5m"
    # Serialized, reloaded configurations still pass the importer.
    StrategyConfig.model_validate(strategy.model_dump())


@pytest.mark.parametrize("variant", ["missing", "chart_only", "wrong_kind", "lower_timeframe"])
def test_atr_dependency_validation_still_fail_closed(variant):
    payload = copy.deepcopy(v6b_risk_fixture())
    if variant == "missing":
        payload["indicators"] = []
    elif variant == "chart_only":
        payload["indicators"][0]["chart_only"] = True
    elif variant == "wrong_kind":
        payload["indicators"][0]["kind"] = "EMA"
        payload["indicators"][0]["params"] = {"period": 14}
    else:
        payload["timeframe"] = "1h"
        payload["indicators"][0]["timeframe"] = "15m"
    with pytest.raises(ValidationError):
        StrategyConfig.model_validate(payload)


def test_confirmed_1h_atr_on_15m_does_not_use_future_data():
    idx = pd.date_range("2026-01-01T00:15:00Z", periods=120, freq="15min")
    closes = [10000 + (i // 4) * 2.0 + (3 if i % 2 else -3) for i in range(len(idx))]
    frame = pd.DataFrame({
        "open": [c - 1 for c in closes],
        "high": [c + 6 for c in closes],
        "low": [c - 6 for c in closes],
        "close": closes,
        "volume": [100.0] * len(idx),
    }, index=idx)
    inst = [IndicatorInstance(id="atr14_1h", kind="ATR", params={"period": 14}, timeframe="1h")]
    before, _ = compute_indicators(frame, inst, "15m")
    # No ATR until the 14th complete 1h bar has closed.
    assert before.loc[pd.Timestamp("2026-01-01T13:45:00Z"), "atr14_1h"] != before.loc[pd.Timestamp("2026-01-01T13:45:00Z"), "atr14_1h"]
    assert pd.notna(before.loc[pd.Timestamp("2026-01-01T14:00:00Z"), "atr14_1h"])
    cutoff = pd.Timestamp("2026-01-01T19:30:00Z")
    changed = frame.copy()
    for column in ("open", "high", "low", "close"):
        changed.loc[changed.index > cutoff, column] += 2000
    after, _ = compute_indicators(changed, inst, "15m")
    pd.testing.assert_series_equal(before.loc[:cutoff, "atr14_1h"], after.loc[:cutoff, "atr14_1h"])
    # Between two completed hourly boundaries, value must not update.
    assert before.loc[pd.Timestamp("2026-01-01T19:15:00Z"), "atr14_1h"] == before.loc[pd.Timestamp("2026-01-01T19:45:00Z"), "atr14_1h"]
