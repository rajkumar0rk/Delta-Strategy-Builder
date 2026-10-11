"""Small, deterministic calculations shared by the research backtests."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol


class VolumePolicy(Protocol):
    min_volume: float
    volume_quantity_multiplier: float


def ema(values: Sequence[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    output = [float(values[0])]
    for value in values[1:]:
        output.append(alpha * float(value) + (1.0 - alpha) * output[-1])
    return output


def rsi_wilder(values: Sequence[float], period: int) -> list[float]:
    output = [math.nan] * len(values)
    if len(values) <= period:
        return output

    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, period + 1):
        change = float(values[index]) - float(values[index - 1])
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    average_gain = sum(gains) / period
    average_loss = sum(losses) / period

    def score() -> float:
        if average_loss == 0.0:
            return 100.0 if average_gain > 0.0 else 50.0
        return 100.0 - 100.0 / (1.0 + average_gain / average_loss)

    output[period] = score()
    for index in range(period + 1, len(values)):
        change = float(values[index]) - float(values[index - 1])
        average_gain = (average_gain * (period - 1) + max(change, 0.0)) / period
        average_loss = (average_loss * (period - 1) + max(-change, 0.0)) / period
        output[index] = score()
    return output


def calculate_quantity(
    *,
    budget_usd: float,
    premium: float,
    contract_value: float,
    min_quantity: float,
    quantity_step: float,
    lot_size: float,
) -> float:
    """Return the largest valid quantity whose premium cost is within budget."""
    if min(budget_usd, premium, contract_value, min_quantity, quantity_step, lot_size) <= 0.0:
        return 0.0
    raw_quantity = budget_usd / (premium * contract_value)
    increment = max(quantity_step, lot_size)
    units = math.floor((raw_quantity + 1e-12) / increment)
    quantity = units * increment
    if quantity + 1e-12 < min_quantity:
        return 0.0
    if premium * contract_value * quantity > budget_usd + 1e-9:
        return 0.0
    return round(quantity, 12)


def required_entry_volume(quantity: float, policy: VolumePolicy) -> float:
    """Return the reported-volume threshold for an intended order quantity."""
    scaled = max(0.0, quantity) * policy.volume_quantity_multiplier
    return max(policy.min_volume, scaled)
