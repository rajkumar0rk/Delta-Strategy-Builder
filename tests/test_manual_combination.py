import pytest

import json
import shutil
from pathlib import Path
from uuid import uuid4

from backtest.manual_combination import (
    build_scenarios,
    configured_segments,
    parse_config,
    resolve_output_path,
    scenario_output_name,
    selected_data_fidelity,
    versioned_output_path,
)


@pytest.fixture
def work_directory():
    directory = Path(__file__).parent / "testdata" / f"manual-{uuid4().hex}"
    directory.mkdir(parents=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


def test_parses_inclusive_backtest_date_range():
    config = parse_config(
        {
            "backtest": {
                "source": "PUBLIC_HISTORY",
                "start_date": "2026-08-01",
                "end_date": "2026-08-31",
            }
        }
    )

    segments = configured_segments(config)

    assert config.backtest.start_date == "2026-08-01"
    assert config.backtest.end_date == "2026-08-31"
    assert segments[0].start == "2026-08-01T00:00:00Z"
    assert segments[-1].end == "2026-09-01T00:00:00Z"


def test_parses_non_contiguous_backtest_months():
    config = parse_config(
        {
            "backtest": {
                "source": "PUBLIC_HISTORY",
                "months": ["2026-08", "2026-06"],
            }
        }
    )

    segments = configured_segments(config)

    assert config.backtest.months == ("2026-06", "2026-08")
    assert {item.start[:7] for item in segments} == {"2026-06", "2026-08"}


def test_public_history_catalog_selects_across_shards(work_directory):
    first = work_directory / "segments" / "2026-01"
    second = work_directory / "segments" / "2026-02"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (work_directory / "catalog.json").write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "name": "2026-01",
                        "directory": "segments/2026-01",
                        "start": "2026-01-01T00:00:00Z",
                        "end_exclusive": "2026-02-01T00:00:00Z",
                    },
                    {
                        "name": "2026-02",
                        "directory": "segments/2026-02",
                        "start": "2026-02-01T00:00:00Z",
                        "end_exclusive": "2026-03-01T00:00:00Z",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    config = parse_config(
        {
            "backtest": {
                "source": "PUBLIC_HISTORY",
                "start_date": "2026-01-31",
                "end_date": "2026-02-01",
                "directory": str(work_directory),
            }
        }
    )

    segments = configured_segments(config)

    assert len(segments) == 2
    assert segments[0].start == "2026-01-31T00:00:00Z"
    assert segments[1].end == "2026-02-02T00:00:00Z"


def test_rejects_combined_dates_and_months():
    with pytest.raises(ValueError, match="cannot be combined"):
        parse_config(
            {
                "backtest": {
                    "start_date": "2026-08-01",
                    "end_date": "2026-08-31",
                    "months": ["2026-08"],
                }
            }
        )


def test_r2_l1_selection_uses_recorded_session_coverage(work_directory):
    manifest = {
        "inferred_bid_sizes": 4,
        "inferred_ask_sizes": 4,
        "sessions": [
            {
                "start": "2026-09-23T07:00:00Z",
                "end": "2026-09-23T09:00:00Z",
                "event_types": {"option_chain": 2},
            }
        ],
    }
    (work_directory / "recording_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    config = parse_config(
        {
            "backtest": {
                "source": "R2_L1",
                "start_date": "2026-09-23",
                "end_date": "2026-09-23",
                "directory": str(work_directory),
            }
        }
    )

    segments = configured_segments(config)

    assert len(segments) == 1
    assert segments[0].start == "2026-09-23T07:00:00Z"
    assert segments[0].end == "2026-09-23T09:00:01Z"
    assert selected_data_fidelity(config) == "RECORDED_BBO_WITH_INFERRED_SIZE"


def test_builds_macd_h6_combination_for_selected_families():
    config = parse_config(
        {
            "name": "macd-h6",
            "bt_families": [1, 3],
            "exit_policy": "PLAIN",
            "filters": {"macd": True, "h6": True},
            "session": {},
        }
    )

    scenarios = build_scenarios(config)

    assert [item.group for item in scenarios] == [1, 3]
    assert all(item.require_macd for item in scenarios)
    assert all(item.min_option_true_ranges == 6 for item in scenarios)
    assert all(item.name.endswith("_MACD_H6") for item in scenarios)


def test_scenario_output_name_uses_generated_single_scenario_name():
    config = parse_config(
        {
            "name": "label-that-does-not-control-the-folder",
            "bt_families": [2],
            "filters": {"macd": True},
        }
    )
    scenarios = build_scenarios(config)

    assert scenario_output_name(scenarios) == scenarios[0].name


def test_scenario_output_name_combines_family_names_with_shared_settings():
    config = parse_config(
        {
            "bt_families": [1, 2, 3],
            "filters": {"macd": True, "h6": True},
        }
    )

    assert scenario_output_name(build_scenarios(config)) == "BT1-BT2-BT3_MACD_H6"


def test_versioned_output_path_increments_existing_folders(monkeypatch):
    base = Path("reports/BT2_EMA_VWAP_BASE")
    existing = {base, base.with_name(f"{base.name}_v2")}
    monkeypatch.setattr(type(base), "exists", lambda value: value in existing)

    assert versioned_output_path(base) == base.with_name(f"{base.name}_v3")


def test_name_is_optional_report_metadata():
    assert parse_config({}).name == "manual-combination"


def test_relative_output_name_is_placed_under_report_root(monkeypatch):
    scenarios = build_scenarios(parse_config({"bt_families": [2]}))
    root = Path("backtest/reports/manual-combinations")
    monkeypatch.setattr(type(root), "exists", lambda value: False)

    assert resolve_output_path(
        Path("02_zigzag_full_bbo"),
        scenarios,
        output_root=root,
    ) == root / "02_zigzag_full_bbo"


def test_default_output_uses_generated_scenario_name(monkeypatch):
    scenarios = build_scenarios(parse_config({"bt_families": [2]}))
    root = Path("backtest/reports/manual-combinations")
    monkeypatch.setattr(type(root), "exists", lambda value: False)

    assert resolve_output_path(None, scenarios, output_root=root) == (
        root / scenarios[0].name
    )


def test_fee_aware_filter_requires_h6():
    with pytest.raises(ValueError, match="FA requires h6=true"):
        parse_config(
            {
                "name": "invalid-fa",
                "filters": {"h6": False, "fee_aware_multiplier": 1.5},
            }
        )


def test_builds_minimum_signal_volume_ratio_filter():
    config = parse_config(
        {
            "name": "volume-ratio",
            "bt_families": [2],
            "filters": {"min_signal_volume_ratio": 0.5},
        }
    )

    scenario = build_scenarios(config)[0]

    assert scenario.min_signal_volume_ratio == pytest.approx(0.5)
    assert "VOLUME_RATIO_0P5" in scenario.name


def test_rejects_negative_signal_volume_ratio():
    with pytest.raises(ValueError, match="min_signal_volume_ratio"):
        parse_config(
            {
                "name": "bad-volume-ratio",
                "filters": {"min_signal_volume_ratio": -0.1},
            }
        )


def test_builds_all_supported_entry_filters():
    config = parse_config(
        {
            "name": "everything",
            "bt_families": [2],
            "exit_policy": "ALL_FAIL",
            "filters": {
                "macd": True,
                "h6": True,
                "h6_true_ranges": 6,
                "fee_aware_multiplier": 1.5,
                "m30": True,
                "m30_minutes": 30,
                "stoch_momentum": True,
            },
            "session": {
                "entry_windows_ist": [
                    "13:30-17:00",
                    "18:30-19:00",
                    "19:00-21:30",
                    "21:30-23:30",
                ],
                "no_trade_days": ["Saturday", "Sunday"],
            },
        }
    )

    scenario = build_scenarios(config)[0]

    assert scenario.require_macd is True
    assert scenario.min_option_true_ranges == 6
    assert scenario.fee_aware_multiplier == pytest.approx(1.5)
    assert scenario.directional_confirmation_minutes == 30
    assert scenario.require_stoch_rsi_momentum_entry is True
    assert scenario.exit_when_all_fail is True
    assert scenario.entry_windows_ist_minutes == (
        (13 * 60 + 30, 17 * 60),
        (18 * 60 + 30, 19 * 60),
        (19 * 60, 21 * 60 + 30),
        (21 * 60 + 30, 23 * 60 + 30),
    )
    assert scenario.blocked_weekdays_ist == (5, 6)
    assert scenario.name.endswith(
        "_ALLFAIL_MACD_H6_FA150_M30_STOCH_MOMENTUM_IST_WINDOWS_4_NO_SATURDAY_SUNDAY"
    )


def test_rejects_overlapping_ist_windows():
    with pytest.raises(ValueError, match="cannot overlap"):
        parse_config(
            {
                "name": "overlap",
                "session": {
                    "entry_windows_ist": ["13:30-17:00", "16:30-18:00"],
                },
            }
        )


def test_rejects_unknown_exit_policy():
    with pytest.raises(ValueError, match="PLAIN or ALL_FAIL"):
        parse_config({"name": "bad-exit", "exit_policy": "sometimes"})


def test_builds_exclusive_near_expiry_filter_without_fa():
    config = parse_config(
        {
            "name": "exclude-near-expiry",
            "filters": {"h6": False, "fee_aware_multiplier": 0.0},
            "option": {
                "min_days_to_expiry": 1.5,
                "min_days_to_expiry_inclusive": False,
                "max_days_to_expiry": 3.0,
            },
        }
    )

    scenario = build_scenarios(config)[0]

    assert scenario.min_days_to_expiry == pytest.approx(1.5)
    assert scenario.min_days_to_expiry_inclusive is False
    assert scenario.max_days_to_expiry == pytest.approx(3.0)
    assert scenario.min_option_true_ranges == 0
    assert scenario.fee_aware_multiplier == 0.0
    assert "DTE_GT_1.5_TO_3" in scenario.name


def test_rejects_invalid_manual_expiry_range():
    with pytest.raises(
        ValueError,
        match="max_days_to_expiry must be greater than min_days_to_expiry",
    ):
        parse_config(
            {
                "name": "invalid-expiry",
                "option": {
                    "min_days_to_expiry": 3.0,
                    "max_days_to_expiry": 1.5,
                },
            }
        )


def test_builds_fast_and_mid_vs_slow_ema_exit_rule():
    config = parse_config(
        {
            "name": "relaxed-ema-exit",
            "bt_families": [2],
            "exit": {"ema_rule": "FAST_AND_MID_VS_SLOW"},
        }
    )

    scenario = build_scenarios(config)[0]

    assert scenario.ema_exit_rule == "FAST_AND_MID_VS_SLOW"
    assert "EXIT_FAST_MID_VS_SLOW" in scenario.name


def test_rejects_unknown_ema_exit_rule():
    with pytest.raises(ValueError, match="exit.ema_rule"):
        parse_config(
            {
                "name": "bad-ema-exit",
                "exit": {"ema_rule": "IGNORE_EVERYTHING"},
            }
        )


def test_builds_fast_or_mid_vs_slow_ema_exit_rule():
    config = parse_config(
        {
            "name": "loose-ema-exit",
            "bt_families": [2],
            "exit": {"ema_rule": "FAST_OR_MID_VS_SLOW"},
        }
    )

    scenario = build_scenarios(config)[0]

    assert scenario.ema_exit_rule == "FAST_OR_MID_VS_SLOW"
    assert "EXIT_FAST_OR_MID_VS_SLOW" in scenario.name


@pytest.mark.parametrize("hours", [1.5, 2.0, 3.0, 4.0])
def test_parses_supported_max_hold_hours(hours):
    config = parse_config(
        {
            "name": "timed-exit",
            "exit": {"max_hold_hours": hours},
        }
    )

    assert config.max_hold_hours == pytest.approx(hours)
    expected = f"{hours:g}".replace(".", "P")
    assert f"HOLD_{expected}H" in build_scenarios(config)[0].name


def test_disables_max_hold_with_none_string():
    config = parse_config(
        {
            "name": "no-time-exit",
            "exit": {"max_hold_hours": "NONE"},
        }
    )

    assert config.max_hold_hours is None
    assert "NO_MAX_HOLD" in build_scenarios(config)[0].name


@pytest.mark.parametrize("days", [1.0, 1.3, 1.5])
def test_parses_expiry_exit_days(days):
    config = parse_config(
        {
            "name": "expiry-exit",
            "exit": {
                "max_hold_hours": "NONE",
                "exit_days_to_expiry": days,
            },
        }
    )

    expected = f"{days:g}".replace(".", "P")
    assert config.exit_days_to_expiry == pytest.approx(days)
    assert f"DTE_EXIT_{expected}D" in build_scenarios(config)[0].name


def test_disables_expiry_exit_with_none_string():
    config = parse_config(
        {
            "name": "no-expiry-exit",
            "exit": {"exit_days_to_expiry": "NONE"},
        }
    )

    assert config.exit_days_to_expiry is None


def test_builds_configurable_peak_profit_protection():
    config = parse_config(
        {
            "name": "profit-protection",
            "bt_families": [2],
            "profit_protection": {
                "enabled": True,
                "activation_percent": 20.0,
                "protect_percent": 50.0,
            },
        }
    )

    scenario = build_scenarios(config)[0]

    assert scenario.protection == "Z"
    assert scenario.activation_percent == pytest.approx(20.0)
    assert scenario.retention == pytest.approx(0.50)
    assert "PP_A20_P50" in scenario.name


@pytest.mark.parametrize(
    "settings,match",
    [
        ({"activation_percent": 0}, "activation_percent"),
        ({"protect_percent": 0}, "protect_percent"),
        ({"protect_percent": 101}, "protect_percent"),
    ],
)
def test_rejects_invalid_profit_protection_settings(settings, match):
    with pytest.raises(ValueError, match=match):
        parse_config(
            {
                "name": "bad-profit-protection",
                "profit_protection": settings,
            }
        )


@pytest.mark.parametrize(
    "activation,protected",
    [(10.0, 0.0), (15.0, 5.0), (20.0, 10.0)],
)
def test_builds_fixed_profit_protection(activation, protected):
    config = parse_config(
        {
            "name": "fixed-profit",
            "bt_families": [2],
            "profit_protection": {
                "enabled": True,
                "mode": "FIXED",
                "activation_percent": activation,
                "protect_percent": protected,
            },
        }
    )

    scenario = build_scenarios(config)[0]

    assert scenario.protection == "FIXED"
    assert scenario.fixed_protected_profit_percent == pytest.approx(protected)
    assert "PP_FIXED" in scenario.name


def test_builds_entry_exit_risk_and_liquidity_controls():
    config = parse_config(
        {
            "name": "all-controls",
            "bt_families": [2],
            "entry": {"mode": "BOTH"},
            "filters": {
                "min_signal_volume_ratio": 0.5,
                "min_vwap_displacement_atr": 1.0,
                "min_ema_strength_atr": 0.25,
                "max_ema_strength_atr": 0.75,
            },
            "momentum_breakout": {
                "lookback_candles": 8,
                "breakout_buffer_atr": 0.1,
                "min_volume_ratio": 1.5,
            },
            "early_failure": {
                "enabled": True,
                "monitor_candles": 4,
                "condition_mode": "ALL",
                "vwap_reclaim_candles": 1,
            },
            "execution": {
                "mode": "SIZE_AWARE",
                "size_participation_rate": 0.5,
                "size_capacity_multiplier": 1.25,
                "entry_fill_timeout_seconds": 10,
                "minimum_entry_fill_percent": 25,
                "max_entry_quote_delay_seconds": 60,
                "max_exit_quote_delay_seconds": 90,
                "exit_fill_timeout_seconds": 30,
                "unfilled_exit_policy": "LAST_BID",
            },
            "risk": {
                "hard_stop_percent": -12.5,
                "hard_stop_fill_mode": "SAME_QUOTE",
            },
            "liquidity": {
                "max_spread_percent": 2.0,
                "min_volume": 10,
                "volume_quantity_multiplier": 2,
            },
        }
    )

    scenario = build_scenarios(config)[0]

    assert scenario.entry_mode == "BOTH"
    assert scenario.pullback_reversal.enabled is True
    assert scenario.momentum_breakout.enabled is True
    assert scenario.momentum_breakout.lookback_candles == 8
    assert scenario.early_failure.enabled is True
    assert scenario.early_failure.monitor_candles == 4
    assert scenario.early_failure.condition_mode == "ALL"
    assert scenario.early_failure.vwap_reclaim_candles == 1
    assert scenario.min_vwap_displacement_atr == pytest.approx(1.0)
    assert scenario.min_ema_strength_atr == pytest.approx(0.25)
    assert scenario.max_ema_strength_atr == pytest.approx(0.75)
    assert scenario.hard_stop_percent_override == pytest.approx(-12.5)
    assert scenario.hard_stop_fill_mode == "SAME_QUOTE"
    assert config.max_spread_percent == pytest.approx(2.0)
    assert config.min_volume == pytest.approx(10)
    assert config.volume_quantity_multiplier == pytest.approx(2)
    assert config.execution.mode == "SIZE_AWARE"
    assert config.execution.size_participation_rate == pytest.approx(0.5)
    assert config.execution.size_capacity_multiplier == pytest.approx(1.25)
    assert config.execution.entry_fill_timeout_seconds == pytest.approx(10)
    assert config.execution.minimum_entry_fill_percent == pytest.approx(25)
    assert config.execution.max_entry_quote_delay_seconds == pytest.approx(60)
    assert config.execution.max_exit_quote_delay_seconds == pytest.approx(90)
    assert config.execution.exit_fill_timeout_seconds == pytest.approx(30)
    assert config.execution.unfilled_exit_policy == "LAST_BID"


@pytest.mark.parametrize("value", [-0.1, True, "later"])
def test_rejects_invalid_expiry_exit_days(value):
    with pytest.raises(ValueError, match="exit_days_to_expiry"):
        parse_config(
            {
                "name": "bad-expiry-exit",
                "exit": {"exit_days_to_expiry": value},
            }
        )


def test_rejects_expiry_exit_at_or_above_maximum_entry_dte():
    with pytest.raises(ValueError, match="must be less than"):
        parse_config(
            {
                "name": "unreachable-expiry-exit",
                "exit": {"exit_days_to_expiry": 3.0},
                "option": {"max_days_to_expiry": 3.0},
            }
        )


@pytest.mark.parametrize(
    "rsi_enabled,atr_enabled,expected_labels",
    [
        (False, False, ("ZZ_NO_RSI", "ZZ_NO_ATR")),
        (True, False, ("ZZ_RSI", "ZZ_NO_ATR")),
        (False, True, ("ZZ_NO_RSI", "ZZ_ATR40")),
        (True, True, ("ZZ_RSI", "ZZ_ATR40")),
    ],
)
def test_builds_zigzag_rsi_atr_combinations(
    rsi_enabled,
    atr_enabled,
    expected_labels,
):
    config = parse_config(
        {
            "name": "zigzag-combination",
            "bt_families": [2],
            "zigzag": {
                "enabled": True,
                "pullback_lookback_candles": 4,
                "rsi_enabled": rsi_enabled,
                "atr_enabled": atr_enabled,
                "atr_reversal_multiplier": 0.4,
            },
        }
    )

    scenario = build_scenarios(config)[0]

    assert scenario.pullback_reversal.enabled is True
    assert scenario.pullback_reversal.rsi_enabled is rsi_enabled
    assert scenario.pullback_reversal.atr_enabled is atr_enabled
    assert "ZIGZAG_L4" in scenario.name
    assert all(label in scenario.name for label in expected_labels)


def test_builds_safer_zigzag_pullback_configuration():
    config = parse_config(
        {
            "name": "safe-zigzag",
            "bt_families": [2],
            "zigzag": {
                "enabled": True,
                "require_ema_slope": True,
                "allow_flat_ema50": True,
                "max_touch_close_distance_atr": 0.2,
                "use_actual_pullback_sequence": True,
            },
        }
    )

    zigzag = build_scenarios(config)[0].pullback_reversal

    assert zigzag.require_ema_slope is True
    assert zigzag.allow_flat_ema50 is True
    assert zigzag.max_touch_close_distance_atr == pytest.approx(0.2)
    assert zigzag.use_actual_pullback_sequence is True


@pytest.mark.parametrize("value", [-0.1, True, "invalid"])
def test_rejects_invalid_zigzag_touch_atr_distance(value):
    with pytest.raises(ValueError, match="max_touch_close_distance_atr"):
        parse_config(
            {
                "name": "bad-zigzag-tolerance",
                "zigzag": {"max_touch_close_distance_atr": value},
            }
        )


@pytest.mark.parametrize("value", [0, -1, True, "later"])
def test_rejects_invalid_max_hold_hours(value):
    with pytest.raises(ValueError, match="max_hold_hours"):
        parse_config(
            {
                "name": "bad-time-exit",
                "exit": {"max_hold_hours": value},
            }
        )
