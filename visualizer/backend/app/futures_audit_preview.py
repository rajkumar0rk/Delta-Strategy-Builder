"""Compact source-derived futures parity view without chart-rendering constraints.

The normal chart preview enforces a 30,000-bar visualization limit and builds
large study/indicator arrays. A historical parity audit needs only the bars
immediately following executed entry signals, rule states on those signals,
and a warmup-inclusive trigger timeline for independent lifecycle replay.

No future candle's values are used to decide whether a past entry was valid.
"""
from __future__ import annotations

import pandas as pd

from .rules import evaluate_condition, evaluate_group, find_condition


def build_futures_audit_preview(frame, strategy, req, result):
    if strategy is None or strategy.market_type != "FUTURES":
        raise ValueError("Audit preview requires a futures strategy")
    if result is None:
        raise ValueError("Audit preview requires the actual backtest result")

    # Import inside function to avoid import cycles with engine.chart_payload.
    from .engine import (_entry_behaviors, _entry_ignore_ids, _big_trend_score,
                         _score_entry_pass)

    start, end = pd.Timestamp(req.start), pd.Timestamp(req.end)
    step = pd.Timedelta({"5m":5,"10m":10,"15m":15,"30m":30,"1h":60}[strategy.timeframe], unit="min")
    trades = list(result.get("trades") or [])
    unresolved = result.get("unresolved_position")
    if unresolved:
        trades.append(unresolved)
    entry_times = {pd.Timestamp(trade["entry_time"]) for trade in trades}
    needed_bar_times = {timestamp + step for timestamp in entry_times}

    enabled = {
        "call": (strategy.direction_mode in ("CALL","BOTH")
                 and strategy.call_signal_mode != "ALERT_ONLY"),
        "put": (strategy.direction_mode in ("PUT","BOTH")
                and strategy.put_signal_mode != "ALERT_ONLY"),
    }
    groups = {"call": strategy.call_entry, "put": strategy.put_entry}
    score_cfg = {"call": strategy.call_big_trend_score,
                 "put": strategy.put_big_trend_score}
    no_trade_cfg = {"call": strategy.call_no_trade, "put": strategy.put_no_trade}
    behaviors = {
        side: _entry_behaviors(strategy, side.upper()) if enabled[side] else []
        for side in ("call","put")
    }
    # Resolve explicit trigger condition IDs once, not on every historical bar.
    triggers = {
        side: [(behavior.id, find_condition(groups[side], behavior.trigger_condition_id)
                if behavior.trigger_condition_id else None,
                behavior.trigger_condition_id is not None)
               for behavior in behaviors[side]]
        for side in ("call","put")
    }

    lifecycle_triggers = []
    condition_states = []
    bars = []
    for index, (ts, candle) in enumerate(frame.iterrows()):
        if ts >= end:
            break
        epoch = int(ts.timestamp())
        if ts in needed_bar_times:
            bars.append({"time":epoch,"open":float(candle.open)})
        if ts in entry_times:
            state = {"time":epoch,
                     "no_trade_active": bool(evaluate_group(frame,index,strategy.no_trade)["passed"])
                         if strategy.no_trade.configured() else False}
            for side in ("call","put"):
                passing = False
                if enabled[side]:
                    rules = evaluate_group(frame,index,groups[side],_entry_ignore_ids(strategy,side.upper()))
                    score = _big_trend_score(frame,index,groups[side],score_cfg[side],side.upper())
                    passing = _score_entry_pass(rules,score,score_cfg[side])
                state[side+"_passed"] = bool(passing)
                state[side+"_no_trade_active"] = (
                    bool(evaluate_group(frame,index,no_trade_cfg[side])["passed"])
                    if enabled[side] and no_trade_cfg[side].configured() else False
                )
            condition_states.append(state)
        # Lifecycle state is replayed from *every* complete source candle, not
        # just signal candles, including indicator/lifecycle warmup.
        row = {"time":epoch, "call":{}, "put":{}}
        for side in ("call","put"):
            fallback = None
            for ident, explicit_condition, has_explicit_trigger in triggers[side]:
                if has_explicit_trigger:
                    active = (bool(evaluate_condition(frame,index,explicit_condition)["passed"])
                              if explicit_condition is not None else False)
                else:
                    if fallback is None:
                        fallback = bool(evaluate_group(frame,index,groups[side])["passed"])
                    active = fallback
                row[side][ident] = active
        lifecycle_triggers.append(row)

    return {
        "bars": bars,
        "condition_states": condition_states,
        "lifecycle_triggers": lifecycle_triggers,
        "audit_only": True,
        "source_candles_scanned": len(lifecycle_triggers),
        "source_entry_candles": len(condition_states),
        "chart_render_limit_bypassed": True,
    }


def futures_audit_payload(req, result):
    """Reload source candles exactly as the backtest/preview do, without UI chart arrays."""
    from .data_store import DataStore
    from .warmup import required_warmup_candles, historical_bar_sources, load_daily_source
    from .indicators import compute_indicators
    from .engine import _prepare_strategy_state
    store = DataStore()
    try:
        parts = store.resolve_request(req, require_options=False)
        strategy = req.strategy
        count = required_warmup_candles(
            strategy.indicators, strategy.timeframe,
            minimum=getattr(req,"warmup_candles",500), strategy=strategy)
        sources = historical_bar_sources(
            store, parts, req.start, strategy.timeframe, count,
            archive_neighbors=getattr(req,"dataset_mode","SINGLE") in ("ARCHIVE","AUTO"))
        store._bar_gap_policy = req.bar_gap_policy
        bars = store.load_bars_many(
            sources,req.start,req.end,strategy.timeframe,warmup_candles=count)
        daily = load_daily_source(
            store,sources,req.start,req.end,strategy.timeframe,count,strategy.indicators)
        frame,_ = compute_indicators(
            bars,strategy.indicators,strategy.timeframe,daily_source=daily)
        _prepare_strategy_state(frame,strategy)
        return build_futures_audit_preview(frame,strategy,req,result)
    finally:
        store.close()
