"""Offline, separate-process legacy EMA/VWAP quote-mode benchmark and parity check.

Both modes run the same input and scenario using no network access. Peak\nprocess resident/working-set memory is measured on Linux and Windows.
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
           retain_decision_events: bool = True) -> None:
    from .ema_vwap_research import run_dataset, locked_h6_scenarios
    begin=time.perf_counter()
    result=run_dataset(directory,start=start,end=end,
                       scenario_set=locked_h6_scenarios(),
                       quote_capture_storage=mode,
                       quote_capture_algorithm=algorithm,
                       max_captured_quotes=max_captured_quotes,
                       retain_decision_events=retain_decision_events)
    elapsed=time.perf_counter()-begin
    rss=peak_process_rss_kib()
    output.write_text(json.dumps({"result":result,"elapsed_seconds":elapsed,
                                  "peak_process_rss_kib":rss},allow_nan=False))


def benchmark(directory: Path,start: str,end: str,output: Path,
              max_captured_quotes: int | None = None,
              retain_decision_events: bool = True) -> dict:
    output.mkdir(parents=True,exist_ok=True)
    paths={}
    measurements={}
    for mode,algorithm in (("MEMORY","LEGACY"),("SQLITE","SWEEP")):
        target=output/f"{mode.lower()}-result.json"
        argv=[sys.executable,"-m","backtest.benchmark_legacy_run","--child",
              "--directory",str(directory),"--start",start,"--end",end,
              "--mode",mode,"--algorithm",algorithm,"--output",str(target)]
        if max_captured_quotes is not None:
            argv+=["--max-captured-quotes",str(max_captured_quotes)]
        if not retain_decision_events:
            argv+=["--omit-decision-events"]
        subprocess.run(argv,check=True)
        artifact=json.loads(target.read_text())
        paths[mode]=output/f"{mode.lower()}-report.json"
        paths[mode].write_text(json.dumps(artifact["result"],allow_nan=False))
        measurements[mode]={"elapsed_seconds":artifact["elapsed_seconds"],
                            "peak_process_rss_kib":artifact["peak_process_rss_kib"],
                            "capture_algorithm":algorithm}
        target.unlink()
    differences=compare(paths["MEMORY"],paths["SQLITE"])
    summary={"input":str(directory),"start":start,"end":end,
             "parity_passed":not differences,"differences":differences[:30],
             "difference_count":len(differences),"measurements":measurements,
             "scope":"locked H6 research; both modes run in separate processes",
             "retained_decision_events":retain_decision_events,
             "peak_rss_definition":"Linux ru_maxrss or Windows PeakWorkingSetSize; KiB"}
    (output/"benchmark.json").write_text(json.dumps(summary,indent=2)+"\n")
    if differences:
        raise ValueError(f"RESULT_PARITY_MISMATCH: {len(differences)} differences")
    return summary


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--directory",type=Path,required=True)
    p.add_argument("--start",required=True)
    p.add_argument("--end",required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--max-captured-quotes",type=int)
    p.add_argument("--omit-decision-events",action="store_true")
    p.add_argument("--child",action="store_true",help=argparse.SUPPRESS)
    p.add_argument("--mode",choices=["MEMORY","SQLITE"],help=argparse.SUPPRESS)
    p.add_argument("--algorithm",choices=["LEGACY","SWEEP"],default="LEGACY",help=argparse.SUPPRESS)
    a=p.parse_args()
    if a.child:
        if not a.mode:
            p.error("--mode required for --child")
        _child(a.directory,a.start,a.end,a.mode,a.output,a.max_captured_quotes,
               a.algorithm,not a.omit_decision_events)
    else:
        print(json.dumps(benchmark(a.directory,a.start,a.end,a.output,
                                   a.max_captured_quotes,
                                   retain_decision_events=not a.omit_decision_events),indent=2))


if __name__=="__main__":
    main()
