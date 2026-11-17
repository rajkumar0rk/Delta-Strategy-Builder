"""Backtest option selection locks strike before attempting later expiries."""
import pandas as pd
import pytest

from app.engine import _select_candidates, _select_option
from app.models import StrategyConfig


AT = pd.Timestamp("2026-11-16T09:00:00Z")


def contract(symbol, strike, expiry_days, option_type="CE", *, activation_days=-1):
    return {
        "symbol": symbol,
        "strike": strike,
        "option_type": option_type,
        "activation": AT + pd.Timedelta(days=activation_days),
        "expiration": AT + pd.Timedelta(days=expiry_days),
    }


def settings(direction="CALL", mode="ATM", steps=0):
    s = StrategyConfig()
    s.option.strike_mode = mode
    s.option.strike_steps = steps
    s.option.min_dte_days = 0
    s.option.max_dte_days = 5
    s.option.max_spread_percent = 5
    s.session.timezone = "UTC"
    s.session.start = "00:00"
    s.session.end = "23:59"
    s.session.blocked_weekdays = []
    return s


class QuoteStore:
    def __init__(self, eligible):
        self.eligible = eligible
        self.seen = []

    def first_quote_many(self, parts, symbol, at, delay):
        self.seen.append(symbol)
        if symbol not in self.eligible:
            return None
        return dict(timestamp=AT.isoformat(), bid=99.9, ask=100.0,
                    volume=1000, open_interest=1000)


def test_same_strike_later_expiry_when_nearest_expiry_lacks_target():
    s = settings()
    inst = pd.DataFrame([
        contract("early-64600", 64600, 2),
        contract("later-64200", 64200, 3),
        contract("later-64600", 64600, 3),
    ])
    store = QuoteStore({"early-64600", "later-64200", "later-64600"})
    spec, quote, reason = _select_option(store, [], inst, AT, 64200, "CALL", s)
    assert spec["symbol"] == "later-64200"
    assert store.seen == ["later-64200"]
    assert quote is not None and reason == ""


def test_missing_first_quote_falls_back_to_same_strike_next_expiry():
    s = settings()
    inst = pd.DataFrame([
        contract("early-64200", 64200, 2),
        contract("early-64600", 64600, 2),
        contract("later-64200", 64200, 3),
    ])
    store = QuoteStore({"early-64600", "later-64200"})
    spec, quote, reason = _select_option(store, [], inst, AT, 64200, "CALL", s)
    assert spec["symbol"] == "later-64200"
    assert store.seen == ["early-64200", "later-64200"]
    assert quote is not None and reason == ""


def test_no_quote_for_locked_strike_rejects_instead_of_changing_strike():
    s = settings()
    inst = pd.DataFrame([
        contract("early-64200", 64200, 2),
        contract("early-64600", 64600, 2),
        contract("later-64200", 64200, 3),
    ])
    store = QuoteStore({"early-64600"})
    spec, quote, reason = _select_option(store, [], inst, AT, 64200, "CALL", s)
    assert spec is None and quote is None and reason == "NO_FRESH_QUOTE"
    assert store.seen == ["early-64200", "later-64200"]


@pytest.mark.parametrize("direction,mode,steps,expected", [
    ("CALL", "ATM", 0, 64200),
    ("CALL", "ITM", 1, 64000),
    ("CALL", "OTM", 1, 64600),
    ("PUT", "ITM", 1, 64600),
    ("PUT", "OTM", 1, 64000),
])
def test_strike_modes_are_locked_across_expiries(direction, mode, steps, expected):
    s = settings(direction, mode, steps)
    typ = "CE" if direction == "CALL" else "PE"
    inst = pd.DataFrame([
        contract(f"early-{strike}", strike, 2, typ)
        for strike in (64000, 64200, 64600)
    ] + [
        contract(f"later-{strike}", strike, 3, typ)
        for strike in (64000, 64200, 64600)
    ])
    ranked = _select_candidates(inst, AT, 64200, direction, s.option)
    assert set(ranked.strike) == {expected}
    assert list(ranked.symbol) == [f"early-{expected}", f"later-{expected}"]


def test_ignore_expired_not_yet_active_or_out_of_dte_strikes():
    s = settings()
    s.option.max_dte_days = 3
    inst = pd.DataFrame([
        contract("expired-64200", 64200, -1),
        contract("inactive-64200", 64200, 2, activation_days=1),
        contract("too-late-64200", 64200, 4),
        contract("eligible-64600", 64600, 2),
        contract("eligible-64600-later", 64600, 3),
    ])
    ranked = _select_candidates(inst, AT, 64200, "CALL", s.option)
    assert list(ranked.symbol) == ["eligible-64600", "eligible-64600-later"]
