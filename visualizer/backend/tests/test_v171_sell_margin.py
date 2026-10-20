from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.engine import _quantity
from app.margin import short_margin_details, short_margin_health
from app.models import StrategyConfig, SellMarginConfig


def _strategy(initial=20, maintenance=10, leverage=5):
    s=StrategyConfig()
    s.risk.sell_margin=SellMarginConfig(
        enabled=True,initial_margin_percent=initial,
        maintenance_margin_percent=maintenance,
        max_notional_leverage=leverage,
        collateral_buffer_percent=0,
    )
    s.risk.quantity_mode='FIXED'
    s.risk.quantity=1
    s.risk.budget_usd=10000
    s.risk.enforce_trade_budget_strict=False
    s.risk.starting_balance_usd=100
    return s


def _spec():
    return dict(contract_value=0.001,min_quantity=1,size_increment=1,price_increment=.1)


def test_disabled_margin_keeps_historical_short_check_without_claiming_collateral():
    s=StrategyConfig()
    assert not s.risk.sell_margin.enabled
    margin=short_margin_details(s.risk.sell_margin,spot=100000,premium=1000,
                                 quantity=1,contract_value=.001,entry_fee=.05)
    assert margin['initial_margin_usd'] is None
    assert margin['cash_required_usd']==pytest.approx(.05)


def test_leverage_cap_is_initial_collateral_floor_not_pnl_multiplier():
    s=_strategy(initial=10,maintenance=5,leverage=5)
    margin=short_margin_details(s.risk.sell_margin,100000,1000,1,.001,
                                 entry_fee=.05,estimated_exit_fee=.05)
    assert margin['notional_usd']==pytest.approx(100)
    assert margin['initial_margin_usd']==pytest.approx(20)
    assert margin['effective_leverage']==pytest.approx(5)
    assert margin['cash_required_usd']==pytest.approx(20.1)
    assert not margin['venue_verified']


def test_margin_enabled_rejects_underfunded_short_even_if_cash_check_disabled():
    s=_strategy(initial=50,maintenance=20,leverage=1)
    s.risk.enforce_cash=False
    qty,cost,reason=_quantity(s,_spec(),1000,100000,50,'SELL')
    assert qty==0
    assert cost>50
    assert reason=='INSUFFICIENT_SELL_MARGIN_ESTIMATE'


def test_margin_isolated_health_breaches_on_rising_ask_to_close():
    s=_strategy()
    details=short_margin_details(s.risk.sell_margin,100000,1000,1,.001)
    good=short_margin_health(s.risk.sell_margin,details,100,0,0,0)
    bad=short_margin_health(s.risk.sell_margin,details,100,0,-15,0)
    assert good['estimated_margin_buffer_usd']==pytest.approx(10)
    assert not good['breached']
    assert bad['breached']
    assert not bad['venue_verified']


def test_cross_assumed_equity_can_withstand_isolated_breach():
    s=_strategy()
    d=short_margin_details(s.risk.sell_margin,100000,1000,1,.001)
    s.risk.sell_margin.margin_mode='CROSS_ESTIMATE'
    health=short_margin_health(s.risk.sell_margin,d,100,0,-15,0)
    assert not health['breached']


def test_invalid_maintenance_and_missing_rates_fail_closed():
    with pytest.raises(ValidationError):
        SellMarginConfig(enabled=True,initial_margin_percent=20)
    with pytest.raises(ValidationError):
        SellMarginConfig(enabled=True,initial_margin_percent=10,maintenance_margin_percent=20)


def test_portfolio_mode_requires_manual_rates_and_forbids_fake_fixed_leverage():
    with pytest.raises(ValidationError, match="requires explicit initial"):
        SellMarginConfig(enabled=True,margin_mode='PORTFOLIO_ESTIMATE')
    with pytest.raises(ValidationError, match="no fixed leverage"):
        SellMarginConfig(
            enabled=True,margin_mode='PORTFOLIO_ESTIMATE',
            initial_margin_percent=20,maintenance_margin_percent=10,
            max_notional_leverage=5,
        )


def test_portfolio_mode_uses_pooled_account_proxy_not_isolated_collateral():
    s=_strategy(initial=20,maintenance=10,leverage=None)
    s.risk.sell_margin.margin_mode='PORTFOLIO_ESTIMATE'
    m=short_margin_details(s.risk.sell_margin,100000,1000,1,.001)
    assert m['mode']=='PORTFOLIO_ESTIMATE'
    assert m['initial_margin_usd']==pytest.approx(20)
    assert m['venue_verified'] is False
    assert m['portfolio_stress_scenarios_computed'] is False
    h=short_margin_health(s.risk.sell_margin,m,100,0,-15,0)
    assert h['breached'] is False
    assert 'MANUAL_PORTFOLIO_PROXY' in h['assumption']


def test_portfolio_mode_roundtrips_strategy_json_without_changing_signals():
    s=StrategyConfig()
    s.risk.sell_margin=SellMarginConfig(
        enabled=True,margin_mode='PORTFOLIO_ESTIMATE',
        initial_margin_percent=20,maintenance_margin_percent=10,
    )
    exported=s.model_dump(mode='json')
    restored=StrategyConfig.model_validate(exported)
    assert restored.risk.sell_margin.margin_mode=='PORTFOLIO_ESTIMATE'
    assert restored.call_entry==s.call_entry
    assert restored.put_entry==s.put_entry
    assert restored.risk.sell_margin.max_notional_leverage is None


def test_buy_premium_cost_unchanged_when_sell_margin_enabled():
    s=_strategy()
    s.risk.quantity=1
    _,buy_cost,why=_quantity(s,_spec(),1000,100000,100,'BUY')
    assert why is None
    assert buy_cost>1
    _,sell_cost,why=_quantity(s,_spec(),1000,100000,100,'SELL')
    assert why is None
    assert sell_cost>buy_cost
