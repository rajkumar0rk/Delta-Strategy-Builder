"""Original signal_events is the reference for incremental H6 signals."""
from dataclasses import asdict, replace
import numpy as np
import pandas as pd
import pytest

from backtest.data import OptionSpec, timestamp_ns
from backtest.ema_vwap_research import (
    Scenario, PullbackReversalConfig, MomentumBreakoutConfig,
    indicators, signal_events,
)
from backtest.legacy_full_indicator_stream import iter_complete_indicator_chunks
from backtest.legacy_incremental_signals import (
    iter_incremental_baseline_signals, IncrementalBaselineSignals,
)
from backtest.option_expiry_index import OptionExpiryIndex


def _market(tmp_path):
    n = 450
    rng = np.random.default_rng(13579)
    close = 100000.0 + np.cumsum(
        rng.choice([-150.0, -40.0, 60.0, 180.0], size=n)
    )
    path = tmp_path / "underlying_bars.csv"
    pd.DataFrame({
        "timestamp": pd.date_range("2026-10-28T00:00:00Z", periods=n, freq="5min"),
        "open": close - 2.0, "high": close + 8.0,
        "low": close - 9.0, "close": close,
        "volume": rng.uniform(1.0, 300.0, size=n),
    }).to_csv(path, index=False)
    specs = [
        OptionSpec(
            symbol=f"BTC-{kind}", source_symbol=f"BTC-{kind}",
            expiry="2026-10-31", strike=100000.0, option_type=kind,
            activation_ns=timestamp_ns("2026-10-27T00:00:00Z"),
            expiration_ns=timestamp_ns("2026-10-31T00:00:00Z"),
            price_precision=2, size_precision=0, price_increment=.01,
            size_increment=1.0, lot_size=1.0, min_quantity=1.0,
            contract_value=0.001,
        ) for kind in ("CE", "PE")
    ]
    return path, specs


def _oracle(frame, specs, start_ns, end_ns, scenario, decisions, option_index):
    return signal_events(
        frame, specs, start_ns, end_ns,
        confirmation_candles=scenario.confirmation_candles,
        require_macd=scenario.require_macd,
        require_stoch_rsi_entry=scenario.require_stoch_rsi_entry,
        require_stoch_rsi_momentum_entry=scenario.require_stoch_rsi_momentum_entry,
        entry_start_hour_utc=scenario.entry_start_hour_utc,
        entry_end_hour_utc=scenario.entry_end_hour_utc,
        entry_windows_ist_minutes=scenario.entry_windows_ist_minutes,
        blocked_weekdays_ist=scenario.blocked_weekdays_ist,
        entry_min_conditions=scenario.entry_min_conditions,
        min_days_to_expiry=scenario.min_days_to_expiry,
        min_days_to_expiry_inclusive=scenario.min_days_to_expiry_inclusive,
        max_days_to_expiry=scenario.max_days_to_expiry,
        pullback_reversal=scenario.pullback_reversal,
        entry_mode=scenario.entry_mode,
        momentum_breakout=scenario.momentum_breakout,
        decision_events=decisions, option_index=option_index,
    )


@pytest.mark.parametrize("chunk_rows", [1, 31, 127])
@pytest.mark.parametrize("macd", [False, True])
@pytest.mark.parametrize("confirmation", [0, 2])
def test_original_and_incremental_h6_records_match(
    tmp_path, chunk_rows, macd, confirmation,
):
    path, specs = _market(tmp_path)
    scenario = Scenario(
        "H6", 1, "EMA", require_macd=macd,
        confirmation_candles=confirmation,
        entry_start_hour_utc=0, entry_end_hour_utc=16,
    )
    start = timestamp_ns("2026-10-28T01:00:00Z")
    end = timestamp_ns("2026-10-29T04:00:00Z")
    full_decisions, stream_decisions = [], []
    reference = _oracle(
        indicators(path), specs, start, end, scenario, full_decisions, None,
    )
    result = list(iter_incremental_baseline_signals(
        iter_complete_indicator_chunks(path, chunk_rows=chunk_rows),
        specs, start_ns=start, end_ns=end,
        scenario=scenario, decision_events=stream_decisions,
    ))
    assert [asdict(event) for event in reference] == [
        asdict(event) for event in result
    ]
    assert full_decisions == stream_decisions


@pytest.mark.parametrize("conditions", [1, 2, 3])
@pytest.mark.parametrize("stoch_mode", ["none", "entry", "momentum"])
def test_extra_conditions_and_stoch_filters_match(tmp_path, conditions, stoch_mode):
    path, specs = _market(tmp_path)
    scenario = Scenario(
        "H6", 1, "EMA",
        entry_min_conditions=conditions,
        require_stoch_rsi_entry=stoch_mode=="entry",
        require_stoch_rsi_momentum_entry=stoch_mode=="momentum",
        blocked_weekdays_ist=(3,),
        entry_windows_ist_minutes=((0, 330), (480, 1200)),
    )
    start = timestamp_ns("2026-10-28T01:00:00Z")
    end = timestamp_ns("2026-10-29T04:00:00Z")
    indexed = OptionExpiryIndex(specs)
    first, second = [], []
    reference = _oracle(
        indicators(path), specs, start, end, scenario, first, indexed,
    )
    result = list(iter_incremental_baseline_signals(
        iter_complete_indicator_chunks(path, chunk_rows=43),
        specs, start_ns=start, end_ns=end, scenario=scenario,
        decision_events=second, option_index=indexed,
    ))
    assert [asdict(e) for e in reference] == [asdict(e) for e in result]
    assert first == second


@pytest.mark.parametrize("overrides", [
    {"entry_mode": "ZIGZAG"},
    {"pullback_reversal": PullbackReversalConfig(enabled=True)},
    {"momentum_breakout": MomentumBreakoutConfig(enabled=True)},
    {"require_stoch_rsi_entry": True,
     "require_stoch_rsi_momentum_entry": True},
    {"entry_min_conditions": 0},
    {"confirmation_candles": -1},
])
def test_unsupported_modes_fail_closed(overrides):
    state_kwargs = dict(
        specs=[], start_ns=1, end_ns=2,
        scenario=replace(Scenario("H6", 1, "EMA"), **overrides),
    )
    with pytest.raises(ValueError):
        IncrementalBaselineSignals(**state_kwargs)


def test_finished_state_rejects_reuse():
    state = IncrementalBaselineSignals(
        [], start_ns=1, end_ns=2, scenario=Scenario("H6", 1, "EMA"),
    )
    state.finish()
    with pytest.raises(RuntimeError, match="FINISHED"):
        state.finish()
