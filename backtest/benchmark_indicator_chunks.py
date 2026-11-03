"""Offline full indicator DataFrame vs bounded indicator iterator A/B benchmark.

Both paths write the same complete indicator table to CSV in independent
subprocesses. An exact comparison is applied to direction/signal flags and
timestamps; numeric floating fields use documented tight tolerance due to
the already existing recursive streaming EMA implementation.
This does not benchmark completed trades or replace the H6 runner.
"""
from __future__ import annotations

import argparse
import csv
from itertools import zip_longest
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import time

from .process_memory import peak_process_rss_kib


def _child(directory: Path, output: Path, mode: str, *,
           chunk_rows: int, max_session_rows: int, metadata: Path):
    from .ema_vwap_research import indicators
    from .legacy_full_indicator_stream import iter_complete_indicator_chunks

    source = directory / "underlying_bars.csv"
    start = time.perf_counter()
    output.parent.mkdir(parents=True, exist_ok=True)
    retained_context_max = 0
    rows = 0
    if mode == "FULL":
        frame = indicators(source)
        frame.to_csv(output, index_label="timestamp")
        rows = len(frame)
    elif mode == "CHUNKED":
        def observe(values):
            nonlocal retained_context_max
            retained_context_max = max(
                retained_context_max, values["context_rows"],
            )
        with output.open("w", encoding="utf-8", newline="") as output_file:
            for part in iter_complete_indicator_chunks(
                source, chunk_rows=chunk_rows,
                max_session_rows=max_session_rows,
                retention_observer=observe,
            ):
                part.to_csv(
                    output_file, index_label="timestamp", header=(rows == 0),
                )
                rows += len(part)
    else:
        raise ValueError("unknown indicator benchmark mode")
    elapsed = time.perf_counter() - start
    metadata.write_text(json.dumps({
        "mode": mode,
        "elapsed_seconds": elapsed,
        "peak_process_rss_kib": peak_process_rss_kib(),
        "rows": rows,
        "retained_context_max_rows": retained_context_max if mode == "CHUNKED" else None,
        "csv_bytes": output.stat().st_size,
    }), encoding="utf-8")


def compare_indicator_csv(
    left: Path, right: Path, *,
    rtol: float = 1e-10, atol: float = 1e-9,
    max_differences: int = 30,
) -> list[str]:
    """Compare all rows including flags, never sampling or truncating input."""
    if not (math.isfinite(rtol) and math.isfinite(atol)) or rtol < 0 or atol < 0:
        raise ValueError("tolerance must be finite and nonnegative")
    errors: list[str] = []
    with left.open(newline="", encoding="utf-8") as a, right.open(
        newline="", encoding="utf-8"
    ) as b:
        first = csv.reader(a)
        second = csv.reader(b)
        columns = next(first, None)
        current_columns = next(second, None)
        if columns != current_columns:
            return [f"headers differ: {columns!r} vs {current_columns!r}"]
        if columns is None:
            return []
        for row_no, (xrow, yrow) in enumerate(
            zip_longest(first, second), start=2,
        ):
            if xrow is None or yrow is None:
                if len(errors) < max_differences:
                    errors.append(f"row {row_no}: row count differs")
                break
            if len(xrow) != len(columns) or len(yrow) != len(columns):
                if len(errors) < max_differences:
                    errors.append(f"row {row_no}: column count differs")
                continue
            for name, x, y in zip(columns, xrow, yrow):
                if x == y:
                    continue
                try:
                    xv, yv = float(x), float(y)
                except (ValueError, TypeError):
                    same = False
                else:
                    same = (
                        (math.isnan(xv) and math.isnan(yv))
                        or math.isclose(xv, yv, rel_tol=rtol, abs_tol=atol)
                    )
                if not same and len(errors) < max_differences:
                    errors.append(
                        f"row {row_no}, {name}: {x!r} -> {y!r}"
                    )
    return errors


def benchmark_indicator_chunks(
    directory: Path, output: Path, *,
    rounds: int = 3, chunk_rows: int = 512,
    max_session_rows: int = 4096,
) -> dict:
    if type(rounds) is not int or not 1 <= rounds <= 10:
        raise ValueError("rounds must be an integer between 1 and 10")
    if type(chunk_rows) is not int or chunk_rows < 1:
        raise ValueError("chunk_rows must be a positive integer")
    if type(max_session_rows) is not int or max_session_rows < 1:
        raise ValueError("max_session_rows must be a positive integer")
    output.mkdir(parents=True, exist_ok=True)
    reference = output / "reference-full-indicators.csv"
    measurements = []
    differences = []
    for round_index in range(rounds):
        sequence = (
            ("FULL", "CHUNKED", "CHUNKED", "FULL")
            if round_index % 2 == 0
            else ("CHUNKED", "FULL", "FULL", "CHUNKED")
        )
        for position, mode in enumerate(sequence, start=1):
            name = f"round-{round_index + 1:02d}-{position}-{mode.lower()}"
            target = output / f"{name}-indicators.csv"
            meta = output / f"{name}-metrics.json"
            subprocess.run([
                sys.executable, "-m", "backtest.benchmark_indicator_chunks",
                "--child", "--directory", str(directory),
                "--output", str(target), "--metadata", str(meta),
                "--mode", mode, "--chunk-rows", str(chunk_rows),
                "--max-session-rows", str(max_session_rows),
            ], check=True)
            reading = json.loads(meta.read_text(encoding="utf-8"))
            meta.unlink()
            if not measurements:
                if mode != "FULL":
                    raise RuntimeError("first benchmark must use FULL")
                reference.write_bytes(target.read_bytes())
            delta = compare_indicator_csv(reference, target)
            differences.extend(f"{name}: {item}" for item in delta)
            measurements.append({
                "round": round_index + 1, "position": position,
                **reading, "difference_count": len(delta),
            })
            if not delta:
                target.unlink()
    stats = {}
    for mode in ("FULL", "CHUNKED"):
        rows = [reading for reading in measurements if reading["mode"] == mode]
        rss = [row["peak_process_rss_kib"] for row in rows
               if row["peak_process_rss_kib"] is not None]
        stats[mode] = {
            "runs": len(rows),
            "median_seconds": statistics.median(row["elapsed_seconds"] for row in rows),
            "median_peak_rss_kib": statistics.median(rss) if rss else None,
            "max_context_rows": max(
                (row["retained_context_max_rows"] or 0) for row in rows
            ),
        }
    result = {
        "input": str(directory), "rounds": rounds,
        "comparison": "FULL_VS_BOUNDED_INDICATOR_CHUNKS",
        "chunk_rows": chunk_rows, "max_session_rows": max_session_rows,
        "parity_passed": not differences,
        "difference_count": len(differences),
        "differences": differences[:30],
        "statistics": stats, "measurements": measurements,
        "notes": (
            "All full indicator rows are compared with tight floating tolerance "
            "(rtol=1e-10, atol=1e-9), exact timestamp, signal flags and directions. "
            "CSV writing is included in both timings and peak RSS. This is an "
            "indicator-only benchmark; no trade/fee/decision report parity is "
            "claimed. Original run_dataset still constructs the full DataFrame."
        ),
    }
    (output / "benchmark.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    if differences:
        raise ValueError(f"INDICATOR_PARITY_MISMATCH: {len(differences)} differences")
    return result


def main():
    parser = argparse.ArgumentParser(description="Compare full vs bounded H6 indicator generation")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--chunk-rows", type=int, default=512)
    parser.add_argument("--max-session-rows", type=int, default=4096)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=["FULL", "CHUNKED"], help=argparse.SUPPRESS)
    parser.add_argument("--metadata", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        if args.mode is None or args.metadata is None:
            parser.error("--mode and --metadata required with --child")
        _child(args.directory, args.output, args.mode,
               chunk_rows=args.chunk_rows,
               max_session_rows=args.max_session_rows, metadata=args.metadata)
    else:
        print(json.dumps(benchmark_indicator_chunks(
            args.directory, args.output, rounds=args.rounds,
            chunk_rows=args.chunk_rows, max_session_rows=args.max_session_rows,
        ), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
