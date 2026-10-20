"""Short-option collateral RESEARCH estimates; no broker margin or L1 simulation.

Does not assert Delta exchange requirements; rates must be supplied by the user.
Sources: Delta margin guide (risk-based portfolio margin), isolated margin guide.
"""
from __future__ import annotations

from typing import Any


def short_margin_details(config, spot: float, premium: float, quantity: float,
                         contract_value: float, entry_fee: float = 0.0,
                         estimated_exit_fee: float = 0.0) -> dict[str, Any]:
    notional = float(spot) * float(quantity) * float(contract_value)
    premium_value = float(premium) * float(quantity) * float(contract_value)
    if not config.enabled:
        return {
            'mode': 'UNMODELED', 'venue_verified': False, 'notional_usd': notional,
            'initial_margin_usd': None, 'maintenance_margin_usd': None,
            'cash_required_usd': entry_fee, 'effective_leverage': None,
        }
    # PORTFOLIO_ESTIMATE is a standalone user-calibrated proxy, NOT Delta's
    # 29-scenario portfolio risk calculation. It cannot model position offsets,
    # current account positions, mark IV shocks, or dynamic requirements.
    # A cap on assumed notional leverage creates a HIGHER collateral floor.
    # This is NOT the exchange's (risk-dependent) permitted options leverage.
    initial_rate = max(
        float(config.initial_margin_percent) / 100,
        1.0 / float(config.max_notional_leverage)
        if config.max_notional_leverage is not None else 0.0,
    )
    initial = notional * initial_rate
    maintenance = notional * float(config.maintenance_margin_percent) / 100
    buffer = initial * float(config.collateral_buffer_percent) / 100
    reserved_exit = estimated_exit_fee if config.reserve_exit_fee else 0.0
    required = initial + buffer + entry_fee + reserved_exit
    return {
        'mode': config.margin_mode, 'venue_verified': False,
        'notional_usd': notional, 'premium_value_usd': premium_value,
        'initial_margin_usd': initial, 'maintenance_margin_usd': maintenance,
        'collateral_buffer_usd': buffer,
        'reserved_entry_fee_usd': entry_fee,
        'reserved_exit_fee_usd': reserved_exit,
        'cash_required_usd': required,
        'effective_leverage': notional / initial if initial > 0 else None,
        'max_notional_leverage_assumption': config.max_notional_leverage,
        'assumption': (
            'PORTFOLIO_MANUAL_COLLATERAL_PROXY_NOT_DELTA_RISK_ENGINE'
            if config.margin_mode == 'PORTFOLIO_ESTIMATE'
            else 'USER_CALIBRATED_RESEARCH_SCENARIO_NOT_EXCHANGE_MARGIN'
        ),
        'portfolio_stress_scenarios_computed': False,
        'other_account_positions_modeled': False,
    }


def short_margin_health(config, details: dict[str, Any], realized_balance: float,
                        entry_fee: float, gross_unrealized_pnl: float,
                        estimated_exit_fee: float) -> dict[str, Any]:
    """Collateral at risk using observed executable ask-to-close.

    ISOLATED: only locked collateral supports loss.
    CROSS/PORTFOLIO_ESTIMATE: assume whole closed-trade account equity
    supports loss, without Delta's portfolio risk, positions, UCF offsets
    or dynamic stress tests. Future mark/volatility changes and auto-topups
    are not known.
    """
    if not config.enabled or details.get('initial_margin_usd') is None:
        return {'breached': False, 'venue_verified': False}
    initial = float(details['initial_margin_usd'])
    maintenance = float(details['maintenance_margin_usd'])
    unrealized_after_fees = gross_unrealized_pnl - entry_fee - estimated_exit_fee
    equity = (
        initial + unrealized_after_fees if config.margin_mode == 'ISOLATED_ESTIMATE'
        else realized_balance + unrealized_after_fees
    )
    return {
        'breached': equity <= maintenance,
        'estimated_margin_equity_usd': equity,
        'estimated_maintenance_margin_usd': maintenance,
        'estimated_margin_buffer_usd': equity - maintenance,
        'venue_verified': False,
        'assumption': (
            'MANUAL_PORTFOLIO_PROXY_NOT_DELTA_LIQUIDATION'
            if config.margin_mode == 'PORTFOLIO_ESTIMATE'
            else 'HYPOTHETICAL_MAINTENANCE_THRESHOLD_NOT_DELTA_LIQUIDATION'
        ),
    }
