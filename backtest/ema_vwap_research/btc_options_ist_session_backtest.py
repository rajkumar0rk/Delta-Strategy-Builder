from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

# This file and core.py live together under:
#   backtest/ema_vwap_research/
# It can be run directly from the repository root.
THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from core import (  # noqa: E402
    Scenario,
    _metrics,
    _option_specs,
    capture_quotes,
    indicators,
    signal_events,
    simulate_trade,
)


UTC = timezone.utc
IST = ZoneInfo("Asia/Kolkata")
OUTLIER_SIGNAL = "2026-08-19T14:35:00+00:00"


@dataclass(frozen=True)
class IstWindow:
    key: str
    label: str
    ranges: tuple[tuple[int, int], ...]

    def contains_timestamp(self, timestamp: datetime) -> bool:
        local = timestamp.astimezone(IST)
        minute = local.hour * 60 + local.minute
        return any(start <= minute < end for start, end in self.ranges)

    def contains_ns(self, timestamp_ns: int) -> bool:
        return self.contains_timestamp(
            datetime.fromtimestamp(timestamp_ns / 1_000_000_000, tz=UTC)
        )

    def contains_iso(self, timestamp: str) -> bool:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return self.contains_timestamp(parsed)


# End times are exclusive. Positions may continue to their normal exit after
# the entry window closes; only NEW entries are blocked outside these windows.
IST_WINDOWS: tuple[IstWindow, ...] = (
    IstWindow(
        key="IST_1330_1700",
        label="13:30-17:00 IST (Europe activity)",
        ranges=((13 * 60 + 30, 17 * 60),),
    ),
    IstWindow(
        key="IST_1830_1900",
        label="18:30-19:00 IST (setup / transition)",
        ranges=((18 * 60 + 30, 19 * 60),),
    ),
    IstWindow(
        key="IST_1900_2130",
        label="19:00-21:30 IST (US prime)",
        ranges=((19 * 60, 21 * 60 + 30),),
    ),
    IstWindow(
        key="IST_2130_2330",
        label="21:30-23:30 IST (US continuation)",
        ranges=((21 * 60 + 30, 23 * 60 + 30),),
    ),
    IstWindow(
        key="IST_ACTIVE_COMBINED",
        label="Combined active windows",
        ranges=(
            (13 * 60 + 30, 17 * 60),
            (18 * 60 + 30, 23 * 60 + 30),
        ),
    ),
)


def _family_scenarios() -> list[Scenario]:
    """Current BT1-BT3 family exits, with and without MACD entry confirmation."""
    exits = (("EMA", 1), ("EMA_VWAP", 2), ("EMA_VWAP_RSI", 3))
    result: list[Scenario] = []
    for exit_mode, group in exits:
        result.append(Scenario(f"BT{group}_{exit_mode}", group, exit_mode))
        result.append(
            Scenario(
                f"BT{group}_{exit_mode}_MACD",
                group,
                exit_mode,
                require_macd=True,
            )
        )
    return result


def _macd_reversal_only_scenarios() -> list[Scenario]:
    """
    Locked MACD-reversal-only policy.

    BT1-BT3 become behaviorally identical when the family condition exit is
    disabled, so this study keeps one unconfirmed and one MACD-entry version
    rather than duplicating identical trades three times.
    """
    return [
        Scenario(
            "BT_MACDREV_ONLY",
            1,
            "EMA",
            macd_exit_policy="REVERSAL_ONLY",
        ),
        Scenario(
            "BT_MACD_ENTRY_MACDREV_ONLY",
            1,
            "EMA",
            require_macd=True,
            macd_exit_policy="REVERSAL_ONLY",
        ),
    ]


def _macd_or_all_fail_scenarios() -> list[Scenario]:
    """Locked MACD reversal OR All-Fail policy for BT1-BT3."""
    exits = (("EMA", 1), ("EMA_VWAP", 2), ("EMA_VWAP_RSI", 3))
    result: list[Scenario] = []
    for exit_mode, group in exits:
        result.append(
            Scenario(
                f"BT{group}_{exit_mode}_ALLFAIL_MACDEXIT",
                group,
                exit_mode,
                exit_when_all_fail=True,
                macd_reversal_exit=True,
            )
        )
        result.append(
            Scenario(
                f"BT{group}_{exit_mode}_MACD_ALLFAIL_MACDEXIT",
                group,
                exit_mode,
                require_macd=True,
                exit_when_all_fail=True,
                macd_reversal_exit=True,
            )
        )
    return result


def build_scenarios(policy: str) -> list[Scenario]:
    if policy == "family":
        return _family_scenarios()
    if policy == "macd_rev_only":
        return _macd_reversal_only_scenarios()
    if policy == "macd_or_allfail":
        return _macd_or_all_fail_scenarios()
    if policy == "all":
        return (
            _family_scenarios()
            + _macd_reversal_only_scenarios()
            + _macd_or_all_fail_scenarios()
        )
    raise ValueError(f"Unknown policy: {policy}")


def scenario_policy(scenario: Scenario) -> str:
    if scenario.macd_exit_policy == "REVERSAL_ONLY":
        return "MACD_REVERSAL_ONLY"
    if scenario.macd_reversal_exit and scenario.exit_when_all_fail:
        return "MACD_REVERSAL_OR_ALL_FAIL"
    return "FAMILY_EXIT"


def _extra_metrics(trades: list[dict[str, Any]]) -> dict[str, float]:
    gross = sum(float(item["gross_pnl_usd"]) for item in trades)
    fees = sum(float(item["fees_usd"]) for item in trades)
    without_exception = sum(
        float(item["pnl_usd"])
        for item in trades
        if str(item["signal_time"]) != OUTLIER_SIGNAL
    )
    return {
        "gross_pnl_usd": gross,
        "fees_usd": fees,
        "net_pnl_without_exception_usd": without_exception,
    }


def _dataset_label(directory: Path) -> str:
    return directory.resolve().name


def run_session_dataset(
    directory: Path,
    *,
    start: str,
    end: str,
    scenario_set: list[Scenario],
    windows: Iterable[IstWindow] = IST_WINDOWS,
    starting_balance: float = 100.0,
    premium_budget_usd: float = 6.67,
    hard_stop_percent: float = -15.0,
    max_hold_minutes: int = 60,
    max_spread_percent: float = 3.0,
    min_volume: float = 30.0,
    volume_quantity_multiplier: float = 5.0,
    option_fee_notional_rate: float = 0.0001,
    option_fee_premium_cap_rate: float = 0.035,
    fee_gst_rate: float = 0.18,
) -> dict[str, Any]:
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    start_ns = int(start_dt.timestamp() * 1_000_000_000)
    end_ns = int(end_dt.timestamp() * 1_000_000_000)

    frame = indicators(directory / "underlying_bars.csv")
    specs = _option_specs(directory / "option_instruments.csv")

    # Generate the current research signals unrestricted by hour, then apply
    # minute-accurate IST session windows below.
    require_macd_values = sorted({item.require_macd for item in scenario_set})
    events_by_macd = {
        require_macd: signal_events(
            frame,
            specs,
            start_ns,
            end_ns,
            confirmation_candles=0,
            require_macd=require_macd,
            entry_start_hour_utc=0,
            entry_end_hour_utc=24,
        )
        for require_macd in require_macd_values
    }

    unique_events: dict[tuple[int, str, str], Any] = {}
    for events in events_by_macd.values():
        for event in events:
            unique_events[(event.timestamp_ns, event.direction, event.option.symbol)] = event

    capture_quotes(
        directory / "option_quotes.csv",
        list(unique_events.values()),
    )

    # Make sure every configuration points at the quote-populated object when
    # an event exists in more than one signal configuration.
    for require_macd, events in events_by_macd.items():
        events_by_macd[require_macd] = [
            unique_events[(event.timestamp_ns, event.direction, event.option.symbol)]
            for event in events
        ]

    result_rows: list[dict[str, Any]] = []
    all_trades: list[dict[str, Any]] = []

    for window in windows:
        for scenario in scenario_set:
            candidate_events = [
                event
                for event in events_by_macd[scenario.require_macd]
                if window.contains_ns(event.timestamp_ns)
            ]

            trades: list[dict[str, Any]] = []
            rejects: dict[str, int] = {}
            available_after_ns = start_ns

            for event in candidate_events:
                if event.timestamp_ns <= available_after_ns:
                    continue

                trade, rejection = simulate_trade(
                    event,
                    frame,
                    scenario,
                    premium_budget_usd=premium_budget_usd,
                    hard_stop_percent=hard_stop_percent,
                    max_hold_minutes=max_hold_minutes,
                    max_spread_percent=max_spread_percent,
                    min_volume=min_volume,
                    volume_quantity_multiplier=volume_quantity_multiplier,
                    option_fee_notional_rate=option_fee_notional_rate,
                    option_fee_premium_cap_rate=option_fee_premium_cap_rate,
                    fee_gst_rate=fee_gst_rate,
                )

                if rejection:
                    rejects[rejection] = rejects.get(rejection, 0) + 1
                    continue

                assert trade is not None

                # The signal must be in the window and the actual next-ask fill
                # must also still be in the window. Exits can occur afterwards.
                if not window.contains_iso(str(trade["entry_time"])):
                    rejects["ENTRY_FILL_OUTSIDE_SESSION"] = (
                        rejects.get("ENTRY_FILL_OUTSIDE_SESSION", 0) + 1
                    )
                    continue

                enriched = dict(trade)
                enriched["dataset"] = _dataset_label(directory)
                enriched["session"] = window.key
                enriched["session_label"] = window.label
                enriched["policy"] = scenario_policy(scenario)
                trades.append(enriched)
                all_trades.append(enriched)
                available_after_ns = int(
                    datetime.fromisoformat(
                        str(trade["exit_time"]).replace("Z", "+00:00")
                    ).timestamp()
                    * 1_000_000_000
                )

            metrics = _metrics(trades, starting_balance)
            result_rows.append(
                {
                    "dataset": _dataset_label(directory),
                    "session": window.key,
                    "session_label": window.label,
                    "policy": scenario_policy(scenario),
                    "scenario": scenario.name,
                    **metrics,
                    **_extra_metrics(trades),
                    "rejects": rejects,
                }
            )

    return {
        "data_directory": str(directory.resolve()),
        "start": start,
        "end": end,
        "settings": {
            "starting_balance": starting_balance,
            "premium_budget_usd": premium_budget_usd,
            "hard_stop_percent": hard_stop_percent,
            "max_hold_minutes": max_hold_minutes,
            "max_spread_percent": max_spread_percent,
            "min_volume": min_volume,
            "volume_quantity_multiplier": volume_quantity_multiplier,
            "fill_model": "next ask entry; next bid after exit trigger",
            "fees": {
                "option_notional_rate": option_fee_notional_rate,
                "option_premium_cap_rate": option_fee_premium_cap_rate,
                "gst_rate": fee_gst_rate,
            },
            "outlier_signal": OUTLIER_SIGNAL,
        },
        "results": result_rows,
        "trades": all_trades,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    flattened: list[dict[str, Any]] = []
    for row in rows:
        copy = dict(row)
        if isinstance(copy.get("rejects"), dict):
            copy["rejects"] = json.dumps(copy["rejects"], sort_keys=True)
        flattened.append(copy)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(flattened[0]))
        writer.writeheader()
        writer.writerows(flattened)


def _combined_summary_rows(
    datasets: list[dict[str, Any]],
    starting_balance: float,
) -> list[dict[str, Any]]:
    all_trades = [trade for dataset in datasets for trade in dataset["trades"]]
    keys = sorted(
        {
            (str(trade["session"]), str(trade["session_label"]), str(trade["policy"]), str(trade["scenario"]))
            for trade in all_trades
        }
    )

    # Preserve zero-trade combinations too.
    all_result_keys = sorted(
        {
            (
                str(result["session"]),
                str(result["session_label"]),
                str(result["policy"]),
                str(result["scenario"]),
            )
            for dataset in datasets
            for result in dataset["results"]
        }
    )
    if all_result_keys:
        keys = all_result_keys

    rows: list[dict[str, Any]] = []
    for session, session_label, policy, scenario in keys:
        selected = [
            trade
            for trade in all_trades
            if trade["session"] == session
            and trade["policy"] == policy
            and trade["scenario"] == scenario
        ]
        metrics = _metrics(selected, starting_balance)
        rows.append(
            {
                "dataset": "COMBINED",
                "session": session,
                "session_label": session_label,
                "policy": policy,
                "scenario": scenario,
                **metrics,
                **_extra_metrics(selected),
            }
        )
    return rows


def _rankable_value(value: Any) -> float:
    if value is None:
        return -math.inf
    try:
        number = float(value)
    except (TypeError, ValueError):
        return -math.inf
    return number if math.isfinite(number) else -math.inf


def print_console_summary(rows: list[dict[str, Any]]) -> None:
    combined = [row for row in rows if row["dataset"] == "COMBINED"]
    if not combined:
        return

    print("\n" + "=" * 100)
    print("BTC OPTIONS IST SESSION BACKTEST - COMBINED DEVELOPMENT + HOLDOUT")
    print("=" * 100)
    print(
        f"{'SESSION':<22} {'POLICY':<28} {'SCENARIO':<42} "
        f"{'TRADES':>7} {'WIN%':>8} {'NET':>10} {'NO-OUTLIER':>12} {'PF':>8} {'MAX DD':>10}"
    )
    print("-" * 155)

    for row in sorted(
        combined,
        key=lambda item: (
            str(item["session"]),
            str(item["policy"]),
            str(item["scenario"]),
        ),
    ):
        win_rate = row["win_rate_percent"]
        pf = row["profit_factor"]
        print(
            f"{str(row['session']):<22} "
            f"{str(row['policy']):<28} "
            f"{str(row['scenario']):<42} "
            f"{int(row['trades']):>7} "
            f"{(f'{float(win_rate):.2f}' if win_rate is not None else 'N/A'):>8} "
            f"{float(row['net_pnl_usd']):>+10.2f} "
            f"{float(row['net_pnl_without_exception_usd']):>+12.2f} "
            f"{(f'{float(pf):.3f}' if pf is not None else 'N/A'):>8} "
            f"{float(row['max_drawdown_usd']):>10.2f}"
        )

    # This is a research convenience only: it surfaces the highest net rows;
    # do not treat it as evidence of a stable live edge.
    print("\nTop rows by outlier-free net P&L (research sorting only):")
    for row in sorted(
        combined,
        key=lambda item: _rankable_value(item["net_pnl_without_exception_usd"]),
        reverse=True,
    )[:10]:
        print(
            f"  {row['session']} | {row['scenario']} | "
            f"trades={row['trades']} | net=${float(row['net_pnl_usd']):+.2f} | "
            f"without_exception=${float(row['net_pnl_without_exception_usd']):+.2f} | "
            f"PF={row['profit_factor']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backtest the active BT1-BT3 BTC option research across selected IST trading windows."
        )
    )
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--policy",
        choices=("family", "macd_rev_only", "macd_or_allfail", "all"),
        default="all",
        help="Which active exit-policy family to test (default: all).",
    )
    parser.add_argument(
        "--development-start",
        default="2026-08-24T00:00:00Z",
    )
    parser.add_argument(
        "--development-end",
        default="2026-09-23T00:00:00Z",
    )
    parser.add_argument(
        "--holdout-start",
        default="2026-07-25T00:00:00Z",
    )
    parser.add_argument(
        "--holdout-end",
        default="2026-08-24T00:00:00Z",
    )
    parser.add_argument("--starting-balance", type=float, default=100.0)
    parser.add_argument("--premium-budget", type=float, default=6.67)
    args = parser.parse_args()

    selected_scenarios = build_scenarios(args.policy)

    datasets = [
        run_session_dataset(
            args.development,
            start=args.development_start,
            end=args.development_end,
            scenario_set=selected_scenarios,
            starting_balance=args.starting_balance,
            premium_budget_usd=args.premium_budget,
        ),
        run_session_dataset(
            args.holdout,
            start=args.holdout_start,
            end=args.holdout_end,
            scenario_set=selected_scenarios,
            starting_balance=args.starting_balance,
            premium_budget_usd=args.premium_budget,
        ),
    ]

    output = args.output
    output.mkdir(parents=True, exist_ok=True)

    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "method": (
            "Research-only IST timing study using local self-contained core.py; "
            "existing production/research files are not modified."
        ),
        "policy": args.policy,
        "sessions": [asdict(window) for window in IST_WINDOWS],
        "scenarios": [asdict(item) for item in selected_scenarios],
        "datasets": [
            {
                key: value
                for key, value in dataset.items()
                if key != "trades"
            }
            for dataset in datasets
        ],
    }
    (output / "session_matrix_summary.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    dataset_rows = [result for dataset in datasets for result in dataset["results"]]
    combined_rows = _combined_summary_rows(datasets, args.starting_balance)
    all_rows = dataset_rows + combined_rows

    _write_csv(output / "session_matrix_summary.csv", all_rows)
    _write_csv(output / "trades.csv", [trade for dataset in datasets for trade in dataset["trades"]])

    print_console_summary(all_rows)
    print(f"\nResults written to: {output.resolve()}")


if __name__ == "__main__":
    main()
