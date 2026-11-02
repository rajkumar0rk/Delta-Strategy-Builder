"""Offline, independent-process memory-growth probe for locked H6 research.

Compares complete reports for fast MEMORY versus PACKED SQLite and exposes
stage cumulative process peaks and retained-object counts. Never downloads
history or changes market execution. Uses a shared existing dataset folder:
indicator loading currently reads the full folder regardless of run window.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

from .compare_legacy_reports import compare


def _horizons(value: str) -> tuple[int, ...]:
    try:
        days = tuple(int(item.strip()) for item in value.split(","))
    except ValueError as exc:
        raise ValueError("days must be comma-separated positive integers") from exc
    if not days or any(day < 1 or day > 365 for day in days) or len(set(days)) != len(days):
        raise ValueError("days must contain unique positive integers between 1 and 365")
    return tuple(sorted(days))


def benchmark_memory_growth(
    directory: Path, start: str, output: Path, *,
    days: tuple[int, ...] = (1, 7, 14),
    modes: tuple[str, ...] = ("MEMORY", "PACKED"),
) -> dict:
    if not days or any(type(day) is not int or not 1 <= day <= 365 for day in days) or len(set(days)) != len(days):
        raise ValueError("days must be unique integers between 1 and 365")
    if not modes or any(mode not in ("MEMORY", "PACKED") for mode in modes) or len(set(modes)) != len(modes):
        raise ValueError("modes must be MEMORY and/or PACKED without duplicates")
    start_at = datetime.fromisoformat(start.replace("Z", "+00:00"))
    if start_at.tzinfo is None or start_at.utcoffset() is None:
        raise ValueError("start must include UTC or timezone offset")
    start_at = start_at.astimezone(timezone.utc)
    output.mkdir(parents=True, exist_ok=True)
    windows = []
    mismatches = []

    for day in sorted(days):
        end = (start_at + timedelta(days=day)).isoformat().replace("+00:00", "Z")
        reference_file = output / f"{day}d-memory-report.json"
        readings = {}
        for mode in modes:
            key = f"{day}d-{mode.lower()}"
            raw_file = output / f"{key}-child.json"
            report_file = output / f"{key}-report.json"
            command = [
                sys.executable, "-m", "backtest.benchmark_legacy_run",
                "--child", "--directory", str(directory),
                "--start", start, "--end", end,
                "--mode", "MEMORY" if mode == "MEMORY" else "SQLITE",
                "--algorithm", "LEGACY" if mode == "MEMORY" else "SWEEP",
                "--quote-csv-parser", "POSITIONAL", "--positional-bar-lookup",
                "--memory-inventory", "--output", str(raw_file),
            ]
            if mode == "PACKED":
                command += ["--quote-spool-encoding", "PACKED", "--quote-spool-metrics"]
            subprocess.run(command, check=True)
            artifact = json.loads(raw_file.read_text(encoding="utf-8"))
            raw_file.unlink()
            report = artifact["result"]
            if not isinstance(artifact.get("phase_memory"), list) or not isinstance(
                artifact.get("retention_inventory"), list
            ):
                raise ValueError("MEMORY_INVENTORY_MISSING")
            if mode == "PACKED" and not isinstance(artifact.get("quote_spool_metrics"), dict):
                raise ValueError("SQLITE_SPOOL_METRICS_MISSING")
            report_file.write_text(json.dumps(report, allow_nan=False), encoding="utf-8")
            differences = []
            if mode == "MEMORY":
                reference_file.write_text(json.dumps(report, allow_nan=False), encoding="utf-8")
            elif "MEMORY" in modes:
                differences = compare(reference_file, report_file)
                mismatches.extend(f"{key}: {problem}" for problem in differences)
            readings[mode] = {
                "elapsed_seconds": artifact["elapsed_seconds"],
                "peak_process_rss_kib": artifact["peak_process_rss_kib"],
                "stage_cumulative_peaks": artifact["phase_memory"],
                "retention_inventory": artifact["retention_inventory"],
                "quote_spool_metrics": artifact.get("quote_spool_metrics"),
                "trades": len(report.get("trades", [])),
                "execution_attempts": len(report.get("execution_attempts", [])),
                "decision_events": len(report.get("decision_events", [])),
                "difference_count": len(differences),
            }
            if not differences:
                report_file.unlink()
        # Keep baseline only if this horizon failed a parity comparison.
        if reference_file.exists() and not any(
            entry["difference_count"] for entry in readings.values()
        ):
            reference_file.unlink()
        windows.append({"days": day, "end": end, "modes": readings})
    summary = {
        "input": str(directory), "start": start, "modes": list(modes),
        "parity_passed": not mismatches,
        "difference_count": len(mismatches),
        "differences": mismatches[:30],
        "windows": windows,
        "notes": (
            "Historical H6 research only; complete trade/fee/decision report parity "
            "is verified per window when MEMORY is included. Stage peaks are "
            "cumulative process peaks, not instantaneous RSS. Current indicator "
            "loading reads the full underlying_bars.csv file even for short "
            "requested windows; compare indicator_rows and indicator_frame_bytes "
            "to understand the retained-data floor. This does not implement "
            "globally bounded-memory or prove JSON strategy engine scalability."
        ),
    }
    (output / "benchmark.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    if mismatches:
        raise ValueError(f"RESULT_PARITY_MISMATCH: {len(mismatches)} differences")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Profile H6 retained-memory growth over different history windows"
    )
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--start", required=True, help="UTC ISO timestamp")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--days", default="1,7,14")
    parser.add_argument("--modes", default="MEMORY,PACKED")
    args = parser.parse_args()
    summary = benchmark_memory_growth(
        args.directory, args.start, args.output,
        days=_horizons(args.days),
        modes=tuple(item.strip().upper() for item in args.modes.split(",")),
    )
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
