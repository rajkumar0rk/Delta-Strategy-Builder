"""Run free futures history sync using the same subprocess pattern as archive_sync.

No eager import of backtest/ from the visualizer/backend Python import path.
"""
from __future__ import annotations

import os
import subprocess
import sys

from .config import data_root, project_root


def ensure_futures_observations(start, end, progress=None):
    if progress:
        progress("Checking free Delta futures mark/index/funding-rate history…", 9,
                 "FUTURES_DATA_SYNC", "Reuse valid stored daily shards")
    cmd=[sys.executable,"-m","backtest.futures_history",
         "--root",str(data_root().resolve()),"--start",start,"--end",end]
    proc=subprocess.Popen(
        cmd,cwd=str(project_root()),env=os.environ.copy(),stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,text=True,encoding="utf-8",errors="replace",bufsize=1)
    try:
        assert proc.stdout is not None
        messages=[]
        for raw in proc.stdout:
            message=raw.strip()
            if message:
                messages.append(message)
                if len(messages)>15:
                    messages.pop(0)
                if progress:
                    progress(message,12,"FUTURES_DATA_SYNC","Load BTC candles and validate funding assumptions")
        status=proc.wait()
        if status:
            raise RuntimeError("Free futures history sync failed: "+("; ".join(messages[-5:])))
        return {"downloaded_or_reused":True,"root":str(data_root()/"futures")}
    except BaseException:
        if proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill()
        raise
