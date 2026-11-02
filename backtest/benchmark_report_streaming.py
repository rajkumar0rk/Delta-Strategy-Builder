"""Independent-process A/B for lossless streamed H6 research reports.

The ordinary report remains the baseline. Each child writes the exact same
logical JSON report to disk; only the retained aggregation mechanism differs.
Peak RSS includes report serialization for both modes. No quote downloads.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

from .compare_legacy_reports import compare
from .process_memory import peak_process_rss_kib


def _child(directory: Path, start: str, end: str, output: Path,
           mode: str, metadata: Path) -> None:
    from .ema_vwap_research import (
        locked_h6_scenarios, run_dataset, run_dataset_to_streamed_report,
    )
    begin = time.perf_counter()
    options = {"start": start, "end": end,
               "scenario_set": locked_h6_scenarios()}
    if mode == "STREAMED":
        manifest = run_dataset_to_streamed_report(
            directory, output=output, **options,
        )
        counts = manifest["counts"]
    elif mode == "MEMORY":
        report = run_dataset(directory, **options)
        output.write_text(
            json.dumps(report, allow_nan=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        counts = {
            field: len(report[field])
            for field in ("trades", "execution_attempts", "decision_events")
        }
    else:
        raise ValueError("mode must be MEMORY or STREAMED")
    elapsed = time.perf_counter() - begin
    metadata.write_text(json.dumps({
        "mode": mode,
        "elapsed_seconds": elapsed,
        "peak_process_rss_kib": peak_process_rss_kib(),
        "report_bytes": output.stat().st_size,
        "counts": counts,
    }, allow_nan=False), encoding="utf-8")


def benchmark_streamed_reports(
    directory: Path, start: str, end: str, output: Path, *,
    rounds: int = 3,
) -> dict:
    if type(rounds) is not int or not 1 <= rounds <= 10:
        raise ValueError("rounds must be an integer between 1 and 10")
    output.mkdir(parents=True, exist_ok=True)
    baseline = output / "reference-memory-report.json"
    measurements = []
    differences = []

    for round_index in range(rounds):
        sequence = (
            ("MEMORY", "STREAMED", "STREAMED", "MEMORY")
            if round_index % 2 == 0
            else ("STREAMED", "MEMORY", "MEMORY", "STREAMED")
        )
        for position, mode in enumerate(sequence, start=1):
            name = f"round-{round_index + 1:02d}-{position}-{mode.lower()}"
            path = output / f"{name}-report.json"
            metadata = output / f"{name}-metrics.json"
            subprocess.run([
                sys.executable, "-m", "backtest.benchmark_report_streaming",
                "--child", "--directory", str(directory),
                "--start", start, "--end", end,
                "--output", str(path), "--metadata", str(metadata),
                "--mode", mode,
            ], check=True)
            result = json.loads(metadata.read_text(encoding="utf-8"))
            metadata.unlink()
            if not measurements:
                if mode != "MEMORY":
                    raise RuntimeError("INITIAL_REPORT_MUST_BE_MEMORY")
                # Always refresh the reference even when output is reused.
                baseline.write_bytes(path.read_bytes())
            change = compare(baseline, path, tolerance=0.0)
            if change:
                differences.extend(f"{name}: {item}" for item in change)
            measurements.append({
                "round": round_index + 1,
                "position": position,
                **result,
                "difference_count": len(change),
            })
            if not change:
                path.unlink()
    statistics_by_mode = {}
    for mode in ("MEMORY", "STREAMED"):
        rows = [row for row in measurements if row["mode"] == mode]
        elapsed = [row["elapsed_seconds"] for row in rows]
        rss = [row["peak_process_rss_kib"] for row in rows
               if row["peak_process_rss_kib"] is not None]
        statistics_by_mode[mode] = {
            "runs": len(rows),
            "median_seconds": statistics.median(elapsed),
            "median_peak_rss_kib": statistics.median(rss) if rss else None,
            "min_seconds": min(elapsed),
            "max_seconds": max(elapsed),
        }
    a = statistics_by_mode["MEMORY"]
    b = statistics_by_mode["STREAMED"]
    summary = {
        "input": str(directory), "start": start, "end": end,
        "rounds": rounds, "order": "ABBA / BAAB",
        "parity_passed": not differences,
        "difference_count": len(differences),
        "differences": differences[:30],
        "statistics": statistics_by_mode,
        "median_time_reduction_percent": (
            100 * (a["median_seconds"] - b["median_seconds"]) / a["median_seconds"]
            if a["median_seconds"] else None
        ),
        "measurements": measurements,
        "scope": "locked H6 legacy research; full report written on both sides",
        "notes": (
            "Independent processes with identical strategies and option costs. "
            "MEMORY retains all report lists before JSON output, STREAMED spools "
            "aggregate trades/attempts/decisions and atomically assembles JSON. "
            "Per-scenario trades, signal/quote events, source indicators and "
            "scenario metrics remain in RAM. Disk I/O and source-cache effects "
            "can influence timing; this is not end-to-end bounded memory."
        ),
    }
    (output / "benchmark.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    if differences:
        raise ValueError(f"RESULT_PARITY_MISMATCH: {len(differences)} differences")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark original vs incremental H6 trade report persistence"
    )
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--metadata", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=["MEMORY", "STREAMED"],
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        if args.mode is None or args.metadata is None:
            parser.error("--mode and --metadata required for --child")
        _child(args.directory, args.start, args.end,
               args.output, args.mode, args.metadata)
    else:
        print(json.dumps(
            benchmark_streamed_reports(
                args.directory, args.start, args.end, args.output,
                rounds=args.rounds,
            ), indent=2, allow_nan=False,
        ))


if __name__ == "__main__":
    main()
