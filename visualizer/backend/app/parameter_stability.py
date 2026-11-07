"""Descriptive stability of neighboring sweep cells, without future data.

Designed for small bounded research sweeps. No optimizer selection, no new
backtests or strategy-JSON changes. Holdout must be evaluated separately.
"""
from __future__ import annotations

from itertools import product
from math import isfinite
from statistics import median
from typing import Any


def parameter_neighborhoods(dimensions: list[Any], rows: list[dict[str, Any]],
                            *, min_trades: int = 10) -> dict[str, Any]:
    """Analyze immediate grid neighbors, excluding invalid/low-sample cells.

    Neighbors differ by one index along exactly one dimension; the metric is
    historical net P&L (not a forecast). Return only computed cells.
    """
    if not 1 <= len(dimensions) <= 3:
        raise ValueError("Stability supports one to three dimensions")
    if not 1 <= min_trades <= 10000:
        raise ValueError("min_trades must be between 1 and 10000")
    axes = []
    for dimension in dimensions:
        values = list(dimension.values)
        if len(values) != len(set(values)):
            raise ValueError("Sweep stability needs unique parameter values per dimension")
        if not values:
            raise ValueError("Empty parameter axis")
        axes.append(values)
    if len(rows) > 200:
        raise ValueError("Stability supports at most 200 evaluated cells")
    paths = [d.path for d in dimensions]
    grid: dict[tuple[int, ...], dict[str, Any]] = {}
    for row in rows:
        coordinates = []
        for path, values in zip(paths, axes):
            if path not in row.get("parameters", {}):
                raise ValueError("Sweep row missing parameter: " + path)
            value = row["parameters"][path]
            if value not in values:
                raise ValueError("Sweep row includes parameter outside requested grid")
            coordinates.append(values.index(value))
        key = tuple(coordinates)
        if key in grid:
            raise ValueError("Duplicate parameter cell")
        grid[key] = row

    def metrics(key: tuple[int, ...]) -> tuple[float, int] | None:
        row = grid.get(key)
        if row is None:
            return None
        m = row.get("metrics", {})
        try:
            net = float(m["net_pnl_usd"])
            trades = int(m["trades"])
        except (TypeError, ValueError, KeyError):
            return None
        if not isfinite(net) or trades < min_trades:
            return None
        return net, trades

    cells = []
    for key in product(*(range(len(axis)) for axis in axes)):
        if key not in grid:
            continue
        neighbors = []
        for axis in range(len(key)):
            for delta in (-1, 1):
                adjacent = list(key)
                adjacent[axis] += delta
                if 0 <= adjacent[axis] < len(axes[axis]):
                    neighbors.append(tuple(adjacent))
        valid_neighbors = [m for k in neighbors if (m := metrics(k)) is not None]
        own = metrics(key)
        nets = [m[0] for m in valid_neighbors]
        cells.append({
            "parameters": {path: axis[i] for path, axis, i in zip(paths, axes, key)},
            "eligible": own is not None,
            "net_pnl_usd": own[0] if own is not None else None,
            "trades": own[1] if own is not None else grid[key].get("metrics", {}).get("trades"),
            "neighbor_slots": len(neighbors),
            "valid_neighbors": len(nets),
            "positive_neighbor_percent": (100.0 * sum(v > 0 for v in nets) / len(nets)) if nets else None,
            "median_neighbor_net_usd": median(nets) if nets else None,
            "worst_neighbor_net_usd": min(nets) if nets else None,
            "neighbor_positive_plateau": bool(own is not None and own[0] > 0 and nets and all(x > 0 for x in nets)),
            "isolated_positive_peak": bool(own is not None and own[0] > 0 and nets and not any(x > 0 for x in nets)),
        })
    eligible = [c for c in cells if c["eligible"]]
    return {
        "kind": "PARAMETER_NEIGHBORHOOD_STABILITY",
        "research_only": True,
        "in_sample_only": True,
        "min_trades": min_trades,
        "evaluated_cells": len(cells),
        "eligible_cells": len(eligible),
        "positive_plateau_cells": sum(c["neighbor_positive_plateau"] for c in eligible),
        "isolated_positive_peak_cells": sum(c["isolated_positive_peak"] for c in eligible),
        "cells": cells,
        "warnings": [
            "Immediate grid neighbors only; axes follow the input value order.",
            "Requires out-of-sample holdout and realistic futures fees/funding before inference.",
            "Missing/low-trade neighbors are excluded; a positive plateau is not proof of profitable trading.",
        ],
    }
