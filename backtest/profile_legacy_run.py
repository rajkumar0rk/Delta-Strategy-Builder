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
from .process_memory import peak_process_rss_kib, current_process_rss_kib
from .report_memory_inventory import report_retained_sizes


def profile_dataset(directory: Path, start: str, end: str, output: Path,
                    *, top_functions: int = 35,
                    track_allocations: bool = False) -> dict:
    if top_functions < 1 or top_functions > 200:
        raise ValueError("top_functions must be between 1 and 200")
    output.mkdir(parents=True, exist_ok=True)
    stages: list[dict] = []
    retention: list[dict] = []
    prof = cProfile.Profile()
    started = time.perf_counter()
    previous_snapshot = None
    if track_allocations:
        tracemalloc.start()

    def on_stage(stage: str, seconds: float) -> None:
        nonlocal previous_snapshot
        entry: dict = {"stage": stage, "elapsed_seconds": seconds}
        if track_allocations:
            current, peak = tracemalloc.get_traced_memory()
            entry["python_traced_current_bytes"] = current
            entry["python_traced_peak_bytes"] = peak
            entry["current_process_rss_kib"] = current_process_rss_kib()
            entry["cumulative_peak_process_rss_kib"] = peak_process_rss_kib()
            snapshot = tracemalloc.take_snapshot()
            if previous_snapshot is not None:
                entry["python_allocation_changes"] = [{
                    "source": str(change.traceback[0]),
                    "net_bytes": change.size_diff,
                    "net_blocks": change.count_diff,
                } for change in snapshot.compare_to(previous_snapshot, "lineno")[:8]
                  if change.size_diff != 0]
            else:
                entry["python_allocation_changes"] = []
            previous_snapshot = snapshot
        stages.append(entry)

    def on_retention(stage: str, counts: dict) -> None:
        retention.append({"stage": stage, **counts})

    try:
        prof.enable()
        try:
            report = run_dataset(
                directory, start=start, end=end,
                scenario_set=locked_h6_scenarios(),
                stage_observer=on_stage,
                **({"retention_observer": on_retention} if track_allocations else {}),
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
        "current_process_rss_kib": current_process_rss_kib() if track_allocations else None,
        "retention_inventory": retention if track_allocations else None,
        "report_retained_python_bytes": (
            report_retained_sizes(report) if track_allocations else None
        ),
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
            "not additive to an unprofiled benchmark. With --track-allocations, "
            "each stage records current process RSS, cumulative process high-water, "
            "Python-traced bytes, allocation source deltas, and an event/count "
            "inventory. Report field memory is an approximate Python object "
            "tree size, not process RSS; field sizes may overlap. Tracemalloc "
            "captures Python-tracked allocations, not all Pandas/NumPy native "
            "memory. Snapshot collection adds extra profiling memory and time. "
            "Use the independent-process benchmark for production RSS, parity "
            "and execution-time comparisons."
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
