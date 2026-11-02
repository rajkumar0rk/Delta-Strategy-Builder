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
           quote_csv_parser: str = 'DICT') -> None:
    from .ema_vwap_research import run_dataset, locked_h6_scenarios
    begin=time.perf_counter()
    result=run_dataset(directory,start=start,end=end,
                       scenario_set=locked_h6_scenarios(),
                       quote_capture_storage=mode,
                       quote_capture_algorithm=algorithm,
                       max_captured_quotes=max_captured_quotes,
                       retain_decision_events=retain_decision_events,
                       prune_inactive_instruments=prune_inactive_instruments,
                       indicator_chunk_rows=indicator_chunk_rows,
                       indexed_option_selection=indexed_option_selection,
                       quote_csv_parser=quote_csv_parser)
    elapsed=time.perf_counter()-begin
    rss=peak_process_rss_kib()
    output.write_text(json.dumps({"result":result,"elapsed_seconds":elapsed,
                                  "peak_process_rss_kib":rss},allow_nan=False))


def benchmark(directory: Path,start: str,end: str,output: Path,
              max_captured_quotes: int | None = None,
              retain_decision_events: bool = True,
              include_pruned_profile: bool = False,
              indicator_chunk_rows: int | None = None,
              include_indexed_profile: bool = False,
              include_positional_profile: bool = False) -> dict:
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
    for key,mode,algorithm,prune in profiles:
        target=output/f"{key.lower()}-result.json"
        argv=[sys.executable,"-m","backtest.benchmark_legacy_run","--child",
              "--directory",str(directory),"--start",start,"--end",end,
              "--mode",mode,"--algorithm",algorithm,"--output",str(target)]
        if max_captured_quotes is not None:
            argv+=["--max-captured-quotes",str(max_captured_quotes)]
        if not retain_decision_events:
            argv+=["--omit-decision-events"]
        if prune:
            argv+=["--prune-inactive-instruments"]
        if key == "MEMORY_POSITIONAL":
            argv += ["--quote-csv-parser", "POSITIONAL"]
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
                           "quote_csv_parser":"POSITIONAL" if key == "MEMORY_POSITIONAL" else "DICT",
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
    p.add_argument("--include-positional-profile",action="store_true")
    p.add_argument("--quote-csv-parser",choices=["DICT","POSITIONAL"],default="DICT",help=argparse.SUPPRESS)
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
               a.indicator_chunk_rows,a.indexed_option_selection,a.quote_csv_parser)
    else:
        print(json.dumps(benchmark(a.directory,a.start,a.end,a.output,
                                   a.max_captured_quotes,
                                   retain_decision_events=not a.omit_decision_events,
                                   include_pruned_profile=a.include_pruned_profile,
                                   indicator_chunk_rows=a.indicator_chunk_rows,
                                   include_indexed_profile=a.include_indexed_profile,
                                   include_positional_profile=a.include_positional_profile),indent=2))


if __name__=="__main__":
    main()
