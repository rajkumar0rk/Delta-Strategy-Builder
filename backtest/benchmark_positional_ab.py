"""Order-balanced, offline A/B benchmark for the legacy quote parser.

Runs the frozen H6 research in independent Python processes and compares
complete trading reports. ABBA/BAAB order balances cold-cache and drift
effects better than the fixed-order single-pass benchmark. This diagnostic
does not change the default parser or any execution behavior.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

from .compare_legacy_reports import compare


def benchmark_positional_ab(
    directory: Path, start: str, end: str, output: Path, *,
    rounds: int = 3,
) -> dict:
    if type(rounds) is not int or not 1 <= rounds <= 12:
        raise ValueError("rounds must be an integer between 1 and 12")
    output.mkdir(parents=True, exist_ok=True)
    baseline_path = output / "reference-dict-report.json"
    samples: list[dict] = []
    differences: list[str] = []

    # A and B have the same mean position within each four-run cycle.
    # Reverse the order in odd rounds for additional protection from drift.
    for round_index in range(rounds):
        sequence = (
            ("DICT", "POSITIONAL", "POSITIONAL", "DICT")
            if round_index % 2 == 0
            else ("POSITIONAL", "DICT", "DICT", "POSITIONAL")
        )
        for position, parser in enumerate(sequence, 1):
            key = f"round-{round_index + 1:02d}-{position}-{parser.lower()}"
            child_path = output / f"{key}-child.json"
            command = [
                sys.executable, "-m", "backtest.benchmark_legacy_run",
                "--child", "--directory", str(directory),
                "--start", start, "--end", end,
                "--mode", "MEMORY", "--algorithm", "LEGACY",
                "--quote-csv-parser", parser,
                "--output", str(child_path),
            ]
            subprocess.run(command, check=True)
            child = json.loads(child_path.read_text(encoding="utf-8"))
            child_path.unlink()
            report = child["result"]
            report_path = output / f"{key}-report.json"
            report_path.write_text(json.dumps(report, allow_nan=False), encoding="utf-8")
            if not baseline_path.exists():
                if parser == "DICT":
                    baseline_path.write_text(
                        json.dumps(report, allow_nan=False), encoding="utf-8"
                    )
                else:
                    # The first odd/even alternating block always begins with
                    # DICT, but retain strict baseline semantics.
                    raise RuntimeError("FIRST_AB_SAMPLE_MUST_BE_DICT")
            changes = compare(baseline_path, report_path)
            differences.extend(f"{key}: {item}" for item in changes)
            samples.append({
                "round": round_index + 1,
                "position": position,
                "quote_csv_parser": parser,
                "elapsed_seconds": child["elapsed_seconds"],
                "peak_process_rss_kib": child.get("peak_process_rss_kib"),
                "trade_count": len(report.get("trades", [])),
                "execution_attempt_count": len(report.get("execution_attempts", [])),
                "difference_count": len(changes),
            })
            # Individual reports remain available if a mismatch occurs.
            if not changes:
                report_path.unlink()

    groups = {
        name: [sample["elapsed_seconds"] for sample in samples
               if sample["quote_csv_parser"] == name]
        for name in ("DICT", "POSITIONAL")
    }
    stats = {
        name: {
            "runs": len(times),
            "median_seconds": statistics.median(times),
            "mean_seconds": statistics.mean(times),
            "min_seconds": min(times),
            "max_seconds": max(times),
        } for name, times in groups.items()
    }
    dict_median = stats["DICT"]["median_seconds"]
    positional_median = stats["POSITIONAL"]["median_seconds"]
    summary = {
        "input": str(directory), "start": start, "end": end,
        "rounds": rounds, "order": "ABBA / BAAB alternating per round",
        "parity_passed": not differences,
        "difference_count": len(differences),
        "differences": differences[:30],
        "baseline_trade_count": samples[0]["trade_count"],
        "baseline_execution_attempt_count": samples[0]["execution_attempt_count"],
        "statistics": stats,
        "median_time_reduction_percent": (
            100.0 * (dict_median - positional_median) / dict_median
            if dict_median else None
        ),
        "measurements": samples,
        "scope": "locked H6 research; original MEMORY+LEGACY quotes",
        "notes": (
            "Repeated separate-process runs balance but cannot eliminate OS,"
            " disk-cache, thermal, and background-workload effects. "
            "Results are not a full JSON strategy engine benchmark. "
            "All runs are compared with the initial DICT trading report."
        ),
    }
    (output / "benchmark.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    if differences:
        raise ValueError(f"RESULT_PARITY_MISMATCH: {len(differences)} differences")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Alternating A/B benchmark for original and positional quote CSV parsers"
    )
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(
        benchmark_positional_ab(
            args.directory, args.start, args.end, args.output, rounds=args.rounds
        ),
        indent=2, allow_nan=False,
    ))


if __name__ == "__main__":
    main()
