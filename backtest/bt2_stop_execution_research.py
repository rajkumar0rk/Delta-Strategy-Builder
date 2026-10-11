from __future__ import annotations

import csv
import statistics
from dataclasses import replace
from pathlib import Path
from typing import Any

from .plain_bt123_2026 import (
    EXCEPTIONAL_SIGNAL,
    plain_scenarios,
    print_summary,
    run,
)


DEFAULT_OUTPUT = Path("backtest/reports/bt2-stop-execution-jan-sep-2026")
STOP_PERCENTAGES = (-10.0, -12.5, -15.0, -17.5)
FILL_MODES = ("SAME_QUOTE", "NEXT_QUOTE")


def stop_execution_scenarios():
    base = next(scenario for scenario in plain_scenarios() if scenario.group == 2)
    return [
        replace(
            base,
            name=(
                f"BT2_STOP_{str(abs(stop)).replace('.', 'P')}PCT_{fill_mode}"
            ),
            hard_stop_percent_override=stop,
            hard_stop_fill_mode=fill_mode,
        )
        for fill_mode in FILL_MODES
        for stop in STOP_PERCENTAGES
    ]


def _comparison_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    scenarios = {
        scenario.name: scenario for scenario in stop_execution_scenarios()
    }
    rows: list[dict[str, Any]] = []
    for name, scenario in scenarios.items():
        metrics = result["combined"][name]
        robust = result["combined_without_exceptional_event"][name]
        trades = [
            trade
            for trade in result["trades"]
            if trade["scenario"] == name
            and str(trade["signal_time"]) != EXCEPTIONAL_SIGNAL
        ]
        hard_stops = [trade for trade in trades if trade["exit_reason"] == "HARD_STOP"]
        stop_returns = [float(trade["return_percent"]) for trade in hard_stops]
        overshoots = [
            max(0.0, scenario.hard_stop_percent_override - value)
            for value in stop_returns
        ]
        positive_months = sum(
            row["scenario"] == name
            and float(row["without_exceptional_event_net_pnl_usd"]) > 0.0
            for row in result["monthly"]
        )
        rows.append({
            "scenario": name,
            "fill_mode": scenario.hard_stop_fill_mode,
            "configured_stop_percent": scenario.hard_stop_percent_override,
            "trades": metrics["trades"],
            "win_rate_percent": metrics["win_rate_percent"],
            "net_pnl_usd": metrics["net_pnl_usd"],
            "profit_factor": metrics["profit_factor"],
            "max_drawdown_usd": metrics["max_drawdown_usd"],
            "robust_net_pnl_usd": robust["net_pnl_usd"],
            "robust_profit_factor": robust["profit_factor"],
            "positive_robust_months": positive_months,
            "hard_stop_trades": len(hard_stops),
            "average_hard_stop_return_percent": (
                statistics.fmean(stop_returns) if stop_returns else None
            ),
            "median_hard_stop_return_percent": (
                statistics.median(stop_returns) if stop_returns else None
            ),
            "average_stop_overshoot_points": (
                statistics.fmean(overshoots) if overshoots else None
            ),
        })
    return rows


def _number(value: float | None, places: int = 2) -> str:
    return "N/A" if value is None else f"{value:.{places}f}"


def write_comparison(result: dict[str, Any], output: Path) -> list[dict[str, Any]]:
    rows = _comparison_rows(result)
    with (output / "stop_comparison.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "# BT2 Hard-Stop Execution Comparison",
        "",
        "January-September 2026. Entry and normal BT2 condition exits are unchanged. ",
        "Delta fees and 18% GST are included. Historical option BBO is synthesized ",
        "from one-minute candles with a 1% spread, so SAME_QUOTE and NEXT_QUOTE are ",
        "optimistic and pessimistic execution boundaries rather than precise fills.",
        "",
        "The robust columns exclude the exceptional signal at ",
        f"`{EXCEPTIONAL_SIGNAL}`.",
        "",
        "| Fill | Stop | Trades | Win rate | Net P&L | PF | Robust P&L | Robust PF | Positive months | Hard stops | Avg stop return | Median stop return | Avg overshoot | Max DD |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['fill_mode']} | {_number(row['configured_stop_percent'])}% | "
            f"{row['trades']} | {_number(row['win_rate_percent'])}% | "
            f"${row['net_pnl_usd']:+.2f} | {_number(row['profit_factor'], 3)} | "
            f"${row['robust_net_pnl_usd']:+.2f} | "
            f"{_number(row['robust_profit_factor'], 3)} | "
            f"{row['positive_robust_months']}/9 | {row['hard_stop_trades']} | "
            f"{_number(row['average_hard_stop_return_percent'])}% | "
            f"{_number(row['median_hard_stop_return_percent'])}% | "
            f"{_number(row['average_stop_overshoot_points'])} pp | "
            f"${row['max_drawdown_usd']:.2f} |"
        )
    (output / "stop_execution_analysis.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return rows


def main() -> None:
    scenarios = stop_execution_scenarios()
    result = run(
        DEFAULT_OUTPUT,
        selected_scenarios=scenarios,
        study="stop_execution",
    )
    rows = write_comparison(result, DEFAULT_OUTPUT)
    print_summary(result)
    print("\nStop comparison")
    for row in rows:
        print(
            f"{row['fill_mode']:10} {row['configured_stop_percent']:5.1f}% "
            f"net=${row['net_pnl_usd']:+8.2f} "
            f"robust=${row['robust_net_pnl_usd']:+8.2f} "
            f"PF={_number(row['profit_factor'], 3)}"
        )
    print(f"\nReports ready: {DEFAULT_OUTPUT.resolve()}")


if __name__ == "__main__":
    main()
