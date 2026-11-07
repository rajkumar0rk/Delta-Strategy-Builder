"""Opt-in, research-only, shared-cash replay of *saved* futures trade results.

This is NOT a re-execution of signals or an exchange margin/liquidation
simulator. Results are conservative scenario comparisons, not executable fills.
Existing backtest calculations, trade files and strategy JSON are unchanged.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from math import isfinite, sqrt
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .storage import load_result


class PortfolioRun(BaseModel):
    run_id: str = Field(min_length=1, max_length=180, pattern=r"^[A-Za-z0-9_.-]+$")
    capital_fraction: float = Field(gt=0, le=1)


class LabeledInterval(BaseModel):
    start: datetime
    end: datetime
    label: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_window(self):
        if (self.start.tzinfo is None or self.end.tzinfo is None
                or self.start >= self.end):
            raise ValueError("Interval needs timezone-aware start < end")
        return self


class UniverseMembership(BaseModel):
    symbol: str = Field(min_length=1, max_length=64)
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_window(self):
        if (self.start.tzinfo is None or self.end.tzinfo is None
                or self.start >= self.end):
            raise ValueError("Universe membership requires timezone-aware start < end")
        return self


class PortfolioResearchRequest(BaseModel):
    runs: list[PortfolioRun] = Field(min_length=2, max_length=12)
    initial_cash_usd: float = Field(gt=0, le=1_000_000_000)
    max_parallel_positions: int = Field(default=3, ge=1, le=50)
    # No implicit hedging or netting: exchange margin semantics remain unknown.
    symbol_conflict_policy: Literal["BLOCK", "SAME_DIRECTION", "ALLOW"] = "BLOCK"
    margin_safety_multiplier: float = Field(default=1.5, ge=1, le=10)
    max_daily_realized_loss_percent: float | None = Field(default=None, gt=0, le=100)
    minimum_correlation_days: int = Field(default=20, ge=3, le=1000)
    max_source_trades: int = Field(default=100000, ge=1, le=500000)
    max_ledger_rows: int = Field(default=500, ge=0, le=10000)
    # Labels must be calculated from *historically available* completed bars.
    regime_intervals: list[LabeledInterval] = Field(default_factory=list, max_length=20000)
    # Supplying a universe activates strict point-in-time membership admission.
    universe_memberships: list[UniverseMembership] = Field(default_factory=list, max_length=20000)

    @model_validator(mode="after")
    def validate_config(self):
        names = [r.run_id for r in self.runs]
        if len(names) != len(set(names)):
            raise ValueError("Portfolio run IDs must be unique")
        if sum(r.capital_fraction for r in self.runs) > 1.000000001:
            raise ValueError("Run capital fractions must total at most 1")
        sorted_regimes = sorted(self.regime_intervals, key=lambda r: r.start)
        for prev, current in zip(sorted_regimes, sorted_regimes[1:]):
            if prev.end > current.start:
                raise ValueError("Regime intervals must not overlap")
        memberships: dict[str, list[UniverseMembership]] = defaultdict(list)
        for row in self.universe_memberships:
            memberships[row.symbol].append(row)
        for symbol, values in memberships.items():
            values.sort(key=lambda x: x.start)
            if any(a.end > b.start for a, b in zip(values, values[1:])):
                raise ValueError(f"Membership windows overlap for {symbol}")
        return self


def _utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Naive timestamp rejected; use UTC offset")
    return dt.astimezone(timezone.utc)


def _finite(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid numeric {field}") from exc
    if not isfinite(number):
        raise ValueError(f"Non-finite {field}")
    return number


def _max_drawdown(cash_points: list[tuple[datetime, float]]) -> tuple[float, float]:
    if not cash_points:
        return 0.0, 0.0
    peak = cash_points[0][1]
    worst = 0.0
    worst_percent = 0.0
    for _, cash in cash_points:
        peak = max(peak, cash)
        worst = max(worst, peak - cash)
        if peak > 0:
            worst_percent = max(worst_percent, 100.0 * (peak - cash) / peak)
    return worst, worst_percent


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    mean_a = sum(left) / len(left)
    mean_b = sum(right) / len(right)
    aa = sum((x - mean_a) ** 2 for x in left)
    bb = sum((y - mean_b) ** 2 for y in right)
    if aa <= 0 or bb <= 0:
        return None
    cross = sum((x - mean_a) * (y - mean_b) for x, y in zip(left, right))
    return max(-1.0, min(1.0, cross / sqrt(aa * bb)))


def _matching_label(ts: datetime, intervals: list[LabeledInterval]) -> str:
    for period in intervals:
        if period.start <= ts < period.end:
            return period.label
    return "UNCLASSIFIED"


def _in_universe(symbol: str, ts: datetime, intervals: list[UniverseMembership]) -> bool:
    return any(i.symbol == symbol and i.start <= ts < i.end for i in intervals)


def _source_trades(run: dict[str, Any], source: PortfolioRun,
                   max_source_trades: int) -> tuple[list[dict[str, Any]], list[str]]:
    strategy = run.get("strategy") or {}
    if strategy.get("market_type") != "FUTURES":
        raise ValueError(f"{source.run_id}: only FUTURES saved runs are supported")
    if run.get("unresolved_position"):
        raise ValueError(f"{source.run_id}: unresolved position; cannot reconcile its closed P&L")
    original = run.get("trades")
    if not isinstance(original, list):
        raise ValueError(f"{source.run_id}: trades are unavailable")
    if len(original) > max_source_trades:
        raise ValueError(f"{source.run_id}: too many trades; lower the requested range")
    cfg = strategy.get("futures") or {}
    leverage = _finite(cfg.get("leverage"), "source leverage")
    if leverage <= 0:
        raise ValueError(f"{source.run_id}: leverage must be positive")
    warnings = []
    if (cfg.get("funding_mode") == "EXCLUDE_WITH_WARNING"):
        warnings.append(f"{source.run_id}: funding excluded from source P&L")
    reliability = run.get("reliability") or {}
    if reliability.get("grade") != "RESEARCH_ONLY":
        warnings.append(f"{source.run_id}: unexpected reliability grade; investigate provenance")
    if run.get("storage_mode") != "FULL_DEBUG":
        warnings.append(f"{source.run_id}: source snapshots may omit intermediate equity curves")
    trades = []
    for number, trade in enumerate(original):
        try:
            entry, exit_at = _utc(trade["entry_time"]), _utc(trade["exit_time"])
            net = _finite(trade["net_pnl_usd"], "net_pnl_usd")
            qty = _finite(trade["quantity"], "quantity")
            price = _finite(trade["entry_price"], "entry_price")
            fee = _finite(trade.get("entry_fee_usd", 0), "entry_fee_usd")
            funding = _finite(trade.get("funding_usd", 0), "funding_usd")
            symbol = str(trade["symbol"])
            direction = str(trade["direction"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"{source.run_id}: invalid trade #{number + 1}: {exc}") from exc
        if exit_at <= entry or qty <= 0 or price <= 0 or fee < 0 or not symbol:
            raise ValueError(f"{source.run_id}: invalid trade timeline/quantity/price/fee #{number + 1}")
        if direction not in {"LONG", "SHORT"}:
            raise ValueError(f"{source.run_id}: invalid direction #{number + 1}")
        margin = price * qty / leverage
        trades.append({
            "run_id": source.run_id, "trade_index": number, "entry": entry,
            "exit": exit_at, "symbol": symbol, "direction": direction,
            "net_usd": net, "entry_fee_usd": fee, "funding_usd": funding,
            "quantity_btc": qty, "estimated_margin_usd": margin,
        })
    metrics = run.get("metrics") or {}
    if "net_pnl_usd" in metrics:
        expected = _finite(metrics["net_pnl_usd"], "summary net_pnl_usd")
        total = sum(t["net_usd"] for t in trades)
        if abs(total - expected) > max(0.01, abs(expected) * 1e-8):
            raise ValueError(f"{source.run_id}: trade P&L does not reconcile with source metrics")
    return trades, warnings


def analyze_portfolio_runs(runs: list[dict[str, Any]], req: PortfolioResearchRequest,
                           progress=None) -> dict[str, Any]:
    """Replay fixed historical trades under shared-cash admission constraints.

    No source position is resized or its P&L fabricated. Skipping a trade does
    NOT re-run the originating strategy, so this is not an executable portfolio
    backtest. Capital and margin assume USD, not Delta INR account accounting.
    """
    if len(runs) != len(req.runs):
        raise ValueError("Source run count must match allocation definitions")
    all_trades: list[dict[str, Any]] = []
    per_run: dict[str, list[dict[str, Any]]] = {}
    warnings = [
        "RESEARCH_ONLY: accepted trades are historical fills replayed under hypothetical "
        "shared-cash gates, not signals re-executed against a live portfolio",
        "Daily drawdown uses realized closes only; open mark-to-market losses are not modeled",
        "Entry collateral is estimated from source USD notional/leverage; liquidation, "
        "funding settlement timing, FX and exchange portfolio-margin tiers are unverified",
    ]
    common_period = None
    for index, (run, spec) in enumerate(zip(runs, req.runs)):
        if progress:
            progress(f"Loading futures run {index + 1}/{len(runs)}",
                     10 + 20 * index / len(runs), "PORTFOLIO_RESEARCH")
        if not isinstance(run, dict):
            raise ValueError(f"{spec.run_id}: source run missing")
        start, end = _utc(run.get("start")), _utc(run.get("end"))
        if start >= end:
            raise ValueError(f"{spec.run_id}: invalid test window")
        period = (start, end)
        if common_period is None:
            common_period = period
        if period != common_period:
            raise ValueError("All runs must use exactly the same start/end; no mixed test periods")
        trades, local_warnings = _source_trades(run, spec, req.max_source_trades)
        per_run[spec.run_id] = trades
        all_trades.extend(trades)
        warnings.extend(local_warnings)
    if common_period is None:
        raise ValueError("No source runs")
    # No lookahead in acceptance ordering: sorting only by known entry timestamp.
    priority = {x.run_id: i for i, x in enumerate(req.runs)}
    all_trades.sort(key=lambda t: (t["entry"], priority[t["run_id"]], t["trade_index"]))
    cash = req.initial_cash_usd
    active: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    closed_pnl_by_day: dict[str, float] = defaultdict(float)
    closed_pnl_by_run: dict[str, float] = defaultdict(float)
    closed_pnl_by_regime: dict[str, dict[str, float]] = defaultdict(
        lambda: {"trades": 0, "net_pnl_usd": 0.0})
    cash_points = [(common_period[0], cash)]
    monthly: dict[str, float] = defaultdict(float)
    allocations = {x.run_id: x.capital_fraction for x in req.runs}

    def close_due(ts: datetime):
        nonlocal cash
        due = sorted((t for t in active if t["exit"] <= ts),
                     key=lambda t: (t["exit"], priority[t["run_id"]], t["trade_index"]))
        for trade in due:
            active.remove(trade)
            # Fee was charged on admission; net_pnl_usd already includes it.
            cash += trade["net_usd"] + trade["entry_fee_usd"]
            day = trade["exit"].date().isoformat()
            closed_pnl_by_day[day] += trade["net_usd"]
            closed_pnl_by_run[trade["run_id"]] += trade["net_usd"]
            monthly[trade["exit"].strftime("%Y-%m")] += trade["net_usd"]
            label = trade["regime"]
            closed_pnl_by_regime[label]["trades"] += 1
            closed_pnl_by_regime[label]["net_pnl_usd"] += trade["net_usd"]
            cash_points.append((trade["exit"], cash))
            accepted.append(trade)

    for index, trade in enumerate(all_trades):
        if progress and index % 10000 == 0:
            progress(f"Portfolio replay {index}/{len(all_trades)}",
                     35 + 55 * index / max(1, len(all_trades)), "PORTFOLIO_RESEARCH")
        close_due(trade["entry"])
        symbol = trade["symbol"]
        direction = trade["direction"]
        day = trade["entry"].date().isoformat()
        margin = trade["estimated_margin_usd"] * req.margin_safety_multiplier
        reserve = sum(t["reserved_margin"] for t in active)
        source_reserve = sum(t["reserved_margin"] for t in active
                             if t["run_id"] == trade["run_id"])
        same_symbol = [t for t in active if t["symbol"] == symbol]
        reason = None
        if req.universe_memberships and not _in_universe(
                symbol, trade["entry"], req.universe_memberships):
            reason = "OUTSIDE_POINT_IN_TIME_UNIVERSE"
        elif (req.max_daily_realized_loss_percent is not None and
              closed_pnl_by_day[day] <= -req.initial_cash_usd *
              req.max_daily_realized_loss_percent / 100):
            reason = "DAILY_REALIZED_LOSS_GATE"
        elif len(active) >= req.max_parallel_positions:
            reason = "MAX_PARALLEL_POSITIONS"
        elif req.symbol_conflict_policy == "BLOCK" and same_symbol:
            reason = "SAME_SYMBOL_BLOCKED"
        elif req.symbol_conflict_policy == "SAME_DIRECTION" and any(
                t["direction"] != direction for t in same_symbol):
            reason = "OPPOSITE_DIRECTION_BLOCKED"
        elif margin + trade["entry_fee_usd"] > cash - reserve + 1e-9:
            reason = "INSUFFICIENT_ESTIMATED_FREE_CASH"
        elif margin + source_reserve > req.initial_cash_usd * allocations[trade["run_id"]] + 1e-9:
            reason = "SOURCE_CAPITAL_ALLOCATION"
        if reason is not None:
            rejected[reason] += 1
            continue
        trade = dict(trade)
        trade["reserved_margin"] = margin
        trade["regime"] = _matching_label(trade["entry"], req.regime_intervals)
        cash -= trade["entry_fee_usd"]
        active.append(trade)
    close_due(datetime.max.replace(tzinfo=timezone.utc))
    if active:
        raise RuntimeError("Portfolio replay ended with unclosed accepted positions")
    # Source correlations use independent FULL source paths, not the gated replay.
    # Include zeros on days with no realized trade; do not imply independence.
    span = (common_period[1].date() - common_period[0].date()).days + 1
    if span > 5000:
        raise ValueError("Correlation range exceeds 5000 days")
    dates = [(common_period[0] + timedelta(days=i)).date().isoformat()
             for i in range(span)]
    raw_day_pnl: dict[str, dict[str, float]] = {}
    for run_id, trades in per_run.items():
        pnl: dict[str, float] = defaultdict(float)
        for trade in trades:
            pnl[trade["exit"].date().isoformat()] += trade["net_usd"]
        raw_day_pnl[run_id] = pnl
    correlation: dict[str, dict[str, float | None]] = {}
    for a in per_run:
        correlation[a] = {}
        for b in per_run:
            if len(dates) < req.minimum_correlation_days:
                correlation[a][b] = None
            else:
                correlation[a][b] = _correlation(
                    [raw_day_pnl[a][d] for d in dates],
                    [raw_day_pnl[b][d] for d in dates])
    if len(dates) < req.minimum_correlation_days:
        warnings.append("Too few calendar days for requested correlation estimate")
    if not req.regime_intervals:
        warnings.append("No point-in-time regime labels supplied; regime performance UNCLASSIFIED")
    if not req.universe_memberships:
        warnings.append("Point-in-time universe filter disabled; BTC-only runs need no universe ranking")
    if rejected:
        warnings.append("Skipped signals did not trigger a fresh strategy simulation: "
                        "subsequent source trades may differ from a real shared-capital run")
    dd_usd, dd_pct = _max_drawdown(cash_points)
    net = cash - req.initial_cash_usd
    gains = sum(max(0.0, t["net_usd"]) for t in accepted)
    losses = -sum(min(0.0, t["net_usd"]) for t in accepted)
    count = len(accepted)
    ledger = [{
        "run_id": t["run_id"], "symbol": t["symbol"], "direction": t["direction"],
        "entry_time": t["entry"].isoformat(), "exit_time": t["exit"].isoformat(),
        "net_pnl_usd": t["net_usd"], "reserved_margin_usd": t["reserved_margin"],
        "regime": t["regime"],
    } for t in accepted[:req.max_ledger_rows]]
    return {
        "kind": "SHARED_CASH_FUTURES_REPLAY",
        "research_only": True,
        "source_run_ids": [x.run_id for x in req.runs],
        "start": common_period[0].isoformat(),
        "end": common_period[1].isoformat(),
        "initial_cash_usd": req.initial_cash_usd,
        "ending_realized_cash_usd": cash,
        "net_realized_pnl_usd": net,
        "realized_return_percent": net * 100 / req.initial_cash_usd,
        "max_closed_trade_drawdown_usd": dd_usd,
        "max_closed_trade_drawdown_percent": dd_pct,
        "accepted_trades": count,
        "source_trade_count": len(all_trades),
        "rejected_trades_by_reason": dict(rejected),
        "positive_accepted_trades": sum(t["net_usd"] > 0 for t in accepted),
        "profit_factor": gains / losses if losses > 0 else None,
        "per_run_net_pnl_usd": dict(closed_pnl_by_run),
        "regime_results": dict(closed_pnl_by_regime),
        "monthly_net_pnl_usd": dict(sorted(monthly.items())),
        "source_daily_realized_pnl_correlation": correlation,
        "correlation_days": len(dates),
        "ledger": ledger,
        "ledger_truncated": len(accepted) > req.max_ledger_rows,
        "warnings": warnings,
        "limitations": [
            "Independent backtest trades are not regenerated after a shared risk gate rejects a trade",
            "Source futures fills are OHLC proxies, not verified orderbook executions",
            "Intrabar equity, historical exchange margin, liquidation, and INR FX not modeled",
            "Regimes and universe memberships require verified point-in-time inputs",
            "Correlation uses daily realized trade closes, not mark-to-market returns",
        ],
    }


def run_portfolio_research(req: PortfolioResearchRequest, progress=None):
    inputs = []
    for spec in req.runs:
        run = load_result(spec.run_id)
        if run is None:
            raise ValueError(f"Unknown saved run_id: {spec.run_id}")
        inputs.append(run)
    return analyze_portfolio_runs(inputs, req, progress)
