"""Opt-in decision-log omission must not change default result semantics."""
from types import SimpleNamespace

from backtest import ema_vwap_research as research


def test_decision_retention_is_opt_in_and_preserves_execution(monkeypatch, tmp_path):
    scenario = research.Scenario(name="retention-test", group=1, exit_mode="NONE")
    event = SimpleNamespace(
        timestamp_ns=research.timestamp_ns("2026-11-01T00:05:00Z"),
        option=SimpleNamespace(symbol="BTC-TEST"),
        direction="CALL",
        entry_type="BASELINE",
        ema_regime_start_ns=0,
        execution_attempt=None,
    )

    monkeypatch.setattr(research, "indicators", lambda path: object())
    monkeypatch.setattr(research, "_option_specs", lambda path: [])
    def signals(*args, **kwargs):
        if kwargs["decision_events"] is not None:
            kwargs["decision_events"].append({"stage": "SIGNAL", "status": "REJECTED"})
        return [event]
    monkeypatch.setattr(research, "signal_events", signals)
    monkeypatch.setattr(research, "capture_quotes", lambda *a, **k: None)
    monkeypatch.setattr(research, "simulate_trade", lambda *a, **k: (None, "TEST_REJECT"))
    baseline = research.run_dataset(
        tmp_path, start="2026-11-01T00:00:00Z",
        end="2026-11-02T00:00:00Z", scenario_set=[scenario]
    )
    reduced = research.run_dataset(
        tmp_path, start="2026-11-01T00:00:00Z",
        end="2026-11-02T00:00:00Z", scenario_set=[scenario],
        retain_decision_events=False,
    )
    assert baseline["decision_events"]
    assert reduced["decision_events"] == []
    for key in baseline:
        if key != "decision_events":
            assert reduced[key] == baseline[key]
