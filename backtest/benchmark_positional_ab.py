"""Order-balanced, offline A/B benchmark for quote parser or candle lookup.

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
    comparison: str = "QUOTE_PARSER",
) -> dict:
    if type(rounds) is not int or not 1 <= rounds <= 12:
        raise ValueError("rounds must be an integer between 1 and 12")
    if comparison not in {"QUOTE_PARSER", "BAR_LOOKUP", "SQLITE_ENCODING"}:
        raise ValueError("comparison must be QUOTE_PARSER, BAR_LOOKUP or SQLITE_ENCODING")
    labels = {
        "QUOTE_PARSER": ("DICT", "POSITIONAL"),
        "BAR_LOOKUP": ("POSITIONAL", "POSITIONAL_BAR_LOOKUP"),
        "SQLITE_ENCODING": ("SQLITE_JSON", "SQLITE_PACKED"),
    }[comparison]
    output.mkdir(parents=True, exist_ok=True)
    baseline_path = output / {
        "QUOTE_PARSER": "reference-dict-report.json",
        "BAR_LOOKUP": "reference-positional-report.json",
        "SQLITE_ENCODING": "reference-sqlite-json-report.json",
    }[comparison]
    samples: list[dict] = []
    differences: list[str] = []

    # A and B have the same mean position within each four-run cycle.
    # Reverse the order in odd rounds for additional protection from drift.
    for round_index in range(rounds):
        a, b = labels
        sequence = ((a, b, b, a) if round_index % 2 == 0 else (b, a, a, b))
        for position, variant in enumerate(sequence, 1):
            key = f"round-{round_index + 1:02d}-{position}-{variant.lower()}"
            parser = "DICT" if variant == "DICT" else "POSITIONAL"
            bar_lookup = variant in {"POSITIONAL_BAR_LOOKUP", "SQLITE_JSON", "SQLITE_PACKED"}
            is_sqlite = comparison == "SQLITE_ENCODING"
            spool_encoding = "PACKED" if variant == "SQLITE_PACKED" else "JSON"
            child_path = output / f"{key}-child.json"
            command = [
                sys.executable, "-m", "backtest.benchmark_legacy_run",
                "--child", "--directory", str(directory),
                "--start", start, "--end", end,
                "--mode", "SQLITE" if is_sqlite else "MEMORY",
                "--algorithm", "SWEEP" if is_sqlite else "LEGACY",
                "--quote-csv-parser", parser,
                "--output", str(child_path),
            ]
            if bar_lookup:
                command.append("--positional-bar-lookup")
            if is_sqlite:
                command += ["--quote-spool-encoding", spool_encoding, "--quote-spool-metrics"]
            subprocess.run(command, check=True)
            child = json.loads(child_path.read_text(encoding="utf-8"))
            child_path.unlink()
            metrics = child.get("quote_spool_metrics")
            if is_sqlite and not isinstance(metrics, dict):
                raise ValueError("SQLITE_SPOOL_METRICS_MISSING")
            report = child["result"]
            report_path = output / f"{key}-report.json"
            report_path.write_text(json.dumps(report, allow_nan=False), encoding="utf-8")
            # Always refresh the baseline on a new invocation, even when
            # reusing an existing output directory from an earlier dataset.
            if not samples:
                if variant != labels[0]:
                    raise RuntimeError("FIRST_AB_SAMPLE_MUST_BE_BASELINE")
                baseline_path.write_text(
                    json.dumps(report, allow_nan=False), encoding="utf-8"
                )
            changes = compare(baseline_path, report_path)
            differences.extend(f"{key}: {item}" for item in changes)
            samples.append({
                "round": round_index + 1,
                "position": position,
                "variant": variant,
                "quote_csv_parser": parser,
                "positional_bar_lookup": bar_lookup,
                "quote_spool_encoding": spool_encoding if is_sqlite else None,
                "quote_spool_metrics": metrics,
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
               if sample["variant"] == name]
        for name in labels
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
    baseline_median = stats[labels[0]]["median_seconds"]
    candidate_median = stats[labels[1]]["median_seconds"]
    summary = {
        "input": str(directory), "start": start, "end": end,
        "rounds": rounds, "order": "ABBA / BAAB alternating per round",
        "comparison": comparison,
        "baseline_variant": labels[0],
        "candidate_variant": labels[1],
        "parity_passed": not differences,
        "difference_count": len(differences),
        "differences": differences[:30],
        "baseline_trade_count": samples[0]["trade_count"],
        "baseline_execution_attempt_count": samples[0]["execution_attempt_count"],
        "statistics": stats,
        "median_time_reduction_percent": (
            100.0 * (baseline_median - candidate_median) / baseline_median
            if baseline_median else None
        ),
        "measurements": samples,
        "scope": (
            "locked H6 research; SQLITE+SWEEP+POSITIONAL+bar lookup"
            if comparison == "SQLITE_ENCODING"
            else "locked H6 research; MEMORY+LEGACY quotes"
        ),
        "notes": (
            "Repeated separate-process runs balance but cannot eliminate OS,"
            " disk-cache, thermal, and background-workload effects. "
            "Results are not a full JSON strategy engine benchmark. "
            "All runs are compared with the first baseline trading report."
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
        description="Alternating A/B benchmark for quote parser, candle lookup, or SQLite encoding"
    )
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--comparison", choices=["QUOTE_PARSER", "BAR_LOOKUP", "SQLITE_ENCODING"],
                        default="QUOTE_PARSER")
    args = parser.parse_args()
    print(json.dumps(
        benchmark_positional_ab(
            args.directory, args.start, args.end, args.output, rounds=args.rounds,
            comparison=args.comparison
        ),
        indent=2, allow_nan=False,
    ))


if __name__ == "__main__":
    main()
