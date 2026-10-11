import pytest
from app.execution_stress import build_execution_stress

def trade(action="BUY", pnl=0.2, **extra):
    return dict(action=action, entry_price=100, exit_price=120, quantity=10,
                contract_value=0.001, entry_spot=50000, exit_spot=50050,
                entry_time="2026-09-01T12:00:00+00:00", net_pnl_usd=pnl, **extra)

def test_zero_scenario_preserves_net_pnl():
    result = build_execution_stress([trade(), trade(action="SELL", pnl=-0.1)])
    assert result["scenarios"][0]["net_pnl_usd"] == pytest.approx(0.1)

@pytest.mark.parametrize("action", ["BUY", "SELL"])
def test_adverse_premium_reduces_profit(action):
    result = build_execution_stress([trade(action=action)], scenarios=(0, 5))
    assert result["scenarios"][1]["net_pnl_usd"] < result["scenarios"][0]["net_pnl_usd"]

def test_invalid_trades_are_not_invented():
    result = build_execution_stress([trade(), {"net_pnl_usd": 0.5}])
    assert result["excluded_trades"] == 1
    assert result["coverage_percent"] == 50

@pytest.mark.parametrize("bad", [-1, 101, float("nan")])
def test_invalid_scenarios_are_rejected(bad):
    with pytest.raises(ValueError):
        build_execution_stress([], scenarios=[bad])

def test_no_trades_is_explicit():
    result = build_execution_stress([])
    assert result["scenarios"][0]["win_rate_percent"] is None

def test_monthly_profitability_is_counted():
    result = build_execution_stress([trade(pnl=0.5), trade(pnl=-0.1)])
    assert result["scenarios"][0]["profitable_months"] == 1
