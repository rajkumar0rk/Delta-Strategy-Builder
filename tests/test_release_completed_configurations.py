"""Last-use release must not change trades, fees, signals, or decision reports."""
from types import SimpleNamespace

from backtest import ema_vwap_research as research


def test_release_completed_configurations_preserves_complete_report(monkeypatch, tmp_path):
    runner = research.run_dataset
    ns = runner.__globals__
    monkeypatch.setitem(ns, "indicators", lambda path: object())
    monkeypatch.setitem(ns, "_option_specs", lambda path: [])

    def signal_events(*args, **kwargs):
        key = "MACD" if kwargs["require_macd"] else "BASE"
        kwargs["signal_diagnostics"]["signals"] = 2
        if kwargs["decision_events"] is not None:
            kwargs["decision_events"].append({
                "stage": "SIGNAL", "reason": key,
            })
        return [
            SimpleNamespace(
                timestamp_ns=research.timestamp_ns(
                    f"2026-11-01T00:0{i}:00Z"
                ),
                option=SimpleNamespace(symbol=f"{key}-{i}"),
                direction="CALL", entry_type="BASELINE",
                ema_regime_start_ns=0, quotes=[], execution_attempt=None,
            )
            for i in (2, 4)
        ]

    def capture(path, events, **kwargs):
        for event in events:
            event.quotes = [{"bid": 1.0, "ask": 2.0}] * 20

    def simulate(event, frame, scenario, **kwargs):
        event.execution_attempt = {"symbol": event.option.symbol, "quantity": 5}
        return {
            "scenario": scenario.name, "symbol": event.option.symbol,
            "exit_time": "2026-11-01T00:03:00+00:00"
            if event.option.symbol.endswith("-2")
            else "2026-11-01T00:05:00+00:00",
            "exit_reason": "MAX_HOLD",
            "fees_usd": 0.02, "pnl_usd": 0.3,
        }, None

    monkeypatch.setitem(ns, "signal_events", signal_events)
    monkeypatch.setitem(ns, "capture_quotes", capture)
    monkeypatch.setitem(ns, "simulate_trade", simulate)
    scenarios = [
        research.Scenario("base-1", 1, "EMA"),
        research.Scenario("macd-1", 1, "EMA", require_macd=True),
        research.Scenario("base-2", 1, "EMA_VWAP"),
        research.Scenario("macd-2", 1, "EMA_VWAP", require_macd=True),
    ]
    common = dict(
        start="2026-11-01T00:00:00Z",
        end="2026-11-02T00:00:00Z",
        scenario_set=scenarios, quote_csv_parser="DICT",
    )
    original = runner(tmp_path, **common)
    released = runner(tmp_path, **common,
                      release_completed_configurations=True)
    assert released == original
    assert original["raw_signals_with_contract"] == released["raw_signals_with_contract"]
    assert len(released["trades"]) == 8
    assert len(released["execution_attempts"]) == 8
    assert len(released["decision_events"]) >= 8


def test_release_is_disabled_by_default():
    from inspect import signature
    assert signature(research.run_dataset).parameters[
        "release_completed_configurations"
    ].default is False
