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


def test_actual_report_spot_does_not_trade_64600_when_64200_history_is_missing():
    """16 Nov case: spot 64166.5; 64600 is not a valid ATM substitute."""
    s = settings()
    inst = pd.DataFrame([
        contract("missing-target-neighbor-64600", 64600, 2),
        contract("missing-target-neighbor-64800", 64800, 2),
        contract("later-65000", 65000, 3),
    ])
    store = QuoteStore({row["symbol"] for row in inst.to_dict("records")})
    spec, quote, why = _select_option(store, [], inst, AT, 64166.5, "CALL", s)
    assert spec is None and quote is None
    assert why == "TARGET_STRIKE_NOT_IN_ARCHIVE"
    assert store.seen == []


def test_actual_report_spot_uses_64200_later_expiry_when_available():
    s = settings()
    inst = pd.DataFrame([
        contract("early-64600", 64600, 2),
        contract("early-64800", 64800, 2),
        contract("later-64200", 64200, 3),
        contract("later-64600", 64600, 3),
    ])
    store = QuoteStore({row["symbol"] for row in inst.to_dict("records")})
    spec, quote, why = _select_option(store, [], inst, AT, 64166.5, "CALL", s)
    assert spec["symbol"] == "later-64200"
    assert why == ""


def test_full_product_reference_can_lock_target_absent_from_quoted_instruments():
    s = settings()
    executable = pd.DataFrame([
        contract("only-64600", 64600, 2),
        contract("only-64800", 64800, 2),
    ])
    metadata = pd.DataFrame([
        contract("full-chain-64200", 64200, 2),
        contract("full-chain-64600", 64600, 2),
        contract("full-chain-64800", 64800, 2),
    ])
    store = QuoteStore({"only-64600", "only-64800"})
    spec, quote, why = _select_option(store, [], executable, AT, 64200, "CALL", s,
                                      strike_reference=metadata)
    assert spec is None and quote is None
    assert why == "TARGET_STRIKE_NOT_IN_ARCHIVE"
    assert store.seen == []


def test_full_cached_product_listing_preserves_missing_contract_metadata(tmp_path):
    import json
    from types import SimpleNamespace
    from app.option_chain import load_strike_reference

    root = tmp_path / "segment"
    products = root / "raw" / "products"
    products.mkdir(parents=True)
    (products / "BTC-2026-11-18.json").write_text(json.dumps({
        "products": [{
            "symbol": "C-BTC-64200-181126",
            "strike_price": 64200,
            "contract_type": "call_options",
            "underlying_asset": {"symbol": "BTC"},
            "launch_time": (AT - pd.Timedelta(days=1)).isoformat(),
            "settlement_time": (AT + pd.Timedelta(days=2)).isoformat(),
        }]
    }), encoding="utf-8")
    normalized = pd.DataFrame([contract("quoted-64600", 64600, 2)])
    ref, full = load_strike_reference([SimpleNamespace(root=root)], normalized)
    assert full is True
    assert set(ref.strike) == {64200, 64600}
    s = settings()
    ranked = _select_candidates(normalized, AT, 64200, "CALL", s.option, ref)
    assert ranked.empty
