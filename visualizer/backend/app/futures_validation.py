"""Milestone 5 frozen-strategy historical futures validation.

Runs genuine Strategy Lab backtests against the user's selected archive.
NEVER invents datasets or market performance results.
"""
from __future__ import annotations
from datetime import timedelta
from .models import BacktestRequest, FuturesValidationRequest
from .research import _parse_dt, _iso, _robustness
from .engine import run_backtest
from .robustness_v163 import analyze_trade_robustness


def _trade_report(result):
    trades=result.get('trades') or []
    stats=analyze_trade_robustness(trades)
    metrics=result['metrics']
    return {
        'run_id':result['run_id'],
        'trades':len(trades),
        'net_closed_usd':metrics.get('net_pnl_usd'),
        'gross_usd':metrics.get('gross_pnl_usd'),
        'fees_including_gst_usd':metrics.get('fees_usd'),
        'funding_usd':metrics.get('funding_usd'),
        'profit_factor':metrics.get('profit_factor'),
        'closed_trade_drawdown_usd':metrics.get('max_closed_trade_drawdown_usd'),
        'estimated_candle_close_drawdown_usd':metrics.get('estimated_candle_close_drawdown_usd'),
        'estimated_candle_close_drawdown_percent':metrics.get('estimated_candle_close_drawdown_percent'),
        'unresolved_position':bool(result.get('unresolved_position')),
        'best_trade_removed_net_usd':stats.get('net_excluding_best_usd'),
        'top_three_removed_net_usd':stats.get('net_excluding_top_3_usd'),
        'bootstrap_sample_warning':stats.get('status'),
        'reliability_grade':(result.get('reliability') or {}).get('grade'),
    }


def run_futures_validation(req:FuturesValidationRequest, progress=None):
    start,end=_parse_dt(req.start),_parse_dt(req.end)
    if end<=start:
        raise ValueError('Validation period end must exceed start')
    minutes={'5m':5,'10m':10,'15m':15,'30m':30,'1h':60}[req.strategy.timeframe]
    total=int((end-start).total_seconds()//(minutes*60))
    train_bars=int(total*req.train_fraction)
    if train_bars<30 or total-train_bars-req.embargo_bars<30:
        raise ValueError('Validation requires >=30 strategy candles in each nonoverlapping period')
    train_end=start+timedelta(minutes=train_bars*minutes)
    test_start=train_end+timedelta(minutes=req.embargo_bars*minutes)
    selection=req.model_dump(include={'dataset_mode','dataset_id','dataset_ids','auto_download_missing_data'})
    # No optimization: the *same frozen* strategy is used on both periods.
    phases=[
        ('train',start,train_end,req.strategy),
        ('holdout',test_start,end,req.strategy),
    ]
    stressed=req.strategy.model_copy(deep=True)
    stressed.futures.slippage_bps+=req.stress_extra_slippage_bps
    stressed.futures.taker_fee_percent*=req.stress_fee_multiplier
    phases.append(('holdout_stressed',test_start,end,stressed))
    rows={}
    for index,(name,lo,hi,strategy) in enumerate(phases):
        if progress:
            progress(f'Futures validation {name}: starting',100*index/len(phases),'FUTURES_VALIDATION','Run strictly historical backtest')
        case=BacktestRequest(**selection,start=_iso(lo),end=_iso(hi),strategy=strategy,
                             storage_mode='COMPACT',bar_gap_policy='REQUIRE')
        result=run_backtest(case,
            (lambda msg,pct=None,stage=None,next_step=None:
                progress(f'{name}: {msg}',100*(index+(pct or 0)/100)/len(phases),'FUTURES_VALIDATION',next_step or 'Next checkpoint'))
            if progress else None)
        rows[name]={**_trade_report(result),'start':_iso(lo),'end':_iso(hi),
                    'monthly':_robustness(result,_iso(lo),_iso(hi))}
    baseline=rows['holdout'];stress=rows['holdout_stressed']
    warnings=[]
    for name in ('train','holdout','holdout_stressed'):
        report=rows[name]
        if report['trades']<30:
            warnings.append(f"{name}: fewer than 30 closed trades; sample too small for confidence")
        if report['unresolved_position']:
            warnings.append(f"{name}: open position unresolved; closed-trade net excludes it")
        if report['reliability_grade']!='RESEARCH_ONLY':
            warnings.append(f"{name}: inspect unexpected reliability grade")
    if progress:progress('Futures historical validation completed',100,'COMPLETE','Inspect holdout robustness')
    return {'kind':'FUTURES_HISTORICAL_VALIDATION','research_only':True,
            'data_status':'ACTUAL_SELECTED_HISTORY_BACKTESTED',
            'strategy_frozen':True,'embargo_bars':req.embargo_bars,
            'train':rows['train'],'holdout':baseline,'holdout_stressed':stress,
            'holdout_stress_net_delta_usd':(stress['net_closed_usd'] or 0)-(baseline['net_closed_usd'] or 0),
            'warnings':warnings,
            'note':'No model selection or parameter fitting used the holdout. Net profit, fees, funding,'
                   ' outlier dependence and candle-close drawdown are hypothetical research estimates;'
                   ' missing funding and exchange-accurate fills remain material uncertainties.'}
