"""Deterministic, bounded in-sample parameter neighborhood diagnostics.

All measurements consume *already-run* backtest metrics. They never change
entry rules, fills, score a holdout, or generate market performance data.
"""
from __future__ import annotations

from itertools import product
from math import isfinite
from statistics import median
from typing import Any, Sequence


def _metric(row: dict[str, Any], name: str) -> float:
    raw = (row.get("metrics") or {}).get(name)
    if raw is None:
        if name == "profit_factor":
            return 0.0  # Unlimited/undefined PF cannot prove robustness.
        raise ValueError(f"Parameter cell missing required metric: {name}")
    value = float(raw)
    if not isfinite(value):
        raise ValueError(f"Parameter cell has nonfinite {name}")
    return value


def analyze_parameter_neighborhoods(
    dimensions: Sequence[Any],
    ordered_cells: Sequence[dict[str, Any]],
    *,
    radius: int = 1,
    min_trades: int = 30,
    min_neighbor_cells: int = 2,
    min_viable_fraction: float = 0.6,
) -> dict[str, Any]:
    """Assess whether positive results form a broad neighboring plateau.

    Neighborhoods are adjacent *listed parameter values*, not arbitrary
    numeric distances. Each cell is connected to up to (2r+1)^D - 1 others,
    including diagonals, excluding the center. No hidden optimization.
    This method must receive results in Cartesian grid order, before sorting.
    """
    if not 1 <= len(dimensions) <= 3:
        raise ValueError("Parameter neighborhood analysis supports 1..3 dimensions")
    if not 1 <= radius <= 3 or not 1 <= min_trades <= 100000:
        raise ValueError("Neighborhood radius/min_trades outside supported bounds")
    if not 1 <= min_neighbor_cells <= 100 or not 0 < min_viable_fraction <= 1:
        raise ValueError("Invalid neighborhood pass requirements")
    axes: list[list[float]] = []
    for dim in dimensions:
        values = [float(v) for v in dim.values]
        if not values or len(values) > 20 or any(not isfinite(v) for v in values):
            raise ValueError("Invalid sweep dimension values")
        if len(values) != len(set(values)):
            raise ValueError("Neighborhood report requires unique values in each dimension")
        axes.append(values)
    index_grid = list(product(*(range(len(axis)) for axis in axes)))
    if len(index_grid) != len(ordered_cells) or len(index_grid) > 200:
        raise ValueError("Parameter sweep results do not match the requested grid")
    positions = {index: pos for pos, index in enumerate(index_grid)}
    nets = [_metric(row, "net_pnl_usd") for row in ordered_cells]
    trades = [_metric(row, "trades") for row in ordered_cells]
    if any(x < 0 or int(x) != x for x in trades):
        raise ValueError("Parameter cell trade counts must be nonnegative integers")
    profits = [_metric(row, "profit_factor") for row in ordered_cells]
    drawdowns = [_metric(row, "max_closed_trade_drawdown_usd")
                 for row in ordered_cells]
    if any(x < 0 for x in drawdowns):
        raise ValueError("Negative drawdown magnitude is invalid")
    viable = [net > 0 and n >= min_trades for net, n in zip(nets, trades)]
    cells = []
    for pos, index in enumerate(index_grid):
        neighbors = [
            positions[key] for key in index_grid
            if key != index and max(abs(x - y) for x, y in zip(key, index)) <= radius
        ]
        neighbors_n = len(neighbors)
        accepted = sum(viable[i] for i in neighbors)
        ratio = accepted / neighbors_n if neighbors_n else 0.0
        neighbors_nets = [nets[i] for i in neighbors]
        neighbors_profit_factors = [profits[i] for i in neighbors]
        neighbors_drawdowns = [drawdowns[i] for i in neighbors]
        plateau = (
            viable[pos] and neighbors_n >= min_neighbor_cells
            and ratio >= min_viable_fraction
            and median(neighbors_nets) > 0
        )
        cell = {
            "index": list(index),
            "parameters": dict(ordered_cells[pos].get("parameters") or {}),
            "center_net_pnl_usd": nets[pos],
            "center_trades": int(trades[pos]),
            "center_viable": viable[pos],
            "neighbor_count": neighbors_n,
            "viable_neighbor_count": accepted,
            "viable_neighbor_fraction_percent": 100 * ratio,
            "neighbor_median_net_pnl_usd": (
                median(neighbors_nets) if neighbors_nets else None
            ),
            "neighbor_worst_net_pnl_usd": (
                min(neighbors_nets) if neighbors_nets else None
            ),
            "neighbor_median_profit_factor": (
                median(neighbors_profit_factors) if neighbors_profit_factors else None
            ),
            "neighbor_median_closed_drawdown_usd": (
                median(neighbors_drawdowns) if neighbors_drawdowns else None
            ),
            "plateau_candidate": plateau,
            "isolated_positive_peak": (
                viable[pos] and neighbors_n >= min_neighbor_cells
                and ratio < min_viable_fraction
            ),
        }
        cells.append(cell)
    plateaus = sorted(
        (row for row in cells if row["plateau_candidate"]),
        key=lambda row: (
            row["viable_neighbor_fraction_percent"],
            row["neighbor_median_net_pnl_usd"],
            row["center_net_pnl_usd"],
        ),
        reverse=True,
    )
    return {
        "kind": "PARAMETER_NEIGHBORHOODS",
        "research_only": True,
        "in_sample_only": True,
        "radius_in_listed_steps": radius,
        "min_trades_per_cell": min_trades,
        "min_neighbor_cells": min_neighbor_cells,
        "min_viable_fraction": min_viable_fraction,
        "total_cells": len(cells),
        "viable_cells": sum(viable),
        "low_sample_cells": sum(n < min_trades for n in trades),
        "plateau_candidates": len(plateaus),
        "isolated_positive_peaks": sum(
            row["isolated_positive_peak"] for row in cells
        ),
        "cells": cells,
        "top_plateaus": plateaus[:10],
        "warning": (
            "In-sample parameter proximity is not evidence of out-of-sample "
            "profitability. The run must pass an untouched holdout plus "
            "execution-cost and funding stress. Profit factor of missing/undefined "
            "values is treated as zero for diagnostics. Counts are based only "
            "on the already supplied grid; no untested cells are invented."
        ),
    }
