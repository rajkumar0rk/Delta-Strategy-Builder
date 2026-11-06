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
            tail="; ".join(messages[-5:])
            # A DNS outage is not a funding or candle-data requirement.
            # Do not swallow explicit download errors or fabricate quotes.
            diagnostic=" ".join(messages).lower()
            if any(token in diagnostic for token in (
                "getaddrinfo failed", "name or service not known",
                "temporary failure in name resolution", "nodename nor servname",
                "no such host is known",
            )):
                raise RuntimeError(
                    "FUTURES_OBSERVATION_DNS_FAILURE: Windows could not resolve "
                    "api.india.delta.exchange. Supplemental 1m mark/index/rate "
                    "download was explicitly enabled. Disable 'Sync optional futures "
                    "observations' to run from existing BTC OHLCV, or fix DNS/network "
                    "and retry. Required missing BTC archive candles still need "
                    "their own successful download. Cause: "+tail[-350:]
                )
            raise RuntimeError("FUTURES_OBSERVATION_SYNC_FAILED: "+tail)
        return {"downloaded_or_reused":True,"root":str(data_root()/"futures")}
    except BaseException:
        if proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill()
        raise
