from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pandas as pd
import pytest

from backtest.data import OptionSpec
from backtest.ema_vwap_research import (
    EarlyFailureConfig,
    ExecutionConfig,
    MomentumBreakoutConfig,
    PullbackReversalConfig,
    Scenario,
    SignalEvent,
    _condition_valid,
    _directional_confirmation_valid,
    _exit_triggered,
    _entry_time_allowed,
    _ema_exit_valid,
    _stoch_rsi_entry_direction,
    _stoch_rsi_momentum_entry_direction,
    activation_scenarios,
    all_fail_exit_scenarios,
    all_fail_atr_scenarios,
    all_fail_atr_sensitivity_scenarios,
    all_fail_macd_exit_scenarios,
    all_fail_z50_scenarios,
    atr_wilder,
    confirmation_scenarios,
    entry_condition_count_scenarios,
    ema_strength_scenarios,
    _ema_strength_atr,
    _signal_entry_features,
    _select_option,
    macd_scenarios,
    momentum_breakout_directions,
    macd_exit_policy_scenarios,
    locked_h6_scenarios,
    locked_h6_fa_scenarios,
    locked_h6_fa150_m30_scenarios,
    locked_h6_fa150_m30_stoch_scenarios,
    locked_m30_scenarios,
    locked_h6_fa150_utc08_scenarios,
    option_fee_components,
    one_trade_per_ema_regime_scenarios,
    option_true_range_observations,
    protected_floor,
    pullback_reversal_directions,
    scenarios,
    signal_events,
    simulate_trade,
    stoch_scenarios,
    stoch_momentum_scenarios,
    stop_loss_scenarios,
    utc_session_scenarios,
    vwap_volume_scenarios,
)


UTC = timezone.utc
BASE_NS = int(datetime(2026, 9, 1, tzinfo=UTC).timestamp() * 1_000_000_000)
MINUTE_NS = 60 * 1_000_000_000


def option() -> OptionSpec:
    return OptionSpec(
        symbol="BTC80000020926CE",
        source_symbol="C-BTC-80000-020926",
        expiry="02SEP26",
        strike=80000,
        option_type="CE",
        activation_ns=BASE_NS - MINUTE_NS,
        expiration_ns=BASE_NS + 2 * 24 * 60 * MINUTE_NS,
        price_precision=1,
        size_precision=0,
        price_increment=0.1,
        size_increment=1,
        lot_size=1,
        min_quantity=1,
        contract_value=0.001,
    )


def pullback_frame(direction: str) -> pd.DataFrame:
    index = pd.date_range("2026-09-01T00:00:00Z", periods=5, freq="5min")
    if direction == "CALL":
        values = {
            "high": [106, 105, 104, 106, 109],
            "low": [103, 102, 101, 103, 104],
            "close": [105, 104, 103, 104, 108],
            "ema9": [104, 104, 104, 104, 105],
            "ema20": [103, 103, 103, 103, 103],
            "ema50": [100, 100, 100, 100, 100],
            "vwap": [102, 102, 102, 102, 102],
            "rsi14": [52, 50, 47, 48, 52],
            "atr14": [10, 10, 10, 10, 10],
        }
    else:
        values = {
            "high": [97, 98, 99, 97, 96],
            "low": [94, 95, 96, 94, 91],
            "close": [96, 97, 98, 96, 92],
            "ema9": [96, 96, 96, 96, 95],
            "ema20": [97, 97, 97, 97, 97],
            "ema50": [100, 100, 100, 100, 100],
            "vwap": [98, 98, 98, 98, 98],
            "rsi14": [52, 55, 57, 52, 48],
            "atr14": [10, 10, 10, 10, 10],
        }
    return pd.DataFrame(values, index=index)


@pytest.mark.parametrize("direction", ["CALL", "PUT"])
def test_pullback_reversal_confirms_both_directions(direction):
    result = pullback_reversal_directions(
        pullback_frame(direction),
        PullbackReversalConfig(enabled=True),
    )

    assert result.iloc[-1] == direction


def test_pullback_reversal_diagnostics_follow_the_entry_funnel():
    frame = pullback_frame("CALL")
    diagnostics = {}
    eligible = pd.Series(False, index=frame.index)
    eligible.iloc[-1] = True

    result = pullback_reversal_directions(
        frame,
        PullbackReversalConfig(enabled=True),
        diagnostics=diagnostics,
        diagnostic_eligible=eligible,
    )

    assert result.iloc[-1] == "CALL"
    assert diagnostics == {
        "CANDLES_EVALUATED": 1,
        "TREND_CANDIDATES": 1,
        "QUALIFYING_CANDLES": 1,
        "CALL_QUALIFYING_CANDLES": 1,
    }


def test_pullback_reversal_diagnostics_identify_touch_tolerance_rejection():
    frame = pullback_frame("CALL")
    frame.loc[frame.index[:-2], ["high", "low", "close"]] = [111, 110, 110]
    frame.loc[frame.index[-2], ["high", "low", "close"]] = [106, 90, 90]
    diagnostics = {}
    eligible = pd.Series(False, index=frame.index)
    eligible.iloc[-1] = True

    result = pullback_reversal_directions(
        frame,
        PullbackReversalConfig(
            enabled=True,
            max_touch_close_distance_atr=0.2,
        ),
        diagnostics=diagnostics,
        diagnostic_eligible=eligible,
    )

    assert result.iloc[-1] == ""
    assert diagnostics["TOUCH_TOLERANCE_REJECTED"] == 1
    assert diagnostics.get("QUALIFYING_CANDLES", 0) == 0


def test_pullback_reversal_rsi_and_atr_switches_are_independent():
    frame = pullback_frame("CALL")
    frame.loc[frame.index[:-1], "rsi14"] = 70.0

    both_enabled = pullback_reversal_directions(
        frame,
        PullbackReversalConfig(
            enabled=True,
            rsi_enabled=True,
            atr_enabled=True,
            atr_reversal_multiplier=1.0,
        ),
    )
    rsi_disabled = pullback_reversal_directions(
        frame,
        PullbackReversalConfig(
            enabled=True,
            rsi_enabled=False,
            atr_enabled=True,
            atr_reversal_multiplier=1.0,
        ),
    )
    atr_disabled = pullback_reversal_directions(
        frame,
        PullbackReversalConfig(
            enabled=True,
            rsi_enabled=True,
            atr_enabled=False,
            atr_reversal_multiplier=1.0,
        ),
    )
    both_disabled = pullback_reversal_directions(
        frame,
        PullbackReversalConfig(
            enabled=True,
            rsi_enabled=False,
            atr_enabled=False,
            atr_reversal_multiplier=1.0,
        ),
    )

    assert both_enabled.iloc[-1] == ""
    assert rsi_disabled.iloc[-1] == ""
    assert atr_disabled.iloc[-1] == ""
    assert both_disabled.iloc[-1] == "CALL"


def test_pullback_ema20_and_vwap_touches_use_or_not_and():
    frame = pullback_frame("CALL")
    frame["vwap"] = 90.0
    frame["ema50"] = 95.0

    result = pullback_reversal_directions(
        frame,
        PullbackReversalConfig(
            enabled=True,
            touch_ema20=True,
            touch_vwap=True,
        ),
    )

    assert result.iloc[-1] == "CALL"


def test_pullback_atr_tolerance_rejects_deep_breakdown_touch():
    frame = pullback_frame("CALL")
    frame.loc[frame.index[:-2], ["high", "low", "close"]] = [111, 110, 110]
    frame.loc[frame.index[-2], ["high", "low", "close"]] = [106, 90, 90]

    protected = pullback_reversal_directions(
        frame,
        PullbackReversalConfig(
            enabled=True,
            max_touch_close_distance_atr=0.2,
        ),
    )
    unprotected = pullback_reversal_directions(
        frame,
        PullbackReversalConfig(
            enabled=True,
            max_touch_close_distance_atr=None,
        ),
    )

    assert protected.iloc[-1] == ""
    assert unprotected.iloc[-1] == "CALL"


def test_pullback_sequence_excludes_unrelated_old_extreme_from_atr_reversal():
    frame = pullback_frame("CALL")
    frame.loc[frame.index[0], ["high", "low", "close"]] = [106, 80, 102]
    frame.loc[frame.index[1:3], ["high", "low", "close"]] = [111, 110, 110]

    actual_sequence = pullback_reversal_directions(
        frame,
        PullbackReversalConfig(
            enabled=True,
            atr_reversal_multiplier=0.6,
            use_actual_pullback_sequence=True,
        ),
    )
    full_window = pullback_reversal_directions(
        frame,
        PullbackReversalConfig(
            enabled=True,
            atr_reversal_multiplier=0.6,
            use_actual_pullback_sequence=False,
        ),
    )

    assert actual_sequence.iloc[-1] == ""
    assert full_window.iloc[-1] == "CALL"


def test_pullback_slope_can_allow_flat_ema50():
    frame = pullback_frame("CALL")
    frame.loc[frame.index[-1], "ema20"] = 104.0

    flat_allowed = pullback_reversal_directions(
        frame,
        PullbackReversalConfig(
            enabled=True,
            require_ema_slope=True,
            allow_flat_ema50=True,
        ),
    )
    strict_slope = pullback_reversal_directions(
        frame,
        PullbackReversalConfig(
            enabled=True,
            require_ema_slope=True,
            allow_flat_ema50=False,
        ),
    )

    assert flat_allowed.iloc[-1] == "CALL"
    assert strict_slope.iloc[-1] == ""


def test_matrix_contains_all_24_requested_scenarios():
    values = scenarios()

    assert len(values) == 24
    assert len({item.name for item in values}) == 24
    assert {item.group for item in values} == set(range(1, 11))


@pytest.mark.parametrize(
    "retention,expected",
    [(0.40, 108), (0.45, 109), (0.50, 110), (0.55, 111), (0.60, 112)],
)
def test_z_protection_activates_at_twenty_percent_and_ratchets(retention, expected):
    scenario = Scenario("Z", 4, "EMA", "Z", retention, 20)

    assert protected_floor(100, 119.99, scenario) is None
    assert protected_floor(100, 120, scenario) == pytest.approx(expected)
    assert protected_floor(100, 140, scenario) == pytest.approx(100 + 40 * retention)


@pytest.mark.parametrize(
    "activation,protected,expected",
    [(10.0, 0.0, 100.0), (15.0, 5.0, 105.0), (20.0, 10.0, 110.0)],
)
def test_fixed_profit_floor_activates_at_peak_and_keeps_fixed_level(
    activation,
    protected,
    expected,
):
    scenario = Scenario(
        "FIXED",
        1,
        "EMA",
        protection="FIXED",
        activation_percent=activation,
        fixed_protected_profit_percent=protected,
    )

    assert protected_floor(100, 100 + activation - 0.01, scenario) is None
    assert protected_floor(100, 100 + activation, scenario) == pytest.approx(expected)
    assert protected_floor(100, 200, scenario) == pytest.approx(expected)


def test_momentum_breakout_requires_range_break_volume_and_trend_quality():
    index = pd.date_range("2026-09-01T00:00:00Z", periods=7, freq="5min")
    frame = pd.DataFrame(
        {
            "high": [101, 102, 103, 104, 105, 106, 109],
            "low": [99, 100, 101, 102, 103, 104, 106],
            "close": [100, 101, 102, 103, 104, 105, 108],
            "volume": [100, 100, 100, 100, 100, 100, 150],
            "volume_median20_prior": [100] * 7,
            "vwap": [100] * 7,
            "ema9": [101, 102, 103, 104, 105, 106, 107],
            "ema50": [100] * 7,
            "atr14": [10] * 7,
            "direction": ["CALL"] * 7,
        },
        index=index,
    )

    result = momentum_breakout_directions(
        frame,
        MomentumBreakoutConfig(
            enabled=True,
            lookback_candles=6,
            min_volume_ratio=1.25,
            min_vwap_displacement_atr=0.5,
            max_ema_strength_atr=0.75,
        ),
    )

    assert result.iloc[-1] == "CALL"


def test_activation_study_varies_activation_and_keeps_z55_fixed():
    values = activation_scenarios()

    assert [item.activation_percent for item in values] == [10, 15, 20, 25, 30]
    assert {item.retention for item in values} == {0.55}
    assert {item.exit_mode for item in values} == {"EMA_VWAP"}


def test_stop_loss_study_uses_bt2_with_fixed_option_point_stops():
    values = stop_loss_scenarios()

    assert [item.stop_loss_points for item in values] == [100, 150, 200]
    assert {item.exit_mode for item in values} == {"EMA_VWAP"}
    assert {item.protection for item in values} == {"NONE"}


def test_confirmation_study_waits_one_to_four_candles():
    values = confirmation_scenarios()

    assert [item.confirmation_candles for item in values] == [1, 2, 3, 4]
    assert {item.exit_mode for item in values} == {"EMA_VWAP"}


def test_macd_study_preserves_three_exit_families():
    values = macd_scenarios()

    assert [item.exit_mode for item in values] == ["EMA", "EMA_VWAP", "EMA_VWAP_RSI"]
    assert all(item.require_macd for item in values)


def test_entry_condition_count_study_crosses_three_thresholds_with_three_exits():
    values = entry_condition_count_scenarios()

    assert len(values) == 9
    assert {item.entry_min_conditions for item in values} == {1, 2, 3}
    assert {item.exit_mode for item in values} == {"EMA", "EMA_VWAP", "EMA_VWAP_RSI"}


def test_one_of_three_entry_skips_tied_direction_scores():
    index = pd.date_range(
        datetime.fromtimestamp(BASE_NS / 1e9, UTC),
        periods=2,
        freq="5min",
    )
    frame = pd.DataFrame({
        "close": [101, 102],
        "vwap": [100, 100],
        "ema9": [99, 103],
        "ema20": [100, 102],
        "ema50": [101, 101],
        "rsi14": [45, 60],
        "direction": ["", "CALL"],
        "entry_signal": [False, True],
    }, index=index)

    events = signal_events(
        frame,
        [option()],
        BASE_NS,
        BASE_NS + 60 * MINUTE_NS,
        entry_min_conditions=1,
    )

    assert len(events) == 1
    assert events[0].direction == "CALL"
    assert events[0].timestamp_ns == BASE_NS + 5 * MINUTE_NS


def test_one_trade_per_ema_regime_study_has_control_and_gated_bt2():
    values = one_trade_per_ema_regime_scenarios()

    assert [item.name for item in values] == [
        "BT2_EMA_VWAP_CONTROL",
        "BT2_EMA_VWAP_ONE_PER_EMA_REGIME",
    ]
    assert not values[0].one_trade_per_ema_regime
    assert values[1].one_trade_per_ema_regime
    assert {item.exit_mode for item in values} == {"EMA_VWAP"}


def test_signal_events_assign_same_id_inside_continuous_ema_regime():
    index = pd.date_range(
        datetime.fromtimestamp(BASE_NS / 1e9, UTC),
        periods=3,
        freq="5min",
    )
    frame = pd.DataFrame({
        "close": [101, 99, 102],
        "vwap": [100, 100, 100],
        "ema9": [103, 103, 103],
        "ema20": [102, 102, 102],
        "ema50": [101, 101, 101],
        "rsi14": [60, 60, 60],
        "direction": ["CALL", "", "CALL"],
        "entry_signal": [True, False, True],
    }, index=index)

    events = signal_events(
        frame,
        [option()],
        BASE_NS,
        BASE_NS + 60 * MINUTE_NS,
    )

    assert len(events) == 2
    assert events[0].ema_regime_start_ns == BASE_NS
    assert events[1].ema_regime_start_ns == BASE_NS


def test_ema_strength_scenarios_keep_bt2_and_one_trade_per_regime():
    values = ema_strength_scenarios()

    assert [item.min_ema_strength_atr for item in values] == [0, 0.25, 0.50, 0.75, 1.0]
    assert all(item.exit_mode == "EMA_VWAP" for item in values)
    assert all(item.one_trade_per_ema_regime for item in values)


def test_ema_strength_uses_completed_signal_candle_ema_gap_over_atr():
    frame = pd.DataFrame(
        [{"ema9": 103.0, "ema50": 100.0, "atr14": 4.0}],
        index=pd.DatetimeIndex([pd.Timestamp(BASE_NS, unit="ns", tz="UTC")]),
    )
    event = SignalEvent(BASE_NS, "CALL", 100.0, option(), [])

    assert _ema_strength_atr(frame, event) == pytest.approx(0.75)


def test_vwap_volume_study_uses_only_the_two_predeclared_thresholds():
    values = vwap_volume_scenarios()

    assert len(values) == 4
    assert [item.min_vwap_displacement_atr for item in values] == [0, 1.5, 0, 1.5]
    assert [item.min_signal_volume_ratio for item in values] == [0, 0, 1.25, 1.25]
    assert all(item.exit_mode == "EMA_VWAP" for item in values)
    assert all(item.one_trade_per_ema_regime for item in values)


def test_signal_entry_features_use_completed_candle_values():
    frame = pd.DataFrame(
        [{
            "close": 106.0,
            "vwap": 100.0,
            "atr14": 4.0,
            "volume": 125.0,
            "volume_median20_prior": 100.0,
        }],
        index=pd.DatetimeIndex([pd.Timestamp(BASE_NS, unit="ns", tz="UTC")]),
    )
    event = SignalEvent(BASE_NS, "CALL", 106.0, option(), [])

    assert _signal_entry_features(frame, event) == pytest.approx((1.5, 1.25))


def test_trade_rejects_option_beyond_scenario_expiry_limit():
    selected_option = option()
    event = SignalEvent(
        BASE_NS,
        "CALL",
        80000.0,
        selected_option,
        [{
            "timestamp_ns": BASE_NS + MINUTE_NS,
            "bid": 99.0,
            "ask": 100.0,
            "volume": 1000.0,
            "open_interest": 1000.0,
        }],
    )
    frame = pd.DataFrame()
    scenario = Scenario(
        "DTE_LIMIT",
        2,
        "EMA_VWAP",
        max_days_to_expiry=1.5,
    )

    trade, rejection = simulate_trade(
        event,
        frame,
        scenario,
        premium_budget_usd=100.0,
        hard_stop_percent=-15.0,
        max_hold_minutes=60,
        max_spread_percent=3.0,
        min_volume=30.0,
        volume_quantity_multiplier=5.0,
    )

    assert trade is None
    assert rejection == "OPTION_EXPIRY_TOO_FAR"


def test_option_selection_can_include_same_day_expiry_when_configured():
    same_day = replace(
        option(),
        symbol="BTC80000010926CE",
        expiration_ns=BASE_NS + 12 * 60 * MINUTE_NS,
    )

    assert _select_option([same_day], BASE_NS, "CALL", 80000.0) is None
    assert _select_option(
        [same_day],
        BASE_NS,
        "CALL",
        80000.0,
        min_days_to_expiry=0.0,
        max_days_to_expiry=1.5,
    ) == same_day


def test_option_selection_can_exclude_exact_minimum_expiry_boundary():
    exact_boundary = replace(
        option(),
        expiration_ns=BASE_NS + 36 * 60 * MINUTE_NS,
    )

    assert _select_option(
        [exact_boundary],
        BASE_NS,
        "CALL",
        80000.0,
        min_days_to_expiry=1.5,
        min_days_to_expiry_inclusive=False,
        max_days_to_expiry=3.0,
    ) is None


def test_macd_entry_requires_directional_confirmation():
    index = pd.date_range(
        datetime.fromtimestamp(BASE_NS / 1e9, UTC),
        periods=4,
        freq="5min",
    )
    frame = pd.DataFrame({
        "close": [80000, 80100, 80200, 80300],
        "direction": ["CALL", "CALL", "CALL", "CALL"],
        "entry_signal": [True, False, False, False],
        "direction_macd": ["", "", "CALL", "CALL"],
        "entry_signal_macd": [False, False, True, False],
    }, index=index)

    events = signal_events(
        frame,
        [option()],
        BASE_NS,
        BASE_NS + 60 * MINUTE_NS,
        require_macd=True,
    )

    assert len(events) == 1
    assert events[0].timestamp_ns == BASE_NS + 10 * MINUTE_NS


def test_utc_session_study_contains_original_and_macd_families():
    values = utc_session_scenarios()

    assert len(values) == 6
    assert sum(item.require_macd for item in values) == 3
    assert {item.exit_mode for item in values} == {"EMA", "EMA_VWAP", "EMA_VWAP_RSI"}
    assert {(item.entry_start_hour_utc, item.entry_end_hour_utc) for item in values} == {
        (0, 16)
    }


def test_utc_entry_session_allows_before_16_and_blocks_16_onward():
    index = pd.DatetimeIndex([
        pd.Timestamp("2026-09-01T15:55:00Z"),
        pd.Timestamp("2026-09-01T16:00:00Z"),
    ])
    frame = pd.DataFrame({
        "close": [80000, 80100],
        "direction": ["CALL", "PUT"],
        "entry_signal": [True, True],
    }, index=index)

    events = signal_events(
        frame,
        [option()],
        int(pd.Timestamp("2026-09-01T00:00:00Z").timestamp() * 1_000_000_000),
        int(pd.Timestamp("2026-09-02T00:00:00Z").timestamp() * 1_000_000_000),
        entry_start_hour_utc=0,
        entry_end_hour_utc=16,
    )

    assert [event.direction for event in events] == ["CALL"]


def test_utc_entry_session_checks_actual_fill_time():
    event = SignalEvent(
        BASE_NS + (15 * 60 + 55) * MINUTE_NS,
        "CALL",
        80000,
        option(),
        [{
            "timestamp_ns": BASE_NS + 16 * 60 * MINUTE_NS,
            "bid": 99,
            "ask": 100,
            "volume": 1000,
            "open_interest": 10,
        }],
    )
    scenario = Scenario(
        "BT1_EMA_UTC00_16",
        1,
        "EMA",
        entry_start_hour_utc=0,
        entry_end_hour_utc=16,
    )

    trade, rejection = simulate_trade(
        event,
        pd.DataFrame(),
        scenario,
        premium_budget_usd=6.67,
        hard_stop_percent=-15,
        max_hold_minutes=60,
        max_spread_percent=3,
        min_volume=30,
        volume_quantity_multiplier=5,
    )

    assert trade is None
    assert rejection == "OUTSIDE_ENTRY_SESSION"


def test_no_max_hold_uses_last_available_pre_expiry_quote():
    event = SignalEvent(
        BASE_NS,
        "CALL",
        80000,
        option(),
        [
            {
                "timestamp_ns": BASE_NS + MINUTE_NS,
                "bid": 99,
                "ask": 100,
                "volume": 1000,
                "open_interest": 10,
            },
            {
                "timestamp_ns": BASE_NS + 121 * MINUTE_NS,
                "bid": 110,
                "ask": 111,
                "volume": 1000,
                "open_interest": 10,
            },
        ],
    )
    frame = pd.DataFrame(
        {"close": pd.Series(dtype=float)},
        index=pd.DatetimeIndex([], tz="UTC"),
    )

    trade, rejection = simulate_trade(
        event,
        frame,
        Scenario("NO_MAX_HOLD", 1, "EMA"),
        premium_budget_usd=6.67,
        hard_stop_percent=-15,
        max_hold_minutes=None,
        max_spread_percent=3,
        min_volume=30,
        volume_quantity_multiplier=5,
    )

    assert rejection is None
    assert trade is not None
    assert trade["exit_reason"] == "OPTION_EXPIRY_OR_DATA_END"
    assert trade["holding_minutes"] == pytest.approx(120)


def test_expiry_exit_closes_at_configured_days_remaining_without_max_hold():
    event = SignalEvent(
        BASE_NS,
        "CALL",
        80000,
        option(),
        [
            {
                "timestamp_ns": BASE_NS + MINUTE_NS,
                "bid": 99,
                "ask": 100,
                "volume": 1000,
                "open_interest": 10,
            },
            {
                "timestamp_ns": BASE_NS + 12 * 60 * MINUTE_NS,
                "bid": 110,
                "ask": 111,
                "volume": 1000,
                "open_interest": 10,
            },
        ],
    )
    frame = pd.DataFrame(
        {"close": pd.Series(dtype=float)},
        index=pd.DatetimeIndex([], tz="UTC"),
    )

    trade, rejection = simulate_trade(
        event,
        frame,
        Scenario("DTE_EXIT", 1, "EMA"),
        premium_budget_usd=6.67,
        hard_stop_percent=-15,
        max_hold_minutes=None,
        exit_days_to_expiry=1.5,
        max_spread_percent=3,
        min_volume=30,
        volume_quantity_multiplier=5,
    )

    assert rejection is None
    assert trade is not None
    assert trade["exit_reason"] == "DTE_EXIT"
    assert trade["holding_minutes"] == pytest.approx(12 * 60 - 1)


def test_ist_windows_allow_weekday_and_block_end_boundary_and_weekend():
    windows = ((13 * 60 + 30, 17 * 60),)
    blocked = (5, 6)

    assert _entry_time_allowed(
        pd.Timestamp("2026-09-01T08:00:00Z"),
        entry_windows_ist_minutes=windows,
        blocked_weekdays_ist=blocked,
    )
    assert not _entry_time_allowed(
        pd.Timestamp("2026-09-01T11:30:00Z"),
        entry_windows_ist_minutes=windows,
        blocked_weekdays_ist=blocked,
    )
    assert not _entry_time_allowed(
        pd.Timestamp("2026-09-05T08:00:00Z"),
        entry_windows_ist_minutes=windows,
        blocked_weekdays_ist=blocked,
    )


def test_ist_entry_window_checks_actual_fill_time():
    signal = pd.Timestamp("2026-09-01T11:25:00Z")
    fill = pd.Timestamp("2026-09-01T11:30:00Z")
    event = SignalEvent(
        int(signal.timestamp() * 1_000_000_000),
        "CALL",
        80000,
        option(),
        [{
            "timestamp_ns": int(fill.timestamp() * 1_000_000_000),
            "bid": 99,
            "ask": 100,
            "volume": 1000,
            "open_interest": 10,
        }],
    )
    scenario = Scenario(
        "BT1_EMA_IST",
        1,
        "EMA",
        entry_windows_ist_minutes=((13 * 60 + 30, 17 * 60),),
        blocked_weekdays_ist=(5, 6),
    )

    trade, rejection = simulate_trade(
        event,
        pd.DataFrame(),
        scenario,
        premium_budget_usd=6.67,
        hard_stop_percent=-15,
        max_hold_minutes=60,
        max_spread_percent=3,
        min_volume=30,
        volume_quantity_multiplier=5,
    )

    assert trade is None
    assert rejection == "OUTSIDE_ENTRY_SESSION"


def test_all_fail_exit_study_contains_six_current_variants():
    values = all_fail_exit_scenarios()

    assert len(values) == 6
    assert sum(item.require_macd for item in values) == 3
    assert all(item.exit_when_all_fail for item in values)
    assert {(item.entry_start_hour_utc, item.entry_end_hour_utc) for item in values} == {
        (0, 16)
    }


def test_bt2_all_fail_exit_requires_ema_and_vwap_to_fail_together():
    scenario = Scenario(
        "BT2_ALLFAIL",
        2,
        "EMA_VWAP",
        exit_when_all_fail=True,
    )
    ema_only_failure = pd.Series({
        "close": 105,
        "vwap": 100,
        "ema9": 99,
        "ema20": 100,
        "ema50": 101,
        "rsi14": 60,
    })
    both_fail = ema_only_failure.copy()
    both_fail["close"] = 95

    assert not _exit_triggered(ema_only_failure, "CALL", scenario)
    assert _exit_triggered(both_fail, "CALL", scenario)


def test_bt3_all_fail_exit_requires_ema_vwap_and_rsi_to_fail_together():
    scenario = Scenario(
        "BT3_ALLFAIL",
        3,
        "EMA_VWAP_RSI",
        exit_when_all_fail=True,
    )
    two_fail = pd.Series({
        "close": 95,
        "vwap": 100,
        "ema9": 99,
        "ema20": 100,
        "ema50": 101,
        "rsi14": 60,
    })
    all_fail = two_fail.copy()
    all_fail["rsi14"] = 45

    assert not _exit_triggered(two_fail, "CALL", scenario)
    assert _exit_triggered(all_fail, "CALL", scenario)


def test_all_fail_z50_activates_at_fifty_and_protects_half_peak_profit():
    values = all_fail_z50_scenarios()

    assert len(values) == 6
    assert sum(item.require_macd for item in values) == 3
    assert all(item.exit_when_all_fail for item in values)
    assert {item.protection for item in values} == {"Z"}
    assert {item.activation_percent for item in values} == {50.0}
    assert {item.retention for item in values} == {0.50}
    assert protected_floor(100, 149.99, values[0]) is None
    assert protected_floor(100, 150.0, values[0]) == pytest.approx(125.0)


def test_all_fail_atr_study_uses_atr14_times_two_for_six_variants():
    values = all_fail_atr_scenarios()

    assert len(values) == 6
    assert sum(item.require_macd for item in values) == 3
    assert all(item.exit_when_all_fail for item in values)
    assert {item.atr_trailing_multiplier for item in values} == {2.0}
    assert {(item.entry_start_hour_utc, item.entry_end_hour_utc) for item in values} == {
        (0, 16)
    }


def test_atr_wilder_uses_true_range_and_fourteen_bar_warmup():
    highs = [11.0] * 14
    lows = [9.0] * 14
    closes = [10.0] * 14

    values = atr_wilder(highs, lows, closes, 14)

    assert all(pd.isna(value) for value in values[:13])
    assert values[13] == pytest.approx(2.0)


def test_atr_trailing_exit_uses_completed_underlying_candle():
    event = SignalEvent(
        BASE_NS,
        "CALL",
        100,
        option(),
        [
            {
                "timestamp_ns": BASE_NS + MINUTE_NS,
                "bid": 99,
                "ask": 100,
                "volume": 1000,
                "open_interest": 10,
            },
            {
                "timestamp_ns": BASE_NS + 6 * MINUTE_NS,
                "bid": 105,
                "ask": 106,
                "volume": 1000,
                "open_interest": 10,
            },
        ],
    )
    frame = pd.DataFrame(
        [{
            "open": 100,
            "high": 110,
            "low": 101,
            "close": 103,
            "vwap": 100,
            "ema9": 105,
            "ema20": 104,
            "ema50": 102,
            "rsi14": 60,
            "atr14": 3,
        }],
        index=pd.DatetimeIndex([
            datetime.fromtimestamp((BASE_NS + 5 * MINUTE_NS) / 1e9, UTC)
        ]),
    )
    scenario = Scenario(
        "BT1_ATR",
        1,
        "EMA",
        exit_when_all_fail=True,
        atr_trailing_multiplier=2.0,
    )

    trade, rejection = simulate_trade(
        event,
        frame,
        scenario,
        premium_budget_usd=6.67,
        hard_stop_percent=-15,
        max_hold_minutes=60,
        max_spread_percent=3,
        min_volume=30,
        volume_quantity_multiplier=5,
    )

    assert rejection is None
    assert trade is not None
    assert trade["exit_reason"] == "ATR_TRAILING_STOP"


def test_atr_sensitivity_covers_two_and_half_and_three_multipliers():
    values = all_fail_atr_sensitivity_scenarios()

    assert len(values) == 12
    assert {item.atr_trailing_multiplier for item in values} == {2.5, 3.0}
    assert sum(item.require_macd for item in values) == 6
    assert all(item.exit_when_all_fail for item in values)


def test_macd_reversal_exit_study_contains_six_all_fail_variants():
    values = all_fail_macd_exit_scenarios()

    assert len(values) == 6
    assert sum(item.require_macd for item in values) == 3
    assert all(item.macd_reversal_exit for item in values)
    assert all(item.exit_when_all_fail for item in values)


def test_macd_exit_policy_study_contains_eighteen_variants():
    values = macd_exit_policy_scenarios()

    assert len(values) == 18
    assert len({item.name for item in values}) == 18
    assert sum(item.require_macd for item in values) == 9
    assert {item.macd_exit_policy for item in values} == {
        "REVERSAL_ONLY",
        "IN_ALL_FAIL",
        "CONFIRMED_REVERSAL_ONLY",
    }
    assert sum(item.exit_when_all_fail for item in values) == 6


def test_locked_h6_study_covers_both_locked_exit_policies():
    values = locked_h6_scenarios()

    assert len(values) == 12
    assert len({item.name for item in values}) == 12
    assert sum(item.require_macd for item in values) == 6
    assert all(item.min_option_true_ranges == 6 for item in values)
    assert sum(item.macd_reversal_exit for item in values) == 6
    assert sum(item.macd_exit_policy == "REVERSAL_ONLY" for item in values) == 6


@pytest.mark.parametrize("multiplier", [1.25, 1.50, 2.00])
def test_locked_h6_fee_aware_studies_preserve_h6(multiplier):
    values = locked_h6_fa_scenarios(multiplier)

    assert len(values) == 12
    assert all(item.min_option_true_ranges == 6 for item in values)
    assert all(item.fee_aware_multiplier == multiplier for item in values)


def test_locked_m30_study_uses_selected_fa150_threshold():
    values = locked_h6_fa150_m30_scenarios()

    assert len(values) == 12
    assert all(item.min_option_true_ranges == 6 for item in values)
    assert all(item.fee_aware_multiplier == 1.50 for item in values)
    assert all(item.directional_confirmation_minutes == 30 for item in values)


def test_locked_m30_stoch_study_adds_only_requested_entry_gate():
    values = locked_h6_fa150_m30_stoch_scenarios()

    assert len(values) == 1
    scenario = values[0]
    assert scenario.name == "BT1_EMA_MACD_MACDREV_ONLY_H6_FA150_M30_STOCH_UTC00_16"
    assert scenario.require_macd is True
    assert scenario.require_stoch_rsi_entry is True
    assert scenario.macd_exit_policy == "REVERSAL_ONLY"
    assert scenario.min_option_true_ranges == 6
    assert scenario.fee_aware_multiplier == pytest.approx(1.5)
    assert scenario.directional_confirmation_minutes == 30


def test_plain_stoch_study_contains_only_bt1_bt2_bt3_and_stoch_gate():
    values = stoch_scenarios()

    assert [scenario.name for scenario in values] == [
        "BT1_EMA_STOCH",
        "BT2_EMA_VWAP_STOCH",
        "BT3_EMA_VWAP_RSI_STOCH",
    ]
    assert [scenario.exit_mode for scenario in values] == [
        "EMA",
        "EMA_VWAP",
        "EMA_VWAP_RSI",
    ]
    assert all(scenario.require_stoch_rsi_entry for scenario in values)
    assert all(not scenario.require_macd for scenario in values)
    assert all(scenario.min_option_true_ranges == 0 for scenario in values)
    assert all(scenario.fee_aware_multiplier == 0.0 for scenario in values)
    assert all(scenario.directional_confirmation_minutes == 0 for scenario in values)


@pytest.mark.parametrize(
    "direction,k_value,d_value,expected",
    [
        ("CALL", 35.0, 45.0, "CALL"),
        ("CALL", 45.0, 35.0, ""),
        ("PUT", 65.0, 55.0, "PUT"),
        ("PUT", 55.0, 65.0, ""),
        ("CALL", float("nan"), 45.0, ""),
    ],
)
def test_stoch_rsi_entry_direction_uses_requested_pullback_relationship(
    direction,
    k_value,
    d_value,
    expected,
):
    assert _stoch_rsi_entry_direction(direction, k_value, d_value) == expected


@pytest.mark.parametrize(
    "direction,k_value,d_value,expected",
    [
        ("CALL", 45.0, 35.0, "CALL"),
        ("CALL", 35.0, 45.0, ""),
        ("PUT", 55.0, 65.0, "PUT"),
        ("PUT", 65.0, 55.0, ""),
        ("PUT", 55.0, float("nan"), ""),
    ],
)
def test_stoch_rsi_momentum_entry_direction_uses_requested_relationship(
    direction,
    k_value,
    d_value,
    expected,
):
    assert _stoch_rsi_momentum_entry_direction(direction, k_value, d_value) == expected


def test_stoch_momentum_is_a_gate_on_original_signal_not_a_new_trigger():
    index = pd.date_range(
        datetime.fromtimestamp(BASE_NS / 1e9, UTC),
        periods=3,
        freq="5min",
    )
    frame = pd.DataFrame({
        "close": [80000, 80100, 80200],
        "direction": ["CALL", "CALL", "CALL"],
        "entry_signal": [True, False, False],
        "stoch_rsi_k": [35.0, 45.0, 55.0],
        "stoch_rsi_d": [45.0, 35.0, 40.0],
    }, index=index)

    events = signal_events(
        frame,
        [option()],
        BASE_NS,
        BASE_NS + 60 * MINUTE_NS,
        require_stoch_rsi_momentum_entry=True,
    )

    assert events == []


def test_stoch_momentum_accepts_original_signal_when_relationship_matches():
    index = pd.DatetimeIndex([pd.Timestamp(BASE_NS, unit="ns", tz="UTC")])
    frame = pd.DataFrame({
        "close": [80000],
        "direction": ["CALL"],
        "entry_signal": [True],
        "stoch_rsi_k": [45.0],
        "stoch_rsi_d": [35.0],
    }, index=index)

    events = signal_events(
        frame,
        [option()],
        BASE_NS,
        BASE_NS + 60 * MINUTE_NS,
        require_stoch_rsi_momentum_entry=True,
    )

    assert len(events) == 1
    assert events[0].direction == "CALL"


def test_plain_momentum_stoch_study_changes_only_entry_gate():
    values = stoch_momentum_scenarios()

    assert [scenario.name for scenario in values] == [
        "BT1_EMA_STOCH_KGT_D",
        "BT2_EMA_VWAP_STOCH_KGT_D",
        "BT3_EMA_VWAP_RSI_STOCH_KGT_D",
    ]
    assert all(scenario.require_stoch_rsi_momentum_entry for scenario in values)
    assert all(not scenario.require_stoch_rsi_entry for scenario in values)
    assert all(not scenario.exit_when_all_fail for scenario in values)


def test_locked_m30_only_study_has_no_h6_or_fee_filter():
    values = locked_m30_scenarios()

    assert len(values) == 12
    assert all(item.min_option_true_ranges == 0 for item in values)
    assert all(item.fee_aware_multiplier == 0.0 for item in values)
    assert all(item.directional_confirmation_minutes == 30 for item in values)


def test_locked_fa150_loss_window_study_starts_at_08_utc():
    values = locked_h6_fa150_utc08_scenarios()

    assert len(values) == 12
    assert all(item.entry_start_hour_utc == 8 for item in values)
    assert all(item.entry_end_hour_utc == 16 for item in values)
    assert all(item.min_option_true_ranges == 6 for item in values)
    assert all(item.fee_aware_multiplier == 1.50 for item in values)


@pytest.mark.parametrize(
    "direction,closes,expected",
    [
        ("CALL", [100, 99, 101, 102, 103, 104, 105], True),
        ("CALL", [100, 101, 102, 103, 102, 101, 99], False),
        ("PUT", [100, 101, 99, 98, 97, 96, 95], True),
        ("PUT", [100, 99, 98, 97, 98, 99, 101], False),
    ],
)
def test_m30_checks_direction_over_six_completed_five_minute_bars(
    direction,
    closes,
    expected,
):
    index = pd.date_range(
        datetime.fromtimestamp((BASE_NS - 30 * MINUTE_NS) / 1e9, UTC),
        periods=7,
        freq="5min",
    )
    frame = pd.DataFrame({"close": closes}, index=index)
    event = SignalEvent(BASE_NS, direction, closes[-1], option(), [])

    assert _directional_confirmation_valid(frame, event, 30) is expected


def test_option_h6_uses_six_true_ranges_from_seven_completed_candles():
    rows = []
    for index in range(7):
        timestamp = BASE_NS // 1_000_000_000 - (35 - index * 5) * 60
        price = 100.0 + index
        rows.append({
            "time": timestamp,
            "open": price,
            "high": price + 1.0,
            "low": price - 1.0,
            "close": price,
            "volume": 1,
        })

    observations = option_true_range_observations(rows)

    assert [value for _, value in observations] == [2.0] * 6


def test_h6_rejects_entry_with_fewer_than_six_true_ranges():
    event = SignalEvent(
        BASE_NS,
        "CALL",
        100,
        option(),
        [{
            "timestamp_ns": BASE_NS + MINUTE_NS,
            "bid": 99,
            "ask": 100,
            "volume": 1000,
            "open_interest": 10,
        }],
        option_true_ranges=[1.0] * 5,
    )
    scenario = Scenario("H6", 1, "EMA", min_option_true_ranges=6)

    trade, rejection = simulate_trade(
        event,
        pd.DataFrame(),
        scenario,
        premium_budget_usd=6.67,
        hard_stop_percent=-15,
        max_hold_minutes=60,
        max_spread_percent=3,
        min_volume=30,
        volume_quantity_multiplier=5,
    )

    assert trade is None
    assert rejection == "OPTION_HISTORY_TOO_SHORT"


def test_fa125_rejects_when_option_movement_is_too_small_for_fees():
    event = SignalEvent(
        BASE_NS,
        "CALL",
        100,
        option(),
        [{
            "timestamp_ns": BASE_NS + MINUTE_NS,
            "bid": 99,
            "ask": 100,
            "volume": 1000,
            "open_interest": 10,
        }],
        option_true_ranges=[0.01] * 6,
    )
    scenario = Scenario(
        "H6_FA125",
        1,
        "EMA",
        min_option_true_ranges=6,
        fee_aware_multiplier=1.25,
    )

    trade, rejection = simulate_trade(
        event,
        pd.DataFrame(),
        scenario,
        premium_budget_usd=6.67,
        hard_stop_percent=-15,
        max_hold_minutes=60,
        max_spread_percent=3,
        min_volume=30,
        volume_quantity_multiplier=5,
    )

    assert trade is None
    assert rejection == "FEE_AWARE_MOVE_TOO_LOW"


def test_call_exits_on_fresh_bearish_macd_crossover():
    event = SignalEvent(
        BASE_NS,
        "CALL",
        100,
        option(),
        [
            {
                "timestamp_ns": BASE_NS + MINUTE_NS,
                "bid": 99,
                "ask": 100,
                "volume": 1000,
                "open_interest": 10,
            },
            {
                "timestamp_ns": BASE_NS + 6 * MINUTE_NS,
                "bid": 105,
                "ask": 106,
                "volume": 1000,
                "open_interest": 10,
            },
        ],
    )
    frame = pd.DataFrame(
        [
            {
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "vwap": 99,
                "ema9": 103,
                "ema20": 102,
                "ema50": 101,
                "rsi14": 60,
                "macd": 2,
                "macd_signal": 1,
                "atr14": 2,
            },
            {
                "open": 100,
                "high": 104,
                "low": 99,
                "close": 103,
                "vwap": 100,
                "ema9": 106,
                "ema20": 104,
                "ema50": 102,
                "rsi14": 60,
                "macd": 0.5,
                "macd_signal": 1,
                "atr14": 2,
            },
        ],
        index=pd.DatetimeIndex([
            datetime.fromtimestamp(BASE_NS / 1e9, UTC),
            datetime.fromtimestamp((BASE_NS + 5 * MINUTE_NS) / 1e9, UTC),
        ]),
    )
    scenario = Scenario(
        "BT1_MACD_EXIT",
        1,
        "EMA",
        exit_when_all_fail=True,
        macd_reversal_exit=True,
    )

    trade, rejection = simulate_trade(
        event,
        frame,
        scenario,
        premium_budget_usd=6.67,
        hard_stop_percent=-15,
        max_hold_minutes=60,
        max_spread_percent=3,
        min_volume=30,
        volume_quantity_multiplier=5,
    )

    assert rejection is None
    assert trade is not None
    assert trade["exit_reason"] == "MACD_REVERSAL_EXIT"


def test_macd_reversal_only_ignores_condition_failure():
    event = SignalEvent(
        BASE_NS,
        "CALL",
        100,
        option(),
        [
            {
                "timestamp_ns": BASE_NS + MINUTE_NS,
                "bid": 99,
                "ask": 100,
                "volume": 1000,
                "open_interest": 10,
            },
            {
                "timestamp_ns": BASE_NS + 6 * MINUTE_NS,
                "bid": 103,
                "ask": 104,
                "volume": 1000,
                "open_interest": 10,
            },
            {
                "timestamp_ns": BASE_NS + 12 * MINUTE_NS,
                "bid": 102,
                "ask": 103,
                "volume": 1000,
                "open_interest": 10,
            },
        ],
    )
    frame = pd.DataFrame(
        [
            {"close": 100, "vwap": 99, "ema9": 103, "ema20": 102, "ema50": 101, "rsi14": 60, "macd": 2, "macd_signal": 1, "high": 101, "low": 99},
            {"close": 99, "vwap": 100, "ema9": 99, "ema20": 100, "ema50": 101, "rsi14": 45, "macd": 1.5, "macd_signal": 1, "high": 100, "low": 98},
            {"close": 98, "vwap": 100, "ema9": 98, "ema20": 100, "ema50": 102, "rsi14": 44, "macd": 0.5, "macd_signal": 1, "high": 99, "low": 97},
        ],
        index=pd.date_range(datetime.fromtimestamp(BASE_NS / 1e9, UTC), periods=3, freq="5min"),
    )
    scenario = Scenario(
        "MACD_ONLY",
        1,
        "EMA",
        macd_exit_policy="REVERSAL_ONLY",
    )

    trade, rejection = simulate_trade(
        event,
        frame,
        scenario,
        premium_budget_usd=6.67,
        hard_stop_percent=-15,
        max_hold_minutes=60,
        max_spread_percent=3,
        min_volume=30,
        volume_quantity_multiplier=5,
    )

    assert rejection is None
    assert trade is not None
    assert trade["exit_reason"] == "MACD_REVERSAL_EXIT"


def test_macd_in_all_fail_requires_macd_to_be_adverse():
    event = SignalEvent(
        BASE_NS,
        "CALL",
        100,
        option(),
        [
            {"timestamp_ns": BASE_NS + MINUTE_NS, "bid": 99, "ask": 100, "volume": 1000, "open_interest": 10},
            {"timestamp_ns": BASE_NS + 6 * MINUTE_NS, "bid": 103, "ask": 104, "volume": 1000, "open_interest": 10},
            {"timestamp_ns": BASE_NS + 11 * MINUTE_NS, "bid": 102, "ask": 103, "volume": 1000, "open_interest": 10},
        ],
    )
    frame = pd.DataFrame(
        [
            {"close": 100, "vwap": 99, "ema9": 103, "ema20": 102, "ema50": 101, "rsi14": 60, "macd": 2, "macd_signal": 1, "high": 101, "low": 99},
            {"close": 99, "vwap": 100, "ema9": 99, "ema20": 100, "ema50": 101, "rsi14": 45, "macd": 1.5, "macd_signal": 1, "high": 100, "low": 98},
            {"close": 98, "vwap": 100, "ema9": 98, "ema20": 100, "ema50": 102, "rsi14": 44, "macd": 0.5, "macd_signal": 1, "high": 99, "low": 97},
        ],
        index=pd.date_range(datetime.fromtimestamp(BASE_NS / 1e9, UTC), periods=3, freq="5min"),
    )
    scenario = Scenario(
        "MACD_IN_ALL_FAIL",
        1,
        "EMA",
        exit_when_all_fail=True,
        macd_exit_policy="IN_ALL_FAIL",
    )

    trade, rejection = simulate_trade(
        event,
        frame,
        scenario,
        premium_budget_usd=6.67,
        hard_stop_percent=-15,
        max_hold_minutes=60,
        max_spread_percent=3,
        min_volume=30,
        volume_quantity_multiplier=5,
    )

    assert rejection is None
    assert trade is not None
    assert trade["exit_reason"] == "CONDITION_EXIT"


def test_confirmed_macd_reversal_waits_one_completed_candle():
    event = SignalEvent(
        BASE_NS,
        "CALL",
        100,
        option(),
        [
            {"timestamp_ns": BASE_NS + MINUTE_NS, "bid": 99, "ask": 100, "volume": 1000, "open_interest": 10},
            {"timestamp_ns": BASE_NS + 6 * MINUTE_NS, "bid": 105, "ask": 106, "volume": 1000, "open_interest": 10},
            {"timestamp_ns": BASE_NS + 11 * MINUTE_NS, "bid": 104, "ask": 105, "volume": 1000, "open_interest": 10},
        ],
    )
    frame = pd.DataFrame(
        [
            {"close": 100, "vwap": 99, "ema9": 103, "ema20": 102, "ema50": 101, "rsi14": 60, "macd": 2, "macd_signal": 1, "high": 101, "low": 99},
            {"close": 103, "vwap": 100, "ema9": 106, "ema20": 104, "ema50": 102, "rsi14": 60, "macd": 0.5, "macd_signal": 1, "high": 104, "low": 99},
            {"close": 102, "vwap": 100, "ema9": 105, "ema20": 103, "ema50": 101, "rsi14": 58, "macd": 0.25, "macd_signal": 1, "high": 103, "low": 100},
        ],
        index=pd.date_range(datetime.fromtimestamp(BASE_NS / 1e9, UTC), periods=3, freq="5min"),
    )
    scenario = Scenario(
        "MACD_CONFIRM1",
        1,
        "EMA",
        macd_exit_policy="CONFIRMED_REVERSAL_ONLY",
    )

    trade, rejection = simulate_trade(
        event,
        frame,
        scenario,
        premium_budget_usd=6.67,
        hard_stop_percent=-15,
        max_hold_minutes=60,
        max_spread_percent=3,
        min_volume=30,
        volume_quantity_multiplier=5,
    )

    assert rejection is None
    assert trade is not None
    assert trade["exit_reason"] == "MACD_CONFIRMED_REVERSAL_EXIT"


def test_confirmation_cancels_when_full_signal_fails_during_wait():
    index = pd.date_range(
        datetime.fromtimestamp(BASE_NS / 1e9, UTC),
        periods=5,
        freq="5min",
    )
    frame = pd.DataFrame({
        "close": [80000, 80100, 80200, 80150, 80300],
        "direction": ["CALL", "CALL", "CALL", "", "CALL"],
        "entry_signal": [True, False, False, False, True],
    }, index=index)

    confirmed = signal_events(
        frame,
        [option()],
        BASE_NS,
        BASE_NS + 60 * MINUTE_NS,
        confirmation_candles=2,
    )
    cancelled = signal_events(
        frame,
        [option()],
        BASE_NS,
        BASE_NS + 60 * MINUTE_NS,
        confirmation_candles=3,
    )

    assert len(confirmed) == 1
    assert confirmed[0].timestamp_ns == BASE_NS + 10 * MINUTE_NS
    assert cancelled == []


def test_e90_and_e95_use_three_profit_tiers():
    e90 = Scenario("E90", 9, "EMA", "E", 0.90)
    e95 = Scenario("E95", 10, "EMA", "E", 0.95)

    assert protected_floor(100, 109.99, e90) is None
    assert protected_floor(100, 110, e90) == pytest.approx(100)
    assert protected_floor(100, 120, e90) == pytest.approx(110)
    assert protected_floor(100, 140, e90) == pytest.approx(136)
    assert protected_floor(100, 140, e95) == pytest.approx(138)


def test_option_fee_uses_notional_rate_then_adds_gst():
    base, gst, total = option_fee_components(
        spot=85000,
        premium=1000,
        quantity=10,
        contract_value=0.001,
    )

    assert base == pytest.approx(0.085)
    assert gst == pytest.approx(0.0153)
    assert total == pytest.approx(0.1003)


def test_option_fee_caps_base_fee_at_three_and_half_percent_of_premium():
    base, gst, total = option_fee_components(
        spot=85000,
        premium=10,
        quantity=10,
        contract_value=0.001,
    )

    assert base == pytest.approx(0.0035)
    assert gst == pytest.approx(0.00063)
    assert total == pytest.approx(0.00413)


def test_condition_modes_add_vwap_then_rsi():
    row = pd.Series({
        "close": 105,
        "vwap": 100,
        "ema9": 103,
        "ema20": 102,
        "ema50": 101,
        "rsi14": 75,
    })

    assert _condition_valid(row, "CALL", "EMA")
    assert _condition_valid(row, "CALL", "EMA_VWAP")
    assert not _condition_valid(row, "CALL", "EMA_VWAP_RSI")


def test_condition_exit_has_priority_over_protected_stop():
    event = SignalEvent(
        BASE_NS,
        "CALL",
        80000,
        option(),
        [
            {"timestamp_ns": BASE_NS + MINUTE_NS, "bid": 99, "ask": 100, "volume": 1000, "open_interest": 10},
            {"timestamp_ns": BASE_NS + 2 * MINUTE_NS, "bid": 120, "ask": 121, "volume": 1000, "open_interest": 10},
            {"timestamp_ns": BASE_NS + 6 * MINUTE_NS, "bid": 125, "ask": 126, "volume": 1000, "open_interest": 10},
        ],
    )
    frame = pd.DataFrame(
        [{"close": 100, "vwap": 101, "ema9": 99, "ema20": 100, "ema50": 101, "rsi14": 45}],
        index=pd.DatetimeIndex([
            datetime.fromtimestamp((BASE_NS + 5 * MINUTE_NS) / 1e9, UTC)
        ]),
    )
    scenario = Scenario("BT4_EMA_Z50", 4, "EMA", "Z", 0.50, 20)

    trade, rejection = simulate_trade(
        event,
        frame,
        scenario,
        premium_budget_usd=6.67,
        hard_stop_percent=-15,
        max_hold_minutes=60,
        max_spread_percent=3,
        min_volume=30,
        volume_quantity_multiplier=5,
    )

    assert rejection is None
    assert trade is not None
    assert trade["exit_reason"] == "CONDITION_EXIT"
    assert trade["exit_bid"] == 125


def test_relaxed_ema_exit_ignores_fast_mid_cross_for_call_and_put():
    call_crossed = pd.Series({"ema9": 105, "ema20": 110, "ema50": 100})
    put_crossed = pd.Series({"ema9": 95, "ema20": 90, "ema50": 100})

    assert not _ema_exit_valid(call_crossed, "CALL", "STRICT_ORDER")
    assert _ema_exit_valid(call_crossed, "CALL", "FAST_AND_MID_VS_SLOW")
    assert not _ema_exit_valid(put_crossed, "PUT", "STRICT_ORDER")
    assert _ema_exit_valid(put_crossed, "PUT", "FAST_AND_MID_VS_SLOW")


def test_relaxed_ema_exit_fails_when_either_fast_or_mid_crosses_ema50():
    call_failed = pd.Series({"ema9": 99, "ema20": 105, "ema50": 100})
    put_failed = pd.Series({"ema9": 101, "ema20": 95, "ema50": 100})

    assert not _ema_exit_valid(call_failed, "CALL", "FAST_AND_MID_VS_SLOW")
    assert not _ema_exit_valid(put_failed, "PUT", "FAST_AND_MID_VS_SLOW")


def test_or_ema_exit_remains_valid_until_both_cross_ema50():
    call_one_above = pd.Series({"ema9": 99, "ema20": 105, "ema50": 100})
    call_both_below = pd.Series({"ema9": 99, "ema20": 98, "ema50": 100})
    put_one_below = pd.Series({"ema9": 101, "ema20": 95, "ema50": 100})
    put_both_above = pd.Series({"ema9": 101, "ema20": 102, "ema50": 100})

    assert _ema_exit_valid(call_one_above, "CALL", "FAST_OR_MID_VS_SLOW")
    assert not _ema_exit_valid(call_both_below, "CALL", "FAST_OR_MID_VS_SLOW")
    assert _ema_exit_valid(put_one_below, "PUT", "FAST_OR_MID_VS_SLOW")
    assert not _ema_exit_valid(put_both_above, "PUT", "FAST_OR_MID_VS_SLOW")


def test_fixed_option_point_stop_replaces_percentage_stop():
    event = SignalEvent(
        BASE_NS,
        "CALL",
        80000,
        option(),
        [
            {"timestamp_ns": BASE_NS + MINUTE_NS, "bid": 499, "ask": 500, "volume": 1000, "open_interest": 10},
            {"timestamp_ns": BASE_NS + 2 * MINUTE_NS, "bid": 420, "ask": 421, "volume": 1000, "open_interest": 10},
            {"timestamp_ns": BASE_NS + 3 * MINUTE_NS, "bid": 390, "ask": 391, "volume": 1000, "open_interest": 10},
            {"timestamp_ns": BASE_NS + 4 * MINUTE_NS, "bid": 385, "ask": 386, "volume": 1000, "open_interest": 10},
        ],
    )
    frame = pd.DataFrame(
        [{"close": 80000, "vwap": 79000, "ema9": 80300, "ema20": 80200, "ema50": 80100, "rsi14": 60}],
        index=pd.DatetimeIndex([datetime.fromtimestamp(BASE_NS / 1e9, UTC)]),
    )
    scenario = Scenario("BT2_EMA_VWAP_SL100", 12, "EMA_VWAP", stop_loss_points=100)

    trade, rejection = simulate_trade(
        event,
        frame,
        scenario,
        premium_budget_usd=6.67,
        hard_stop_percent=-15,
        max_hold_minutes=60,
        max_spread_percent=3,
        min_volume=30,
        volume_quantity_multiplier=5,
    )

    assert rejection is None
    assert trade is not None
    assert trade["exit_reason"] == "HARD_STOP"
    assert trade["exit_bid"] == 385


def test_same_quote_hard_stop_exits_on_breach_quote():
    event = SignalEvent(
        BASE_NS,
        "CALL",
        80000,
        option(),
        [
            {
                "timestamp_ns": BASE_NS + MINUTE_NS,
                "bid": 99,
                "ask": 100,
                "volume": 1000,
                "open_interest": 10,
            },
            {
                "timestamp_ns": BASE_NS + 2 * MINUTE_NS,
                "bid": 84,
                "ask": 85,
                "volume": 1000,
                "open_interest": 10,
            },
            {
                "timestamp_ns": BASE_NS + 3 * MINUTE_NS,
                "bid": 75,
                "ask": 76,
                "volume": 1000,
                "open_interest": 10,
            },
        ],
    )
    scenario = Scenario(
        "BT2_STOP_M15_SAME",
        2,
        "EMA_VWAP",
        hard_stop_percent_override=-15.0,
        hard_stop_fill_mode="SAME_QUOTE",
    )

    trade, rejection = simulate_trade(
        event,
        pd.DataFrame(
            columns=["close"],
            index=pd.DatetimeIndex([], tz="UTC"),
        ),
        scenario,
        premium_budget_usd=6.67,
        hard_stop_percent=-10.0,
        max_hold_minutes=60,
        max_spread_percent=3,
        min_volume=30,
        volume_quantity_multiplier=5,
    )

    assert rejection is None
    assert trade is not None
    assert trade["exit_reason"] == "HARD_STOP"
    assert trade["exit_bid"] == 84
    assert trade["configured_hard_stop_percent"] == -15.0
    assert trade["hard_stop_fill_mode"] == "SAME_QUOTE"


def test_trade_rejects_overextended_ema_signal():
    event = SignalEvent(
        BASE_NS,
        "CALL",
        80000,
        option(),
        [
            {
                "timestamp_ns": BASE_NS + MINUTE_NS,
                "bid": 99,
                "ask": 100,
                "volume": 1000,
                "open_interest": 10,
            }
        ],
    )
    frame = pd.DataFrame(
        [
            {
                "close": 80000,
                "vwap": 79000,
                "ema9": 81000,
                "ema20": 80500,
                "ema50": 80000,
                "rsi14": 60,
                "atr14": 500,
                "volume": 100,
                "volume_median20_prior": 100,
            }
        ],
        index=pd.DatetimeIndex([pd.Timestamp(BASE_NS, unit="ns", tz="UTC")]),
    )

    trade, rejection = simulate_trade(
        event,
        frame,
        Scenario("MAX_EMA", 1, "EMA", max_ema_strength_atr=0.75),
        premium_budget_usd=6.67,
        hard_stop_percent=-15,
        max_hold_minutes=60,
        max_spread_percent=3,
        min_volume=30,
        volume_quantity_multiplier=5,
    )

    assert trade is None
    assert rejection == "EMA_STRENGTH_TOO_HIGH"


def test_early_failure_exits_on_next_quote_during_monitor_window():
    event = SignalEvent(
        BASE_NS,
        "CALL",
        100,
        option(),
        [
            {
                "timestamp_ns": BASE_NS + MINUTE_NS,
                "bid": 99,
                "ask": 100,
                "volume": 1000,
                "open_interest": 10,
            },
            {
                "timestamp_ns": BASE_NS + 6 * MINUTE_NS,
                "bid": 94,
                "ask": 95,
                "volume": 1000,
                "open_interest": 10,
            },
        ],
    )
    frame = pd.DataFrame(
        [
            {
                "open": 99,
                "high": 102,
                "low": 98,
                "close": 101,
                "vwap": 100,
                "ema9": 103,
                "ema20": 102,
                "ema50": 101,
                "rsi14": 60,
                "atr14": 2,
                "volume": 100,
                "volume_median20_prior": 100,
            },
            {
                "open": 101,
                "high": 102,
                "low": 96,
                "close": 97,
                "vwap": 100,
                "ema9": 102,
                "ema20": 101,
                "ema50": 100,
                "rsi14": 45,
                "atr14": 2,
                "volume": 100,
                "volume_median20_prior": 100,
            },
        ],
        index=pd.DatetimeIndex(
            [
                pd.Timestamp(BASE_NS, unit="ns", tz="UTC"),
                pd.Timestamp(BASE_NS + 5 * MINUTE_NS, unit="ns", tz="UTC"),
            ]
        ),
    )
    scenario = Scenario(
        "EARLY",
        1,
        "EMA",
        early_failure=EarlyFailureConfig(
            enabled=True,
            monitor_candles=2,
            condition_mode="ANY",
            exit_on_vwap_failure=True,
            exit_on_structure_break=False,
            exit_on_ema9_ema20_cross=False,
        ),
    )

    trade, rejection = simulate_trade(
        event,
        frame,
        scenario,
        premium_budget_usd=6.67,
        hard_stop_percent=-15,
        max_hold_minutes=60,
        max_spread_percent=3,
        min_volume=30,
        volume_quantity_multiplier=5,
    )

    assert rejection is None
    assert trade is not None
    assert trade["exit_reason"] == "EARLY_FAILURE_VWAP"
    assert trade["exit_bid"] == 94


def test_vwap_reclaim_grace_resets_after_successful_reclaim():
    event = SignalEvent(
        BASE_NS,
        "CALL",
        100,
        option(),
        [
            {
                "timestamp_ns": BASE_NS + MINUTE_NS,
                "bid": 99,
                "ask": 100,
                "volume": 1000,
                "open_interest": 10,
            },
            {
                "timestamp_ns": BASE_NS + 6 * MINUTE_NS,
                "bid": 98,
                "ask": 99,
                "volume": 1000,
                "open_interest": 10,
            },
            {
                "timestamp_ns": BASE_NS + 11 * MINUTE_NS,
                "bid": 101,
                "ask": 102,
                "volume": 1000,
                "open_interest": 10,
            },
            {
                "timestamp_ns": BASE_NS + 21 * MINUTE_NS,
                "bid": 102,
                "ask": 103,
                "volume": 1000,
                "open_interest": 10,
            },
        ],
    )
    frame = pd.DataFrame(
        [
            {"high": 101, "low": 98, "close": 99, "vwap": 100, "ema9": 103, "ema20": 102, "ema50": 101, "rsi14": 60},
            {"high": 102, "low": 99, "close": 101, "vwap": 100, "ema9": 104, "ema20": 103, "ema50": 102, "rsi14": 60},
            {"high": 101, "low": 98, "close": 99, "vwap": 100, "ema9": 105, "ema20": 104, "ema50": 103, "rsi14": 60},
        ],
        index=pd.DatetimeIndex(
            [
                pd.Timestamp(BASE_NS + 5 * MINUTE_NS, unit="ns", tz="UTC"),
                pd.Timestamp(BASE_NS + 10 * MINUTE_NS, unit="ns", tz="UTC"),
                pd.Timestamp(BASE_NS + 15 * MINUTE_NS, unit="ns", tz="UTC"),
            ]
        ),
    )
    scenario = Scenario(
        "VWAP_RECLAIM",
        1,
        "EMA",
        early_failure=EarlyFailureConfig(
            enabled=True,
            monitor_candles=3,
            condition_mode="ANY",
            exit_on_vwap_failure=True,
            vwap_reclaim_candles=1,
            exit_on_structure_break=False,
            exit_on_ema9_ema20_cross=False,
        ),
    )

    trade, rejection = simulate_trade(
        event,
        frame,
        scenario,
        premium_budget_usd=1.0,
        hard_stop_percent=-15,
        max_hold_minutes=20,
        max_spread_percent=3,
        min_volume=30,
        volume_quantity_multiplier=5,
    )

    assert rejection is None
    assert trade is not None
    assert trade["exit_reason"] == "MAX_HOLD"


def test_vwap_reclaim_grace_exits_after_consecutive_failed_closes():
    event = SignalEvent(
        BASE_NS,
        "CALL",
        100,
        option(),
        [
            {
                "timestamp_ns": BASE_NS + MINUTE_NS,
                "bid": 99,
                "ask": 100,
                "volume": 1000,
                "open_interest": 10,
            },
            {
                "timestamp_ns": BASE_NS + 11 * MINUTE_NS,
                "bid": 96,
                "ask": 97,
                "volume": 1000,
                "open_interest": 10,
            },
        ],
    )
    frame = pd.DataFrame(
        [
            {"high": 101, "low": 98, "close": 99, "vwap": 100, "ema9": 103, "ema20": 102, "ema50": 101, "rsi14": 60},
            {"high": 100, "low": 97, "close": 98, "vwap": 100, "ema9": 104, "ema20": 103, "ema50": 102, "rsi14": 60},
        ],
        index=pd.DatetimeIndex(
            [
                pd.Timestamp(BASE_NS + 5 * MINUTE_NS, unit="ns", tz="UTC"),
                pd.Timestamp(BASE_NS + 10 * MINUTE_NS, unit="ns", tz="UTC"),
            ]
        ),
    )
    scenario = Scenario(
        "VWAP_RECLAIM_FAIL",
        1,
        "EMA",
        early_failure=EarlyFailureConfig(
            enabled=True,
            monitor_candles=3,
            condition_mode="ANY",
            exit_on_vwap_failure=True,
            vwap_reclaim_candles=1,
            exit_on_structure_break=False,
            exit_on_ema9_ema20_cross=False,
        ),
    )

    trade, rejection = simulate_trade(
        event,
        frame,
        scenario,
        premium_budget_usd=1.0,
        hard_stop_percent=-15,
        max_hold_minutes=60,
        max_spread_percent=3,
        min_volume=30,
        volume_quantity_multiplier=5,
    )

    assert rejection is None
    assert trade is not None
    assert trade["exit_reason"] == "EARLY_FAILURE_VWAP"
    assert trade["exit_bid"] == 96


def test_size_aware_execution_uses_displayed_sizes_for_partial_fills():
    event = SignalEvent(
        BASE_NS,
        "CALL",
        100,
        option(),
        [
            {
                "timestamp_ns": BASE_NS + MINUTE_NS,
                "bid": 99,
                "ask": 100,
                "bid_size": 0,
                "ask_size": 2,
                "volume": 1000,
                "open_interest": 10,
            },
            {
                "timestamp_ns": BASE_NS + MINUTE_NS + 5_000_000_000,
                "bid": 101,
                "ask": 102,
                "bid_size": 0,
                "ask_size": 3,
                "volume": 1000,
                "open_interest": 10,
            },
            {
                "timestamp_ns": BASE_NS + 11 * MINUTE_NS + 5_000_000_000,
                "bid": 110,
                "ask": 111,
                "bid_size": 2,
                "ask_size": 0,
                "volume": 1000,
                "open_interest": 10,
            },
            {
                "timestamp_ns": BASE_NS + 11 * MINUTE_NS + 10_000_000_000,
                "bid": 108,
                "ask": 109,
                "bid_size": 1,
                "ask_size": 0,
                "volume": 1000,
                "open_interest": 10,
            },
        ],
    )
    execution = ExecutionConfig(
        mode="SIZE_AWARE",
        entry_fill_timeout_seconds=5,
        exit_fill_timeout_seconds=5,
        unfilled_exit_policy="ZERO",
    )

    trade, rejection = simulate_trade(
        event,
        pd.DataFrame({"close": pd.Series(dtype=float)}, index=pd.DatetimeIndex([], tz="UTC")),
        Scenario("SIZE_AWARE", 1, "EMA"),
        premium_budget_usd=1.0,
        hard_stop_percent=-15,
        max_hold_minutes=10,
        max_spread_percent=3,
        min_volume=30,
        volume_quantity_multiplier=5,
        execution=execution,
    )

    assert rejection is None
    assert trade is not None
    assert trade["requested_quantity"] == pytest.approx(10)
    assert trade["quantity"] == pytest.approx(5)
    assert trade["entry_fill_percent"] == pytest.approx(50)
    assert trade["entry_ask"] == pytest.approx((2 * 100 + 3 * 102) / 5)
    assert trade["exit_filled_quantity"] == pytest.approx(3)
    assert trade["exit_unfilled_quantity"] == pytest.approx(2)
    assert trade["exit_marked_quantity"] == pytest.approx(0)
    assert trade["exit_average_fill_bid"] == pytest.approx((2 * 110 + 108) / 3)
    assert trade["exit_bid"] == pytest.approx((2 * 110 + 108) / 5)


def test_size_aware_entry_can_reject_small_fill_percentage():
    event = SignalEvent(
        BASE_NS,
        "CALL",
        100,
        option(),
        [
            {
                "timestamp_ns": BASE_NS + MINUTE_NS,
                "bid": 99,
                "ask": 100,
                "bid_size": 10,
                "ask_size": 2,
                "volume": 1000,
                "open_interest": 10,
            }
        ],
    )

    trade, rejection = simulate_trade(
        event,
        pd.DataFrame(),
        Scenario("MIN_FILL", 1, "EMA"),
        premium_budget_usd=1.0,
        hard_stop_percent=-15,
        max_hold_minutes=60,
        max_spread_percent=3,
        min_volume=30,
        volume_quantity_multiplier=5,
        execution=ExecutionConfig(
            mode="SIZE_AWARE",
            minimum_entry_fill_percent=50,
        ),
    )

    assert trade is None
    assert rejection == "ENTRY_FILL_PERCENT_TOO_LOW"
    assert event.execution_attempt is not None
    assert event.execution_attempt["requested_quantity"] == pytest.approx(10)
    assert event.execution_attempt["hypothetical_filled_quantity"] == pytest.approx(2)
    assert event.execution_attempt["entry_fill_percent"] == pytest.approx(20)
    assert event.execution_attempt["entry_quotes_observed"] == 1
    assert event.execution_attempt["displayed_ask_size_sum"] == pytest.approx(2)
    assert event.execution_attempt["participating_capacity_sum"] == pytest.approx(2)
    assert event.execution_attempt["entry_fill_threshold_passed"] is False


def test_rejects_recorded_entry_quote_after_freshness_limit():
    event = SignalEvent(
        BASE_NS,
        "CALL",
        80000,
        option(),
        [{
            "timestamp_ns": BASE_NS + 61_000_000_000,
            "bid": 99,
            "ask": 100,
            "volume": 1000,
            "open_interest": 10,
        }],
    )

    trade, rejection = simulate_trade(
        event,
        pd.DataFrame(),
        Scenario("LATE_ENTRY", 1, "EMA"),
        premium_budget_usd=1.0,
        hard_stop_percent=-15,
        max_hold_minutes=None,
        max_spread_percent=3,
        min_volume=0,
        volume_quantity_multiplier=0,
        execution=ExecutionConfig(max_entry_quote_delay_seconds=60),
        data_fidelity="RECORDED_BBO_WITH_INFERRED_SIZE",
    )

    assert trade is None
    assert rejection == "ENTRY_QUOTE_TOO_LATE"
    assert event.execution_attempt is not None
    assert event.execution_attempt["signal_to_entry_delay_seconds"] == pytest.approx(61)


def test_rejects_recorded_exit_fill_after_freshness_limit():
    event = SignalEvent(
        BASE_NS,
        "CALL",
        80000,
        option(),
        [
            {
                "timestamp_ns": BASE_NS + 10_000_000_000,
                "bid": 99,
                "ask": 100,
                "volume": 1000,
                "open_interest": 10,
            },
            {
                "timestamp_ns": BASE_NS + 131_000_000_000,
                "bid": 101,
                "ask": 102,
                "volume": 1000,
                "open_interest": 10,
            },
        ],
    )

    trade, rejection = simulate_trade(
        event,
        pd.DataFrame(),
        Scenario("LATE_EXIT", 1, "EMA"),
        premium_budget_usd=1.0,
        hard_stop_percent=-15,
        max_hold_minutes=1,
        max_spread_percent=3,
        min_volume=0,
        volume_quantity_multiplier=0,
        execution=ExecutionConfig(
            max_entry_quote_delay_seconds=60,
            max_exit_quote_delay_seconds=60,
        ),
        data_fidelity="RECORDED_BBO_WITH_INFERRED_SIZE",
    )

    assert trade is None
    assert rejection == "EXIT_QUOTE_TOO_LATE"
    assert event.execution_attempt is not None
    assert event.execution_attempt["exit_trigger_to_fill_delay_seconds"] == pytest.approx(61)
    assert event.execution_attempt["coverage_resume_ns"] == BASE_NS + 131_000_000_000


def test_recorded_data_end_is_incomplete_instead_of_expiry_exit():
    event = SignalEvent(
        BASE_NS,
        "CALL",
        80000,
        option(),
        [
            {
                "timestamp_ns": BASE_NS + 10_000_000_000,
                "bid": 99,
                "ask": 100,
                "volume": 1000,
                "open_interest": 10,
            },
            {
                "timestamp_ns": BASE_NS + 120_000_000_000,
                "bid": 100,
                "ask": 101,
                "volume": 1000,
                "open_interest": 10,
            },
        ],
    )

    trade, rejection = simulate_trade(
        event,
        pd.DataFrame(),
        Scenario("R2_DATA_END", 1, "EMA"),
        premium_budget_usd=1.0,
        hard_stop_percent=-15,
        max_hold_minutes=None,
        max_spread_percent=3,
        min_volume=0,
        volume_quantity_multiplier=0,
        execution=ExecutionConfig(
            max_entry_quote_delay_seconds=60,
            max_exit_quote_delay_seconds=60,
        ),
        data_fidelity="RECORDED_BBO_WITH_INFERRED_SIZE",
    )

    assert trade is None
    assert rejection == "INCOMPLETE_R2_COVERAGE"
    assert event.execution_attempt is not None
    assert event.execution_attempt["coverage_status"] == "INCOMPLETE_R2_COVERAGE"
