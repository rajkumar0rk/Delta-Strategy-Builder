"""Deterministic tests for opt-in legacy research resource admission."""
import pytest
from backtest.resource_limits import (
    DecisionEventBudget, LegacyResourceLimits, LimitedDecisionEvents,
)


def test_all_limits_are_opt_in_and_validate_positive_values():
    assert all(value is None for value in vars(LegacyResourceLimits()).values())
    for name in vars(LegacyResourceLimits()):
        for bad in (0, -1, 1.2, True, "10"):
            with pytest.raises(ValueError, match=name):
                LegacyResourceLimits(**{name: bad})
    assert LegacyResourceLimits(max_trades=1).max_trades == 1


def test_shared_decision_budget_rejects_without_truncating():
    budget = DecisionEventBudget(2)
    first = LimitedDecisionEvents(budget)
    second = LimitedDecisionEvents(budget)
    first.append({"reason": "ONE"})
    second.append({"reason": "TWO"})
    with pytest.raises(ValueError, match="LEGACY_DECISION_EVENT_LIMIT_EXCEEDED"):
        first.append({"reason": "THREE"})
    assert first == [{"reason": "ONE"}]
    assert second == [{"reason": "TWO"}]
    assert budget.count == 2


def test_scenario_admission_prevents_oversized_run(monkeypatch, tmp_path):
    from backtest import ema_vwap_research as research
    runner = research.run_dataset
    globals_for_run = runner.__globals__
    monkeypatch.setitem(globals_for_run, "indicators", lambda path: [object()])
    monkeypatch.setitem(globals_for_run, "_option_specs", lambda path: [])
    scenarios = [research.Scenario(name=f"S{i}", group=1, exit_mode="EMA") for i in range(2)]
    with pytest.raises(ValueError, match="LEGACY_SCENARIO_LIMIT_EXCEEDED"):
        runner(tmp_path, start="2026-11-01T00:00:00Z", end="2026-11-02T00:00:00Z",
               scenario_set=scenarios, resource_limits=LegacyResourceLimits(max_scenarios=1))


def test_bar_and_instrument_admission(monkeypatch, tmp_path):
    from backtest import ema_vwap_research as research
    runner = research.run_dataset
    globals_for_run = runner.__globals__
    monkeypatch.setitem(globals_for_run, "indicators", lambda path: [1, 2])
    monkeypatch.setitem(globals_for_run, "_option_specs", lambda path: [object(), object()])
    scenario = [research.Scenario(name="S", group=1, exit_mode="EMA")]
    common = dict(start="2026-11-01T00:00:00Z", end="2026-11-02T00:00:00Z", scenario_set=scenario)
    with pytest.raises(ValueError, match="LEGACY_UNDERLYING_BAR_LIMIT_EXCEEDED"):
        runner(tmp_path, **common, resource_limits=LegacyResourceLimits(max_underlying_bars=1))
    with pytest.raises(ValueError, match="LEGACY_OPTION_INSTRUMENT_LIMIT_EXCEEDED"):
        runner(tmp_path, **common, resource_limits=LegacyResourceLimits(max_option_instruments=1))
