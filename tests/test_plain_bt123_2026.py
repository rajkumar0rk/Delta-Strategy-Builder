from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from backtest.plain_bt123_2026 import (
    SEGMENTS,
    Segment,
    _months_for_segments,
    _money,
    _without_cross_segment_overlap,
    all_fail_scenarios,
    condition_count_scenarios,
    displacement_volume_scenarios,
    ema_regime_trade_scenarios,
    trend_strength_scenarios,
    momentum_stoch_scenarios,
    plain_ist_window_scenarios,
    plain_ist_window_fa150_scenarios,
    plain_ist_window_dte15_scenarios,
    plain_scenarios,
)


UTC = timezone.utc


def test_plain_scenarios_have_only_bt1_bt2_bt3():
    selected = plain_scenarios()

    assert [scenario.name for scenario in selected] == [
        "BT1_EMA",
        "BT2_EMA_VWAP",
        "BT3_EMA_VWAP_RSI",
    ]
    assert all(not scenario.require_macd for scenario in selected)
    assert all(not scenario.require_stoch_rsi_entry for scenario in selected)
    assert all(scenario.min_option_true_ranges == 0 for scenario in selected)
    assert all(scenario.fee_aware_multiplier == 0.0 for scenario in selected)


def test_money_formats_empty_metrics_without_crashing_report():
    assert _money(None) == "N/A"
    assert _money(1.234) == "$+1.23"


def test_all_fail_scenarios_change_only_exit_combination_policy():
    plain = plain_scenarios()
    all_fail = all_fail_scenarios()

    assert [scenario.name for scenario in all_fail] == [
        "BT1_EMA_ALLFAIL",
        "BT2_EMA_VWAP_ALLFAIL",
        "BT3_EMA_VWAP_RSI_ALLFAIL",
    ]
    assert all(scenario.exit_when_all_fail for scenario in all_fail)
    assert [replace(scenario, name=plain_item.name, exit_when_all_fail=False)
            for scenario, plain_item in zip(all_fail, plain)] == plain


def test_momentum_stoch_scenarios_keep_plain_exits():
    selected = momentum_stoch_scenarios()

    assert [scenario.name for scenario in selected] == [
        "BT1_EMA_STOCH_KGT_D",
        "BT2_EMA_VWAP_STOCH_KGT_D",
        "BT3_EMA_VWAP_RSI_STOCH_KGT_D",
    ]
    assert all(scenario.require_stoch_rsi_momentum_entry for scenario in selected)
    assert all(not scenario.exit_when_all_fail for scenario in selected)


def test_condition_count_scenarios_compare_all_thresholds_and_exit_families():
    selected = condition_count_scenarios()

    assert len(selected) == 9
    assert {scenario.entry_min_conditions for scenario in selected} == {1, 2, 3}
    assert {scenario.exit_mode for scenario in selected} == {
        "EMA",
        "EMA_VWAP",
        "EMA_VWAP_RSI",
    }


def test_ema_regime_trade_scenarios_compare_control_and_gated_bt2():
    selected = ema_regime_trade_scenarios()

    assert len(selected) == 2
    assert all(scenario.exit_mode == "EMA_VWAP" for scenario in selected)
    assert [scenario.one_trade_per_ema_regime for scenario in selected] == [False, True]


def test_trend_strength_scenarios_compare_requested_atr_thresholds():
    selected = trend_strength_scenarios()

    assert [scenario.min_ema_strength_atr for scenario in selected] == [
        0,
        0.25,
        0.50,
        0.75,
        1.0,
    ]
    assert all(scenario.one_trade_per_ema_regime for scenario in selected)


def test_displacement_volume_scenarios_are_fixed_before_backtest():
    selected = displacement_volume_scenarios()

    assert len(selected) == 4
    assert [scenario.min_vwap_displacement_atr for scenario in selected] == [
        0,
        1.5,
        0,
        1.5,
    ]
    assert [scenario.min_signal_volume_ratio for scenario in selected] == [
        0,
        0,
        1.25,
        1.25,
    ]


def test_plain_ist_window_scenarios_cross_four_windows_and_three_families():
    selected = plain_ist_window_scenarios()

    assert len(selected) == 12
    assert {scenario.exit_mode for scenario in selected} == {
        "EMA",
        "EMA_VWAP",
        "EMA_VWAP_RSI",
    }
    assert {scenario.entry_windows_ist_minutes for scenario in selected} == {
        ((810, 1020),),
        ((1110, 1140),),
        ((1140, 1290),),
        ((1290, 1410),),
    }


def test_plain_ist_window_fa150_scenarios_add_required_history_and_fee_filter():
    selected = plain_ist_window_fa150_scenarios()

    assert len(selected) == 12
    assert all(scenario.min_option_true_ranges == 6 for scenario in selected)
    assert all(scenario.fee_aware_multiplier == 1.50 for scenario in selected)
    assert all(scenario.name.endswith("H6_FA150") for scenario in selected)


def test_plain_ist_window_dte15_scenarios_use_no_fa_and_exclude_near_expiry():
    selected = plain_ist_window_dte15_scenarios()

    assert len(selected) == 12
    assert all(scenario.min_days_to_expiry == 1.5 for scenario in selected)
    assert all(not scenario.min_days_to_expiry_inclusive for scenario in selected)
    assert all(scenario.max_days_to_expiry == 3.0 for scenario in selected)
    assert all(scenario.min_option_true_ranges == 0 for scenario in selected)
    assert all(scenario.fee_aware_multiplier == 0.0 for scenario in selected)
    assert all(scenario.name.endswith("DTE1P5_TO_3") for scenario in selected)


def test_segments_cover_january_through_october_3_without_gaps():
    assert SEGMENTS[0].start == "2026-01-01T00:00:00Z"
    assert SEGMENTS[-1].end == "2026-10-04T00:00:00Z"
    assert all(left.end == right.start for left, right in zip(SEGMENTS, SEGMENTS[1:]))


def test_month_labels_follow_selected_segments_instead_of_fixed_2026_range():
    selected = (
        Segment(
            "june",
            SEGMENTS[0].directory,
            "2026-06-15T00:00:00Z",
            "2026-07-02T00:00:00Z",
        ),
        Segment(
            "september",
            SEGMENTS[-1].directory,
            "2026-09-20T00:00:00Z",
            "2026-10-01T00:00:00Z",
        ),
    )

    assert _months_for_segments(selected) == ["2026-06", "2026-07", "2026-09"]


def test_cross_segment_overlap_is_removed_per_scenario():
    trades = [
        {
            "scenario": "BT1_EMA",
            "entry_time": "2026-08-23T23:55:00+00:00",
            "exit_time": "2026-08-24T00:30:00+00:00",
        },
        {
            "scenario": "BT1_EMA",
            "entry_time": "2026-08-24T00:05:00+00:00",
            "exit_time": "2026-08-24T00:20:00+00:00",
        },
        {
            "scenario": "BT2_EMA_VWAP",
            "entry_time": "2026-08-24T00:05:00+00:00",
            "exit_time": "2026-08-24T00:20:00+00:00",
        },
    ]

    selected = _without_cross_segment_overlap(trades)

    assert len(selected) == 2
    assert {trade["scenario"] for trade in selected} == {
        "BT1_EMA",
        "BT2_EMA_VWAP",
    }
