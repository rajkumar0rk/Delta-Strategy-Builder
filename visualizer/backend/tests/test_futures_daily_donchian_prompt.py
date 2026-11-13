"""Daily-trend Donchian futures schema, completed-bar and prompt regression tests."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from app.ai_prompt import _dataset_context, build_strategy_prompt
from app.indicators import compute_indicators
from app.models import AiStrategyPromptRequest, IndicatorInstance, StrategyConfig


EXAMPLE = (
    Path(__file__).resolve().parents[1] / "examples" /
    "btc-futures-1d-ema200-4h-donchian55-20-atr-trail.strategy.json"
)


def test_daily_donchian_example_schema_and_risk_contract():
    payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 15
    assert payload["app"] == "BTC Strategy Lab"
    strategy = StrategyConfig.model_validate(payload["strategy"])
    assert strategy.market_type == "FUTURES"
    assert strategy.timeframe == "4h"
    assert strategy.direction_mode == "BOTH"
    assert strategy.position_policy == "EXCLUSIVE"
    assert {ind.id: (ind.kind, ind.timeframe) for ind in strategy.indicators} == {
        "ema200_1d": ("EMA", "1D"),
        "daily_close": ("EMA", "1D"),
        "donchian55_4h": ("DONCHIAN", "strategy"),
        "donchian20_4h": ("DONCHIAN", "strategy"),
        "atr14_4h": ("ATR", "strategy"),
    }
    assert all(not ind.chart_only for ind in strategy.indicators)
    risk = strategy.futures.rule_risk
    assert risk.enabled and risk.execution_timeframe == "5m"
    assert risk.stop_mode == "ATR" and risk.atr_indicator_id == "atr14_4h"
    assert risk.atr_stop_anchor == "ENTRY_FILL"
    assert risk.stop_atr_multiple == 2.5 and risk.stop_buffer_atr == 0
    assert risk.trailing_enabled and risk.trailing_mode == "ATR"
    assert risk.trailing_atr_multiple == 3 and risk.trailing_source == "HIGH_LOW"
    assert risk.reward_r_multiple is None and risk.take_profit_points is None
    assert risk.size_mode == "RISK_EQUITY" and risk.equity_risk_percent == 0.5
    assert strategy.futures.stop_loss_percent is None
    assert strategy.futures.take_profit_percent is None
    assert not strategy.futures.pullback.enabled
    assert not strategy.futures.adaptive.enabled
    assert not strategy.futures.candle_pattern.enabled
    assert not strategy.pattern_trade.enabled
    assert not strategy.options_pullback.enabled
    for side, breakout_operand, exit_operand in (
        ("call", "donchian55_4h.upper", "donchian20_4h.lower"),
        ("put", "donchian55_4h.lower", "donchian20_4h.upper"),
    ):
        entry = getattr(strategy, f"{side}_entry")
        exit_group = getattr(strategy, f"{side}_exit")
        assert len(entry.conditions) == 2
        assert entry.conditions[1].right == breakout_operand
        assert len(exit_group.conditions) == 1
        assert exit_group.conditions[0].right == exit_operand
        life = getattr(strategy, f"{side}_entry_lifecycles")
        assert len(life) == 1 and life[0].max_entries_per_activation == 1
        assert life[0].trigger_condition_id == entry.conditions[1].id


def test_daily_trend_stays_unavailable_until_daily_close():
    # Six 4h candles per UTC day; last confirmed day must not leak into the
    # first five candles of the next day. 200-day warmup is not needed to
    # establish the alignment invariant, so a short EMA2 is used here.
    idx = pd.date_range("2026-01-01T04:00:00Z", periods=6 * 5, freq="4h")
    close = [100.0] * 6 + [130.0] * 6 + [90.0] * 6 + [145.0] * 6 + [80.0] * 6
    frame = pd.DataFrame({
        "open": close, "high": [x + 1 for x in close],
        "low": [x - 1 for x in close], "close": close,
        "volume": [100.0] * len(idx),
    }, index=idx)
    indicators = [
        IndicatorInstance(id="daily_close", kind="EMA", params={"period": 1}, timeframe="1D"),
        IndicatorInstance(id="daily_ema", kind="EMA", params={"period": 2}, timeframe="1D"),
        IndicatorInstance(id="channel", kind="DONCHIAN", params={"period": 2}),
    ]
    before, _ = compute_indicators(frame, indicators, "4h")
    changed = frame.copy()
    changed.loc[changed.index >= pd.Timestamp("2026-01-05T04:00:00Z"), "close"] += 200
    after, _ = compute_indicators(changed, indicators, "4h")
    # Past completed 4h signals and daily snapshots cannot change from
    # modifying future 4h candles.
    cutoff = pd.Timestamp("2026-01-05T00:00:00Z")
    for key in ("daily_close", "daily_ema", "channel.upper", "channel.lower"):
        pd.testing.assert_series_equal(before.loc[:cutoff, key], after.loc[:cutoff, key])


def test_futures_prompt_respects_new_strategies_without_forcing_rsi():
    strategy = StrategyConfig.model_validate(
        json.loads(EXAMPLE.read_text(encoding="utf-8"))["strategy"]
    )
    prompt = build_strategy_prompt(AiStrategyPromptRequest(strategy=strategy))
    assert "STRATEGY SELECTION: FOLLOW THE USER'S REQUESTED TRADING IDEA" in prompt
    assert "current strategy below is CONTEXT ONLY" in prompt
    assert "4h Donchian55/20 + 1D EMA200" in prompt
    assert "execution_timeframe=5m" in prompt
    assert "generic rule_risk trailing is evaluated on strategy-timeframe completed OHLC" not in prompt
    assert "DONCHIAN indicator bands already exclude their current candle" in prompt
    assert '"schema_version": 15' in prompt or "schema_version=15" in prompt


def test_prompt_dataset_coverage_warning_is_informational(monkeypatch):
    class FakeStore:
        def resolve(self, dataset_id):
            return dataset_id

        def metadata(self, dataset_id):
            return {
                "id": dataset_id, "bar_count": 1000,
                "start": "2025-01-01T00:00:00Z",
                "end": "2026-01-01T00:00:00Z",
                "has_options": False,
            }

    monkeypatch.setattr("app.ai_prompt.DataStore", FakeStore)
    wrong = _dataset_context(AiStrategyPromptRequest(
        dataset_id="segments/2025",
        start="2026-09-27T00:05:00Z", end="2026-10-04T00:05:00Z",
        strategy=StrategyConfig(market_type="FUTURES"),
    ))
    assert wrong["selected_window_covered"] is False
    assert "coverage_warning" in wrong
    assert "BacktestRequest" in wrong["coverage_warning"]
    correct = _dataset_context(AiStrategyPromptRequest(
        dataset_id="segments/2025",
        start="2025-09-27T00:05:00Z", end="2025-10-04T00:05:00Z",
        strategy=StrategyConfig(market_type="FUTURES"),
    ))
    assert correct["selected_window_covered"] is True
    assert "coverage_warning" not in correct
