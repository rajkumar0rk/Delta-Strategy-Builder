"""Milestone 6 futures chart / trade audit.

This verifies internal chart-signal, candle-open fill and accounting consistency.
It deliberately does NOT verify exchange execution or true mark/liquidation prices.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import math


def _epoch(value):
    if isinstance(value, (int, float)):
        return int(value)
    dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if dt.tzinfo is None:
        dt=dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _same(a, b, atol=1e-8):
    return math.isclose(float(a),float(b),abs_tol=atol,rel_tol=1e-9)


def audit_futures_parity(result:dict, chart:dict, *, timeframe_minutes:int) -> dict:
    """Compare executed futures with independently calculated preview signals.

    Preview trade markers are result overlays; the independent check is against
    preview condition_states and the actual candle open.
    """
    if result.get("strategy",{}).get("market_type")!="FUTURES":
        raise ValueError("Futures parity audit only accepts market_type=FUTURES")
    if timeframe_minutes not in (5,10,15,30,60):
        raise ValueError("Unsupported futures timeframe")
    trades=result.get("trades") or []
    from .futures_engine import _slipped
    futures=result.get("strategy",{}).get("futures",{})
    bps=float(futures.get("slippage_bps",2))
    tick=float(futures.get("tick_size",0.5))
    extra_ticks=int(futures.get("slippage_ticks",0))
    markers=result.get("markers") or []
    states={int(s["time"]):s for s in chart.get("condition_states") or []}
    bars={int(b["time"]):b for b in chart.get("bars") or []}
    entries=Counter((int(m["time"]),m.get("direction")) for m in markers if m.get("kind")=="entry")
    exits=Counter((int(m["time"]),m.get("direction")) for m in markers if m.get("kind")=="exit")
    failures=[]; warnings=[];checked_signals=0;checked_fills=0
    used_entries=Counter();used_exits=Counter()
    all_trades=list(trades)
    # Keep completed trades separate from the one unresolved end-of-range exposure.
    for t in all_trades:
        direction=t.get("direction")
        side="CALL" if direction=="LONG" else "PUT"
        sign=1 if direction=="LONG" else -1
        if direction not in ("LONG","SHORT"):
            failures.append("Unrecognized futures trade direction")
            continue
        entry=_epoch(t["entry_time"]);finish=_epoch(t["exit_time"])
        if finish<=entry:
            failures.append("Trade exit is not later than its entry")
        key=(entry,side);used_entries[key]+=1
        used_exits[(finish,side)]+=1
        if used_entries[key]>entries[key]:
            failures.append(f"Missing entry chart marker at {t['entry_time']} {direction}")
        if used_exits[(finish,side)]>exits[(finish,side)]:
            failures.append(f"Missing exit chart marker at {t['exit_time']} {direction}")
        # Provenance comes from the engine's consumed, position-aware lifecycle
        # rather than the independent chart preview's non-consuming state.
        if "entry_lifecycle_id" in t:
            if not t.get("entry_lifecycle_eligible") or t.get("entry_lifecycle_expired"):
                failures.append(f"Entry lifecycle was not eligible: trade {t.get('id')}")
            if int(t.get("entry_lifecycle_age_bars", -1)) < int(t.get("entry_lifecycle_delay_bars", 0)):
                failures.append(f"Entry lifecycle delay not satisfied: trade {t.get('id')}")
            if int(t.get("entry_lifecycle_entries_before", 0)) >= int(t.get("entry_lifecycle_max_entries", 1)):
                failures.append(f"Entry lifecycle activation limit exceeded: trade {t.get('id')}")
            if _epoch(t["entry_lifecycle_signal_time"]) != entry:
                failures.append(f"Entry lifecycle signal/next-open mismatch: trade {t.get('id')}")
        else:
            warnings.append(f"Legacy result has no lifecycle provenance: trade {t.get('id')}")
        quantity=float(t["quantity"])
        gross=(float(t["exit_price"])-float(t["entry_price"]))*quantity*sign
        fees=float(t["entry_fee_usd"])+float(t["exit_fee_usd"])
        net=gross-fees+float(t.get("funding_usd") or 0)
        if not _same(gross,t["gross_pnl_usd"]):
            failures.append(f"Gross P&L inconsistent with executed fill: trade {t.get('id')}")
        if not _same(fees,t["fees_usd"]) or not _same(net,t["net_pnl_usd"]):
            failures.append(f"Net P&L / fees inconsistent: trade {t.get('id')}")
        if any(not math.isfinite(float(t[k])) for k in ("entry_price","exit_price","quantity")):
            failures.append(f"Nonfinite futures execution: trade {t.get('id')}")
        bar=bars.get(entry+timeframe_minutes*60)
        if bar is None:
            failures.append(f"Missing OHLC entry bar at {t['entry_time']}; cannot certify parity")
        else:
            opened=float(bar["open"]);fill=float(t["entry_price"])
            expected=_slipped(opened,direction,True,bps,tick,extra_ticks)
            if not _same(fill,expected):
                failures.append(f"Futures entry fill differs from configured adverse slippage/tick model: trade {t.get('id')}")
            checked_fills+=1
        signal=states.get(entry)
        if signal is None:
            failures.append(f"Missing completed-candle preview signal at {t['entry_time']}; cannot certify parity")
        else:
            prefix="call" if sign==1 else "put"
            if not signal.get(prefix+"_passed"):
                failures.append(f"Backtest entered without independent chart rule pass: trade {t.get('id')}")
            if signal.get("no_trade_active") or signal.get(prefix+"_no_trade_active"):
                failures.append(f"Backtest entered while preview NO TRADE gate active: trade {t.get('id')}")
            if not signal.get(prefix+"_delay_ready"):
                # Chart preview does not consume actual entry cycles, unlike the engine.
                warnings.append(f"Lifecycle readiness differs on preview: trade {t.get('id')}; inspect full execution trace")
            checked_signals+=1
    unresolved=result.get("unresolved_position")
    if unresolved:
        side="CALL" if unresolved.get("direction")=="LONG" else "PUT"
        key=(_epoch(unresolved["entry_time"]),side)
        used_entries[key]+=1
        if used_entries[key]>entries[key]:
            failures.append("Missing chart marker for unresolved futures entry")
        if "quantity" in unresolved:
            q=float(unresolved["quantity"])
            expected_entry=_slipped(float(bars.get(_epoch(unresolved["entry_time"])+timeframe_minutes*60,{}).get("open",float("nan"))),
                                    unresolved["direction"],True,bps,tick,extra_ticks) if _epoch(unresolved["entry_time"])+timeframe_minutes*60 in bars else None
            if expected_entry is None or not _same(expected_entry,unresolved["entry_price"]):
                failures.append("Unresolved futures entry fill cannot be reconciled with chart OHLC")
        if "entry_lifecycle_id" in unresolved and (
            not unresolved.get("entry_lifecycle_eligible") or
            _epoch(unresolved["entry_lifecycle_signal_time"])!=_epoch(unresolved["entry_time"])
        ):
            failures.append("Unresolved position lifecycle provenance is invalid")
        warnings.append("Unresolved open exposure is excluded from closed-trade net P&L")
    if not chart.get("condition_states") or not chart.get("bars"):
        failures.append("Chart preview contains no rule states or OHLC bars")
    if sum(entries.values())!=len(trades)+int(bool(unresolved)):
        failures.append("Futures entry marker count does not equal opened positions")
    if sum(exits.values())!=len(trades):
        failures.append("Futures exit marker count does not equal closed trades")
    ordered=sorted(trades,key=lambda t:_epoch(t["entry_time"]))
    for first,second in zip(ordered,ordered[1:]):
        if _epoch(second["entry_time"])<_epoch(first["exit_time"]):
            failures.append("Futures positions overlapped despite EXCLUSIVE policy")
    closed_net=sum(float(t["net_pnl_usd"]) for t in trades)
    if not _same(closed_net,(result.get("metrics") or {}).get("net_pnl_usd",0)):
        failures.append("Aggregate closed-trade net P&L does not reconcile")
    if checked_signals < len(trades) or checked_fills < len(trades):
        failures.append("Not all closed-trade signals and execution bars were independently checked")
    metrics=result.get("metrics") or {}
    if "cash_reconciliation_residual_usd" in metrics and not _same(metrics["cash_reconciliation_residual_usd"],0):
        failures.append("Cash reconciliation residual is non-zero")
    if "ending_balance_usd" in metrics and "cash_balance_change_usd" in metrics:
        start=float(result.get("strategy",{}).get("risk",{}).get("starting_balance_usd",0))
        if not _same(float(metrics["ending_balance_usd"])-start,metrics["cash_balance_change_usd"]):
            failures.append("Cash balance change does not match ending minus starting balance")
    if unresolved and "unresolved_entry_fee_usd" in metrics and not _same(
        metrics["unresolved_entry_fee_usd"],unresolved.get("entry_fee_usd",0)):
        failures.append("Unresolved entry fee does not reconcile")
    from .futures_lifecycle_replay import independently_replay_lifecycles
    timeline=chart.get("lifecycle_triggers")
    replay=None
    if timeline is None:
        warnings.append("Historical independent lifecycle trigger timeline unavailable")
    else:
        replay=independently_replay_lifecycles(result,timeline,timeframe_minutes)
        failures.extend(replay["failures"])
    warnings.append("Lifecycle replay independently evaluates trigger transitions, but not exchange orders or fill outcomes")
    warnings.append("Chart markers are backtest overlays; source OHLC and rule states are independent")
    warnings.append("Actual Delta orderbook fills, historical mark prices, FX collateral and liquidations are not verified")
    return {
        "kind":"FUTURES_INTERNAL_PARITY_AUDIT",
        "status":"FAILED" if failures else "PASSED_RESEARCH_ONLY",
        "research_only":True,
        "checked_closed_trades":len(trades),
        "checked_preview_signals":checked_signals,
        "checked_ohlc_entry_fills":checked_fills,
        "failure_count":len(failures),
        "failures":failures[:20],
        "warnings":list(dict.fromkeys(warnings))[:20],
        "exchange_fills_verified":False,
        "mark_price_verified":False,
        "unresolved_position":bool(unresolved),
        "independent_lifecycle":replay,
    }
