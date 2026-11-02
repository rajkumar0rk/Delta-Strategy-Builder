"""Offline, deterministic-source CPU and memory profiler for the legacy runner.

This executes the same frozen H6 research scenario; cProfile and tracemalloc
are diagnostic and introduce overhead. No market download and no live orders.
"""
from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import time
import tracemalloc
from pathlib import Path

from .ema_vwap_research import locked_h6_scenarios, run_dataset
from .process_memory import peak_process_rss_kib


def profile_dataset(directory: Path, start: str, end: str, output: Path,
                    *, top_functions: int = 35,
                    track_allocations: bool = False) -> dict:
    if top_functions < 1 or top_functions > 200:
        raise ValueError("top_functions must be between 1 and 200")
    output.mkdir(parents=True, exist_ok=True)
    stages: list[dict] = []
    prof = cProfile.Profile()
    started = time.perf_counter()
    if track_allocations:
        tracemalloc.start()
    try:
        prof.enable()
        try:
            report = run_dataset(
                directory, start=start, end=end,
                scenario_set=locked_h6_scenarios(),
                stage_observer=lambda stage, seconds: stages.append({
                    "stage": stage, "elapsed_seconds": seconds,
                }),
            )
        finally:
            prof.disable()
        elapsed = time.perf_counter() - started
        trace_peak = tracemalloc.get_traced_memory()[1] if track_allocations else None
    finally:
        if track_allocations:
            tracemalloc.stop()
    prof.dump_stats(str(output / "cpu.pstats"))
    stats = pstats.Stats(prof)
    funcs = sorted(
        stats.stats.items(), key=lambda entry: entry[1][3], reverse=True
    )[:top_functions]
    function_rows = [{
        "function": f"{source}:{line}:{name}",
        "calls": detail[1],
        "self_seconds": detail[2],
        "cumulative_seconds": detail[3],
    } for (source, line, name), detail in funcs]
    summary = {
        "input": str(directory),
        "start": start, "end": end,
        "elapsed_seconds_profiled": elapsed,
        "peak_process_rss_kib": peak_process_rss_kib(),
        "peak_traced_python_bytes": trace_peak,
        "trades": len(report.get("trades", [])),
        "execution_attempts": len(report.get("execution_attempts", [])),
        "decision_events": len(report.get("decision_events", [])),
        "signals_with_contract": report.get("raw_signals_with_contract"),
        "scenario_trade_counts": [
            {"scenario": item["scenario"]["name"],
             "trades": item["metrics"]["trades"]}
            for item in report["results"]
        ],
        "stages": stages,
        "hot_functions": function_rows,
        "notes": (
            "Profiling adds overhead. Stage times include profiling cost and are "
            "not additive to an unprofiled benchmark. Tracemalloc captures Python "
            "tracked allocations, not all Pandas/NumPy native memory. "
            "Use the existing benchmark for parity and speed comparisons."
        ),
    }
    (output / "profile.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile frozen legacy H6 research on existing CSVs")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-functions", type=int, default=35)
    parser.add_argument("--track-allocations", action="store_true")
    args = parser.parse_args()
    summary = profile_dataset(args.directory, args.start, args.end, args.output,
                              top_functions=args.top_functions,
                              track_allocations=args.track_allocations)
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
