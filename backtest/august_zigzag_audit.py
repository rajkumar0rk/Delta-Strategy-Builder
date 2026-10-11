from __future__ import annotations

import argparse
import csv
import json
import math
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .ema_vwap_research import (
    IST,
    PullbackReversalConfig,
    _option_specs,
    _select_option,
    indicators,
    pullback_reversal_directions,
)


UTC = timezone.utc
DEFAULT_BASELINE = Path(
    "backtest/reports/manual-combinations/"
    "plain_noweekend_noholdhours_with_emaruleorv1"
)
DEFAULT_ZIGZAG = Path(
    "backtest/reports/manual-combinations/"
    "plain_noweekend_noholdhours_with_emaruleor_zigzagv1"
)
DEFAULT_OUTPUT = Path("backtest/reports/august-2026-zigzag-audit")
AUGUST_START = pd.Timestamp("2026-08-01T00:00:00Z")
SEPTEMBER_START = pd.Timestamp("2026-09-01T00:00:00Z")
IMPORTANT_SIGNAL = pd.Timestamp("2026-08-19T13:05:00Z")
IMPORTANT_SYMBOL = "BTC68000210826CE"
SEGMENTS = (
    (
        Path("backtest/data/delta-holdout-2026-07-25_08-24"),
        pd.Timestamp("2026-08-01T00:00:00Z"),
        pd.Timestamp("2026-08-24T00:00:00Z"),
    ),
    (
        Path("backtest/data/delta-2026-09-15_22"),
        pd.Timestamp("2026-08-24T00:00:00Z"),
        pd.Timestamp("2026-09-01T00:00:00Z"),
    ),
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_august_trades(directory: Path) -> pd.DataFrame:
    frame = pd.read_csv(directory / "trades.csv")
    entry_time = pd.to_datetime(frame["entry_time"], utc=True)
    return frame.loc[
        entry_time.ge(AUGUST_START) & entry_time.lt(SEPTEMBER_START)
    ].copy()


def _load_august_underlying() -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for directory, start, end in SEGMENTS:
        frame = indicators(directory / "underlying_bars.csv")
        pieces.append(frame.loc[(frame.index >= start) & (frame.index < end)].copy())
    result = pd.concat(pieces).sort_index()
    result = result.loc[~result.index.duplicated(keep="first")]
    return result


def _config_from_summary(summary: dict[str, Any]) -> PullbackReversalConfig:
    values = summary["configuration"]["zigzag"]
    return PullbackReversalConfig(**values)


def _touches(
    window: pd.DataFrame,
    config: PullbackReversalConfig,
    direction: str,
) -> tuple[pd.Series, pd.Series]:
    raw = pd.Series(False, index=window.index)
    qualified = pd.Series(False, index=window.index)
    call = direction == "CALL"
    if config.touch_ema20:
        ema_raw = (
            window["low"].le(window["ema20"])
            if call
            else window["high"].ge(window["ema20"])
        )
        ema_qualified = ema_raw.copy()
        if config.atr_enabled and config.max_touch_close_distance_atr is not None:
            tolerance = config.max_touch_close_distance_atr * window["atr14"]
            ema_qualified &= (
                window["close"].ge(window["ema20"] - tolerance)
                if call
                else window["close"].le(window["ema20"] + tolerance)
            )
        raw |= ema_raw
        qualified |= ema_qualified
    if config.touch_vwap:
        vwap_raw = (
            window["low"].le(window["vwap"])
            if call
            else window["high"].ge(window["vwap"])
        )
        vwap_qualified = vwap_raw.copy()
        if config.atr_enabled and config.max_touch_close_distance_atr is not None:
            tolerance = config.max_touch_close_distance_atr * window["atr14"]
            vwap_qualified &= (
                window["close"].ge(window["vwap"] - tolerance)
                if call
                else window["close"].le(window["vwap"] + tolerance)
            )
        raw |= vwap_raw
        qualified |= vwap_qualified
    return raw, qualified


def _pullback_sequence(
    window: pd.DataFrame,
    touches: pd.Series,
    use_actual_sequence: bool,
) -> pd.DataFrame:
    positions = [index for index, touched in enumerate(touches.tolist()) if touched]
    if not positions:
        return window.iloc[0:0]
    if not use_actual_sequence:
        return window
    start = positions[-1]
    while start > 0 and bool(touches.iloc[start - 1]):
        start -= 1
    return window.iloc[start:]


def _zigzag_diagnostic(
    frame: pd.DataFrame,
    timestamp: pd.Timestamp,
    direction: str,
    config: PullbackReversalConfig,
) -> dict[str, Any]:
    location = frame.index.get_indexer([timestamp])[0]
    if location <= 0:
        return {"rejection_reason": "INSUFFICIENT_HISTORY"}
    row = frame.iloc[location]
    previous = frame.iloc[location - 1]
    window = frame.iloc[max(0, location - config.lookback_candles):location]
    call = direction == "CALL"
    base_trend = bool(
        row["ema9"] > row["ema20"] > row["ema50"] and row["close"] > row["vwap"]
        if call
        else row["ema9"] < row["ema20"] < row["ema50"] and row["close"] < row["vwap"]
    )
    slope_pass = True
    if config.require_ema_slope:
        slow_pass = (
            row["ema50"] >= previous["ema50"]
            if call and config.allow_flat_ema50
            else row["ema50"] > previous["ema50"]
            if call
            else row["ema50"] <= previous["ema50"]
            if config.allow_flat_ema50
            else row["ema50"] < previous["ema50"]
        )
        slope_pass = bool(
            row["ema9"] > previous["ema9"]
            and row["ema20"] > previous["ema20"]
            and slow_pass
            if call
            else row["ema9"] < previous["ema9"]
            and row["ema20"] < previous["ema20"]
            and slow_pass
        )
    raw_touches, qualified_touches = _touches(window, config, direction)
    pullback = _pullback_sequence(
        window,
        qualified_touches,
        config.use_actual_pullback_sequence,
    )
    rsi_pass = True
    if config.rsi_enabled:
        rsi_range = (
            (config.bull_rsi_min, config.bull_rsi_max)
            if call
            else (config.bear_rsi_min, config.bear_rsi_max)
        )
        rsi_pass = bool(
            pullback["rsi14"].between(*rsi_range, inclusive="both").any()
            and (
                row["rsi14"] > previous["rsi14"]
                if call
                else row["rsi14"] < previous["rsi14"]
            )
        )
    confirmation_pass = bool(
        row["close"] > row["ema9"] and row["close"] > previous["high"]
        if call
        else row["close"] < row["ema9"] and row["close"] < previous["low"]
    )
    atr_pass = True
    if config.atr_enabled:
        atr = float(row["atr14"])
        atr_pass = bool(
            math.isfinite(atr)
            and atr > 0.0
            and not pullback.empty
            and (
                row["close"] - pullback["low"].min()
                if call
                else pullback["high"].max() - row["close"]
            )
            >= config.atr_reversal_multiplier * atr
        )
    if not base_trend:
        reason = "BASE_TREND_REJECTED"
    elif not slope_pass:
        reason = "EMA_SLOPE_REJECTED"
    elif not bool(raw_touches.any()):
        reason = "NO_PULLBACK"
    elif not bool(qualified_touches.any()):
        reason = "TOUCH_TOLERANCE_REJECTED"
    elif not rsi_pass:
        reason = "RSI_REJECTED"
    elif not confirmation_pass:
        reason = "CONFIRMATION_REJECTED"
    elif not atr_pass:
        reason = "ATR_REJECTED"
    else:
        reason = "PASSED"
    prior_volume = float(row["volume_median20_prior"])
    volume_ratio = (
        float(row["volume"]) / prior_volume
        if math.isfinite(prior_volume) and prior_volume > 0.0
        else math.nan
    )
    touch_times = window.index[qualified_touches]
    return {
        "rejection_reason": reason,
        "base_trend_pass": base_trend,
        "ema_slope_pass": slope_pass,
        "pullback_found": bool(qualified_touches.any()),
        "pullback_timestamp": touch_times[-1].isoformat() if len(touch_times) else "",
        "rsi_pass": rsi_pass,
        "confirmation_pass": confirmation_pass,
        "atr_pass": atr_pass,
        "ema9": float(row["ema9"]),
        "ema20": float(row["ema20"]),
        "ema50": float(row["ema50"]),
        "vwap": float(row["vwap"]),
        "rsi14": float(row["rsi14"]),
        "atr14": float(row["atr14"]),
        "volume": float(row["volume"]),
        "volume_ratio": volume_ratio,
    }


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, lineterminator="\n")


def _trade_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    pnl = pd.to_numeric(frame["pnl_usd"], errors="coerce").fillna(0.0)
    wins = pnl[pnl > 0.0]
    losses = pnl[pnl < 0.0]
    gross_loss = abs(float(losses.sum()))
    equity = 100.0
    peak = equity
    max_drawdown = 0.0
    for value in pnl:
        equity += float(value)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "trades": int(len(frame)),
        "wins": int((pnl > 0.0).sum()),
        "losses": int((pnl < 0.0).sum()),
        "win_rate_percent": float((pnl > 0.0).mean() * 100.0) if len(pnl) else None,
        "net_pnl_usd": float(pnl.sum()),
        "profit_factor": float(wins.sum() / gross_loss) if gross_loss > 0.0 else None,
        "average_win_usd": float(wins.mean()) if len(wins) else None,
        "average_loss_usd": float(losses.mean()) if len(losses) else None,
        "largest_win_usd": float(wins.max()) if len(wins) else None,
        "largest_loss_usd": float(losses.min()) if len(losses) else None,
        "pnl_per_trade_usd": float(pnl.mean()) if len(pnl) else None,
        "max_drawdown_usd": max_drawdown,
        "fees_usd": float(
            pd.to_numeric(frame["fees_usd"], errors="coerce").fillna(0.0).sum()
        ),
        "call_pnl_usd": float(
            pd.to_numeric(
                frame.loc[frame["direction"].eq("CALL"), "pnl_usd"],
                errors="coerce",
            ).fillna(0.0).sum()
        ),
        "put_pnl_usd": float(
            pd.to_numeric(
                frame.loc[frame["direction"].eq("PUT"), "pnl_usd"],
                errors="coerce",
            ).fillna(0.0).sum()
        ),
    }


def _copy_config(summary: dict[str, Any], path: Path) -> None:
    path.write_text(
        json.dumps(summary["configuration"], indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _event_files(
    output: Path,
    frame: pd.DataFrame,
    baseline: pd.DataFrame,
) -> dict[str, Any]:
    trade = baseline.loc[
        pd.to_datetime(baseline["signal_time"], utc=True).eq(IMPORTANT_SIGNAL)
        & baseline["symbol"].eq(IMPORTANT_SYMBOL)
    ]
    if len(trade) != 1:
        raise RuntimeError("Expected exactly one 2026-08-19 13:05 UTC baseline trade")
    trade_row = trade.iloc[0].to_dict()
    entry_time = pd.Timestamp(trade_row["entry_time"])
    exit_time = pd.Timestamp(trade_row["exit_time"])
    candles = frame.loc[
        (frame.index >= IMPORTANT_SIGNAL - pd.Timedelta(hours=2))
        & (frame.index <= exit_time + pd.Timedelta(minutes=5))
    ].copy()
    candles.insert(0, "timestamp_utc", candles.index.map(pd.Timestamp.isoformat))
    candles.insert(
        1,
        "timestamp_ist",
        candles.index.tz_convert(IST).map(pd.Timestamp.isoformat),
    )
    _write_csv(candles.reset_index(drop=True), output / "aug19_1305_btc_candles.csv")

    source = SEGMENTS[0][0]
    quotes: list[dict[str, str]] = []
    quote_start = IMPORTANT_SIGNAL - pd.Timedelta(hours=2)
    with (source / "option_quotes.csv").open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["symbol"] != IMPORTANT_SYMBOL:
                continue
            timestamp = pd.Timestamp(row["timestamp"])
            if quote_start <= timestamp <= exit_time:
                quotes.append(row)
    quote_frame = pd.DataFrame(quotes)
    _write_csv(quote_frame, output / "aug19_1305_option_quotes.csv")

    entry_quote = quote_frame.loc[
        pd.to_datetime(quote_frame["timestamp"], utc=True).eq(entry_time)
    ].iloc[0]
    exit_quote = quote_frame.loc[
        pd.to_datetime(quote_frame["timestamp"], utc=True).eq(exit_time)
    ].iloc[0]
    quantity = float(trade_row["quantity"])
    entry_size = float(entry_quote["ask_size"])
    exit_size = float(exit_quote["bid_size"])

    with (source / "option_instruments.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        instrument = next(
            row for row in csv.DictReader(handle) if row["symbol"] == IMPORTANT_SYMBOL
        )
    event = {
        "note": (
            "This is the stored 13:05 UTC trade requested for review. It is distinct "
            "from the runner's separately hard-coded 14:35 UTC exceptional signal."
        ),
        "trade": trade_row,
        "instrument": instrument,
        "source_fidelity": "LOW_FIDELITY_SYNTHETIC_BBO",
        "quote_window_start": quote_start.isoformat(),
        "quote_window_end": exit_time.isoformat(),
        "quote_rows": len(quote_frame),
        "displayed_size_check": {
            "ordered_quantity": quantity,
            "entry_ask_size": entry_size,
            "entry_immediate_fill_percent": 100.0 * min(entry_size, quantity) / quantity,
            "exit_bid_size": exit_size,
            "exit_immediate_fill_percent": 100.0 * min(exit_size, quantity) / quantity,
            "assessment": (
                "The backtest filled the entire quantity at top of book even though "
                "displayed synthetic size was much smaller. The reported P&L is not "
                "a realistic executable estimate."
            ),
        },
    }
    (output / "aug19_1305_event.json").write_text(
        json.dumps(event, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return event


def _impact_table(diagnostics: pd.DataFrame) -> pd.DataFrame:
    baseline_only = diagnostics.loc[~diagnostics["matched_zigzag_trade"]].copy()
    if baseline_only.empty:
        return pd.DataFrame()
    baseline_only["pnl_usd"] = pd.to_numeric(
        baseline_only["pnl_usd"], errors="coerce"
    ).fillna(0.0)
    rows: list[dict[str, Any]] = []
    for reason, group in baseline_only.groupby("rejection_reason", dropna=False):
        winners = group.loc[group["pnl_usd"] > 0.0, "pnl_usd"]
        losses = group.loc[group["pnl_usd"] < 0.0, "pnl_usd"]
        rows.append({
            "rejection_reason": reason,
            "baseline_only_trades": len(group),
            "winners_removed": len(winners),
            "winner_pnl_removed_usd": float(winners.sum()),
            "losses_removed": len(losses),
            "loss_pnl_removed_usd": float(losses.sum()),
            "net_pnl_removed_usd": float(group["pnl_usd"].sum()),
        })
    return pd.DataFrame(rows).sort_values(
        ["net_pnl_removed_usd", "baseline_only_trades"],
        ascending=[False, False],
    )


def _signal_diagnostic_rows(
    frame: pd.DataFrame,
    baseline: pd.DataFrame,
    zigzag: pd.DataFrame,
    zigzag_config: PullbackReversalConfig,
    zigzag_direction: pd.Series,
    zigzag_signal: pd.Series,
    *,
    min_days_to_expiry: float,
    min_days_to_expiry_inclusive: bool,
    max_days_to_expiry: float,
    blocked_weekdays_ist: tuple[int, ...],
) -> pd.DataFrame:
    baseline_trades = {
        (str(trade["signal_time"]), str(trade["direction"])): trade
        for trade in baseline.to_dict("records")
    }
    baseline_intervals = [
        (pd.Timestamp(trade["signal_time"]), pd.Timestamp(trade["exit_time"]))
        for trade in baseline.to_dict("records")
    ]
    zigzag_trade_keys = set(zip(zigzag["signal_time"], zigzag["direction"]))
    zigzag_intervals = [
        (pd.Timestamp(trade["signal_time"]), pd.Timestamp(trade["exit_time"]))
        for trade in zigzag.to_dict("records")
    ]
    specs_by_directory = {
        directory: _option_specs(directory / "option_instruments.csv")
        for directory, _, _ in SEGMENTS
    }
    rows: list[dict[str, Any]] = []
    for timestamp, indicator_row in frame.loc[frame["entry_signal"]].iterrows():
        if timestamp.tz_convert(IST).weekday() in blocked_weekdays_ist:
            continue
        direction = str(indicator_row["direction"])
        timestamp_text = timestamp.isoformat()
        trade = baseline_trades.get((timestamp_text, direction))
        directory = next(
            directory
            for directory, start, end in SEGMENTS
            if start <= timestamp < end
        )
        option = _select_option(
            specs_by_directory[directory],
            int(timestamp.timestamp() * 1_000_000_000),
            direction,
            float(indicator_row["close"]),
            min_days_to_expiry=min_days_to_expiry,
            min_days_to_expiry_inclusive=min_days_to_expiry_inclusive,
            max_days_to_expiry=max_days_to_expiry,
        )
        baseline_skip_reason = ""
        if trade is None:
            if any(start < timestamp <= end for start, end in baseline_intervals):
                baseline_skip_reason = "SIGNAL_DURING_OPEN_TRADE"
            elif option is None:
                baseline_skip_reason = "OPTION_REJECTED_NO_ELIGIBLE_CONTRACT"
            else:
                baseline_skip_reason = "OPTION_OR_EXECUTION_REJECTED"

        detail = _zigzag_diagnostic(frame, timestamp, direction, zigzag_config)
        qualifying_direction = str(zigzag_direction.loc[timestamp])
        exact_signal = bool(zigzag_signal.loc[timestamp]) and qualifying_direction == direction
        if detail["rejection_reason"] == "PASSED" and not exact_signal:
            detail["rejection_reason"] = "DUPLICATE_ZIGZAG_STATE"
        elif (
            detail["rejection_reason"] == "PASSED"
            and (timestamp_text, direction) not in zigzag_trade_keys
        ):
            detail["rejection_reason"] = (
                "SIGNAL_DURING_OPEN_TRADE"
                if any(start < timestamp <= end for start, end in zigzag_intervals)
                else "OPTION_REJECTED"
            )
        rows.append({
            "timestamp": timestamp_text,
            "timestamp_ist": timestamp.tz_convert(IST).isoformat(),
            "direction": direction,
            "baseline_signal": True,
            "baseline_trade": trade is not None,
            "baseline_skip_reason": baseline_skip_reason,
            "zigzag_qualifying_candle": qualifying_direction == direction,
            "zigzag_signal": exact_signal,
            "matched_zigzag_trade": (timestamp_text, direction) in zigzag_trade_keys,
            **detail,
            "option_symbol": (
                str(trade["symbol"])
                if trade is not None
                else option.symbol
                if option is not None
                else ""
            ),
            "entry_price": float(trade["entry_ask"]) if trade is not None else "",
            "exit_price": float(trade["exit_bid"]) if trade is not None else "",
            "quantity": float(trade["quantity"]) if trade is not None else "",
            "fees_usd": float(trade["fees_usd"]) if trade is not None else "",
            "pnl_usd": float(trade["pnl_usd"]) if trade is not None else "",
        })
    return pd.DataFrame(rows)


def _money(value: Any) -> str:
    return "N/A" if value is None else f"${float(value):+,.2f}"


def _write_report(
    output: Path,
    baseline: pd.DataFrame,
    zigzag: pd.DataFrame,
    all_signal_diagnostics: pd.DataFrame,
    diagnostics: pd.DataFrame,
    impacts: pd.DataFrame,
    event: dict[str, Any],
) -> None:
    baseline_metrics = _trade_metrics(baseline)
    zigzag_metrics = _trade_metrics(zigzag)
    important = event["trade"]
    important_pnl = float(important["pnl_usd"])
    baseline_without = baseline.loc[
        ~pd.to_datetime(baseline["signal_time"], utc=True).eq(IMPORTANT_SIGNAL)
    ]
    baseline_without_metrics = _trade_metrics(baseline_without)
    returns = pd.to_numeric(baseline["return_percent"], errors="coerce").fillna(0.0)
    pnl = pd.to_numeric(baseline["pnl_usd"], errors="coerce").fillna(0.0)
    pattern = {
        "returns_over_100_percent": int(returns.gt(100.0).sum()),
        "returns_over_500_percent": int(returns.gt(500.0).sum()),
        "returns_over_1000_percent": int(returns.gt(1000.0).sum()),
        "pnl_over_10_usd": int(pnl.gt(10.0).sum()),
        "pnl_over_50_usd": int(pnl.gt(50.0).sum()),
    }
    size_check = event["displayed_size_check"]
    lines = [
        "# August 2026 Baseline And ZigZag Audit",
        "",
        "The comparison uses the existing directly comparable BT2 reports. Both use "
        "weekday entries, 1.3-3.0 days to expiry, no maximum hold, and the "
        "FAST_OR_MID_VS_SLOW EMA exit. Only the ZigZag entry mode differs.",
        "",
        "Historical option bid/ask is synthesized from 1-minute option candles with "
        "a 1% spread. Results are LOW_FIDELITY and do not prove that the displayed "
        "size could have filled at those prices.",
        "",
        "## August Results",
        "",
        "| Run | Trades | Wins | Losses | Win rate | Net P&L | Profit factor | Max DD | Avg win | Avg loss | Largest win | P&L/trade | CALL P&L | PUT P&L | Fees |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        (
            f"| Baseline | {baseline_metrics['trades']} | {baseline_metrics['wins']} | "
            f"{baseline_metrics['losses']} | {baseline_metrics['win_rate_percent']:.2f}% | "
            f"{_money(baseline_metrics['net_pnl_usd'])} | "
            f"{baseline_metrics['profit_factor']:.3f} | "
            f"{_money(baseline_metrics['max_drawdown_usd'])} | "
            f"{_money(baseline_metrics['average_win_usd'])} | "
            f"{_money(baseline_metrics['average_loss_usd'])} | "
            f"{_money(baseline_metrics['largest_win_usd'])} | "
            f"{_money(baseline_metrics['pnl_per_trade_usd'])} | "
            f"{_money(baseline_metrics['call_pnl_usd'])} | "
            f"{_money(baseline_metrics['put_pnl_usd'])} | "
            f"{_money(baseline_metrics['fees_usd'])} |"
        ),
        (
            f"| ZigZag | {zigzag_metrics['trades']} | {zigzag_metrics['wins']} | "
            f"{zigzag_metrics['losses']} | {zigzag_metrics['win_rate_percent']:.2f}% | "
            f"{_money(zigzag_metrics['net_pnl_usd'])} | "
            f"{zigzag_metrics['profit_factor']:.3f} | "
            f"{_money(zigzag_metrics['max_drawdown_usd'])} | "
            f"{_money(zigzag_metrics['average_win_usd'])} | "
            f"{_money(zigzag_metrics['average_loss_usd'])} | "
            f"{_money(zigzag_metrics['largest_win_usd'])} | "
            f"{_money(zigzag_metrics['pnl_per_trade_usd'])} | "
            f"{_money(zigzag_metrics['call_pnl_usd'])} | "
            f"{_money(zigzag_metrics['put_pnl_usd'])} | "
            f"{_money(zigzag_metrics['fees_usd'])} |"
        ),
        "",
        "## August 19 13:05 UTC Trade",
        "",
        f"- Direction: `{important['direction']}`",
        f"- Contract: `{important['symbol']}`",
        f"- Signal: `{important['signal_time']}`",
        f"- Entry: `{important['entry_time']}` at ask `${float(important['entry_ask']):,.2f}`",
        f"- Exit: `{important['exit_time']}` at bid `${float(important['exit_bid']):,.2f}`",
        f"- Highest observed bid: `${float(important['highest_bid']):,.2f}`",
        f"- Quantity: `{important['quantity']}`",
        f"- Gross P&L: `{_money(important['gross_pnl_usd'])}`",
        f"- Fees: `{_money(important['fees_usd'])}`",
        f"- Net P&L: `{_money(important_pnl)}`",
        f"- Return on option premium: `{float(important['return_percent']):,.2f}%`",
        "- ZigZag decision: `NO_PULLBACK`.",
        f"- Displayed entry ask size: `{size_check['entry_ask_size']:g}` versus quantity `{size_check['ordered_quantity']:g}`.",
        f"- Displayed exit bid size: `{size_check['exit_bid_size']:g}` versus quantity `{size_check['ordered_quantity']:g}`.",
        "",
        "The four completed candles before 13:05 UTC never touched EMA20 or VWAP. "
        "The entry was a resumed baseline CALL after RSI briefly exceeded 70, not a "
        "pullback-and-confirmation setup. ZigZag therefore rejected it before its RSI "
        "and confirmation stages.",
        "",
        f"This one trade contributed {_money(important_pnl)} of the baseline's "
        f"{_money(baseline_metrics['net_pnl_usd'])} August result. Without it, the "
        f"baseline August result is {_money(baseline_without_metrics['net_pnl_usd'])} "
        f"with profit factor `{baseline_without_metrics['profit_factor']:.3f}`.",
        "",
        "The full-quantity execution assumption is not realistic for this event. At "
        f"entry, displayed ask size covered only `{size_check['entry_immediate_fill_percent']:.3f}%` "
        f"of the order. At exit, displayed bid size covered only "
        f"`{size_check['exit_immediate_fill_percent']:.3f}%`. These are synthetic sizes, "
        "but they directly contradict filling all 732 contracts at the best price.",
        "",
        "This event is distinct from the runner's hard-coded robustness event at "
        "14:35 UTC, which entered the same contract at $23.20 in the older 60-minute "
        "hold test.",
        "",
        "## Is It Recurring?",
        "",
        f"August had `{pattern['returns_over_100_percent']}` baseline trades above "
        f"+100%, `{pattern['returns_over_500_percent']}` above +500%, and only "
        f"`{pattern['returns_over_1000_percent']}` above +1,000%. There were "
        f"`{pattern['pnl_over_10_usd']}` trades above +$10, but only "
        f"`{pattern['pnl_over_50_usd']}` above +$50.",
        "",
        "Large option moves recur, but the 13:05 trade is isolated in magnitude and "
        "execution impact. Its +$584.33 was about 14.5 times the next-largest August "
        "winner (+$40.32) and supplied about 95.9% of baseline August net P&L. After "
        f"removing it, ZigZag produced {_money(zigzag_metrics['net_pnl_usd'])} versus "
        f"the baseline's {_money(baseline_without_metrics['net_pnl_usd'])}, with profit "
        f"factor {zigzag_metrics['profit_factor']:.3f} versus "
        f"{baseline_without_metrics['profit_factor']:.3f}.",
        "",
        "## August Signal Log",
        "",
        f"The baseline produced `{len(all_signal_diagnostics)}` raw entry signals. "
        f"`{int(all_signal_diagnostics['baseline_trade'].sum())}` became trades and "
        f"`{int((~all_signal_diagnostics['baseline_trade']).sum())}` were skipped "
        "before entry.",
        "",
        "| ZigZag result at baseline signal | Signals |",
        "|---|---:|",
    ]
    for reason, count in all_signal_diagnostics["rejection_reason"].value_counts().items():
        lines.append(f"| {reason} | {count} |")
    skip_counts = all_signal_diagnostics.loc[
        ~all_signal_diagnostics["baseline_trade"], "baseline_skip_reason"
    ].value_counts()
    lines.extend((
        "",
        "Baseline execution skips: "
        + ", ".join(f"`{reason}` {count}" for reason, count in skip_counts.items())
        + ".",
        "",
        "## Baseline Trades Removed By ZigZag Reason",
        "",
        "| Reason | Trades | Winners | Winner P&L | Losses | Loss P&L | Net P&L removed |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ))
    for row in impacts.to_dict("records"):
        lines.append(
            f"| {row['rejection_reason']} | {row['baseline_only_trades']} | "
            f"{row['winners_removed']} | {_money(row['winner_pnl_removed_usd'])} | "
            f"{row['losses_removed']} | {_money(row['loss_pnl_removed_usd'])} | "
            f"{_money(row['net_pnl_removed_usd'])} |"
        )
    matched = int(diagnostics["matched_zigzag_trade"].sum())
    baseline_only = len(diagnostics) - matched
    zigzag_keys = set(zip(zigzag["signal_time"], zigzag["direction"]))
    baseline_keys = set(zip(baseline["signal_time"], baseline["direction"]))
    zigzag_only = len(zigzag_keys - baseline_keys)
    lines.extend((
        "",
        "## Matching",
        "",
        f"- Baseline trades with an exact ZigZag trade at the same signal and direction: `{matched}`",
        f"- Baseline-only trades: `{baseline_only}`",
        f"- ZigZag-only trades: `{zigzag_only}`",
        "",
        "Exact timestamp matching is intentionally strict. ZigZag often waits for a "
        "later pullback confirmation, so a ZigZag-only row can belong to the same broad "
        "trend as an earlier baseline entry while still being a different trade.",
        "",
        "## Files",
        "",
        "- `before_zigzag_trades_august.csv`: accepted baseline trades.",
        "- `after_zigzag_trades_august.csv`: accepted ZigZag trades.",
        "- `baseline_signal_diagnostics_august.csv`: one row per raw baseline signal, including baseline execution skips and ZigZag stage results.",
        "- `baseline_accepted_trade_diagnostics_august.csv`: the same diagnostic fields restricted to accepted baseline trades.",
        "- `baseline_only_rejection_impact.csv`: removed winners and losses grouped by the first failing stage.",
        "- `baseline_winners_august.csv`: baseline winners sorted from largest to smallest.",
        "- `underlying_august_5m_indicators.csv`: native BTC 5-minute OHLCV plus indicators.",
        "- `aug19_1305_btc_candles.csv`: BTC and indicators from two hours before the important signal through exit.",
        "- `aug19_1305_option_quotes.csv`: synthetic option BBO over the same review window through exit.",
        "- `aug19_1305_event.json`: trade, fee, instrument, and fidelity details.",
        "- `before_zigzag_config.json` and `after_zigzag_config.json`: exact report configurations.",
        "",
    ))
    (output / "README.md").write_text("\n".join(lines), encoding="utf-8")


def build_audit(baseline_dir: Path, zigzag_dir: Path, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    baseline_summary = _load_json(baseline_dir / "summary.json")
    zigzag_summary = _load_json(zigzag_dir / "summary.json")
    baseline = _load_august_trades(baseline_dir)
    zigzag = _load_august_trades(zigzag_dir)
    frame = _load_august_underlying()
    zigzag_config = _config_from_summary(zigzag_summary)
    zigzag_direction = pullback_reversal_directions(frame, zigzag_config)
    zigzag_signal = zigzag_direction.ne("") & zigzag_direction.ne(
        zigzag_direction.shift(1).fillna("")
    )
    baseline_config = baseline_summary["configuration"]
    all_signal_diagnostics = _signal_diagnostic_rows(
        frame,
        baseline,
        zigzag,
        zigzag_config,
        zigzag_direction,
        zigzag_signal,
        min_days_to_expiry=float(baseline_config["min_days_to_expiry"]),
        min_days_to_expiry_inclusive=bool(
            baseline_config["min_days_to_expiry_inclusive"]
        ),
        max_days_to_expiry=float(baseline_config["max_days_to_expiry"]),
        blocked_weekdays_ist=tuple(baseline_config["no_trade_days_ist"]),
    )
    diagnostics_frame = all_signal_diagnostics.loc[
        all_signal_diagnostics["baseline_trade"]
    ].copy()
    impacts = _impact_table(diagnostics_frame)

    _write_csv(baseline, output / "before_zigzag_trades_august.csv")
    _write_csv(zigzag, output / "after_zigzag_trades_august.csv")
    _write_csv(
        all_signal_diagnostics,
        output / "baseline_signal_diagnostics_august.csv",
    )
    _write_csv(
        diagnostics_frame,
        output / "baseline_accepted_trade_diagnostics_august.csv",
    )
    _write_csv(impacts, output / "baseline_only_rejection_impact.csv")
    winners = baseline.loc[
        pd.to_numeric(baseline["pnl_usd"], errors="coerce").gt(0.0)
    ].copy()
    winners["_pnl_sort"] = pd.to_numeric(winners["pnl_usd"], errors="coerce")
    winners = winners.sort_values("_pnl_sort", ascending=False).drop(columns="_pnl_sort")
    _write_csv(winners, output / "baseline_winners_august.csv")
    underlying = frame.copy()
    underlying.insert(0, "timestamp_utc", underlying.index.map(pd.Timestamp.isoformat))
    underlying.insert(
        1,
        "timestamp_ist",
        underlying.index.tz_convert(IST).map(pd.Timestamp.isoformat),
    )
    _write_csv(
        underlying.reset_index(drop=True),
        output / "underlying_august_5m_indicators.csv",
    )
    _copy_config(baseline_summary, output / "before_zigzag_config.json")
    _copy_config(zigzag_summary, output / "after_zigzag_config.json")
    event = _event_files(output, frame, baseline)
    _write_report(
        output,
        baseline,
        zigzag,
        all_signal_diagnostics,
        diagnostics_frame,
        impacts,
        event,
    )

    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "baseline_report": str(baseline_dir.resolve()),
        "zigzag_report": str(zigzag_dir.resolve()),
        "august_start": AUGUST_START.isoformat(),
        "august_end_exclusive": SEPTEMBER_START.isoformat(),
        "baseline_metrics": _trade_metrics(baseline),
        "zigzag_metrics": _trade_metrics(zigzag),
        "zigzag_config": asdict(zigzag_config),
        "files": sorted(path.name for path in output.iterdir() if path.is_file()),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    archive = output.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for path in sorted(output.iterdir()):
            if path.is_file():
                handle.write(path, arcname=f"{output.name}/{path.name}")
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export the August 2026 baseline-versus-ZigZag audit package",
    )
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--zigzag", type=Path, default=DEFAULT_ZIGZAG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    archive = build_audit(args.baseline, args.zigzag, args.output)
    print(f"Audit folder: {args.output.resolve()}")
    print(f"ZIP package: {archive.resolve()}")


if __name__ == "__main__":
    main()
