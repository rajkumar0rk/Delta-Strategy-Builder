from __future__ import annotations
import itertools, json, statistics
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from .models import ResearchSweepRequest, AblationRequest, StrategyConfig, BacktestRequest
from .engine import run_backtest
from .config import result_root

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
    return {
        'kind': 'PARAMETER_SWEEP',
        'count': len(rows),
        'dimensions': [d.model_dump() for d in req.dimensions],
        'rows': rows,
        'walk_forward': walk_forward,
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
