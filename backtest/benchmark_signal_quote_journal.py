"""A/B: original H6 positional quote capture vs streamed signal/quote journal.

This is a *quote capture and event replay* benchmark, not a trading report
benchmark. Both modes consume the actual underlying and option quote CSVs.
Every selected quote, option ID and signal metadata is compared, with no
floating-point tolerance or sampling. Fees/exits are NOT evaluated.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from itertools import zip_longest
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

from .process_memory import peak_process_rss_kib


def _scenarios():
    from .benchmark_incremental_signals import _configurations
    return _configurations()


def _legacy_signal_options(scenario):
    fields = (
        "confirmation_candles", "require_macd", "require_stoch_rsi_entry",
        "require_stoch_rsi_momentum_entry", "entry_start_hour_utc",
        "entry_end_hour_utc", "entry_windows_ist_minutes",
        "blocked_weekdays_ist", "entry_min_conditions",
        "min_days_to_expiry", "min_days_to_expiry_inclusive",
        "max_days_to_expiry", "pullback_reversal", "entry_mode",
        "momentum_breakout",
    )
    return {field: getattr(scenario, field) for field in fields}


def _record(event):
    return {
        "timestamp_ns": event.timestamp_ns,
        "direction": event.direction, "underlying": event.underlying,
        "option": asdict(event.option),
        "ema_regime_start_ns": event.ema_regime_start_ns,
        "entry_type": event.entry_type,
        "quotes": list(event.quotes),
    }


def _child(
    directory: Path, start: str, end: str,
    output: Path, metadata: Path, mode: str, *,
    chunk_rows: int, max_session_rows: int,
    journal_matching: str = "SQL", bucket_minutes: int = 5,
    max_cache_buckets: int = 256, max_cached_candidates: int = 4096,
    max_cached_symbols: int = 256,
):
    from .data import timestamp_ns
    from .ema_vwap_research import indicators, signal_events, _option_specs
    from .legacy_full_indicator_stream import iter_complete_indicator_chunks
    from .legacy_incremental_signals import iter_incremental_baseline_signals
    from .legacy_signal_quote_journal import StreamingSignalQuoteJournal
    from .positional_quote_capture import capture_quotes_positional

    output.mkdir(parents=True, exist_ok=True)
    start_clock = time.perf_counter()
    specs = _option_specs(directory / "option_instruments.csv")
    start_ns, end_ns = timestamp_ns(start), timestamp_ns(end)
    counts = {}
    lookup_metrics = None
    if mode == "FULL":
        frame = indicators(directory / "underlying_bars.csv")
        groups = {}
        for config, scenario in _scenarios():
            groups[config] = signal_events(
                frame, specs, start_ns, end_ns,
                **_legacy_signal_options(scenario),
            )
        capture_quotes_positional(
            directory / "option_quotes.csv",
            [event for group in groups.values() for event in group],
            horizon_minutes=65.0,
        )
        for config, events in groups.items():
            with (output / f"config-{config}-events.jsonl").open(
                "w", encoding="utf-8"
            ) as handle:
                for event in events:
                    handle.write(json.dumps(
                        _record(event), separators=(",", ":"),
                    ) + "\n")
            counts[config] = len(events)
        quote_rows = sum(
            len(event.quotes) for events in groups.values() for event in events
        )
    elif mode == "JOURNAL":
        with StreamingSignalQuoteJournal(specs) as journal:
            for config, scenario in _scenarios():
                events = iter_incremental_baseline_signals(
                    iter_complete_indicator_chunks(
                        directory / "underlying_bars.csv",
                        chunk_rows=chunk_rows,
                        max_session_rows=max_session_rows,
                    ),
                    specs, start_ns=start_ns, end_ns=end_ns,
                    scenario=scenario,
                )
                journal.add_signals(config, events, horizon_minutes=65.0)
            journal.capture_quotes(
                directory / "option_quotes.csv",
                matching_mode=journal_matching,
                bucket_minutes=bucket_minutes,
                max_cache_buckets=max_cache_buckets,
                max_cached_candidates=max_cached_candidates,
                max_cached_symbols=max_cached_symbols,
            )
            for config, _ in _scenarios():
                with (output / f"config-{config}-events.jsonl").open(
                    "w", encoding="utf-8"
                ) as handle:
                    for event in journal.iter_events(config):
                        handle.write(json.dumps(
                            _record(event), separators=(",", ":"),
                        ) + "\n")
                counts[config] = journal.count(config)
            lookup_metrics = journal.snapshot_metrics()
            quote_rows = lookup_metrics["captured_quote_rows"]
    else:
        raise ValueError("mode must be FULL or JOURNAL")
    elapsed = time.perf_counter() - start_clock
    metadata.write_text(json.dumps({
        "mode": mode, "elapsed_seconds": elapsed,
        "peak_process_rss_kib": peak_process_rss_kib(),
        "counts": counts, "captured_quote_rows": quote_rows,
        "lookup_metrics": lookup_metrics,
    }, allow_nan=False), encoding="utf-8")


def compare_event_records(reference: Path, candidate: Path, max_examples=30):
    from .benchmark_incremental_signals import _compare_value
    count = 0
    examples = []
    with reference.open(encoding="utf-8") as left, candidate.open(
        encoding="utf-8"
    ) as right:
        for row_number, (old, new) in enumerate(
            zip_longest(left, right), start=1,
        ):
            if old is None or new is None:
                count += 1
                if len(examples) < max_examples:
                    examples.append(f"row {row_number}: row count differs")
                break
            differences = []
            _compare_value(
                json.loads(old), json.loads(new), f"row {row_number}",
                differences, rtol=0.0, atol=0.0,
            )
            count += len(differences)
            examples.extend(differences[:max(0, max_examples-len(examples))])
    return count, examples


def benchmark_signal_quote_journal(
    directory: Path, start: str, end: str, output: Path, *,
    rounds: int = 3, chunk_rows: int = 512,
    max_session_rows: int = 4096,
    journal_matching: str = "SQL", bucket_minutes: int = 5,
    max_cache_buckets: int = 256, max_cached_candidates: int = 4096,
    max_cached_symbols: int = 256,
):
    if type(rounds) is not int or not 1 <= rounds <= 10:
        raise ValueError("rounds must be an integer between 1 and 10")
    if type(chunk_rows) is not int or chunk_rows < 1:
        raise ValueError("chunk_rows must be a positive integer")
    if type(max_session_rows) is not int or max_session_rows < 1:
        raise ValueError("max_session_rows must be a positive integer")
    if journal_matching not in {"SQL", "BUCKET_CACHE", "SYMBOL_INDEX"}:
        raise ValueError("journal_matching must be SQL, BUCKET_CACHE or SYMBOL_INDEX")
    for name, value in (
        ("bucket_minutes", bucket_minutes),
        ("max_cache_buckets", max_cache_buckets),
        ("max_cached_candidates", max_cached_candidates),
        ("max_cached_symbols", max_cached_symbols),
    ):
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    output.mkdir(parents=True, exist_ok=True)
    reference_dir = output / "reference-full"
    results = []
    examples = []
    for iteration in range(rounds):
        modes = (
            ("FULL", "JOURNAL", "JOURNAL", "FULL")
            if iteration % 2 == 0
            else ("JOURNAL", "FULL", "FULL", "JOURNAL")
        )
        for position, mode in enumerate(modes, start=1):
            label = f"round-{iteration + 1:02d}-{position}-{mode.lower()}"
            run_dir = output / label
            run_dir.mkdir(exist_ok=True)
            metrics_file = output / f"{label}.json"
            subprocess.run([
                sys.executable, "-m", "backtest.benchmark_signal_quote_journal",
                "--child", "--directory", str(directory),
                "--start", start, "--end", end,
                "--output", str(run_dir), "--metadata", str(metrics_file),
                "--mode", mode, "--chunk-rows", str(chunk_rows),
                "--max-session-rows", str(max_session_rows),
                "--journal-matching", journal_matching,
                "--bucket-minutes", str(bucket_minutes),
                "--max-cache-buckets", str(max_cache_buckets),
                "--max-cached-candidates", str(max_cached_candidates),
                "--max-cached-symbols", str(max_cached_symbols),
            ], check=True)
            metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
            metrics_file.unlink()
            if not results:
                if mode != "FULL":
                    raise RuntimeError("INITIAL_BENCHMARK_MUST_BE_FULL")
                reference_dir.mkdir(exist_ok=True)
                for item in run_dir.iterdir():
                    (reference_dir / item.name).write_bytes(item.read_bytes())
            difference_count = 0
            for config, _ in _scenarios():
                filename = f"config-{config}-events.jsonl"
                delta, sample = compare_event_records(
                    reference_dir / filename, run_dir / filename,
                )
                difference_count += delta
                examples.extend(
                    f"{label}/{filename}: {message}" for message in sample
                    if len(examples) < 30
                )
            if results and (
                metrics["counts"] != results[0]["counts"]
                or metrics["captured_quote_rows"] != results[0]["captured_quote_rows"]
            ):
                difference_count += 1
                if len(examples) < 30:
                    examples.append(f"{label}: signal/quote counts mismatch")
            results.append({
                "round": iteration + 1, "position": position,
                **metrics, "difference_count": difference_count,
            })
            if not difference_count:
                for item in run_dir.iterdir():
                    item.unlink()
                run_dir.rmdir()
    summary = {}
    for mode in ("FULL", "JOURNAL"):
        selected = [entry for entry in results if entry["mode"] == mode]
        rss = [row["peak_process_rss_kib"] for row in selected
               if row["peak_process_rss_kib"] is not None]
        summary[mode] = {
            "runs": len(selected),
            "median_seconds": statistics.median(
                row["elapsed_seconds"] for row in selected
            ),
            "median_peak_rss_kib": statistics.median(rss) if rss else None,
        }
    total = sum(entry["difference_count"] for entry in results)
    manifest = {
        "input": str(directory), "start": start, "end": end,
        "rounds": rounds, "comparison": "H6_SIGNAL_QUOTE_JOURNAL",
        "journal_matching": journal_matching,
        "bucket_minutes": bucket_minutes,
        "max_cache_buckets": max_cache_buckets,
        "max_cached_candidates": max_cached_candidates,
        "max_cached_symbols": max_cached_symbols,
        "chunk_rows": chunk_rows,
        "max_session_rows": max_session_rows,
        "parity_passed": total == 0, "difference_count": total,
        "differences": examples[:30], "statistics": summary,
        "measurements": results,
        "notes": (
            "All H6 BASELINE signal events and their ordered normalized option "
            "bid/ask, sizes, volume and OI quote records are compared exactly, "
            "including event metadata and counts. This is an opt-in quote "
            "replay experiment, NOT end-to-end trade, exit, fee or GST parity. "
            "SQL preserves original per-quote database matching; BUCKET_CACHE "
            "uses bounded cached candidate windows with original SQL fallback "
            "for dense time buckets. SYMBOL_INDEX caches per-symbol windows "
            "with capped LRU bounds and per-quote SQL fallback for dense "
            "symbols. Original run_dataset remains unchanged."
        ),
    }
    (output / "benchmark.json").write_text(json.dumps(
        manifest, indent=2, allow_nan=False,
    ) + "\n", encoding="utf-8")
    if total:
        raise ValueError(f"SIGNAL_QUOTE_PARITY_MISMATCH: {total} differences")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Compare original H6 quote capture against streaming signal journal")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--chunk-rows", type=int, default=512)
    parser.add_argument("--max-session-rows", type=int, default=4096)
    parser.add_argument("--journal-matching", choices=["SQL", "BUCKET_CACHE", "SYMBOL_INDEX"],
                        default="SQL")
    parser.add_argument("--bucket-minutes", type=int, default=5)
    parser.add_argument("--max-cache-buckets", type=int, default=256)
    parser.add_argument("--max-cached-candidates", type=int, default=4096)
    parser.add_argument("--max-cached-symbols", type=int, default=256)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=["FULL", "JOURNAL"], help=argparse.SUPPRESS)
    parser.add_argument("--metadata", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        if args.mode is None or args.metadata is None:
            parser.error("--mode and --metadata required with --child")
        _child(
            args.directory, args.start, args.end,
            args.output, args.metadata, args.mode,
            chunk_rows=args.chunk_rows,
            max_session_rows=args.max_session_rows,
            journal_matching=args.journal_matching,
            bucket_minutes=args.bucket_minutes,
            max_cache_buckets=args.max_cache_buckets,
            max_cached_candidates=args.max_cached_candidates,
            max_cached_symbols=args.max_cached_symbols,
        )
    else:
        print(json.dumps(benchmark_signal_quote_journal(
            args.directory, args.start, args.end, args.output,
            rounds=args.rounds, chunk_rows=args.chunk_rows,
            max_session_rows=args.max_session_rows,
            journal_matching=args.journal_matching,
            bucket_minutes=args.bucket_minutes,
            max_cache_buckets=args.max_cache_buckets,
            max_cached_candidates=args.max_cached_candidates,
            max_cached_symbols=args.max_cached_symbols,
        ), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
