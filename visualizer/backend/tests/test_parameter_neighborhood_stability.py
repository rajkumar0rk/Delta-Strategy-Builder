from types import SimpleNamespace

import pytest

from app.parameter_stability import parameter_neighborhoods


def axis(path, values):
    return SimpleNamespace(path=path, values=values)


def row(value, net, trades=30):
    return {"parameters": {"risk.stop_loss.value": value},
            "metrics": {"net_pnl_usd": net, "trades": trades}}


def test_plateau_is_descriptive_and_causal():
    result = parameter_neighborhoods(
        [axis("risk.stop_loss.value", [10, 15, 20])],
        [row(10, 20), row(15, 30), row(20, 25)])
    assert result["positive_plateau_cells"] == 3
    assert result["in_sample_only"] is True
    assert result["cells"][1]["valid_neighbors"] == 2
    assert result["cells"][1]["median_neighbor_net_usd"] == 22.5


def test_isolated_positive_peak():
    result = parameter_neighborhoods(
        [axis("risk.stop_loss.value", [10, 15, 20])],
        [row(10, -1), row(15, 100), row(20, -10)])
    assert result["isolated_positive_peak_cells"] == 1
    assert result["positive_plateau_cells"] == 0


def test_low_trade_neighbors_not_counted_as_evidence():
    result = parameter_neighborhoods(
        [axis("risk.stop_loss.value", [10, 15])],
        [row(10, 5, 100), row(15, 100, 2)], min_trades=10)
    assert result["eligible_cells"] == 1
    assert result["cells"][0]["valid_neighbors"] == 0
    assert result["cells"][0]["positive_neighbor_percent"] is None
    assert not result["cells"][0]["neighbor_positive_plateau"]


def test_2d_geometry_uses_only_axial_neighbors():
    dimensions = [axis("x", [1, 2]), axis("y", [10, 20])]
    rows = [
        {"parameters": {"x": x, "y": y},
         "metrics": {"net_pnl_usd": x + y, "trades": 40}}
        for x in (1, 2) for y in (10, 20)
    ]
    result = parameter_neighborhoods(dimensions, rows)
    assert len(result["cells"]) == 4
    assert all(cell["neighbor_slots"] == 2 for cell in result["cells"])


def test_duplicate_coordinates_fail_closed():
    with pytest.raises(ValueError, match="Duplicate parameter cell"):
        parameter_neighborhoods([axis("x", [1])],
            [{"parameters": {"x": 1}, "metrics": {"net_pnl_usd": 1, "trades": 11}}] * 2)


def test_invalid_trade_value_not_eligible():
    result = parameter_neighborhoods([axis("x", [1])],
        [{"parameters": {"x": 1}, "metrics": {"net_pnl_usd": float("nan"), "trades": 20}}])
    assert result["eligible_cells"] == 0


def test_duplicate_parameter_values_rejected():
    with pytest.raises(ValueError, match="unique"):
        parameter_neighborhoods([axis("x", [1, 1])], [])


def test_request_keeps_legacy_default():
    from app.models import ResearchSweepRequest, StrategyConfig, SweepDimension
    req = ResearchSweepRequest(
        dataset_id="x", start="2026-01-01T00:00:00Z", end="2026-02-01T00:00:00Z",
        strategy=StrategyConfig(),
        dimensions=[SweepDimension(path="risk.stop_loss.value", values=[10, 20])])
    assert req.stability_min_trades == 10
