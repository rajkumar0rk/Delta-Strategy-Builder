from __future__ import annotations
import itertools, json, statistics
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable
from .models import ResearchSweepRequest, AblationRequest, StrategyConfig, BacktestRequest, ExecutionReplayRequest, HoldoutResearchRequest
from .engine import run_backtest
from .config import result_root
from .robustness_v163 import analyze_trade_robustness

UTC = timezone.utc


def _walk_conditions(group: dict[str, Any]):
    for condition in group.get('conditions', []) or []:
        yield condition
    for child in group.get('groups', []) or []:
        yield from _walk_conditions(child)


def _find_condition(group: dict[str, Any], condition_id: str) -> dict[str, Any] | None:
    for condition in _walk_conditions(group):
        if str(condition.get('id')) == condition_id:
            return condition
    return None


def _set_path(strategy: dict[str, Any], path: str, value: float) -> None:
    if path.startswith('indicator:'):
        _, indicator_id, param = path.split(':', 2)
        item = next((x for x in strategy.get('indicators', []) if x.get('id') == indicator_id), None)
        if item is None:
            raise ValueError(f'Unknown indicator in sweep path: {indicator_id}')
        current = item.setdefault('params', {}).get(param)
        item['params'][param] = int(value) if isinstance(current, int) and not isinstance(current, bool) else float(value)
        return
    if path.startswith('condition:'):
        _, scope, condition_id, field = path.split(':', 3)
        if scope not in {'call_entry','put_entry','call_exit','put_exit','no_trade'}:
            raise ValueError(f'Unsupported condition scope: {scope}')
        condition = _find_condition(strategy[scope], condition_id)
        if condition is None:
            raise ValueError(f'Unknown condition in sweep path: {condition_id}')
        condition[field] = float(value)
        return
    parts = path.split('.')
    node: Any = strategy
    for part in parts[:-1]:
        if isinstance(node, dict):
            if part not in node:
                raise ValueError(f'Unknown sweep path: {path}')
            node = node[part]
        elif isinstance(node, list) and part.isdigit():
            index = int(part)
            if index < 0 or index >= len(node):
                raise ValueError(f'Unknown sweep path: {path}')
            node = node[index]
        else:
            raise ValueError(f'Unknown sweep path: {path}')
    leaf = parts[-1]
    if isinstance(node, dict):
        if leaf not in node:
            raise ValueError(f'Unknown sweep path: {path}')
        current = node[leaf]
        node[leaf] = int(value) if isinstance(current, int) and not isinstance(current, bool) else float(value)
    elif isinstance(node, list) and leaf.isdigit():
        index = int(leaf)
        current = node[index]
        node[index] = int(value) if isinstance(current, int) and not isinstance(current, bool) else float(value)
    else:
        raise ValueError(f'Unknown sweep path: {path}')


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace('+00:00', 'Z')


def _month_keys(start: str, end: str) -> list[str]:
    cur = _parse_dt(start).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    stop = _parse_dt(end)
    out: list[str] = []
    while cur < stop:
        out.append(f'{cur:%Y-%m}')
        cur = cur.replace(year=cur.year + 1, month=1) if cur.month == 12 else cur.replace(month=cur.month + 1)
    return out


def _robustness(result: dict[str, Any], start: str, end: str) -> dict[str, Any]:
    months = _month_keys(start, end)
    pnl = {m: 0.0 for m in months}
    for trade in result.get('trades', []) or []:
        key = str(trade.get('entry_time') or '')[:7]
        if key in pnl:
            pnl[key] += float(trade.get('net_pnl_usd') or 0.0)
    values = list(pnl.values())
    positive = sum(v > 1e-12 for v in values)
    negative = sum(v < -1e-12 for v in values)
    return {
        'months_tested': len(values),
        'positive_months': positive,
        'negative_months': negative,
        'flat_months': len(values) - positive - negative,
        'positive_month_ratio': (positive / len(values) * 100.0 if values else 0.0),
        'worst_month_net_pnl_usd': (min(values) if values else 0.0),
        'best_month_net_pnl_usd': (max(values) if values else 0.0),
        'median_month_net_pnl_usd': (statistics.median(values) if values else 0.0),
        'monthly_net_pnl': pnl,
    }


def _strategy_for_combo(base: StrategyConfig, dimensions, combo) -> tuple[StrategyConfig, dict[str, float]]:
    payload = base.model_dump(mode='json')
    labels: dict[str, float] = {}
    for dimension, value in zip(dimensions, combo):
        _set_path(payload, dimension.path, value)
        labels[dimension.path] = value
    return StrategyConfig.model_validate(payload), labels


def _score_metrics(metrics: dict[str, Any]) -> tuple[float, float, float]:
    # Prefer net P&L, then PF, then smaller drawdown. This is deliberately simple
    # and visible; V7 never hides an opaque optimization objective from the user.
    net = float(metrics.get('net_pnl_usd') or 0.0)
    pf = float(metrics.get('profit_factor') or 0.0)
    dd = float(metrics.get('max_closed_trade_drawdown_usd') or 0.0)
    return net, pf, -dd


def _walk_forward(req: ResearchSweepRequest, combos: list[tuple[float, ...]], progress: Callable[[str], None] | None = None) -> dict[str, Any] | None:
    folds = int(req.walk_forward_folds or 0)
    if folds < 2:
        return None
    if len(combos) > 20:
        raise ValueError('Walk-forward validation is limited to 20 parameter combinations per sweep to keep runtime bounded.')
    start = _parse_dt(req.start)
    end = _parse_dt(req.end)
    total = (end - start).total_seconds()
    if total <= 0:
        raise ValueError('Invalid walk-forward date range')
    # One initial training block + N forward test blocks.
    boundaries = [start + (end - start) * (i / (folds + 1)) for i in range(folds + 2)]
    fold_rows: list[dict[str, Any]] = []
    selected_test_trades: list[dict[str, Any]] = []
    for fold in range(1, folds + 1):
        train_start, train_end = boundaries[0], boundaries[fold]
        test_start, test_end = boundaries[fold], boundaries[fold + 1]
        # Embargo is a temporal gap between training and holdout evaluation;
        # it must never be used in either period's strategy selection.
        test_start += timedelta(
            minutes={'5m':5,'10m':10,'15m':15,'30m':30,'1h':60}[req.strategy.timeframe]
            * req.walk_forward_embargo_bars,
        )
        if test_start >= test_end:
            raise ValueError('Walk-forward embargo consumes the entire test fold')
        candidates: list[dict[str, Any]] = []
        for index, combo in enumerate(combos, start=1):
            if progress:
                progress(f'Walk-forward fold {fold}/{folds}: training candidate {index}/{len(combos)}…')
            strategy, labels = _strategy_for_combo(req.strategy, req.dimensions, combo)
            train = run_backtest(BacktestRequest(dataset_id=req.dataset_id, start=_iso(train_start), end=_iso(train_end), strategy=strategy, storage_mode='COMPACT'))
            candidates.append({'strategy': strategy, 'parameters': labels, 'metrics': train['metrics'], 'run_id': train['run_id'], 'cache_hit': bool(train.get('cache_hit'))})
        best = max(candidates, key=lambda x: _score_metrics(x['metrics']))
        if progress:
            progress(f'Walk-forward fold {fold}/{folds}: testing selected training winner on unseen next block…')
        test = run_backtest(BacktestRequest(dataset_id=req.dataset_id, start=_iso(test_start), end=_iso(test_end), strategy=best['strategy'], storage_mode='COMPACT'))
        selected_test_trades.extend(test.get('trades', []) or [])
        fold_rows.append({
            'fold': fold,
            'train_start': _iso(train_start),
            'train_end': _iso(train_end),
            'test_start': _iso(test_start),
            'test_end': _iso(test_end),
            'selected_parameters': best['parameters'],
            'train_metrics': best['metrics'],
            'test_metrics': test['metrics'],
            'train_run_id': best['run_id'],
            'test_run_id': test['run_id'],
            'test_cache_hit': bool(test.get('cache_hit')),
        })
    wins = sum(float(t.get('net_pnl_usd') or 0.0) > 0 for t in selected_test_trades)
    losses = sum(float(t.get('net_pnl_usd') or 0.0) < 0 for t in selected_test_trades)
    gp = sum(max(0.0, float(t.get('net_pnl_usd') or 0.0)) for t in selected_test_trades)
    gl = -sum(min(0.0, float(t.get('net_pnl_usd') or 0.0)) for t in selected_test_trades)
    nets = [float(x['test_metrics'].get('net_pnl_usd') or 0.0) for x in fold_rows]
    return {
        'folds': fold_rows,
        'summary': {
            'test_folds': len(fold_rows),
            'positive_test_folds': sum(v > 0 for v in nets),
            'net_pnl_usd': sum(nets),
            'worst_fold_net_pnl_usd': min(nets) if nets else 0.0,
            'best_fold_net_pnl_usd': max(nets) if nets else 0.0,
            'trades': len(selected_test_trades),
            'wins': wins,
            'losses': losses,
            'win_rate_percent': wins / len(selected_test_trades) * 100.0 if selected_test_trades else 0.0,
            'profit_factor': gp / gl if gl > 0 else None,
        },
    }


def run_sweep(req: ResearchSweepRequest, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    combos = list(itertools.product(*(d.values for d in req.dimensions)))
    if len(combos) > req.max_combinations:
        raise ValueError(f'Sweep creates {len(combos)} combinations; max is {req.max_combinations}')
    rows = []
    for index, combo in enumerate(combos, start=1):
        if progress:
            progress(f'Parameter sweep {index}/{len(combos)}…')
        strategy, labels = _strategy_for_combo(req.strategy, req.dimensions, combo)
        result = run_backtest(BacktestRequest(dataset_id=req.dataset_id, start=req.start, end=req.end, strategy=strategy, storage_mode='COMPACT'))
        rows.append({
            'parameters': labels,
            'run_id': result['run_id'],
            'cache_hit': bool(result.get('cache_hit')),
            'metrics': result['metrics'],
            'robustness': _robustness(result, req.start, req.end),
        })
    rows.sort(key=lambda x: ((x['robustness'].get('positive_month_ratio') or 0.0), (x['metrics'].get('net_pnl_usd') or 0.0), (x['metrics'].get('profit_factor') or 0.0)), reverse=True)
    walk_forward = _walk_forward(req, combos, progress)
    # Stability across nearby tested parameter cells; this is in-sample
    # descriptive robustness, not proof of generalization.
    finite_nets=[float(row['metrics'].get('net_pnl_usd') or 0) for row in rows]
    stability={
        'combinations':len(rows),
        'positive_fraction_percent':100*sum(x>0 for x in finite_nets)/len(finite_nets) if finite_nets else 0,
        'median_net_pnl_usd':statistics.median(finite_nets) if finite_nets else None,
        'worst_net_pnl_usd':min(finite_nets) if finite_nets else None,
        'best_net_pnl_usd':max(finite_nets) if finite_nets else None,
        'best_minus_median_usd':max(finite_nets)-statistics.median(finite_nets) if finite_nets else None,
        'note':'Describes all supplied parameter cells, not an independent holdout.',
    }
    return {
        'kind': 'PARAMETER_SWEEP',
        'parameter_stability':stability,
        'count': len(rows),
        'dimensions': [d.model_dump() for d in req.dimensions],
        'rows': rows,
        'walk_forward': walk_forward,
        'walk_forward_embargo_bars': req.walk_forward_embargo_bars,
    }


def _condition_uses(condition: dict[str, Any], indicator_id: str) -> bool:
    for ref in (condition.get('left'), condition.get('right')):
        if ref and str(ref).split('.', 1)[0] == indicator_id:
            return True
    return False


def _remove_indicator_conditions(group: dict[str, Any], indicator_id: str, removed_ids: set[str]) -> None:
    kept = []
    for c in group.get('conditions', []) or []:
        if _condition_uses(c, indicator_id):
            if c.get('id'):
                removed_ids.add(str(c['id']))
        else:
            kept.append(c)
    group['conditions'] = kept
    for child in group.get('groups', []) or []:
        _remove_indicator_conditions(child, indicator_id, removed_ids)


def run_ablation(req: AblationRequest, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    variants: list[tuple[str, StrategyConfig]] = [('FULL', req.strategy)]
    for indicator in req.strategy.indicators:
        if indicator.chart_only:
            continue
        payload = req.strategy.model_dump(mode='json')
        payload['indicators'] = [x for x in payload['indicators'] if x['id'] != indicator.id]
        removed_ids: set[str] = set()
        for scope in ('call_entry','put_entry','call_exit','put_exit','no_trade','call_no_trade','put_no_trade'):
            _remove_indicator_conditions(payload[scope], indicator.id, removed_ids)
        # Removing an indicator must not leave dangling alert identities or
        # condition references; legacy custom conditions are pruned as well.
        kept_alerts = []
        for alert in payload.get('alerts', []):
            if (alert.get('condition_id') in removed_ids or
                    str(alert.get('reset_operand') or '').split('.', 1)[0] == indicator.id):
                continue
            if alert.get('source') == 'LEGACY_CUSTOM':
                _remove_indicator_conditions(alert.get('conditions', {}), indicator.id, set())
            kept_alerts.append(alert)
        payload['alerts'] = kept_alerts
        for side in ('call','put'):
            for lifecycle in payload.get(f'{side}_entry_lifecycles', []):
                if lifecycle.get('trigger_condition_id') in removed_ids:
                    lifecycle['trigger_condition_id'] = None
            behavior = payload.get(f'{side}_entry_behavior', {})
            if behavior.get('trigger_condition_id') in removed_ids:
                behavior['trigger_condition_id'] = None
            score = payload.get(f'{side}_big_trend_score', {})
            score['components'] = [c for c in score.get('components', []) if c.get('condition_id') not in removed_ids]
            if score.get('enabled') and not score['components']:
                score['enabled'] = False
                payload.get(f'{side}_trend_phase', {})['enabled'] = False
            breakout = payload.get(f'{side}_breakout_retest', {})
            relevant = (breakout.get('breakout_condition_id') in removed_ids
                or any(str(breakout.get(key) or '').split('.', 1)[0] == indicator.id
                       for key in ('breakout_level_operand', 'atr_operand')))
            if relevant:
                breakout['enabled'] = False
        variants.append((f'WITHOUT {indicator.id}', StrategyConfig.model_validate(payload)))
    rows = []
    for index, (label, strategy) in enumerate(variants, start=1):
        if progress:
            progress(f'Indicator ablation {index}/{len(variants)}: {label}…')
        result = run_backtest(BacktestRequest(dataset_id=req.dataset_id, start=req.start, end=req.end, strategy=strategy, storage_mode='COMPACT'))
        rows.append({'variant': label, 'run_id': result['run_id'], 'cache_hit': bool(result.get('cache_hit')), 'metrics': result['metrics'], 'robustness': _robustness(result, req.start, req.end)})
    baseline = rows[0]['metrics'] if rows else {}
    for row in rows:
        row['delta_net_pnl_usd'] = (row['metrics'].get('net_pnl_usd') or 0.0) - (baseline.get('net_pnl_usd') or 0.0)
        pf = row['metrics'].get('profit_factor')
        base_pf = baseline.get('profit_factor')
        row['delta_profit_factor'] = None if pf is None or base_pf is None else pf - base_pf
    return {'kind': 'INDICATOR_ABLATION', 'count': len(rows), 'rows': rows}


def list_results(limit: int = 100) -> list[dict[str, Any]]:
    root = result_root()
    if not root.exists():
        return []
    rows = []
    for path in root.iterdir():
        summary = path / 'summary.json'
        if not summary.exists():
            continue
        try:
            data = json.loads(summary.read_text(encoding='utf-8'))
            rows.append({
                'run_id': data.get('run_id', path.name),
                'strategy_name': (data.get('strategy') or {}).get('name', ''),
                'dataset_id': data.get('dataset_id'),
                'start': data.get('start'),
                'end': data.get('end'),
                'metrics': data.get('metrics', {}),
                'fee_model': data.get('fee_model', {}),
            })
        except Exception:
            continue
    rows.sort(key=lambda x: x['run_id'], reverse=True)
    return rows[:limit]


def _research_subrun_progress(
    progress: Callable[..., None] | None,
    label: str,
    index: int,
    total: int,
    stage: str,
) -> Callable[..., None] | None:
    """Translate a sub-backtest's 0..100 percent into its parent job interval.

    The outer JobManager callback is also the cooperative cancellation
    checkpoint. Never swallow JobCancelled or substitute time-based estimates.
    """
    if progress is None:
        return None

    def forward(
        message: str,
        percent: float | None = None,
        inner_stage: str | None = None,
        next_step: str | None = None,
    ) -> None:
        bounded = max(0.0, min(100.0, float(percent))) if percent is not None else 0.0
        parent_percent = (index - 1 + bounded / 100.0) / total * 100.0
        progress(
            f'{label} ({index}/{total}): {message}',
            parent_percent,
            stage,
            next_step or inner_stage or 'Run historical backtest',
        )

    return forward


def run_execution_replay(req: ExecutionReplayRequest, progress: Callable[..., None] | None = None) -> dict[str, Any]:
    """Full decision/position replays; never mutate the input strategy or L1 archive."""
    rows = []
    combos = list(itertools.product(req.extra_half_spread_percent, req.extra_slippage_ticks))
    if (0.0, 0) not in combos:
        combos = [(0.0, 0), *combos]
    if len(combos) > 12:
        raise ValueError('Baseline plus scenarios must not exceed 12 runs')
    if req.strategy.execution.extra_half_spread_percent + max(v for v, _ in combos) > 25:
        raise ValueError('Total assumed half-spread cannot exceed 25 percent')
    for index, (half_spread, extra_ticks) in enumerate(combos, start=1):
        label = (
            f'Execution scenario +{half_spread:g}% half-spread '
            f'/ +{extra_ticks} ticks'
        )
        if progress:
            progress(
                f'{label} ({index}/{len(combos)}): starting',
                (index - 1) / len(combos) * 100.0,
                'EXECUTION_REPLAY',
                'Run entry, exit and risk evaluation',
            )
        config = req.strategy.model_copy(deep=True)
        config.execution.extra_half_spread_percent += half_spread
        config.execution.slippage_ticks += extra_ticks
        case = BacktestRequest(
            **req.model_dump(include={'dataset_mode','dataset_id','dataset_ids','auto_download_missing_data'}),
            start=req.start, end=req.end, strategy=config,
            storage_mode='COMPACT', bar_gap_policy=req.bar_gap_policy,
        )
        result = run_backtest(
            case,
            _research_subrun_progress(
                progress, label, index, len(combos), 'EXECUTION_REPLAY',
            ),
        )
        if progress:
            progress(
                f'{label} ({index}/{len(combos)}): complete',
                index / len(combos) * 100.0,
                'EXECUTION_REPLAY',
                'Next scenario' if index < len(combos) else 'Finalize replay results',
            )
        rows.append({
            'extra_half_spread_percent': half_spread,
            'extra_slippage_ticks': extra_ticks,
            'run_id': result['run_id'], 'cache_hit': bool(result.get('cache_hit')),
            'metrics': result['metrics'],
            'unresolved_position': result.get('unresolved_position'),
            'trades': len(result.get('trades') or []),
        })
    baseline = rows[0]['metrics']
    for row in rows:
        row['delta_net_pnl_usd'] = (
            float(row['metrics'].get('net_pnl_usd') or 0.0) -
            float(baseline.get('net_pnl_usd') or 0.0)
        )
        row['delta_trades'] = int(row['trades']) - int(rows[0]['trades'])
    return {
        'kind': 'FULL_EXECUTION_REPLAY', 'mode': 'LOW_FIDELITY_RESEARCH_ONLY',
        'scenario_count': len(rows), 'scenarios': rows,
        'base_slippage_ticks': req.strategy.execution.slippage_ticks,
        'base_extra_half_spread_percent': req.strategy.execution.extra_half_spread_percent,
        'note': (
            'Each case reruns entry selection, spread rejection, position sizing, '
            'stops, fee gates and exits from original synthetic/unverified quotes; '
            'extra half-spread widens midpoint BBO symmetrically; extra ticks worsen '
            'fills. No recorded L1 depth, queue modeling, or proven fill probability.'
        ),
    }



def run_holdout(req: HoldoutResearchRequest, progress: Callable[..., None] | None = None) -> dict[str, Any]:
    """Chronological unoptimized train/holdout check with configurable embargo."""
    start, end = _parse_dt(req.start), _parse_dt(req.end)
    if end <= start:
        raise ValueError('End must follow start')
    tf_minutes = {'5m':5, '10m':10, '15m':15, '30m':30, '1h':60}[req.strategy.timeframe]
    step = tf_minutes*60
    total_candles = int((end-start).total_seconds()//step)
    embargo = req.embargo_bars
    train_bars = int(total_candles*req.train_fraction)
    if train_bars < 3 or total_candles-train_bars-embargo < 3:
        raise ValueError('Holdout needs at least three train/test candles after embargo')
    train_end = start + timedelta(seconds=step*train_bars)
    test_start = train_end + timedelta(seconds=step*embargo)
    if progress:
        progress('Training reference (1/2): starting', 0.0,
                 'HOLDOUT_TRAIN', 'Evaluate earlier training interval')
    selection = req.model_dump(include={
        'dataset_mode', 'dataset_id', 'dataset_ids', 'auto_download_missing_data',
    })
    before = run_backtest(
        BacktestRequest(
            **selection, start=_iso(start), end=_iso(train_end),
            strategy=req.strategy, storage_mode='COMPACT',
            bar_gap_policy=req.bar_gap_policy,
        ),
        _research_subrun_progress(
            progress, 'Training reference', 1, 2, 'HOLDOUT_TRAIN',
        ),
    )
    if progress:
        progress('Training reference (1/2): complete', 50.0,
                 'HOLDOUT_TRAIN', 'Start untouched holdout')
        progress('Unseen holdout (2/2): starting', 50.0,
                 'HOLDOUT_TEST', 'Evaluate holdout interval')
    after = run_backtest(
        BacktestRequest(
            **selection, start=_iso(test_start), end=_iso(end),
            strategy=req.strategy, storage_mode='COMPACT',
            bar_gap_policy=req.bar_gap_policy,
        ),
        _research_subrun_progress(
            progress, 'Unseen holdout', 2, 2, 'HOLDOUT_TEST',
        ),
    )
    if progress:
        progress('Unseen holdout (2/2): complete', 100.0,
                 'HOLDOUT_TEST', 'Build robustness summary')
    return {
        'kind':'CHRONOLOGICAL_HOLDOUT','research_only':True,
        'train':{'start':_iso(start),'end':_iso(train_end),'run_id':before['run_id'],'metrics':before['metrics'],
                 'robustness':analyze_trade_robustness(before.get('trades') or [])},
        'holdout':{'start':_iso(test_start),'end':_iso(end),'run_id':after['run_id'],'metrics':after['metrics'],
                   'robustness':analyze_trade_robustness(after.get('trades') or [])},
        'embargo_bars':embargo,
        'note':'Same frozen strategy is used in chronological train and unseen holdout. '
               'No model selection happens here; warm-up may use earlier bars, and '
               'capital is reset between windows. No guarantee of future profit.',
    }

