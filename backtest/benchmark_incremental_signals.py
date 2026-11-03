"""Offline full-frame versus incremental locked-H6 signal and decision parity.

Only ENTRY/SIGNAL stage is tested. This does not run quotes, margin, or trade
simulation and therefore does not establish final report or fee parity.
The full-frame path is the independent reference for option selection,
EMA-regime starts, signal and session rejection reasons, and event ordering.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from itertools import zip_longest
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import time

from .process_memory import peak_process_rss_kib


class _JsonlSink:
    def __init__(self, file):
        self._file = file
        self.count = 0

    def append(self, record):
        self._file.write(json.dumps(
            record, allow_nan=False, separators=(",", ":"),
        ) + "\n")
        self.count += 1


def _encode_event(event):
    return {
        "timestamp_ns": event.timestamp_ns,
        "direction": event.direction,
        "underlying": event.underlying,
        "option": asdict(event.option),
        "ema_regime_start_ns": event.ema_regime_start_ns,
        "entry_type": event.entry_type,
    }


def _configurations():
    from .ema_vwap_research import locked_h6_scenarios

    # The locked H6 matrix contains 12 execution scenarios but exactly
    # two shared BASELINE signal filters. Match those signal filters once.
    result = {}
    for scenario in locked_h6_scenarios():
        result.setdefault(bool(scenario.require_macd), scenario)
    return [(str(int(key)), result[key]) for key in sorted(result)]


def _child(directory: Path, start: str, end: str, output: Path,
           mode: str, metadata: Path, chunk_rows: int, max_session_rows: int):
    from .data import timestamp_ns
    from .ema_vwap_research import indicators, signal_events, _option_specs
    from .legacy_full_indicator_stream import iter_complete_indicator_chunks
    from .legacy_incremental_signals import iter_incremental_baseline_signals

    specs = _option_specs(directory / "option_instruments.csv")
    start_ns, end_ns = timestamp_ns(start), timestamp_ns(end)
    output.mkdir(parents=True, exist_ok=True)
    counts = {}
    start_clock = time.perf_counter()
    for name, scenario in _configurations():
        events_path = output / f"config-{name}-events.jsonl"
        decisions_path = output / f"config-{name}-decisions.jsonl"
        diagnostics: dict[str, int] = {}
        with events_path.open("w", encoding="utf-8") as events_output, (
            decisions_path.open("w", encoding="utf-8")
        ) as decision_output:
            decisions = _JsonlSink(decision_output)
            if mode == "FULL":
                frame = indicators(directory / "underlying_bars.csv")
                events = signal_events(
                    frame, specs, start_ns, end_ns,
                    confirmation_candles=scenario.confirmation_candles,
                    require_macd=scenario.require_macd,
                    require_stoch_rsi_entry=scenario.require_stoch_rsi_entry,
                    require_stoch_rsi_momentum_entry=scenario.require_stoch_rsi_momentum_entry,
                    entry_start_hour_utc=scenario.entry_start_hour_utc,
                    entry_end_hour_utc=scenario.entry_end_hour_utc,
                    entry_windows_ist_minutes=scenario.entry_windows_ist_minutes,
                    blocked_weekdays_ist=scenario.blocked_weekdays_ist,
                    entry_min_conditions=scenario.entry_min_conditions,
                    min_days_to_expiry=scenario.min_days_to_expiry,
                    min_days_to_expiry_inclusive=scenario.min_days_to_expiry_inclusive,
                    max_days_to_expiry=scenario.max_days_to_expiry,
                    pullback_reversal=scenario.pullback_reversal,
                    entry_mode=scenario.entry_mode,
                    momentum_breakout=scenario.momentum_breakout,
                    signal_diagnostics=diagnostics,
                    decision_events=decisions,
                )
            elif mode == "INCREMENTAL":
                chunks = iter_complete_indicator_chunks(
                    directory / "underlying_bars.csv",
                    chunk_rows=chunk_rows,
                    max_session_rows=max_session_rows,
                )
                events = iter_incremental_baseline_signals(
                    chunks, specs, start_ns=start_ns, end_ns=end_ns,
                    scenario=scenario, decision_events=decisions,
                    signal_diagnostics=diagnostics,
                )
            else:
                raise ValueError("unrecognized signal benchmark mode")
            signal_count = 0
            for event in events:
                events_output.write(json.dumps(
                    _encode_event(event), allow_nan=False,
                    separators=(",", ":"),
                ) + "\n")
                signal_count += 1
        counts[name] = {
            "events": signal_count, "decision_events": decisions.count,
            "diagnostics": diagnostics,
        }
    elapsed = time.perf_counter() - start_clock
    metadata.write_text(json.dumps({
        "mode": mode,
        "elapsed_seconds": elapsed,
        "peak_process_rss_kib": peak_process_rss_kib(),
        "counts": counts,
    }, allow_nan=False))


def _compare_value(reference, candidate, path, errors, *,
                   rtol=1e-10, atol=1e-9):
    if type(reference) is dict and type(candidate) is dict:
        if reference.keys() != candidate.keys():
            errors.append(f"{path}: changed keys")
            return
        for key in reference:
            _compare_value(
                reference[key], candidate[key], f"{path}.{key}",
                errors, rtol=rtol, atol=atol,
            )
    elif type(reference) is list and type(candidate) is list:
        if len(reference) != len(candidate):
            errors.append(f"{path}: changed length")
        else:
            for index, (left, right) in enumerate(zip(reference, candidate)):
                _compare_value(left, right, f"{path}[{index}]",
                               errors, rtol=rtol, atol=atol)
    elif type(reference) is int and type(candidate) is int:
        # Nanosecond timestamps and integer counts must match exactly.
        if reference != candidate:
            errors.append(f"{path}: {reference!r} vs {candidate!r}")
    elif type(reference) in (int, float) and type(candidate) in (int, float):
        if not (
            (math.isnan(reference) and math.isnan(candidate))
            or math.isclose(reference, candidate, rel_tol=rtol, abs_tol=atol)
        ):
            errors.append(f"{path}: {reference!r} vs {candidate!r}")
    elif type(reference) != type(candidate) or reference != candidate:
        errors.append(f"{path}: {reference!r} vs {candidate!r}")


def compare_jsonl(reference: Path, candidate: Path, *, max_examples=30):
    """Compare all records without retaining either full file in memory."""
    differences: list[str] = []
    samples: list[str] = []
    with reference.open(encoding="utf-8") as left, candidate.open(
        encoding="utf-8"
    ) as right:
        for index, (old, new) in enumerate(zip_longest(left, right), start=1):
            if old is None or new is None:
                message = f"row {index}: row count differs"
                differences.append(message)
                if len(samples) < max_examples:
                    samples.append(message)
                break
            original = json.loads(old)
            updated = json.loads(new)
            row_errors: list[str] = []
            _compare_value(original, updated, f"row {index}", row_errors)
            if row_errors:
                differences.extend(row_errors)
                if len(samples) < max_examples:
                    samples.extend(row_errors[:max_examples-len(samples)])
    return len(differences), samples


def benchmark_incremental_signals(
    directory: Path, start: str, end: str, output: Path, *,
    rounds: int = 3, chunk_rows: int = 512, max_session_rows: int = 4096,
):
    if type(rounds) is not int or not 1 <= rounds <= 10:
        raise ValueError("rounds must be an integer between 1 and 10")
    if type(chunk_rows) is not int or chunk_rows < 1:
        raise ValueError("chunk_rows must be a positive integer")
    if type(max_session_rows) is not int or max_session_rows < 1:
        raise ValueError("max_session_rows must be a positive integer")
    output.mkdir(parents=True, exist_ok=True)
    reference_directory = output / "reference-full"
    runs = []
    differences = []
    for iteration in range(rounds):
        modes = (
            ("FULL", "INCREMENTAL", "INCREMENTAL", "FULL")
            if iteration % 2 == 0
            else ("INCREMENTAL", "FULL", "FULL", "INCREMENTAL")
        )
        for position, mode in enumerate(modes, start=1):
            label = f"round-{iteration+1:02d}-{position}-{mode.lower()}"
            run_dir = output / label
            run_dir.mkdir(exist_ok=True)
            meta = output / f"{label}-metrics.json"
            subprocess.run([
                sys.executable, "-m", "backtest.benchmark_incremental_signals",
                "--child", "--directory", str(directory),
                "--start", start, "--end", end, "--output", str(run_dir),
                "--metadata", str(meta), "--mode", mode,
                "--chunk-rows", str(chunk_rows),
                "--max-session-rows", str(max_session_rows),
            ], check=True)
            reading = json.loads(meta.read_text(encoding="utf-8"))
            meta.unlink()
            if not runs:
                if mode != "FULL":
                    raise RuntimeError("first comparison must be FULL")
                reference_directory.mkdir(exist_ok=True)
                for item in run_dir.iterdir():
                    (reference_directory / item.name).write_bytes(item.read_bytes())
            count_diff = 0
            for name, _ in _configurations():
                for kind in ("events", "decisions"):
                    filename = f"config-{name}-{kind}.jsonl"
                    delta_count, sample = compare_jsonl(
                        reference_directory / filename, run_dir / filename,
                    )
                    count_diff += delta_count
                    differences.extend(f"{label}/{filename}: {msg}" for msg in sample)
            if runs and reading["counts"] != runs[0]["counts"]:
                count_diff += 1
                differences.append(f"{label}: event/decision/diagnostic counts changed")
            runs.append({
                "round": iteration+1, "position": position,
                **reading, "difference_count": count_diff,
            })
            if count_diff == 0:
                for item in run_dir.iterdir():
                    item.unlink()
                run_dir.rmdir()
    stats = {}
    for mode in ("FULL", "INCREMENTAL"):
        subset = [r for r in runs if r["mode"] == mode]
        rss = [r["peak_process_rss_kib"] for r in subset
               if r["peak_process_rss_kib"] is not None]
        stats[mode] = {
            "runs": len(subset),
            "median_seconds": statistics.median(r["elapsed_seconds"] for r in subset),
            "median_peak_rss_kib": statistics.median(rss) if rss else None,
        }
    total = sum(run["difference_count"] for run in runs)
    result = {
        "input": str(directory), "start": start, "end": end,
        "rounds": rounds, "chunk_rows": chunk_rows,
        "comparison": "LOCKED_H6_BASELINE_FULL_VS_INCREMENTAL_SIGNALS",
        "parity_passed": total == 0,
        "difference_count": total,
        "differences": differences[:30],
        "statistics": stats, "measurements": runs,
        "notes": (
            "Both locked H6 BASELINE signal configurations (MACD enabled/disabled) "
            "checked over the full CSV. Exact event count, option identity, "
            "signal status, reason, session decision and ordering; numeric "
            "decision fields rtol=1e-10, atol=1e-9. Only signal selection is "
            "covered. Option quote capture, execution fees and full trading "
            "report parity remain untested for this new path."
        ),
    }
    (output / "benchmark.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8",
    )
    if total:
        raise ValueError(f"SIGNAL_PARITY_MISMATCH: {total} differences")
    return result


def main():
    parser = argparse.ArgumentParser(description="Benchmark original vs incremental locked H6 signals")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--chunk-rows", type=int, default=512)
    parser.add_argument("--max-session-rows", type=int, default=4096)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=["FULL","INCREMENTAL"], help=argparse.SUPPRESS)
    parser.add_argument("--metadata", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        if args.mode is None or args.metadata is None:
            parser.error("--mode and --metadata required with --child")
        _child(args.directory, args.start, args.end, args.output,
               args.mode, args.metadata, args.chunk_rows, args.max_session_rows)
    else:
        print(json.dumps(benchmark_incremental_signals(
            args.directory, args.start, args.end, args.output,
            rounds=args.rounds, chunk_rows=args.chunk_rows,
            max_session_rows=args.max_session_rows,
        ), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
