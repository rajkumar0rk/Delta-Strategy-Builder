"""Research-only sensitivity to additional adverse entry/exit option premiums.

This does not replay signals, liquidity, stops, or trade timing.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import math
from typing import Any, Iterable, Mapping

DEFAULT_SCENARIOS = (0.0, 0.5, 1.0, 2.0, 5.0)
FEE_DEFAULTS = {"option_notional_fee_rate_percent": 0.01,
                "premium_fee_cap_percent": 3.5, "gst_percent": 18.0}


def _number(v):
    x = float(v)
    if not math.isfinite(x):
        raise ValueError("Non-finite value")
    return x


def _fee(spot, premium, qty, contract_value, cfg):
    notional = spot * qty * contract_value * cfg["option_notional_fee_rate_percent"] / 100
    cap = premium * qty * contract_value * cfg["premium_fee_cap_percent"] / 100
    return min(notional, cap) * (1 + cfg["gst_percent"] / 100)


def _month(timestamp):
    try:
        dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        return (dt.astimezone(timezone.utc) if dt.tzinfo else dt).strftime("%Y-%m")
    except (TypeError, ValueError):
        return "UNKNOWN"


def build_execution_stress(trades: Iterable[Mapping[str, Any]], fee_model=None,
                           reliability=None, scenarios=DEFAULT_SCENARIOS):
    rows = list(trades)
    fees = {}
    for name, default in FEE_DEFAULTS.items():
        try:
            value = _number((fee_model or {}).get(name, default))
            fees[name] = value if value >= 0 else default
        except (TypeError, ValueError):
            fees[name] = default
    valid = []
    exclusions = defaultdict(int)
    all_original = 0.0
    for row in rows:
        try:
            pnl = _number(row["net_pnl_usd"])
            all_original += pnl
            action = str(row["action"]).upper()
            entry, exit_ = _number(row["entry_price"]), _number(row["exit_price"])
            qty, cv = _number(row["quantity"]), _number(row["contract_value"])
            spot_in, spot_out = _number(row["entry_spot"]), _number(row["exit_spot"])
            if action not in ("BUY", "SELL") or min(entry, qty, cv, spot_in, spot_out) <= 0 or exit_ < 0:
                raise ValueError("Invalid trade")
            valid.append((action, entry, exit_, qty, cv, spot_in, spot_out, pnl, _month(row.get("entry_time"))))
        except (KeyError, ValueError, TypeError, OverflowError):
            exclusions["MISSING_OR_INVALID_TRADE_FIELDS"] += 1
    steps = list(scenarios)
    if not steps or len(steps) > 50 or any(not isinstance(p, (int, float)) or not math.isfinite(p) or p < 0 or p > 100 for p in steps):
        raise ValueError("Stress scenarios must be finite percentages from 0 to 100 (max 50)")
    outcomes = []
    for pct in steps:
        variation = pct / 100
        pnl_values = []
        months = defaultdict(float)
        extra = 0.0
        for action, entry, exit_, qty, cv, spot_in, spot_out, original, month in valid:
            side = 1 if action == "BUY" else -1
            adverse_entry = max(0, entry * (1 + side * variation))
            adverse_exit = max(0, exit_ * (1 - side * variation))
            previous_fees = _fee(spot_in, entry, qty, cv, fees) + _fee(spot_out, exit_, qty, cv, fees)
            new_fees = _fee(spot_in, adverse_entry, qty, cv, fees) + _fee(spot_out, adverse_exit, qty, cv, fees)
            pnl = original + side * ((adverse_exit - exit_) - (adverse_entry - entry)) * qty * cv - (new_fees - previous_fees)
            pnl_values.append(pnl)
            months[month] += pnl
            extra += original - pnl
        wins = sum(p > 0 for p in pnl_values)
        gains = sum(max(p, 0) for p in pnl_values)
        losses = -sum(min(p, 0) for p in pnl_values)
        outcomes.append({
            "adverse_premium_percent_per_side": pct, "trades": len(valid),
            "wins": wins, "win_rate_percent": round(100 * wins / len(valid), 2) if valid else None,
            "net_pnl_usd": round(sum(pnl_values), 6),
            "extra_execution_cost_usd": round(extra, 6),
            "profit_factor": round(gains / losses, 4) if losses > 0 else None,
            "profitable_months": sum(v > 0 for v in months.values()), "months": len(months),
        })
    return {
        "kind": "ADVERSE_OPTION_PREMIUM_FILL_STRESS",
        "mode": "POST_TRADE_SENSITIVITY_ONLY",
        "data_fidelity": str((reliability or {}).get("quote_fidelity") or "UNVERIFIED"),
        "research_only": True,
        "note": "Hypothetical additional adverse fill cost per side. Timing, quote depth, stops, margin and orders are NOT re-simulated.",
        "all_trades": len(rows), "eligible_trades": len(valid),
        "excluded_trades": len(rows)-len(valid), "excluded_reasons": dict(exclusions),
        "coverage_percent": round(100*len(valid)/len(rows), 2) if rows else 0,
        "all_trades_original_net_pnl_usd": round(all_original, 6),
        "eligible_baseline_net_pnl_usd": round(sum(v[7] for v in valid), 6),
        "fee_model": fees, "scenarios": outcomes,
    }
