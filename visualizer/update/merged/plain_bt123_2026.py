from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .ema_vwap_research import (
    ExecutionConfig,
    entry_condition_count_scenarios,
    ema_strength_scenarios,
    one_trade_per_ema_regime_scenarios,
    run_dataset,
    scenarios,
    stoch_momentum_scenarios,
    vwap_volume_scenarios,
    write_report,
)
from .jan_jul_2026 import _aggregate_metrics


UTC = timezone.utc
DEFAULT_OUTPUT = Path("backtest/reports/plain-bt123-jan-sep-2026")
DEFAULT_ALL_FAIL_OUTPUT = Path("backtest/reports/all-fail-bt123-jan-sep-2026")
DEFAULT_STOCH_MOMENTUM_OUTPUT = Path(
    "backtest/reports/stoch-momentum-bt123-jan-sep-2026"
)
DEFAULT_ENTRY_CONDITION_COUNT_OUTPUT = Path(
    "backtest/reports/entry-condition-count-bt123-jan-sep-2026"
)
DEFAULT_ONE_PER_EMA_REGIME_OUTPUT = Path(
    "backtest/reports/one-trade-per-ema-regime-bt2-jan-sep-2026"
)
DEFAULT_EMA_STRENGTH_OUTPUT = Path(
    "backtest/reports/ema-strength-bt2-one-per-regime-jan-sep-2026"
)
DEFAULT_VWAP_VOLUME_OUTPUT = Path(
    "backtest/reports/vwap-volume-bt2-one-per-regime-jan-sep-2026"
)
DEFAULT_IST_WINDOWS_OUTPUT = Path(
    "backtest/reports/plain-bt123-ist-windows-jan-sep-2026"
)
DEFAULT_IST_WINDOWS_FA150_OUTPUT = Path(
    "backtest/reports/plain-bt123-ist-windows-h6-fa150-jan-sep-2026"
)
DEFAULT_IST_WINDOWS_DTE15_OUTPUT = Path(
    "backtest/reports/plain-bt123-ist-windows-dte1p5-to-3-jan-sep-2026"
)
EXCEPTIONAL_SIGNAL = "2026-08-19T14:35:00+00:00"

IST_ENTRY_WINDOWS = (
    ("IST_1330_1700", ((13 * 60 + 30, 17 * 60),)),
    ("IST_1830_1900", ((18 * 60 + 30, 19 * 60),)),
    ("IST_1900_2130", ((19 * 60, 21 * 60 + 30),)),
    ("IST_2130_2330", ((21 * 60 + 30, 23 * 60 + 30),)),
)


@dataclass(frozen=True)
class Segment:
    name: str
    directory: Path
    start: str
    end: str


SEGMENTS = (
    Segment(
        "jan_jul",
        Path("backtest/data/delta-2026-01-01_08-01"),
        "2026-01-01T00:00:00Z",
        "2026-08-01T00:00:00Z",
    ),
    Segment(
        "aug_01_24",
        Path("backtest/data/delta-holdout-2026-07-25_08-24"),
        "2026-08-01T00:00:00Z",
        "2026-08-24T00:00:00Z",
    ),
    Segment(
        "aug_24_sep_23",
        Path("backtest/data/delta-2026-09-15_22"),
        "2026-08-24T00:00:00Z",
        "2026-09-23T00:00:00Z",
    ),
    Segment(
        "sep_23",
        Path("backtest/data/delta-2026-09-23"),
        "2026-09-23T00:00:00Z",
        "2026-09-24T00:00:00Z",
    ),
    Segment(
        "sep_24_30",
        Path("backtest/data/delta-2026-09-24-to-26"),
        "2026-09-24T00:00:00Z",
        "2026-10-01T00:00:00Z",
    ),
    Segment(
        "oct_01_03",
        Path("backtest/data/delta-2026-10-01-to-03"),
        "2026-10-01T00:00:00Z",
        "2026-10-04T00:00:00Z",
    ),
)


def plain_scenarios():
    return scenarios()[:3]


def all_fail_scenarios():
    return [
        replace(
            scenario,
            name=f"{scenario.name}_ALLFAIL",
            exit_when_all_fail=True,
        )
        for scenario in plain_scenarios()
    ]


def momentum_stoch_scenarios():
    return stoch_momentum_scenarios()


def condition_count_scenarios():
    return entry_condition_count_scenarios()


def ema_regime_trade_scenarios():
    return one_trade_per_ema_regime_scenarios()


def trend_strength_scenarios():
    return ema_strength_scenarios()


def displacement_volume_scenarios():
    return vwap_volume_scenarios()


def plain_ist_window_scenarios():
    return [
        replace(
            scenario,
            name=f"{scenario.name}_{label}",
            entry_windows_ist_minutes=windows,
        )
        for label, windows in IST_ENTRY_WINDOWS
        for scenario in plain_scenarios()
    ]


def plain_ist_window_fa150_scenarios():
    return [
        replace(
            scenario,
            name=f"{scenario.name}_{label}_H6_FA150",
            entry_windows_ist_minutes=windows,
            min_option_true_ranges=6,
            fee_aware_multiplier=1.50,
        )
        for label, windows in IST_ENTRY_WINDOWS
        for scenario in plain_scenarios()
    ]


def plain_ist_window_dte15_scenarios():
    return [
        replace(
            scenario,
            name=f"{scenario.name}_{label}_DTE1P5_TO_3",
            entry_windows_ist_minutes=windows,
            min_days_to_expiry=1.50,
            min_days_to_expiry_inclusive=False,
            max_days_to_expiry=3.0,
        )
        for label, windows in IST_ENTRY_WINDOWS
        for scenario in plain_scenarios()
    ]


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _manifest_range(directory: Path) -> tuple[datetime, datetime]:
    sync_path = directory / "sync_manifest.json"
    if sync_path.exists():
        manifest = json.loads(sync_path.read_text(encoding="utf-8"))
        start = manifest.get("start")
        end = manifest.get("end_exclusive", manifest.get("end"))
        if not start or not end:
            raise RuntimeError(
                f"Dataset manifest does not contain a date range: {sync_path}"
            )
        return _parse_timestamp(str(start)), _parse_timestamp(str(end))

    recording_path = directory / "recording_manifest.json"
    if recording_path.exists():
        manifest = json.loads(recording_path.read_text(encoding="utf-8"))
        sessions = [
            session
            for session in manifest.get("sessions", [])
            if session.get("start") and session.get("end")
            and int(session.get("event_types", {}).get("option_chain", 0)) > 0
        ]
        if not sessions:
            sessions = [
                session
                for session in manifest.get("sessions", [])
                if session.get("start") and session.get("end")
            ]
        if not sessions:
            raise RuntimeError(
                f"Recording manifest contains no timestamped sessions: {recording_path}"
            )
        start = min(_parse_timestamp(str(session["start"])) for session in sessions)
        end = max(_parse_timestamp(str(session["end"])) for session in sessions)
        return start, end + timedelta(seconds=1)

    raise RuntimeError(
        f"Missing sync_manifest.json or recording_manifest.json in {directory}"
    )


def validate_segments(segments: tuple[Segment, ...] = SEGMENTS) -> None:
    if not segments:
        raise RuntimeError("At least one backtest data segment is required")
    for segment in segments:
        available_start, available_end = _manifest_range(segment.directory)
        required_start = _parse_timestamp(segment.start)
        required_end = _parse_timestamp(segment.end)
        if available_start > required_start or available_end < required_end:
            raise RuntimeError(
                f"Dataset {segment.directory} covers "
                f"{available_start.isoformat()} to {available_end.isoformat()}, but "
                f"{segment.start} to {segment.end} is required."
            )


def _months_for_segments(segments: tuple[Segment, ...]) -> list[str]:
    months: set[str] = set()
    for segment in segments:
        current = _parse_timestamp(segment.start).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        end = _parse_timestamp(segment.end)
        while current < end:
            months.add(f"{current:%Y-%m}")
            current = (
                current.replace(year=current.year + 1, month=1)
                if current.month == 12
                else current.replace(month=current.month + 1)
            )
    return sorted(months)


def _without_cross_segment_overlap(
    trades: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    available_after: dict[str, datetime] = {}
    used_ema_regimes: set[tuple[str, str, str]] = set()
    for trade in sorted(
        trades,
        key=lambda item: (
            str(item["scenario"]),
            str(item["entry_time"]),
            str(item["exit_time"]),
        ),
    ):
        scenario = str(trade["scenario"])
        entry = _parse_timestamp(str(trade["entry_time"]))
        if entry <= available_after.get(scenario, datetime.min.replace(tzinfo=UTC)):
            continue
        regime_start = str(trade.get("ema_regime_start_time") or "")
        regime_key = (scenario, str(trade.get("direction") or ""), regime_start)
        if (
            bool(trade.get("one_trade_per_ema_regime"))
            and regime_start
            and regime_key in used_ema_regimes
        ):
            continue
        selected.append(trade)
        if bool(trade.get("one_trade_per_ema_regime")) and regime_start:
            used_ema_regimes.add(regime_key)
        available_after[scenario] = _parse_timestamp(str(trade["exit_time"]))
    return selected


def _summary_row(
    month: str,
    scenario: str,
    trades: list[dict[str, Any]],
) -> dict[str, Any]:
    robust_trades = [
        trade for trade in trades
        if str(trade["signal_time"]) != EXCEPTIONAL_SIGNAL
    ]
    robust = _aggregate_metrics(robust_trades, starting_balance=100.0)
    return {
        "month": month,
        "scenario": scenario,
        **_aggregate_metrics(trades, starting_balance=100.0),
        "without_exceptional_event_trades": robust["trades"],
        "without_exceptional_event_net_pnl_usd": robust["net_pnl_usd"],
        "without_exceptional_event_profit_factor": robust["profit_factor"],
        "exceptional_event_pnl_usd": sum(
            float(trade["pnl_usd"])
            for trade in trades
            if str(trade["signal_time"]) == EXCEPTIONAL_SIGNAL
        ),
    }


def run(
    output: Path = DEFAULT_OUTPUT,
    *,
    selected_scenarios=None,
    study: str = "plain",
    configuration: dict[str, Any] | None = None,
    max_hold_minutes: float | None = 60,
    exit_days_to_expiry: float | None = None,
    hard_stop_percent: float = -15.0,
    max_spread_percent: float = 3.0,
    min_volume: float = 30.0,
    volume_quantity_multiplier: float = 5.0,
    execution: ExecutionConfig = ExecutionConfig(),
    segments: tuple[Segment, ...] | None = None,
    data_source: str = "PUBLIC_HISTORY",
    data_fidelity: str = "LOW_FIDELITY_SYNTHETIC_BBO",
) -> dict[str, Any]:
    active_segments = tuple(segments or SEGMENTS)
    validate_segments(active_segments)
    selected_scenarios = selected_scenarios or plain_scenarios()
    datasets: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    execution_attempts: list[dict[str, Any]] = []
    decision_events: list[dict[str, Any]] = []
    for segment in active_segments:
        print(f"[backtest] {segment.name}", flush=True)
        report = run_dataset(
            segment.directory,
            start=segment.start,
            end=segment.end,
            scenario_set=selected_scenarios,
            max_hold_minutes=max_hold_minutes,
            exit_days_to_expiry=exit_days_to_expiry,
            hard_stop_percent=hard_stop_percent,
            max_spread_percent=max_spread_percent,
            min_volume=min_volume,
            volume_quantity_multiplier=volume_quantity_multiplier,
            execution=execution,
            data_fidelity=data_fidelity,
        )
        datasets.append(report)
        trades.extend(report["trades"])
        execution_attempts.extend(report.get("execution_attempts", []))
        decision_events.extend(report.get("decision_events", []))
        write_report(report, output / "segments" / segment.name)

    trades = _without_cross_segment_overlap(trades)
    rows: list[dict[str, Any]] = []
    for month in _months_for_segments(active_segments):
        for scenario in selected_scenarios:
            monthly_trades = [
                trade
                for trade in trades
                if trade["scenario"] == scenario.name
                and str(trade["entry_time"]).startswith(month)
            ]
            rows.append(_summary_row(month, scenario.name, monthly_trades))

    combined = {
        scenario.name: _aggregate_metrics(
            [trade for trade in trades if trade["scenario"] == scenario.name],
            starting_balance=100.0,
        )
        for scenario in selected_scenarios
    }
    for scenario in selected_scenarios:
        combined[scenario.name]["profitable_months"] = sum(
            row["scenario"] == scenario.name
            and row["month"] != "TOTAL"
            and float(row["net_pnl_usd"]) > 0.0
            for row in rows
        )
    combined_without_exceptional_event = {
        scenario.name: _aggregate_metrics(
            [
                trade for trade in trades
                if trade["scenario"] == scenario.name
                and str(trade["signal_time"]) != EXCEPTIONAL_SIGNAL
            ],
            starting_balance=100.0,
        )
        for scenario in selected_scenarios
    }
    combined_signal_diagnostics: dict[str, dict[str, int]] = {
        scenario.name: {} for scenario in selected_scenarios
    }
    combined_entry_rejections: dict[str, dict[str, int]] = {
        scenario.name: {} for scenario in selected_scenarios
    }
    signals_with_contract = {scenario.name: 0 for scenario in selected_scenarios}
    for dataset in datasets:
        for scenario_result in dataset["results"]:
            name = str(scenario_result["scenario"]["name"])
            signals_with_contract[name] += int(
                scenario_result.get("signals_with_contract", 0)
            )
            for key, value in scenario_result.get("signal_diagnostics", {}).items():
                combined_signal_diagnostics[name][key] = (
                    combined_signal_diagnostics[name].get(key, 0) + int(value)
                )
            for key, value in scenario_result.get("rejects", {}).items():
                combined_entry_rejections[name][key] = (
                    combined_entry_rejections[name].get(key, 0) + int(value)
                )
    selected_start = min(_parse_timestamp(item.start) for item in active_segments)
    selected_end = max(_parse_timestamp(item.end) for item in active_segments)
    if active_segments == SEGMENTS:
        period_ranges = {
            "development_jan_jun": (
                "2026-01-01T00:00:00+00:00",
                "2026-07-01T00:00:00+00:00",
            ),
            "confirmation_jul_sep": (
                "2026-07-01T00:00:00+00:00",
                "2026-10-01T00:00:00+00:00",
            ),
            "extension_oct_01_03": (
                "2026-10-01T00:00:00+00:00",
                "2026-10-04T00:00:00+00:00",
            ),
        }
    else:
        period_ranges = {
            "selected_period": (selected_start.isoformat(), selected_end.isoformat())
        }
    period_metrics = {
        label: {
            scenario.name: _aggregate_metrics(
                [
                    trade for trade in trades
                    if trade["scenario"] == scenario.name
                    and start <= str(trade["entry_time"]) < end
                ],
                starting_balance=100.0,
            )
            for scenario in selected_scenarios
        }
        for label, (start, end) in period_ranges.items()
    }
    rows.extend(
        {
            "month": "TOTAL",
            "scenario": scenario.name,
            **combined[scenario.name],
            "without_exceptional_event_trades": (
                combined_without_exceptional_event[scenario.name]["trades"]
            ),
            "without_exceptional_event_net_pnl_usd": (
                combined_without_exceptional_event[scenario.name]["net_pnl_usd"]
            ),
            "without_exceptional_event_profit_factor": (
                combined_without_exceptional_event[scenario.name]["profit_factor"]
            ),
            "exceptional_event_pnl_usd": (
                combined[scenario.name]["net_pnl_usd"]
                - combined_without_exceptional_event[scenario.name]["net_pnl_usd"]
            ),
        }
        for scenario in selected_scenarios
    )

    # Keep the potentially large timestamped decision trace out of summary.json.
    # Each segment still writes its own decision_events.csv, and the combined run
    # writes a root decision_events.csv below.
    summary_datasets: list[dict[str, Any]] = []
    for dataset in datasets:
        compact = dict(dataset)
        compact["decision_event_count"] = len(dataset.get("decision_events", []))
        compact.pop("decision_events", None)
        summary_datasets.append(compact)

    result = {
        "created_at": datetime.now(UTC).isoformat(),
        "period": {
            "start": selected_start.isoformat().replace("+00:00", "Z"),
            "end_exclusive": selected_end.isoformat().replace("+00:00", "Z"),
        },
        "method": (
            f"BT1-BT3 {study} research backtest; production strategy.py unchanged."
        ),
        "study": study,
        "configuration": configuration,
        "data_source": data_source,
        "fidelity": data_fidelity,
        "scenarios": [scenario.name for scenario in selected_scenarios],
        "segments": [
            {
                "name": segment.name,
                "directory": str(segment.directory.resolve()),
                "start": segment.start,
                "end": segment.end,
            }
            for segment in active_segments
        ],
        "monthly": [row for row in rows if row["month"] != "TOTAL"],
        "combined": combined,
        "combined_without_exceptional_event": combined_without_exceptional_event,
        "period_metrics": period_metrics,
        "signal_diagnostics": combined_signal_diagnostics,
        "signals_with_contract": signals_with_contract,
        "entry_rejections": combined_entry_rejections,
        "execution_attempt_count": len(execution_attempts),
        "exceptional_event_pnl_usd": {
            scenario.name: (
                combined[scenario.name]["net_pnl_usd"]
                - combined_without_exceptional_event[scenario.name]["net_pnl_usd"]
            )
            for scenario in selected_scenarios
        },
        "exceptional_event_signal": EXCEPTIONAL_SIGNAL,
        "datasets": summary_datasets,
        "decision_event_count": len(decision_events),
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    with (output / "monthly_summary.csv").open("w", encoding="utf-8", newline="") as handle:
        fieldnames = list(dict.fromkeys(key for row in rows for key in row))
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    with (output / "trades.csv").open("w", encoding="utf-8", newline="") as handle:
        if trades:
            writer = csv.DictWriter(handle, fieldnames=list(trades[0]))
            writer.writeheader()
            writer.writerows(sorted(trades, key=lambda item: str(item["entry_time"])))
    with (output / "execution_attempts.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        if execution_attempts:
            fieldnames = list(
                dict.fromkeys(key for row in execution_attempts for key in row)
            )
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(
                sorted(
                    execution_attempts,
                    key=lambda item: str(item["signal_time"]),
                )
            )
    if decision_events:
        with (output / "decision_events.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            fieldnames = list(
                dict.fromkeys(key for row in decision_events for key in row)
            )
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(
                sorted(
                    decision_events,
                    key=lambda item: (
                        str(item.get("timestamp", "")),
                        str(item.get("scenario", "")),
                        str(item.get("stage", "")),
                    ),
                )
            )
    _write_markdown(result, output / "results.md")
    result["trades"] = trades
    return result


def _money(value: float | None) -> str:
    return "N/A" if value is None else f"${value:+.2f}"


def _write_markdown(result: dict[str, Any], path: Path) -> None:
    all_fail = result["study"] == "all_fail"
    stoch_momentum = result["study"] == "stoch_momentum"
    condition_count = result["study"] == "entry_condition_count"
    one_per_ema_regime = result["study"] == "one_per_ema_regime"
    ema_strength = result["study"] == "ema_strength"
    vwap_volume = result["study"] == "vwap_volume"
    ist_windows = result["study"] == "ist_windows"
    ist_windows_fa150 = result["study"] == "ist_windows_fa150"
    ist_windows_dte15 = result["study"] == "ist_windows_dte15"
    stop_execution = result["study"] == "stop_execution"
    configuration = result.get("configuration")
    period_start = _parse_timestamp(str(result["period"]["start"]))
    period_end = _parse_timestamp(str(result["period"]["end_exclusive"]))
    period_label = (
        f"{period_start.date().isoformat()} through "
        f"{(period_end - timedelta(microseconds=1)).date().isoformat()}"
    )
    tested_months = len({str(row["month"]) for row in result["monthly"]})
    fidelity = str(result.get("fidelity", "UNKNOWN"))
    if fidelity == "LOW_FIDELITY_SYNTHETIC_BBO":
        fidelity_description = (
            "Historical option BBO is synthesized with a 1% spread, so fidelity "
            "is LOW_FIDELITY_SYNTHETIC_BBO."
        )
    elif fidelity == "RECORDED_BBO_WITH_INFERRED_SIZE":
        fidelity_description = (
            "Option bid/ask prices are recorded R2 snapshots. Bid/ask sizes are "
            "inferred, so fidelity is RECORDED_BBO_WITH_INFERRED_SIZE."
        )
    else:
        fidelity_description = f"Data fidelity: {fidelity}."
    title = (
        "All-Fail BT1-BT3"
        if all_fail
        else "Momentum-Stoch BT1-BT3"
        if stoch_momentum
        else "Entry Condition Count BT1-BT3"
        if condition_count
        else "BT2 One Trade Per EMA Regime"
        if one_per_ema_regime
        else "BT2 EMA Strength With One Trade Per Regime"
        if ema_strength
        else "BT2 VWAP Displacement And Volume Expansion"
        if vwap_volume
        else "Plain BT1-BT3 By IST Entry Window"
        if ist_windows
        else "Plain BT1-BT3 By IST Entry Window With H6 And FA150"
        if ist_windows_fa150
        else "Plain BT1-BT3 By IST Entry Window Excluding 0-1.5 DTE Options"
        if ist_windows_dte15
        else "BT2 Hard-Stop Execution And Threshold Sensitivity"
        if stop_execution
        else f"Manual Combination: {configuration['name']}"
        if configuration
        else "Plain BT1-BT3"
    )
    manual_all_fail = bool(
        configuration and configuration.get("exit_policy") == "ALL_FAIL"
    )
    manual_relaxed_ema_exit = bool(
        configuration
        and configuration.get("ema_exit_rule") == "FAST_AND_MID_VS_SLOW"
    )
    manual_loose_ema_exit = bool(
        configuration
        and configuration.get("ema_exit_rule") == "FAST_OR_MID_VS_SLOW"
    )
    exit_description = (
        "BT2 exits only when EMA and VWAP both fail; BT3 exits only when EMA, VWAP, "
        "and RSI all fail. BT1 is unchanged because it has only the EMA condition."
        if all_fail or manual_all_fail
        else "Entries retain strict EMA9/EMA20/EMA50 ordering. For exits, CALL EMA "
        "alignment remains valid while EMA9 and EMA20 are both above EMA50; PUT "
        "alignment remains valid while both are below EMA50. EMA9 crossing EMA20 alone "
        "does not trigger an exit. Other BT-family exit conditions remain active."
        if manual_relaxed_ema_exit
        else "Entries retain strict EMA9/EMA20/EMA50 ordering. For exits, CALL EMA "
        "alignment remains valid while either EMA9 or EMA20 is above EMA50; PUT "
        "alignment remains valid while either is below EMA50. The EMA exit therefore "
        "requires both averages to move to the wrong side of EMA50. Other BT-family "
        "exit conditions remain active."
        if manual_loose_ema_exit
        else "Each scenario exits when any condition required by its exit family fails."
    )
    if configuration and configuration.get("profit_protection_enabled"):
        activation = configuration["profit_protection_activation_percent"]
        protected = configuration["profit_protection_protect_percent"]
        exit_description += (
            f" Peak-profit protection activates at +{activation:g}% and protects "
            f"{protected:g}% of the highest open profit reached. The protected stop "
            "ratchets upward; existing condition exits retain priority."
        )
    filter_description = (
        "Entry additionally requires Stoch RSI(14,14,3,3) K > D for CALL and "
        "D > K for PUT on the original BT1/BT2/BT3 signal candle. A later Stoch "
        "cross does not create a new entry. No MACD, H6, FA, M30, UTC-session, "
        "or profit-protection filter is used."
        if stoch_momentum
        else "Entry uses a directional score from VWAP, EMA9/20/50 ordering, and RSI. "
        "The scenario requires at least 1, 2, or 3 agreeing conditions; CALL/PUT score "
        "ties are skipped. No additional MACD, H6, FA, M30, Stoch RSI, UTC-session, "
        "or profit-protection filter is used."
        if condition_count
        else "Both scenarios use the original 3-of-3 BT2 entry. The gated scenario "
        "allows only one successfully entered trade during each continuous directional "
        "EMA9/20/50 regime; rejected entries do not consume the regime."
        if one_per_ema_regime
        else "All scenarios use the original 3-of-3 BT2 entry and allow one trade per "
        "continuous EMA regime. They compare minimum abs(EMA9-EMA50)/ATR14 values of "
        "0.00, 0.25, 0.50, 0.75, and 1.00 on the completed signal candle."
        if ema_strength
        else "All scenarios use the original 3-of-3 BT2 entry and allow one trade per "
        "continuous EMA regime. The fixed research filters compare signal-candle "
        "abs(close-VWAP)/ATR14 >= 1.50, signal volume >= 1.25 times the median volume "
        "of the previous 20 completed candles, and both conditions together."
        if vwap_volume
        else "Plain BT1, BT2, and BT3 are tested independently in four fixed IST "
        "entry windows: 13:30-17:00, 18:30-19:00, 19:00-21:30, and 21:30-23:30. "
        "Only new entries are restricted; an open position follows its normal exit "
        "rules even after the entry window closes."
        if ist_windows
        else "Plain BT1, BT2, and BT3 are tested independently in the four fixed IST "
        "entry windows with H6 and FA150. The selected option must have six valid "
        "completed True Range observations and estimated movement capacity of at "
        "least 1.50 times estimated round-trip fees. Only entries are time-restricted."
        if ist_windows_fa150
        else "Plain BT1, BT2, and BT3 are tested independently in the four fixed IST "
        "entry windows without H6 or FA. Entries use the normally selected nearest "
        "expiry only when it has more than 36 and at most 72 hours remaining at the "
        "signal; options with 1.5 days or less remaining are excluded."
        if ist_windows_dte15
        else "BT2 entry and condition-exit rules are unchanged. The matrix varies only "
        "the hard-stop threshold (-10%, -12.5%, -15%, or -17.5%) and whether a breached "
        "stop fills at the observed quote or the following quote. No additional entry "
        "filter is used."
        if stop_execution
        else "Enabled entry filters: "
        + (", ".join(configuration["enabled_filters"]) or "none")
        + "."
        if configuration
        else "No MACD, H6, FA, M30, UTC-session, Stoch RSI, or profit-protection "
        "filter is used."
    )
    lines = [
        f"# {title}: {period_label}",
        "",
        "Research calculation only. Delta fees and 18% GST are included. "
        + fidelity_description,
        "",
        filter_description,
        "",
        exit_description,
        "",
        "## Monthly Results",
        "",
        "| Month | Scenario | Trades | Win rate | Net P&L | PF | Net without exceptional event |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in result["monthly"]:
        pf = row["profit_factor"]
        pf_text = f"{pf:.3f}" if pf is not None else "N/A"
        win_rate = row["win_rate_percent"]
        win_text = f"{win_rate:.2f}%" if win_rate is not None else "N/A"
        lines.append(
            f"| {row['month']} | {row['scenario']} | {row['trades']} | {win_text} | "
            f"{_money(row['net_pnl_usd'])} | {pf_text} | "
            f"{_money(row['without_exceptional_event_net_pnl_usd'])} |"
        )
    lines.extend((
        "",
        "## Combined Results",
        "",
        "| Scenario | Trades | Wins | Losses | Win rate | Net P&L | PF | Max DD | Avg win | Avg loss | Largest win | P&L/trade | Profitable months | CALL P&L | PUT P&L | Fees | Net without exceptional event | PF without event |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ))
    for scenario, metrics in result["combined"].items():
        robust = result["combined_without_exceptional_event"][scenario]
        pf = metrics["profit_factor"]
        robust_pf = robust["profit_factor"]
        pf_text = f"{pf:.3f}" if pf is not None else "N/A"
        robust_pf_text = f"{robust_pf:.3f}" if robust_pf is not None else "N/A"
        win_rate = metrics["win_rate_percent"]
        win_text = f"{win_rate:.2f}%" if win_rate is not None else "N/A"
        lines.append(
            f"| {scenario} | {metrics['trades']} | {metrics['wins']} | "
            f"{metrics['losses']} | {win_text} | "
            f"{_money(metrics['net_pnl_usd'])} | {pf_text} | "
            f"{_money(metrics['max_drawdown_usd'])} | "
            f"{_money(metrics['average_win_usd'])} | "
            f"{_money(metrics['average_loss_usd'])} | "
            f"{_money(metrics['largest_win_usd'])} | "
            f"{_money(metrics['pnl_per_trade_usd'])} | "
            f"{metrics['profitable_months']}/{tested_months} | "
            f"{_money(metrics['call_pnl_usd'])} | "
            f"{_money(metrics['put_pnl_usd'])} | "
            f"{_money(metrics['fees_usd'])} | "
            f"{_money(robust['net_pnl_usd'])} | {robust_pf_text} |"
        )
    if configuration and configuration.get("zigzag", {}).get("enabled"):
        lines.extend((
            "",
            "## ZigZag Entry Funnel",
            "",
            "Rejections are sequential: each candle appears only at the first stage "
            "that rejects it. Counts include only permitted entry times in the "
            f"configured period ({period_label}).",
            "",
            "| Scenario | Trend candidates | Slope reject | No touch | Touch tolerance reject | RSI reject | Confirmation reject | ATR reject | Qualifying candles | Signals | CALL signals | PUT signals | Signals with contract | Accepted trades |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ))
        for scenario, diagnostics in result["signal_diagnostics"].items():
            metrics = result["combined"][scenario]
            lines.append(
                f"| {scenario} | {diagnostics.get('TREND_CANDIDATES', 0)} | "
                f"{diagnostics.get('SLOPE_REJECTED', 0)} | "
                f"{diagnostics.get('TOUCH_REJECTED', 0)} | "
                f"{diagnostics.get('TOUCH_TOLERANCE_REJECTED', 0)} | "
                f"{diagnostics.get('RSI_REJECTED', 0)} | "
                f"{diagnostics.get('CONFIRMATION_REJECTED', 0)} | "
                f"{diagnostics.get('ATR_REJECTED', 0)} | "
                f"{diagnostics.get('QUALIFYING_CANDLES', 0)} | "
                f"{diagnostics.get('SIGNALS', 0)} | "
                f"{diagnostics.get('CALL_SIGNALS', 0)} | "
                f"{diagnostics.get('PUT_SIGNALS', 0)} | "
                f"{result['signals_with_contract'][scenario]} | "
                f"{metrics['trades']} |"
            )
        lines.extend(("", "### Option And Execution Rejections", ""))
        for scenario, rejects in result["entry_rejections"].items():
            if rejects:
                lines.append(
                    f"- `{scenario}`: "
                    + ", ".join(
                        f"`{reason}` {count}"
                        for reason, count in sorted(rejects.items())
                    )
                )
            else:
                lines.append(f"- `{scenario}`: none")
        lines.append("")
    lines.extend((
        "",
        "## Exceptional Event",
        "",
        f"The robustness column excludes the signal at `{result['exceptional_event_signal']}`. "
        "Its contribution by scenario was: "
        + ", ".join(
            f"`{scenario}` {_money(value)}"
            for scenario, value in result["exceptional_event_pnl_usd"].items()
        )
        + ".",
        "",
    ))
    if vwap_volume:
        lines.extend((
            "## Development And Confirmation",
            "",
            "July-September has already been inspected during diagnosis, so it is a "
            "confirmation period rather than a pristine holdout. Future October data "
            "is still required for a genuine out-of-sample test.",
            "",
            "| Period | Scenario | Trades | Win rate | Gross P&L | Fees | Net P&L | PF | Max DD |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ))
        for period, scenarios_for_period in result["period_metrics"].items():
            for scenario, metrics in scenarios_for_period.items():
                pf = metrics["profit_factor"]
                pf_text = f"{pf:.3f}" if pf is not None else "N/A"
                win_rate = metrics["win_rate_percent"]
                win_text = f"{win_rate:.2f}%" if win_rate is not None else "N/A"
                lines.append(
                    f"| {period} | {scenario} | {metrics['trades']} | {win_text} | "
                    f"{_money(metrics['gross_pnl_usd'])} | {_money(metrics['fees_usd'])} | "
                    f"{_money(metrics['net_pnl_usd'])} | {pf_text} | "
                    f"{_money(metrics['max_drawdown_usd'])} |"
                )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def print_summary(result: dict[str, Any]) -> None:
    print("\nMonth    Trades  Wins  Losses  Win Rate   Net P&L     Robust P&L  PF      Scenario")
    print("-------  ------  ----  ------  ---------  ----------  ----------  ------  --------")
    total_rows = [
        {
            "month": "TOTAL",
            "scenario": name,
            **metrics,
            "without_exceptional_event_net_pnl_usd": (
                result["combined_without_exceptional_event"][name]["net_pnl_usd"]
            ),
        }
        for name, metrics in result["combined"].items()
    ]
    for row in [*result["monthly"], *total_rows]:
        profit_factor = row["profit_factor"]
        pf = f"{profit_factor:.3f}" if profit_factor is not None else "N/A"
        win_rate = row["win_rate_percent"]
        wr = f"{win_rate:.2f}%" if win_rate is not None else "N/A"
        print(
            f"{row['month']:<7}  {row['trades']:>6}  {row['wins']:>4}  "
            f"{row['losses']:>6}  {wr:>9}  ${row['net_pnl_usd']:>+9.2f}  "
            f"${row['without_exceptional_event_net_pnl_usd']:>+9.2f}  "
            f"{pf:>6}  {row['scenario']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backtest BT1-BT3 from January through September 2026",
    )
    parser.add_argument(
        "--exit-policy",
        choices=("plain", "all-fail"),
        default="plain",
    )
    parser.add_argument(
        "--entry-filter",
        choices=(
            "none",
            "stoch-momentum",
            "condition-count",
            "one-per-ema-regime",
            "ema-strength",
            "vwap-volume",
            "ist-windows",
            "ist-windows-fa150",
            "ist-windows-dte15",
        ),
        default="none",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.exit_policy == "all-fail" and args.entry_filter != "none":
        parser.error("the Stoch momentum study uses the plain exit policy")
    if args.entry_filter == "stoch-momentum":
        selected_scenarios = momentum_stoch_scenarios()
        output = args.output or DEFAULT_STOCH_MOMENTUM_OUTPUT
        study = "stoch_momentum"
    elif args.entry_filter == "condition-count":
        selected_scenarios = condition_count_scenarios()
        output = args.output or DEFAULT_ENTRY_CONDITION_COUNT_OUTPUT
        study = "entry_condition_count"
    elif args.entry_filter == "one-per-ema-regime":
        selected_scenarios = ema_regime_trade_scenarios()
        output = args.output or DEFAULT_ONE_PER_EMA_REGIME_OUTPUT
        study = "one_per_ema_regime"
    elif args.entry_filter == "ema-strength":
        selected_scenarios = trend_strength_scenarios()
        output = args.output or DEFAULT_EMA_STRENGTH_OUTPUT
        study = "ema_strength"
    elif args.entry_filter == "vwap-volume":
        selected_scenarios = displacement_volume_scenarios()
        output = args.output or DEFAULT_VWAP_VOLUME_OUTPUT
        study = "vwap_volume"
    elif args.entry_filter == "ist-windows":
        selected_scenarios = plain_ist_window_scenarios()
        output = args.output or DEFAULT_IST_WINDOWS_OUTPUT
        study = "ist_windows"
    elif args.entry_filter == "ist-windows-fa150":
        selected_scenarios = plain_ist_window_fa150_scenarios()
        output = args.output or DEFAULT_IST_WINDOWS_FA150_OUTPUT
        study = "ist_windows_fa150"
    elif args.entry_filter == "ist-windows-dte15":
        selected_scenarios = plain_ist_window_dte15_scenarios()
        output = args.output or DEFAULT_IST_WINDOWS_DTE15_OUTPUT
        study = "ist_windows_dte15"
    elif args.exit_policy == "all-fail":
        selected_scenarios = all_fail_scenarios()
        output = args.output or DEFAULT_ALL_FAIL_OUTPUT
        study = "all_fail"
    else:
        selected_scenarios = plain_scenarios()
        output = args.output or DEFAULT_OUTPUT
        study = "plain"
    result = run(output, selected_scenarios=selected_scenarios, study=study)
    print_summary(result)
    print(f"\nReports ready: {output.resolve()}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(f"Error: {exc}") from None
