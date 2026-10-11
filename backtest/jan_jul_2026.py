from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .data import timestamp_ns
from .ema_vwap_research import (
    Scenario,
    locked_h6_fa150_m30_scenarios,
    locked_h6_fa150_m30_stoch_scenarios,
    locked_h6_fa150_utc08_scenarios,
    run_dataset,
    stoch_scenarios,
    write_report,
)
from .providers.delta_india import DeltaPublicClient, sync_historical_dataset


UTC = timezone.utc
START = "2026-01-01T00:00:00Z"
END = "2026-08-01T00:00:00Z"
DEFAULT_DATA = Path("backtest/data/delta-history/segments/2026-01_07")
DEFAULT_REPORT = Path("backtest/reports/h6-fa150-utc08-jan-jul-2026")
PREFERRED_SCENARIO = "BT1_EMA_MACD_MACDREV_ONLY_H6_FA150_UTC08_16"
M30_SCENARIO = "BT1_EMA_MACD_MACDREV_ONLY_H6_FA150_M30_UTC00_16"


@dataclass(frozen=True)
class MonthRange:
    label: str
    start: str
    end: str


MONTHS = (
    MonthRange("2026-01", "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"),
    MonthRange("2026-02", "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z"),
    MonthRange("2026-03", "2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z"),
    MonthRange("2026-04", "2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z"),
    MonthRange("2026-05", "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z"),
    MonthRange("2026-06", "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"),
    MonthRange("2026-07", "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"),
)


def preferred_scenario() -> Scenario:
    return next(
        scenario
        for scenario in locked_h6_fa150_utc08_scenarios()
        if scenario.name == PREFERRED_SCENARIO
    )


def research_scenarios() -> list[Scenario]:
    m30 = next(
        scenario
        for scenario in locked_h6_fa150_m30_scenarios()
        if scenario.name == M30_SCENARIO
    )
    return [
        preferred_scenario(),
        m30,
        *locked_h6_fa150_m30_stoch_scenarios(),
        *stoch_scenarios(),
    ]


def _retryable_download_error(exc: RuntimeError) -> bool:
    message = str(exc)
    return message.startswith("Delta API request failed:") or any(
        f"Delta API returned HTTP {status}" in message
        for status in (429, 500, 502, 503, 504)
    )


def _with_download_retries(
    operation: Callable[[int], dict[str, Any]],
    *,
    attempts: int,
    wait_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if attempts < 1:
        raise ValueError("resume attempts must be at least 1")
    if wait_seconds < 0:
        raise ValueError("retry wait seconds cannot be negative")
    for attempt in range(1, attempts + 1):
        try:
            return operation(attempt)
        except RuntimeError as exc:
            if not _retryable_download_error(exc) or attempt == attempts:
                raise
            delay = min(wait_seconds * (2 ** (attempt - 1)), 60.0)
            print(
                f"[retry] transient download failure: {exc}\n"
                f"[retry] resuming from cached files in {delay:.0f}s "
                f"(attempt {attempt + 1}/{attempts})",
                flush=True,
            )
            sleep(delay)
    raise AssertionError("download retry loop ended unexpectedly")


def download(
    data_directory: Path,
    *,
    refresh: bool = False,
    resume_attempts: int = 20,
    retry_wait_seconds: float = 15.0,
) -> dict[str, Any]:
    client = DeltaPublicClient("https://api.india.delta.exchange")
    counts = _with_download_retries(
        lambda attempt: sync_historical_dataset(
            client,
            data_directory,
            start=timestamp_ns(START) // 1_000_000_000,
            end=timestamp_ns(END) // 1_000_000_000,
            warmup_bars=150,
            candle_seconds=300,
            option_resolution="1m",
            estimated_spread_percent=1.0,
            expiry_horizon_days=3,
            strikes_around_atm=3,
            min_days_to_expiry=1,
            allow_same_day_expiry=False,
            refresh=refresh and attempt == 1,
            progress=lambda message: print(message, flush=True),
        ),
        attempts=resume_attempts,
        wait_seconds=retry_wait_seconds,
    )
    manifest = {
        "source": "delta_india_public_history",
        "generated_at": datetime.now(UTC).isoformat(),
        "start": START,
        "end_exclusive": END,
        "months": [month.label for month in MONTHS],
        "historical_option_bbo_included": False,
        "execution_prices": "option candle close with 1% synthetic spread",
        "warning": "LOW_FIDELITY: estimated quotes are not historical L1 observations.",
        **counts,
    }
    data_directory.mkdir(parents=True, exist_ok=True)
    (data_directory / "sync_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def _required_dataset_files(data_directory: Path) -> Iterable[Path]:
    yield data_directory / "underlying_bars.csv"
    yield data_directory / "option_instruments.csv"
    yield data_directory / "option_quotes.csv"
    yield data_directory / "raw" / "candles" / "1m"


def validate_dataset(data_directory: Path) -> None:
    missing = [path for path in _required_dataset_files(data_directory) if not path.exists()]
    if missing:
        formatted = "\n".join(f"- {path}" for path in missing)
        raise RuntimeError(
            "The January-July dataset is incomplete. Run the download command first.\n"
            f"Missing:\n{formatted}"
        )


def _aggregate_metrics(trades: list[dict[str, Any]], starting_balance: float) -> dict[str, Any]:
    ordered = sorted(trades, key=lambda item: (str(item["entry_time"]), str(item["exit_time"])))
    pnl = [float(item["pnl_usd"]) for item in ordered]
    winning_pnl = [value for value in pnl if value > 0.0]
    losing_pnl = [value for value in pnl if value < 0.0]
    gross_profit = sum(value for value in pnl if value > 0.0)
    gross_loss = abs(sum(value for value in pnl if value < 0.0))
    equity = starting_balance
    peak = starting_balance
    max_drawdown = 0.0
    for value in pnl:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "trades": len(ordered),
        "wins": sum(value > 0.0 for value in pnl),
        "losses": sum(value < 0.0 for value in pnl),
        "win_rate_percent": 100.0 * sum(value > 0.0 for value in pnl) / len(pnl) if pnl else None,
        "gross_pnl_usd": sum(float(item["gross_pnl_usd"]) for item in ordered),
        "fees_usd": sum(float(item["fees_usd"]) for item in ordered),
        "net_pnl_usd": sum(pnl),
        "return_percent": 100.0 * sum(pnl) / starting_balance,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0.0 else None,
        "expectancy_usd": sum(pnl) / len(pnl) if pnl else None,
        "pnl_per_trade_usd": sum(pnl) / len(pnl) if pnl else None,
        "average_win_usd": (
            sum(winning_pnl) / len(winning_pnl) if winning_pnl else None
        ),
        "average_loss_usd": (
            sum(losing_pnl) / len(losing_pnl) if losing_pnl else None
        ),
        "largest_win_usd": max(winning_pnl) if winning_pnl else None,
        "call_trades": sum(item.get("direction") == "CALL" for item in ordered),
        "put_trades": sum(item.get("direction") == "PUT" for item in ordered),
        "call_pnl_usd": sum(
            float(item["pnl_usd"])
            for item in ordered
            if item.get("direction") == "CALL"
        ),
        "put_pnl_usd": sum(
            float(item["pnl_usd"])
            for item in ordered
            if item.get("direction") == "PUT"
        ),
        "max_drawdown_usd": max_drawdown,
    }


def _summary_row(
    label: str,
    report: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    scenario = str(result["scenario"]["name"])
    metrics = result["metrics"]
    trades = [trade for trade in report["trades"] if trade["scenario"] == scenario]
    return {
        "month": label,
        "scenario": scenario,
        "trades": metrics["trades"],
        "wins": metrics["wins"],
        "losses": metrics["losses"],
        "win_rate_percent": metrics["win_rate_percent"],
        "gross_pnl_usd": sum(float(item["gross_pnl_usd"]) for item in trades),
        "fees_usd": sum(float(item["fees_usd"]) for item in trades),
        "net_pnl_usd": metrics["net_pnl_usd"],
        "return_percent": metrics["return_percent"],
        "profit_factor": metrics["profit_factor"],
        "expectancy_usd": metrics["expectancy_usd"],
        "max_drawdown_usd": metrics["max_drawdown_usd"],
    }


def backtest(data_directory: Path, report_directory: Path) -> dict[str, Any]:
    validate_dataset(data_directory)
    scenarios = research_scenarios()
    datasets: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    all_trades: list[dict[str, Any]] = []

    for month in MONTHS:
        print(f"[backtest] {month.label}", flush=True)
        report = run_dataset(
            data_directory,
            start=month.start,
            end=month.end,
            scenario_set=scenarios,
        )
        datasets.append(report)
        rows.extend(
            _summary_row(month.label, report, result)
            for result in report["results"]
        )
        all_trades.extend(report["trades"])
        write_report(report, report_directory / month.label)

    combined = {
        scenario.name: _aggregate_metrics(
            [trade for trade in all_trades if trade["scenario"] == scenario.name],
            starting_balance=100.0,
        )
        for scenario in scenarios
    }
    rows.extend(
        {"month": "TOTAL", "scenario": scenario.name, **combined[scenario.name]}
        for scenario in scenarios
    )
    result = {
        "created_at": datetime.now(UTC).isoformat(),
        "method": "Research-only calculation backtest.",
        "scenarios": [scenario.name for scenario in scenarios],
        "data_directory": str(data_directory.resolve()),
        "start": START,
        "end_exclusive": END,
        "fidelity": "LOW_FIDELITY_SYNTHETIC_BBO",
        "monthly": [row for row in rows if row["month"] != "TOTAL"],
        "combined": combined,
        "datasets": datasets,
    }
    report_directory.mkdir(parents=True, exist_ok=True)
    (report_directory / "summary.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    with (report_directory / "monthly_summary.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        fieldnames = list(dict.fromkeys(key for row in rows for key in row))
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    if all_trades:
        with (report_directory / "trades.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=list(all_trades[0]))
            writer.writeheader()
            writer.writerows(sorted(all_trades, key=lambda item: str(item["entry_time"])))
    return result


def _print_summary(result: dict[str, Any]) -> None:
    print("\nMonth    Trades  Wins  Losses  Net P&L     PF      Scenario")
    print("-------  ------  ----  ------  ----------  ------  --------")
    for row in result["monthly"]:
        profit_factor = row["profit_factor"]
        pf = f"{profit_factor:.3f}" if profit_factor is not None else "N/A"
        print(
            f"{row['month']:<7}  {row['trades']:>6}  {row['wins']:>4}  "
            f"{row['losses']:>6}  ${row['net_pnl_usd']:>+9.2f}  {pf:>6}  "
            f"{row['scenario']}"
        )
    for scenario, combined in result["combined"].items():
        combined_pf = combined["profit_factor"]
        pf = f"{combined_pf:.3f}" if combined_pf is not None else "N/A"
        print(
            f"TOTAL    {combined['trades']:>6}  {combined['wins']:>4}  "
            f"{combined['losses']:>6}  ${combined['net_pnl_usd']:>+9.2f}  "
            f"{pf:>6}  {scenario}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download and backtest Delta BTC option history for January-July 2026",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    download_parser = subparsers.add_parser(
        "download",
        help="Download and normalize January 1 through July 31, 2026",
    )
    download_parser.add_argument("--output", type=Path, default=DEFAULT_DATA)
    download_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Redownload cached API responses; normally leave this off",
    )
    download_parser.add_argument(
        "--resume-attempts",
        type=int,
        default=20,
        help="Automatic resume attempts for transient DNS, network, 429, and 5xx failures",
    )
    download_parser.add_argument(
        "--retry-wait-seconds",
        type=float,
        default=15.0,
        help="Initial delay before automatically resuming a transient failure",
    )

    backtest_parser = subparsers.add_parser(
        "backtest",
        help="Backtest the preferred and requested Stoch comparisons month by month",
    )
    backtest_parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    backtest_parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)

    args = parser.parse_args()
    if args.command == "download":
        manifest = download(
            args.output,
            refresh=args.refresh,
            resume_attempts=args.resume_attempts,
            retry_wait_seconds=args.retry_wait_seconds,
        )
        print(json.dumps(manifest, indent=2))
        print(f"Dataset ready: {args.output.resolve()}")
    else:
        result = backtest(args.data, args.output)
        _print_summary(result)
        print(f"\nReports ready: {args.output.resolve()}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(f"Error: {exc}") from None
