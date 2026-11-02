"""Offline streaming CSV benchmark without fetching or modifying market history.

python -m backtest.benchmark_legacy_csv --path /path/to/option_quotes.csv --max-rows 100000
Reports peak traced Python allocations and elapsed time for a bounded scan.
Tracemalloc excludes native/Pandas allocator overhead; not a process RSS cap.
"""
from __future__ import annotations
import argparse
import json
import resource
import time
import tracemalloc
from pathlib import Path

from .csv_stream import iter_csv_rows


def benchmark(path:Path,max_rows:int=100000)->dict:
    if max_rows<1:
        raise ValueError("max_rows must be positive")
    t=time.perf_counter();tracemalloc.start()
    count=0
    try:
        for _ in iter_csv_rows(path):
            count+=1
            if count>=max_rows:
                break
        _,peak=tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return {"path":str(path),"rows_scanned":count,
            "python_peak_memory_bytes":peak,
            "elapsed_seconds":round(time.perf_counter()-t,4),
            "process_max_rss_kib_linux":(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if __import__("sys").platform.startswith("linux") else None),
            "note":"Streaming scan only; not complete backtest peak RSS or execution benchmark"}


def main()->None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--path",type=Path,required=True)
    parser.add_argument("--max-rows",type=int,default=100000)
    args=parser.parse_args()
    print(json.dumps(benchmark(args.path,args.max_rows),indent=2))


if __name__=="__main__":
    main()
