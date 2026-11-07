"""Portfolio research validation: no invented fills, cash, margin or correlation."""
from datetime import datetime, timedelta, timezone
import pytest
from pydantic import ValidationError

from app.portfolio_research import (
    PortfolioResearchRequest, PortfolioRun, LabeledInterval, UniverseMembership,
    analyze_portfolio_runs,
)

UTC = timezone.utc


def request(**override):
    args = dict(runs=[
        PortfolioRun(run_id="one", capital_fraction=0.5),
        PortfolioRun(run_id="two", capital_fraction=0.5),
    ], initial_cash_usd=1000.0, margin_safety_multiplier=1,
        max_parallel_positions=2, minimum_correlation_days=3)
    args.update(override)
    return PortfolioResearchRequest(**args)


def sample(run_id, trades, start="2026-09-01T00:00:00Z", end="2026-09-20T00:00:00Z"):
    return {
        "run_id": run_id, "start": start, "end": end, "storage_mode": "COMPACT",
        "strategy": {"market_type": "FUTURES", "futures": {
            "leverage": 5, "funding_mode": "EXCLUDE_WITH_WARNING"}},
        "reliability": {"grade": "RESEARCH_ONLY"},
        "unresolved_position": None,
        "metrics": {"net_pnl_usd": sum(t["net_pnl_usd"] for t in trades)},
        "trades": trades,
    }


def trade(start, end, pnl, *, symbol="BTCUSD", direction="LONG", qty=0.01,
          fee=1.0, price=10000):
    return {
        "entry_time": start, "exit_time": end, "net_pnl_usd": pnl,
        "symbol": symbol, "direction": direction, "quantity": qty,
        "entry_price": price, "entry_fee_usd": fee, "funding_usd": 0.0,
    }


def test_nonoverlap_accounting_and_cash_reconciliation():
    a = [trade("2026-09-01T00:00:00Z", "2026-09-01T01:00:00Z", 100)]
    b = [trade("2026-09-02T00:00:00Z", "2026-09-02T01:00:00Z", -30)]
    result = analyze_portfolio_runs([sample("one", a), sample("two", b)], request())
    assert result["accepted_trades"] == 2
    assert result["net_realized_pnl_usd"] == pytest.approx(70)
    assert result["ending_realized_cash_usd"] == pytest.approx(1070)
    assert result["source_trade_count"] == 2
    assert result["research_only"]


def test_same_symbol_blocked_and_opt_in_allow():
    a = [trade("2026-09-01T00:00:00Z", "2026-09-01T03:00:00Z", 10)]
    b = [trade("2026-09-01T01:00:00Z", "2026-09-01T02:00:00Z", 30,
               direction="SHORT")]
    blocked = analyze_portfolio_runs([sample("one", a), sample("two", b)], request())
    assert blocked["accepted_trades"] == 1
    assert blocked["rejected_trades_by_reason"]["SAME_SYMBOL_BLOCKED"] == 1
    allow = analyze_portfolio_runs([sample("one", a), sample("two", b)],
                                   request(symbol_conflict_policy="ALLOW"))
    assert allow["accepted_trades"] == 2
    assert allow["net_realized_pnl_usd"] == pytest.approx(40)


def test_margin_safety_fails_closed():
    a = [trade("2026-09-01T00:00:00Z", "2026-09-01T03:00:00Z", 10,
               qty=2)]
    out = analyze_portfolio_runs([sample("one", a), sample("two", [])], request())
    assert out["accepted_trades"] == 0
    assert out["rejected_trades_by_reason"]["INSUFFICIENT_ESTIMATED_FREE_CASH"] == 1


def test_reject_non_futures_and_unresolved():
    run = sample("one", [])
    run["strategy"]["market_type"] = "OPTIONS"
    with pytest.raises(ValueError, match="FUTURES"):
        analyze_portfolio_runs([run, sample("two", [])], request())
    run = sample("one", [])
    run["unresolved_position"] = {"quantity": 0.01}
    with pytest.raises(ValueError, match="unresolved"):
        analyze_portfolio_runs([run, sample("two", [])], request())


def test_missing_funding_explicitly_warned():
    result = analyze_portfolio_runs([sample("one", []), sample("two", [])], request())
    assert any("funding excluded" in x for x in result["warnings"])


def test_mismatched_period_fails_closed():
    with pytest.raises(ValueError, match="same start/end"):
        analyze_portfolio_runs([
            sample("one", []), sample("two", [], end="2026-09-21T00:00:00Z"),
        ], request())


def test_point_in_time_membership_blocks_outside_window():
    a = [trade("2026-09-01T01:00:00Z", "2026-09-01T03:00:00Z", 10)]
    params = request(universe_memberships=[UniverseMembership(
        symbol="BTCUSD", start=datetime(2026, 9, 2, tzinfo=UTC),
        end=datetime(2026, 9, 10, tzinfo=UTC))])
    out = analyze_portfolio_runs([sample("one", a), sample("two", [])], params)
    assert out["rejected_trades_by_reason"]["OUTSIDE_POINT_IN_TIME_UNIVERSE"] == 1


def test_regime_labels_are_entry_time_based():
    a = [trade("2026-09-01T01:00:00Z", "2026-09-03T01:00:00Z", 10)]
    params = request(regime_intervals=[LabeledInterval(
        start=datetime(2026, 9, 1, tzinfo=UTC),
        end=datetime(2026, 9, 2, tzinfo=UTC), label="TREND")])
    out = analyze_portfolio_runs([sample("one", a), sample("two", [])], params)
    assert out["regime_results"]["TREND"]["net_pnl_usd"] == 10


def test_bad_inputs_rejected():
    with pytest.raises(ValidationError, match="total at most 1"):
        request(runs=[PortfolioRun(run_id="one", capital_fraction=0.8),
                      PortfolioRun(run_id="two", capital_fraction=0.8)])
    with pytest.raises(ValidationError, match="unique"):
        request(runs=[PortfolioRun(run_id="one", capital_fraction=0.5),
                      PortfolioRun(run_id="one", capital_fraction=0.5)])
    with pytest.raises(ValueError, match="does not reconcile"):
        run = sample("one", [trade("2026-09-01T01:00:00Z", "2026-09-01T02:00:00Z", 3)])
        run["metrics"]["net_pnl_usd"] = 100
        analyze_portfolio_runs([run, sample("two", [])], request())


def test_daily_close_correlation():
    # Opposite realized returns on independent days imply negative correlation.
    one = [
        trade("2026-09-01T00:00:00Z", "2026-09-01T02:00:00Z", 10),
        trade("2026-09-02T00:00:00Z", "2026-09-02T02:00:00Z", -10),
    ]
    two = [
        trade("2026-09-01T00:00:00Z", "2026-09-01T02:00:00Z", -10),
        trade("2026-09-02T00:00:00Z", "2026-09-02T02:00:00Z", 10),
    ]
    result = analyze_portfolio_runs([sample("one", one), sample("two", two)],
                                    request(symbol_conflict_policy="ALLOW"))
    assert result["source_daily_realized_pnl_correlation"]["one"]["two"] == pytest.approx(-1)
