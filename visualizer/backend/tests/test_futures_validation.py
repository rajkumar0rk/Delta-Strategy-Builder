from __future__ import annotations

import pytest
from pydantic import ValidationError
from app.models import FuturesValidationRequest, StrategyConfig
from app.futures_validation import run_futures_validation


def _request(**overrides):
    strategy=StrategyConfig(market_type='FUTURES')
    strategy.futures.funding_mode='EXCLUDE_WITH_WARNING'
    return FuturesValidationRequest(dataset_id='sample',start='2026-01-01T00:00:00Z',
        end='2026-01-10T00:00:00Z',strategy=strategy,**overrides)


def test_validation_rejects_option_market():
    with pytest.raises(ValidationError):
        FuturesValidationRequest(dataset_id='sample',start='2026-01-01T00:00:00Z',
            end='2026-01-10T00:00:00Z',strategy=StrategyConfig())


def test_validation_keeps_holdout_frozen_and_excludes_overlap(monkeypatch):
    calls=[]
    def fake_run(req,progress=None):
        calls.append(req)
        if progress:progress('done',100,'BACKTEST','finish')
        return {'run_id':str(len(calls)), 'trades':[],
                'metrics':{'net_pnl_usd':0,'gross_pnl_usd':0,'fees_usd':0,
                           'profit_factor':None,'funding_usd':0,
                           'max_closed_trade_drawdown_usd':0,
                           'estimated_candle_close_drawdown_usd':0,
                           'estimated_candle_close_drawdown_percent':0},
                'reliability':{'grade':'RESEARCH_ONLY'},'unresolved_position':None}
    monkeypatch.setattr('app.futures_validation.run_backtest',fake_run)
    req=_request()
    result=run_futures_validation(req)
    assert len(calls)==3
    assert calls[0].end<calls[1].start
    assert calls[1].start==calls[2].start
    assert calls[1].end==calls[2].end
    assert calls[0].strategy.model_dump()==calls[1].strategy.model_dump()
    assert calls[2].strategy.futures.slippage_bps==pytest.approx(
        calls[1].strategy.futures.slippage_bps+5)
    assert calls[2].strategy.futures.taker_fee_percent==pytest.approx(
        calls[1].strategy.futures.taker_fee_percent*1.5)
    assert all(c.storage_mode=='COMPACT' and c.bar_gap_policy=='REQUIRE' for c in calls)
    assert result['strategy_frozen'] is True
    assert result['holdout_stress_net_delta_usd']==0
    assert result['warnings']
    assert req.strategy.futures.slippage_bps==2


def test_validation_fails_for_short_coverage():
    req=_request()
    req.end='2026-01-01T01:00:00Z'
    with pytest.raises(ValueError,match='30 strategy candles'):
        run_futures_validation(req)
