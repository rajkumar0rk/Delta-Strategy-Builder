"""Published Delta Exchange India BTCUSD contract snapshot and research-only math.

Data checked 2026-10-29 against https://www.delta.exchange/contracts and
https://www.delta.exchange/fees . These public specifications are *current*,
not historical observations for every date in the research archive.

Collateral is quoted in USD-equivalent for comparisons ONLY. The real
contract settles in INR; no historical USD/INR conversion, portfolio margin,
mark price, auto-top-up or exchange liquidation execution is reconstructed.
"""
from __future__ import annotations

from datetime import datetime, timezone

CONTRACT_SPEC_URL = "https://www.delta.exchange/contracts"
FEES_URL = "https://www.delta.exchange/fees"
FUNDING_URL = "https://www.delta.exchange/support/solutions?articleId=80001199725"
SPEC_CHECKED_DATE = "2026-10-29"

# 2025-09-08 17:30 IST; prior regime exchanged funding minute by minute.
EIGHT_HOUR_FUNDING_FROM_UTC = datetime(2025, 9, 8, 12, 0, tzinfo=timezone.utc)

BTCUSD_SNAPSHOT = {
    "symbol": "BTCUSD",
    "contract_btc": 0.001,
    "tick_size_usd": 0.5,
    "max_leverage": 200,
    "base_initial_margin_percent": 0.5,
    "base_maintenance_margin_percent": 0.25,
    "taker_fee_percent": 0.05,
    "maker_fee_percent": 0.02,
    "gst_percent_on_trading_fees": 18,
    "position_limit_usd": 5_000_000,
    "tier_boundary_usd": 100_000,
    "initial_margin_increase_percent_per_usd": 0.0000025,
    "maintenance_margin_increase_percent_per_usd": 0.00000125,
    "funding_interval_hours": 8,
    "current_funding_cap_percent": 1.0,
    "settlement_currency": "INR",
    "margin_mark_method": "FAIR_PRICE",
    "checked_date": SPEC_CHECKED_DATE,
    "contract_spec_url": CONTRACT_SPEC_URL,
    "fees_url": FEES_URL,
    "funding_method_url": FUNDING_URL,
}


def published_margin_percent(notional_usd: float, *, initial: bool) -> float:
    """Current published BTCUSD IM/MM tier, NOT historical margin replay."""
    if notional_usd < 0:
        raise ValueError("Notional must not be negative")
    excess = max(0.0, notional_usd - BTCUSD_SNAPSHOT["tier_boundary_usd"])
    if initial:
        return (BTCUSD_SNAPSHOT["base_initial_margin_percent"] +
                excess * BTCUSD_SNAPSHOT["initial_margin_increase_percent_per_usd"])
    return (BTCUSD_SNAPSHOT["base_maintenance_margin_percent"] +
            excess * BTCUSD_SNAPSHOT["maintenance_margin_increase_percent_per_usd"])


def assumed_initial_margin_usd(price: float, qty_btc: float, config) -> float:
    """Apply the published snapshot minimum or explicit flat research scenario."""
    notional = price * qty_btc
    required = notional / config.leverage
    if config.margin_tier_mode == "DELTA_PUBLISHED_SNAPSHOT":
        required = max(required, notional * published_margin_percent(notional, initial=True) / 100)
    return required


def assumed_maintenance_margin_usd(price: float, qty_btc: float, config) -> float:
    notional = price * qty_btc
    percent = config.maintenance_margin_percent
    if config.margin_tier_mode == "DELTA_PUBLISHED_SNAPSHOT":
        percent = max(percent, published_margin_percent(notional, initial=False))
    return notional * percent / 100


def assumed_contract_warnings(config) -> list[str]:
    """Expose deviations rather than silently replacing user research settings."""
    checks = [
        ("contract_btc", "contract_btc"),
        ("tick_size", "tick_size_usd"),
        ("taker_fee_percent", "taker_fee_percent"),
        ("gst_percent", "gst_percent_on_trading_fees"),
    ]
    warnings = []
    for user_field, official_field in checks:
        actual = float(getattr(config, user_field))
        published = float(BTCUSD_SNAPSHOT[official_field])
        if not abs(actual - published) < 1e-10:
            warnings.append(f"{user_field}={actual:g} differs from public BTCUSD snapshot {published:g}")
    if config.margin_tier_mode == "FLAT_RESEARCH":
        warnings.append("Flat margin mode ignores published BTCUSD size-dependent minimums")
    if config.maintenance_margin_percent < BTCUSD_SNAPSHOT["base_maintenance_margin_percent"]:
        warnings.append("Research maintenance margin below today's published minimum")
    return warnings
