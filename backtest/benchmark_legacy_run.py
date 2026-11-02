"""Offline, separate-process legacy EMA/VWAP quote-mode benchmark and parity check.

All modes run identical input and scenarios in separate processes without\nnetwork access. Peak process RSS is measured on Windows and Linux.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .compare_legacy_reports import compare
from .process_memory import peak_process_rss_kib


def _child(directory: Path, start: str, end: str, mode: str, output: Path,
           max_captured_quotes: int | None, algorithm: str = 'LEGACY',
           retain_decision_events: bool = True,
           prune_inactive_instruments: bool = False,
           indicator_chunk_rows: int | None = None,
           indexed_option_selection: bool = False,
           quote_csv_parser: str = 'POSITIONAL',
           positional_bar_lookup: bool = False,
           quote_spool_encoding: str = "JSON",
           record_spool_metrics: bool = False,
           record_memory_inventory: bool = False) -> None:
    from .ema_vwap_research import run_dataset, locked_h6_scenarios
    begin=time.perf_counter()
    spool_metrics = {}
    phase_memory = []
    retention_inventory = []
    def on_stage(stage, seconds):
        phase_memory.append({
            "stage": stage,
            "elapsed_seconds": seconds,
            "cumulative_peak_rss_kib": peak_process_rss_kib(),
        })
    def on_retention(stage, counts):
        retention_inventory.append({"stage": stage, **counts})
    result=run_dataset(directory,start=start,end=end,
                       scenario_set=locked_h6_scenarios(),
                       quote_capture_storage=mode,
                       quote_capture_algorithm=algorithm,
                       max_captured_quotes=max_captured_quotes,
                       retain_decision_events=retain_decision_events,
                       prune_inactive_instruments=prune_inactive_instruments,
                       indicator_chunk_rows=indicator_chunk_rows,
                       indexed_option_selection=indexed_option_selection,
                       quote_csv_parser=quote_csv_parser,
                       positional_bar_lookup=positional_bar_lookup,
                       quote_spool_encoding=quote_spool_encoding,
                       quote_spool_observer=spool_metrics.update if record_spool_metrics else None,
                       stage_observer=on_stage if record_memory_inventory else None,
                       retention_observer=on_retention if record_memory_inventory else None)
    elapsed=time.perf_counter()-begin
    rss=peak_process_rss_kib()
    output.write_text(json.dumps({"result":result,"elapsed_seconds":elapsed,
                                  "peak_process_rss_kib":rss,
                                  "quote_spool_metrics":spool_metrics or None,
                                  "phase_memory":phase_memory if record_memory_inventory else None,
                                  "retention_inventory":retention_inventory if record_memory_inventory else None},allow_nan=False))


def benchmark(directory: Path,start: str,end: str,output: Path,
              max_captured_quotes: int | None = None,
              retain_decision_events: bool = True,
              include_pruned_profile: bool = False,
              indicator_chunk_rows: int | None = None,
              include_indexed_profile: bool = False,
              include_positional_profile: bool = False,
              include_bar_lookup_profile: bool = False,
              include_combined_profile: bool = False,
              include_packed_sqlite_profile: bool = False) -> dict:
    output.mkdir(parents=True,exist_ok=True)
    paths={}
    measurements={}
    profiles = [("MEMORY", "MEMORY", "LEGACY", False),
                ("SQLITE", "SQLITE", "SWEEP", False)]
    if include_pruned_profile:
        profiles.append(("SQLITE_PRUNED", "SQLITE", "SWEEP", True))
    if indicator_chunk_rows is not None:
        if type(indicator_chunk_rows) is not int or indicator_chunk_rows < 1:
            raise ValueError("indicator_chunk_rows must be a positive integer")
        profiles.append(("SQLITE_STREAMED_INDICATORS", "SQLITE", "SWEEP", False))
    if include_indexed_profile:
        profiles.append(("MEMORY_INDEXED", "MEMORY", "LEGACY", False))
    if include_positional_profile:
        profiles.append(("MEMORY_POSITIONAL", "MEMORY", "LEGACY", False))
    if include_bar_lookup_profile:
        profiles.append(("MEMORY_BAR_LOOKUP", "MEMORY", "LEGACY", False))
    if include_combined_profile:
        profiles.append(("MEMORY_COMBINED", "MEMORY", "LEGACY", False))
    if include_packed_sqlite_profile:
        profiles += [
            ("SQLITE_POSITIONAL_JSON", "SQLITE", "SWEEP", False),
            ("SQLITE_POSITIONAL_PACKED", "SQLITE", "SWEEP", False),
        ]
    for key,mode,algorithm,prune in profiles:
        target=output/f"{key.lower()}-result.json"
        argv=[sys.executable,"-m","backtest.benchmark_legacy_run","--child",
              "--directory",str(directory),"--start",start,"--end",end,
              "--mode",mode,"--algorithm",algorithm,"--output",str(target)]
        # Freeze historical benchmark profiles to their original DICT parser;
        # the opt-in positional profile is compared independently.
        csv_parser = "POSITIONAL" if key in {
            "MEMORY_POSITIONAL", "MEMORY_COMBINED",
            "SQLITE_POSITIONAL_JSON", "SQLITE_POSITIONAL_PACKED",
        } else "DICT"
        bar_lookup = key in {
            "MEMORY_BAR_LOOKUP", "MEMORY_COMBINED",
            "SQLITE_POSITIONAL_JSON", "SQLITE_POSITIONAL_PACKED",
        }
        spool_encoding = "PACKED" if key == "SQLITE_POSITIONAL_PACKED" else "JSON"
        argv += ["--quote-csv-parser", csv_parser,
                 "--quote-spool-encoding", spool_encoding]
        if bar_lookup:
            argv.append("--positional-bar-lookup")
        if mode == "SQLITE":
            argv.append("--quote-spool-metrics")
        if max_captured_quotes is not None:
            argv+=["--max-captured-quotes",str(max_captured_quotes)]
        if not retain_decision_events:
            argv+=["--omit-decision-events"]
        if prune:
            argv+=["--prune-inactive-instruments"]
        if key == "MEMORY_INDEXED":
            argv.append("--indexed-option-selection")
        if key == "SQLITE_STREAMED_INDICATORS":
            argv += ["--indicator-chunk-rows", str(indicator_chunk_rows)]
        subprocess.run(argv,check=True)
        artifact=json.loads(target.read_text())
        paths[key]=output/f"{key.lower()}-report.json"
        paths[key].write_text(json.dumps(artifact["result"],allow_nan=False))
        measurements[key]={"elapsed_seconds":artifact["elapsed_seconds"],
                           "peak_process_rss_kib":artifact["peak_process_rss_kib"],
                           "capture_algorithm":algorithm,
                           "indexed_option_selection":key == "MEMORY_INDEXED",
                           "positional_bar_lookup":bar_lookup,
                           "quote_csv_parser":csv_parser,
                           "quote_spool_encoding":spool_encoding,
                           "quote_spool_metrics":artifact.get("quote_spool_metrics"),
                           "prune_inactive_instruments":prune,
                           "indicator_chunk_rows":indicator_chunk_rows if key == "SQLITE_STREAMED_INDICATORS" else None}
        target.unlink()
    differences_by_mode={
        key:compare(paths["MEMORY"],paths[key])
        for key in paths if key!="MEMORY"
    }
    difference_count=sum(len(diffs) for diffs in differences_by_mode.values())
    differences=[
        f"{key}: {problem}"
        for key,diffs in differences_by_mode.items() for problem in diffs
    ]
    summary={"input":str(directory),"start":start,"end":end,
             "parity_passed":not differences,"differences":differences[:30],
             "difference_count":difference_count,
             "difference_counts_by_mode":{
                 key:len(items) for key,items in differences_by_mode.items()
             },
             "measurements":measurements,
             "scope":"locked H6 research; independent processes",
             "retained_decision_events":retain_decision_events,
             "peak_rss_definition":"Linux ru_maxrss or Windows PeakWorkingSetSize; KiB"}
    (output/"benchmark.json").write_text(json.dumps(summary,indent=2)+"\n")
    if differences:
        raise ValueError(f"RESULT_PARITY_MISMATCH: {difference_count} differences")
    return summary


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--directory",type=Path,required=True)
    p.add_argument("--start",required=True)
    p.add_argument("--end",required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--max-captured-quotes",type=int)
    p.add_argument("--omit-decision-events",action="store_true")
    p.add_argument("--include-pruned-profile",action="store_true")
    p.add_argument("--indicator-chunk-rows",type=int)
    p.add_argument("--include-indexed-profile",action="store_true")
    p.add_argument("--include-bar-lookup-profile",action="store_true")
    p.add_argument("--include-combined-profile",action="store_true")
    p.add_argument("--include-packed-sqlite-profile",action="store_true")
    p.add_argument("--quote-spool-metrics",action="store_true",help=argparse.SUPPRESS)
    p.add_argument("--memory-inventory",action="store_true",help=argparse.SUPPRESS)
    p.add_argument("--quote-spool-encoding",choices=["JSON", "PACKED"],default="JSON",
                   help=argparse.SUPPRESS)
    p.add_argument("--positional-bar-lookup",action="store_true",help=argparse.SUPPRESS)
    p.add_argument("--include-positional-profile",action="store_true")
    p.add_argument("--quote-csv-parser",choices=["DICT","POSITIONAL"],default="POSITIONAL",help=argparse.SUPPRESS)
    p.add_argument("--indexed-option-selection",action="store_true",help=argparse.SUPPRESS)
    p.add_argument("--prune-inactive-instruments",action="store_true",help=argparse.SUPPRESS)
    p.add_argument("--child",action="store_true",help=argparse.SUPPRESS)
    p.add_argument("--mode",choices=["MEMORY","SQLITE"],help=argparse.SUPPRESS)
    p.add_argument("--algorithm",choices=["LEGACY","SWEEP"],default="LEGACY",help=argparse.SUPPRESS)
    a=p.parse_args()
    if a.child:
        if not a.mode:
            p.error("--mode required for --child")
        _child(a.directory,a.start,a.end,a.mode,a.output,a.max_captured_quotes,
               a.algorithm,not a.omit_decision_events,a.prune_inactive_instruments,
               a.indicator_chunk_rows,a.indexed_option_selection,a.quote_csv_parser,
               a.positional_bar_lookup,a.quote_spool_encoding,a.quote_spool_metrics,
               a.memory_inventory)
    else:
        print(json.dumps(benchmark(a.directory,a.start,a.end,a.output,
                                   a.max_captured_quotes,
                                   retain_decision_events=not a.omit_decision_events,
                                   include_pruned_profile=a.include_pruned_profile,
                                   indicator_chunk_rows=a.indicator_chunk_rows,
                                   include_indexed_profile=a.include_indexed_profile,
                                   include_positional_profile=a.include_positional_profile,
                                   include_bar_lookup_profile=a.include_bar_lookup_profile,
                                   include_combined_profile=a.include_combined_profile,
                                   include_packed_sqlite_profile=a.include_packed_sqlite_profile),indent=2))


if __name__=="__main__":
    main()
