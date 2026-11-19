"""Frozen V5.2B BTCUSD perpetual futures research port, 2025/2026.

Strategy signals are unchanged; the BTC execution contract is 0.001 BTC/lot
and tick is 0.5 USD. Runs the exact original BTCUSD engine and frozen strategy without production changes.
"""
from __future__ import annotations
import gzip, hashlib, io, json, os, sys, time, urllib.request, urllib.parse
from pathlib import Path
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PIN="98d2751f3ab357ae247b0416eeb266093967e16d"
RAW=f"https://raw.githubusercontent.com/rajkumar0rk/BTC-Analysis/{PIN}/data/delta_india/BTCUSD/1m/"
API="https://api.india.delta.exchange/v2/history/candles"
OUT=HERE/"outputs"
DROOT=HERE/"data"
FROZEN=HERE/"strategy_btc_original.json"

def fetch(url):
    for attempt in range(5):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"Independent-V5.2B-BTC-futures-study"})
            with urllib.request.urlopen(req,timeout=75) as resp:
                return resp.read()
        except Exception as exc:
            if attempt==4: raise RuntimeError(f"DOWNLOAD_FAILED {url}: {exc}") from exc
            time.sleep((attempt+1)*2)

def load_btc_1m(months):
    manifest=json.loads(fetch(RAW+"manifest.json"))
    known={p["file"][:7]:p for p in manifest["partitions"]}
    frames=[];checks={}
    for month in months:
        row=known.get(month)
        if row is None: raise RuntimeError(f"MISSING_ARCHIVE_MONTH {month}")
        payload=fetch(RAW+row["file"])
        checksum=hashlib.sha256(payload).hexdigest()
        if checksum!=row["sha256_gzip"]:raise RuntimeError(f"SHA256_MISMATCH {month}")
        f=pd.read_csv(io.BytesIO(gzip.decompress(payload)))
        if not {"time","open","high","low","close","volume"}.issubset(f.columns):
            raise RuntimeError(f"INVALID_1M_COLUMNS {month}")
        if len(f)!=row["expected_minutes"] or row["missing_minutes"]!=0:
            raise RuntimeError(f"INCOMPLETE_1M_MONTH {month}")
        timestamps=pd.to_datetime(f["time"],unit="s",utc=True)
        if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
            raise RuntimeError(f"1M_NONMONOTONIC {month}")
        if not timestamps.diff().dropna().eq(pd.Timedelta(minutes=1)).all():
            raise RuntimeError(f"1M_GAPS {month}")
        f=f[["open","high","low","close","volume"]].apply(pd.to_numeric,errors="raise")
        f.index=timestamps+pd.Timedelta(minutes=1) # Convert minute OPEN stamp -> minute CLOSE.
        agg=f.resample("5min",label="right",closed="right").agg(
           {"open":"first","high":"max","low":"min","close":"last","volume":"sum"})
        counts=f["close"].resample("5min",label="right",closed="right").count()
        if (counts!=5).any():
            raise RuntimeError(f"INCOMPLETE_DERIVED_5M {month}")
        frames.append(agg)
        checks[month]={"1m":len(f),"5m":len(agg),"sha256":checksum}
        print("Checked BTCUSD 1m",month,len(f),"-> 5m",len(agg),flush=True)
    return pd.concat(frames),checks

def download_2024_warmup():
    # V5.2B uses 4H EMA200, so the full 5x conservative warmup requires
    # about 167 days before Jan 1, 2025. Use 184 days of 2024 5m BTC candles.
    start=pd.Timestamp("2024-07-01T00:00:00Z")
    end=pd.Timestamp("2025-01-01T00:00:00Z")
    allrows=[]
    cursor=start
    chunk=1500 # exchange documents max 2000 candles per response
    num=0
    while cursor<end:
        stop=min(cursor+pd.Timedelta(minutes=5*chunk),end)
        left=int(cursor.timestamp())
        right=int((stop-pd.Timedelta(seconds=1)).timestamp())
        query=urllib.parse.urlencode({"resolution":"5m","symbol":"BTCUSD","start":left,"end":right})
        raw=json.loads(fetch(API+"?"+query))
        rows=raw.get("result",[])
        if raw.get("success") is not True or not isinstance(rows,list):
            raise RuntimeError(f"DELTA_2024_WARMUP_API_ERROR {cursor} {str(raw)[:500]}")
        allrows.extend(rows)
        num+=1
        if num%10==0:
            print("2024 warmup API windows",num,flush=True)
        cursor=stop
        time.sleep(0.14)
    if not allrows: raise RuntimeError("NO_2024_BTC_CANDLES")
    f=pd.DataFrame(allrows)
    if not {"time","open","high","low","close","volume"}.issubset(f.columns):
        raise RuntimeError("2024_API_SCHEMA_MISMATCH "+str(list(f.columns)))
    timestamps=pd.to_datetime(pd.to_numeric(f["time"]),unit="s",utc=True)
    if timestamps.duplicated().any():
        f=f.drop_duplicates(subset=["time"],keep="last")
        timestamps=pd.to_datetime(pd.to_numeric(f["time"]),unit="s",utc=True)
    f=f[["open","high","low","close","volume"]].apply(pd.to_numeric,errors="raise")
    f.index=timestamps
    f=f.sort_index()
    expected=pd.date_range(start=start,end=end-pd.Timedelta(minutes=5),freq="5min",tz="UTC")
    if len(f)!=len(expected) or not f.index.equals(expected):
        missing=expected.difference(f.index)
        raise RuntimeError(f"2024_WARMUP_INCOMPLETE expected={len(expected)} actual={len(f)} missing={len(missing)} first={missing[:5].tolist()}")
    f.index=f.index+pd.Timedelta(minutes=5) # Convert 5m OPEN -> 5m CLOSE
    print("2024 BTCUSD 5m warmup verified",len(f),"candles",flush=True)
    return f,{"source":API,"resolution":"5m","start":"2024-07-01","end_exclusive":"2025-01-01","candles":len(f),"api_calls":num}

def main():
    year=sys.argv[1]
    if year not in {"2025","2026"}:raise ValueError("Usage: run.py 2025|2026")
    out=OUT/year;out.mkdir(parents=True,exist_ok=True)
    data_root=DROOT/year
    dataset=data_root/"frozen";dataset.mkdir(parents=True,exist_ok=True)
    os.environ["STRATEGY_LAB_DATA_ROOT"]=str(data_root)
    os.environ["STRATEGY_LAB_RESULT_ROOT"]=str(out/"original_engine")
    os.environ["STRATEGY_LAB_CACHE_ROOT"]=str(out/"cache")
    begin="2026-01-01T00:00:00Z" if year=="2026" else "2025-01-01T00:00:00Z"
    end="2026-11-01T00:00:00Z" if year=="2026" else "2026-01-01T00:00:00Z"
    months=list(pd.period_range("2025-01", "2026-10" if year=="2026" else "2025-12",freq="M").astype(str))
    f,checks=load_btc_1m(months)
    warmup=None
    if year=="2025":
        older,warmup=download_2024_warmup()
        f=pd.concat([older,f])
    f=f.sort_index()
    if f.index.has_duplicates or not f.index.to_series().diff().dropna().eq(pd.Timedelta(minutes=5)).all():
        raise RuntimeError("GAP_IN_FULL_5M_SERIES")
    f.insert(0,"timestamp",f.index.strftime("%Y-%m-%dT%H:%M:%SZ"))
    f.to_csv(dataset/"underlying_bars.csv",index=False)
    print("Converted complete 5m BTC candles",len(f),flush=True)

    sys.path.insert(0,str(ROOT/"visualizer"/"backend"))
    from app.models import StrategyConfig, BacktestRequest
    from app.engine import run_backtest

    original=json.loads(FROZEN.read_text())
    strategy=StrategyConfig.model_validate(original["strategy"])
    if strategy.market_type!="FUTURES" or strategy.futures.funding_mode!="EXCLUDE_WITH_WARNING":
        raise RuntimeError("STRATEGY_INTEGRITY_MISMATCH")
    if strategy.futures.taker_fee_percent!=0.05 or strategy.futures.gst_percent!=18:
        raise RuntimeError("FROZEN_FEE_MODEL_CHANGED")
    if strategy.futures.margin_tier_mode!="FLAT_RESEARCH":
        raise RuntimeError("FROZEN_MARGIN_POLICY_CHANGED")
    if not strategy.name.startswith("BTCUSD Futures | V5.2 B"):
        raise RuntimeError("WRONG_ORIGINAL_STRATEGY")
    # BTCUSD: original strategy, contract, tick size and costs UNCHANGED.
    req=BacktestRequest(dataset_mode="SINGLE",dataset_id="frozen",start=begin,end=end,
        strategy=strategy,storage_mode="COMPACT",bar_gap_policy="REQUIRE",
        warmup_policy="REQUIRE")
    print("Run 2025/26 BTC futures in original strategy engine",year,flush=True)
    result=run_backtest(req,lambda msg,*args:print("ENGINE",msg,flush=True))
    m=result["metrics"];trades=result["trades"]
    if not result["warmup"]["contiguous"]:raise RuntimeError("WARMUP_INCOMPLETE")
    if abs(sum(t["net_pnl_usd"] for t in trades)-m["net_pnl_usd"])>1e-5:
        raise RuntimeError("NET_PNL_RECONCILIATION_FAILED")
    if any(abs(t["net_pnl_usd"]-(t["gross_pnl_usd"]-t["fees_usd"]+t["funding_usd"]))>1e-5 for t in trades):
        raise RuntimeError("GROSS_FEES_GST_RECONCILIATION_FAILED")
    if any(t["symbol"]!="BTCUSD" for t in trades):
        raise RuntimeError("WRONG_OUTPUT_SYMBOL")
    by_month={}
    for t in trades:
        key=pd.Timestamp(t["exit_time"]).tz_convert("Asia/Kolkata").strftime("%Y-%m")
        by_month.setdefault(key,[]).append(t)
    rows=[]
    for month in pd.period_range(year+"-01",year+"-12" if year=="2025" else "2026-10",freq="M").astype(str):
        ts=by_month.get(month,[])
        wins=sum(t["net_pnl_usd"]>0 for t in ts)
        profits=sum(max(0,t["net_pnl_usd"]) for t in ts)
        losses=-sum(min(0,t["net_pnl_usd"]) for t in ts)
        rows.append({"month_ist":month,"trades":len(ts),"wins":wins,"losses":len(ts)-wins,
          "gross_usd":sum(t["gross_pnl_usd"] for t in ts),
          "base_fees_usd":sum(t["base_fees_usd"] for t in ts),
          "gst_usd":sum(t["gst_usd"] for t in ts),
          "net_pnl_usd":sum(t["net_pnl_usd"] for t in ts),
          "profit_factor":profits/losses if losses else ("inf" if profits else None)})
    pd.DataFrame(rows).to_csv(out/("monthly_"+year+"_IST.csv"),index=False)
    pd.DataFrame(trades).to_csv(out/("trades_"+year+".csv"),index=False)
    spillover=sum(t["net_pnl_usd"] for k,ts in by_month.items()
        if k not in {r["month_ist"] for r in rows} for t in ts)
    if abs(sum(r["net_pnl_usd"] for r in rows)+spillover-m["net_pnl_usd"])>1e-5:
        raise RuntimeError("MONTHLY_TOTAL_MISMATCH")
    summary={
      "strategy":"BTCUSD V5.2B research port of original BTC rules",
      "source_sha256":hashlib.sha256(FROZEN.read_bytes()).hexdigest(),
      "year":year,"start":begin,"end":end,"data_source":PIN,"data_quality":checks,
      "warmup_2024":warmup,"metrics":m,"warmup":result.get("warmup"),
      "preflight":result.get("preflight"),"unresolved_position":result.get("unresolved_position"),
      "reliability":result.get("reliability"),"spillover_usd":spillover}
    (out/("summary_"+year+".json")).write_text(json.dumps(summary,indent=2,default=str))
    lines=[
      "# V5.2B BTCUSD futures "+year+" independent research replay",
      "", "Actual Strategy Lab futures engine run, BTC V5.2B signals and risk unchanged.",
      "BTC contract port: 0.001 BTC per lot; tick USD 0.5; 3x isolated; modeled 0.05% taker/side, 18% GST and 2bps slippage.",
      "Funding excluded and OHLC proxy used; historical BTC venue fills and margin tiers not reconstructed.",
      f"Source 2025/26 Delta BTC 1m archive pinned to BTC-Analysis SHA {PIN}.",
      "All monthly rows are realized net at IST EXIT month. Separate $1,000 starting balance for each calendar-year test.",
      "", "## Aggregate", "",
      f"- Trades {m['trades']} / winners {m['wins']}, win rate {m['win_rate_percent']:.2f}%, PF {m['profit_factor']}",
      f"- Gross USD {m['gross_pnl_usd']:+.4f}, fees USD {m['base_fees_usd']:.4f}, GST USD {m['gst_usd']:.4f}, net USD {m['net_pnl_usd']:+.4f}",
      f"- Profitable months {sum(x['net_pnl_usd']>0 for x in rows)}/{len(rows)}; losing {sum(x['net_pnl_usd']<0 for x in rows)}; idle {sum(x['trades']==0 for x in rows)}",
      f"- Warmup contiguous {result['warmup']['contiguous']}, requested {result['warmup']['requested_candles']}, available {result['warmup']['available_candles']}",
      f"- Other IST exit-month P&L USD {spillover:+.4f}",
      "", "## Monthly", "",
      "| IST month | Trades | Wins | Losses | Gross USD | Fees USD | GST USD | Net USD | PF |",
      "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        pf=r["profit_factor"]
        lines.append(f"| {r['month_ist']} | {r['trades']} | {r['wins']} | {r['losses']} | {r['gross_usd']:+.2f} | {r['base_fees_usd']:.2f} | {r['gst_usd']:.2f} | {r['net_pnl_usd']:+.2f} | {pf if isinstance(pf,str) or pf is None else f'{pf:.3f}'} |")
    lines+=["","Research not approved for live deployment. Backtest research only; no live fills, real order-book spreads or funding modeled."]
    md="\n".join(lines)+"\n"
    (out/("RESEARCH_REPORT_"+year+".md")).write_text(md)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a") as f:f.write(md)
    print(md,flush=True)

if __name__=="__main__":main()
