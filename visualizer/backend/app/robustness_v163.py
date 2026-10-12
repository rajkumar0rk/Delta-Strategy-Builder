"""V16.3 deterministic research-only trade sequence robustness diagnostics.

Bootstraps observed closed-trade returns. It cannot establish a distribution of
future trades or account for changing market regimes or unresolved positions.
"""
from __future__ import annotations
import random
import math
from typing import Any

def _quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    x = fraction * (len(ordered)-1)
    low = math.floor(x)
    upper = math.ceil(x)
    return ordered[low] * (upper-x) + ordered[upper] * (x-low) if low != upper else ordered[low]

def _drawdown(pnls: list[float]) -> float:
    equity = 0.0
    top = 0.0
    worst = 0.0
    for pnl in pnls:
        equity += pnl
        top = max(top,equity)
        worst = max(worst,top-equity)
    return worst

def analyze_trade_robustness(trades: list[dict[str, Any]], *, simulations: int = 1000, seed: int = 163) -> dict[str, Any]:
    if not 100 <= simulations <= 10000:
        raise ValueError('simulations must be between 100 and 10000')
    ordered = sorted(trades,key=lambda row: str(row.get('exit_time') or row.get('entry_time') or ''))
    pnls = [float(t['net_pnl_usd']) for t in ordered if t.get('net_pnl_usd') is not None]
    if any(not math.isfinite(x) for x in pnls):
        raise ValueError('Trade P&L must be finite')
    count = len(pnls)
    net = sum(pnls)
    if not count:
        return {'kind':'TRADE_BOOTSTRAP','research_only':True,'closed_trades':0,
                'status':'INSUFFICIENT_TRADES','simulations':0,
                'note':'No closed trades to sample. No forecast can be inferred.'}
    rand = random.Random(seed)
    totals=[]
    drawdowns=[]
    loss_counts=0
    for _ in range(simulations):
        sample = [pnls[rand.randrange(count)] for _ in range(count)]
        total = sum(sample)
        totals.append(total)
        drawdowns.append(_drawdown(sample))
        if total < 0:
            loss_counts += 1
    winners=sorted(((i,x) for i,x in enumerate(pnls)),key=lambda item:(-item[1],item[0]))
    top_indices={i for i,_ in winners[:min(3,count)]}
    without_top=sum(x for i,x in enumerate(pnls) if i not in top_indices)
    top_one=max(pnls)
    top_three=sum(x for _,x in winners[:3])
    return {
        'kind':'TRADE_BOOTSTRAP',
        'research_only':True,
        'status':'LOW_SAMPLE_WARNING' if count < 30 else 'MODELED_SCENARIOS',
        'closed_trades':count,
        'simulations':simulations,
        'seed':seed,
        'historical_net_pnl_usd':net,
        'historical_max_closed_trade_drawdown_usd':_drawdown(pnls),
        'bootstrap_net_pnl_usd_p05':_quantile(totals,0.05),
        'bootstrap_net_pnl_usd_median':_quantile(totals,0.50),
        'bootstrap_net_pnl_usd_p95':_quantile(totals,0.95),
        'bootstrap_max_drawdown_usd_p95':_quantile(drawdowns,0.95),
        'bootstrap_negative_net_frequency_percent':loss_counts/simulations*100,
        'best_trade_usd':top_one,
        'top_3_trades_pnl_usd':top_three,
        'net_excluding_best_usd':net-top_one,
        'net_excluding_top_3_usd':without_top,
        'top_3_share_of_positive_pnl_percent':(
            top_three/sum(max(0,x) for x in pnls)*100
            if sum(max(0,x) for x in pnls)>0 else None
        ),
        'note':('Independent resampling of the same closed-trade P&L sample, '
                'not an out-of-sample simulation or probability of future profit. '
                'Does not price unresolved/expired positions, quote gaps, or new executions.'),
    }
