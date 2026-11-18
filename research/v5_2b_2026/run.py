"""2026 frozen V5.2B BTCUSD futures replay in the original BTC Strategy Lab engine."""
from __future__ import annotations
import gzip, hashlib, io, json, os, sys, time, urllib.request
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
DATA_ROOT = HERE / "market_data"
PIN = "98d2751f3ab357ae247b0416eeb266093967e16d"
RAW = f"https://raw.githubusercontent.com/rajkumar0rk/BTC-Analysis/{PIN}/data/delta_india/BTCUSD/1m/"
START, END = "2026-01-01T00:00:00Z", "2026-11-01T00:00:00Z"

def fetch(url):
    for retry in range(4):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"v5-2b-futures-replay"})
            with urllib.request.urlopen(req,timeout=60) as f:
                return f.read()
        except Exception:
            if retry==3: raise
            time.sleep(retry+1)

def assemble():
    d=DATA_ROOT/"frozen";d.mkdir(parents=True,exist_ok=True)
    manifest=json.loads(fetch(RAW+"manifest.json"))
    parts=[]; hashes={}; minute_total=0
    for row in manifest["partitions"]:
        month=row["file"][:7]
        if not ("2025-01"<=month<="2026-10"): continue
        content=fetch(RAW+row["file"]); sha=hashlib.sha256(content).hexdigest()
        if sha!=row["sha256_gzip"]: raise RuntimeError("ARCHIVE_SHA256_MISMATCH "+month)
        f=pd.read_csv(io.BytesIO(gzip.decompress(content)))
        needed={"time","open","high","low","close","volume"}
        if not needed.issubset(f.columns): raise RuntimeError("ARCHIVE_COLUMNS_MISSING "+month)
        if len(f)!=row["expected_minutes"]: raise RuntimeError("INCOMPLETE_MINUTES "+month)
        stamps=pd.to_datetime(f["time"],unit="s",utc=True)
        if stamps.duplicated().any() or not stamps.is_monotonic_increasing or not stamps.diff().dropna().eq(pd.Timedelta(minutes=1)).all():
            raise RuntimeError("MINUTE_GAP_OR_DUPLICATE "+month)
        f=f[["open","high","low","close","volume"]].apply(pd.to_numeric,errors="raise")
        f.index=stamps+pd.Timedelta(minutes=1)  # Delta candle open timestamp -> lab candle close timestamp
        agg=f.resample("5min",label="right",closed="right").agg(
            {"open":"first","high":"max","low":"min","close":"last","volume":"sum"})
        counts=f["close"].resample("5min",label="right",closed="right").count()
        if (counts!=5).any(): raise RuntimeError("INCOMPLETE_5M_BARS "+month)
        parts.append(agg);hashes[month]=sha;minute_total+=len(f)
        print("Verified",month,"minute candles:",len(f),flush=True)
    bars=pd.concat(parts).sort_index()
    if bars.index.has_duplicates or not bars.index.to_series().diff().dropna().eq(pd.Timedelta(minutes=5)).all():
        raise RuntimeError("COMBINED_BARS_GAP")
    bars.insert(0,"timestamp",bars.index.strftime("%Y-%m-%dT%H:%M:%SZ"))
    bars.to_csv(d/"underlying_bars.csv",index=False)
    return {"source_commit":PIN,"minute_candles":minute_total,"five_minute_candles":len(bars),"gzip_sha256":hashes}

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    os.environ["STRATEGY_LAB_DATA_ROOT"]=str(DATA_ROOT)
    os.environ["STRATEGY_LAB_RESULT_ROOT"]=str(OUT/"engine")
    os.environ["STRATEGY_LAB_CACHE_ROOT"]=str(OUT/"cache")
    source=assemble()
    sys.path.insert(0,str(ROOT/"visualizer"/"backend"))
    from app.models import BacktestRequest,StrategyConfig
    from app.engine import run_backtest
    strategy_path=HERE/"strategy.json"
    original=json.loads(strategy_path.read_text())
    strategy=StrategyConfig.model_validate(original["strategy"])
    if strategy.market_type!="FUTURES" or "V5.2 B" not in strategy.name:
        raise RuntimeError("FROZEN_STRATEGY_IDENTITY_MISMATCH")
    if strategy.futures.funding_mode!="EXCLUDE_WITH_WARNING":
        raise RuntimeError("FROZEN_FUNDING_ASSUMPTION_CHANGED")
    if strategy.futures.taker_fee_percent!=0.05 or strategy.futures.gst_percent!=18:
        raise RuntimeError("FROZEN_TAKER_FEE_OR_GST_CHANGED")
    req=BacktestRequest(dataset_mode="SINGLE",dataset_id="frozen",
        start=START,end=END,strategy=strategy,storage_mode="COMPACT",
        warmup_policy="REQUIRE",bar_gap_policy="REQUIRE")
    print("Running unchanged V5.2B through original futures engine",flush=True)
    result=run_backtest(req,lambda msg,*args:print("ENGINE",msg,flush=True))
    trades=result["trades"];m=result["metrics"]
    if abs(sum(t["net_pnl_usd"] for t in trades)-m["net_pnl_usd"])>0.00001:
        raise RuntimeError("NET_RECONCILIATION_MISMATCH")
    by_month={}
    for t in trades:
        key=pd.Timestamp(t["exit_time"]).tz_convert("Asia/Kolkata").strftime("%Y-%m")
        by_month.setdefault(key,[]).append(t)
    rows=[]
    for month in pd.period_range("2026-01","2026-10",freq="M").astype(str):
        ts=by_month.get(month,[])
        gp=sum(max(0,t["net_pnl_usd"]) for t in ts)
        gl=-sum(min(0,t["net_pnl_usd"]) for t in ts)
        rows.append({"month_ist":month,"trades":len(ts),
           "wins":sum(t["net_pnl_usd"]>0 for t in ts),
           "losses":sum(t["net_pnl_usd"]<0 for t in ts),
           "gross_usd":sum(t["gross_pnl_usd"] for t in ts),
           "base_fees_usd":sum(t["base_fees_usd"] for t in ts),
           "gst_usd":sum(t["gst_usd"] for t in ts),
           "net_pnl_usd":sum(t["net_pnl_usd"] for t in ts),
           "profit_factor":gp/gl if gl else ("inf" if gp else None)})
    pd.DataFrame(rows).to_csv(OUT/"monthly_2026_IST.csv",index=False)
    pd.DataFrame(trades).to_csv(OUT/"trades_2026.csv",index=False)
    other=sum(t["net_pnl_usd"] for month,ts in by_month.items()
              if month not in {r["month_ist"] for r in rows} for t in ts)
    if abs(sum(r["net_pnl_usd"] for r in rows)+other-m["net_pnl_usd"])>0.00001:
        raise RuntimeError("MONTHLY_RECONCILIATION_MISMATCH")
    summary={"market_type":"FUTURES","strategy":strategy.name,
        "start":START,"end":END,"strategy_sha256":hashlib.sha256(strategy_path.read_bytes()).hexdigest(),
        "data":source,"metrics":m,"warmup":result.get("warmup"),
        "preflight":result.get("preflight"),"unresolved_position":result.get("unresolved_position"),
        "reliability":result.get("reliability"),"other_ist_exit_months_net_usd":other}
    (OUT/"summary_2026.json").write_text(json.dumps(summary,indent=2,default=str))
    report=[
        "# V5.2B 2026 BTCUSD Futures: frozen strategy / original engine",
        "", "Backtest UTC start 2026-01-01, end exclusive 2026-11-01.",
        "Months are grouped by IST exit time; net includes modeled entry/exit taker fees, GST, assumed slippage; funding is excluded.",
        "Original V5.2B JSON retained unchanged. Delta 1m data pinned to BTC-Analysis commit "+PIN+".",
        "", "## Totals",
        f"- Trades: {m['trades']}; win rate: {m['win_rate_percent']:.2f}%; PF: {m['profit_factor']}",
        f"- Gross closed-trade P&L: USD {m['gross_pnl_usd']:+.4f}",
        f"- Base fees: USD {m['base_fees_usd']:.4f}; GST: USD {m['gst_usd']:.4f}",
        f"- Net closed-trade P&L: USD {m['net_pnl_usd']:+.4f}",
        f"- Warmup contiguous: {result['warmup']['contiguous']}",
        f"- 2026 Jan-Oct profitable months: {sum(r['net_pnl_usd']>0 for r in rows)}/10",
        f"- Other IST exit-month net P&L (possible Nov 1 IST spillover): USD {other:+.4f}",
        "", "## Monthly results", "",
        "| IST month | Trades | Wins | Losses | Gross USD | Fees USD | GST USD | Net USD | PF |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        pf=r["profit_factor"]
        report.append(f"| {r['month_ist']} | {r['trades']} | {r['wins']} | {r['losses']} | {r['gross_usd']:+.2f} | {r['base_fees_usd']:.2f} | {r['gst_usd']:.2f} | {r['net_pnl_usd']:+.2f} | {pf if isinstance(pf,str) or pf is None else f'{pf:.3f}'} |")
    report += ["","Research only. OHLC proxy, not real order fills. Funding excluded. The reported 2025 run used other historical data; 2025 parity is not claimed."]
    md="\n".join(report)+"\n"
    (OUT/"RESEARCH_REPORT.md").write_text(md)
    print(md,flush=True)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a") as f:f.write(md)

if __name__=="__main__":main()
