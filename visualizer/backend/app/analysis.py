from __future__ import annotations
import csv, io, json, statistics, zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from .config import result_root, cache_root
from .storage import read_csv_any, read_json_any

IST = ZoneInfo('Asia/Kolkata')


def _safe_run_dir(run_id: str) -> Path:
    base = result_root().resolve()
    path = (base / run_id).resolve()
    if base not in path.parents or not path.exists():
        raise FileNotFoundError(run_id)
    return path


def _read_json(path: Path, default):
    return read_json_any(path, default)


def _read_csv(path: Path) -> list[dict[str, str]]:
    return read_csv_any(path)


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x and x not in (float('inf'), float('-inf')) else None
    except Exception:
        return None


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {'count': 0, 'avg_return_percent': None, 'avg_mfe_percent': None, 'avg_mae_percent': None, 'avg_holding_minutes': None, 'net_pnl_usd': 0.0}
    def avg(key):
        vals = [x for r in rows if (x := _f(r.get(key))) is not None]
        return statistics.fmean(vals) if vals else None
    return {
        'count': len(rows),
        'avg_return_percent': avg('return_percent'),
        'avg_mfe_percent': avg('mfe_percent'),
        'avg_mae_percent': avg('mae_percent'),
        'avg_holding_minutes': avg('holding_minutes'),
        'net_pnl_usd': sum(_f(r.get('net_pnl_usd')) or 0.0 for r in rows),
    }


def _walk_failed(tree: dict[str, Any], counter: Counter[str]):
    for c in tree.get('conditions', []) or []:
        if not c.get('passed'):
            rhs = c.get('right') if c.get('right') else c.get('value')
            if c.get('operator') == 'BETWEEN':
                rhs = f"{c.get('value')}..{c.get('value2')}"
            counter[f"{c.get('left')} {c.get('operator')} {rhs}"] += 1
    for g in tree.get('groups', []) or []:
        _walk_failed(g, counter)


def build_analysis(run_id: str) -> dict[str, Any]:
    path = _safe_run_dir(run_id)
    summary = _read_json(path / 'summary.json', {})
    trades = summary.get('trades') or _read_csv(path / 'trades.csv')
    decisions = _read_csv(path / 'decision_events.csv') or _read_csv(path / 'decision_events.csv.gz')
    markers = summary.get('markers') or _read_json(path / 'markers.json', []) or _read_json(path / 'markers.json.gz', [])

    winners = [t for t in trades if (_f(t.get('net_pnl_usd')) or 0) > 0]
    losers = [t for t in trades if (_f(t.get('net_pnl_usd')) or 0) < 0]
    breakeven = [t for t in trades if (_f(t.get('net_pnl_usd')) or 0) == 0]

    exit_reasons = Counter(str(t.get('exit_reason') or 'UNKNOWN') for t in trades)
    directions = Counter(str(t.get('direction') or 'UNKNOWN') for t in trades)
    rejection_reasons = Counter()
    failed_conditions = Counter()
    seen_rejections: set[tuple[str, str, str]] = set()
    def add_rejection(timestamp, direction, reason):
        key = (str(timestamp or ''), str(direction or ''), str(reason or 'UNKNOWN'))
        if key not in seen_rejections:
            seen_rejections.add(key)
            rejection_reasons[key[2]] += 1
    def bucket():
        return {'trades': 0, 'net_pnl_usd': 0.0, 'gross_pnl_usd': 0.0, 'fees_usd': 0.0, 'wins': 0, 'losses': 0}
    by_hour: dict[str, dict[str, float]] = defaultdict(bucket)
    by_day: dict[str, dict[str, float]] = defaultdict(bucket)
    by_month: dict[str, dict[str, float]] = defaultdict(bucket)
    by_weekday: dict[str, dict[str, float]] = defaultdict(bucket)

    for d in decisions:
        if str(d.get('kind')) == 'EXECUTION' and str(d.get('passed', '')).lower() != 'true':
            add_rejection(d.get('timestamp'), d.get('direction'), d.get('reason'))
        if str(d.get('kind')) == 'ENTRY' and str(d.get('passed', '')).lower() != 'true':
            try:
                tree = json.loads(d.get('details') or '{}')
                _walk_failed(tree, failed_conditions)
            except Exception:
                pass

    for t in trades:
        try:
            dt = datetime.fromisoformat(str(t.get('entry_time')).replace('Z', '+00:00')).astimezone(IST)
            pnl = _f(t.get('net_pnl_usd')) or 0.0
            gross = _f(t.get('gross_pnl_usd')) or 0.0
            fees = _f(t.get('fees_usd')) or 0.0
            keys = (
                (by_hour, f'{dt.hour:02d}:00'),
                (by_day, dt.strftime('%Y-%m-%d')),
                (by_month, dt.strftime('%Y-%m')),
                (by_weekday, dt.strftime('%A')),
            )
            for container, key in keys:
                b = container[key]
                b['trades'] += 1
                b['net_pnl_usd'] += pnl
                b['gross_pnl_usd'] += gross
                b['fees_usd'] += fees
                b['wins'] += 1 if pnl > 0 else 0
                b['losses'] += 1 if pnl < 0 else 0
        except Exception:
            pass

    reject_markers = [m for m in markers if str(m.get('kind')) == 'reject']
    for m in reject_markers:
        reason = str((m.get('details') or {}).get('reason') or m.get('text') or 'UNKNOWN')
        add_rejection(m.get('timestamp'), m.get('direction'), reason)

    def rows_for(container):
        return [
            {
                'period': key,
                **vals,
                'win_rate_percent': (vals['wins'] / vals['trades'] * 100 if vals['trades'] else 0),
                'avg_pnl_usd': (vals['net_pnl_usd'] / vals['trades'] if vals['trades'] else 0),
            }
            for key, vals in container.items()
        ]

    weekday_order = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
    analysis = {
        'run_id': run_id,
        'dataset_id': summary.get('dataset_id'),
        'period': {'start': summary.get('start'), 'end': summary.get('end')},
        'metrics': summary.get('metrics', {}),
        'winners': _stats(winners),
        'losers': _stats(losers),
        'breakeven_count': len(breakeven),
        'exit_reasons': dict(exit_reasons.most_common()),
        'directions': dict(directions.most_common()),
        'rejection_reasons': dict(rejection_reasons.most_common(20)),
        'top_failed_entry_conditions': [
            {'condition': name, 'count': count}
            for name, count in failed_conditions.most_common(20)
        ],
        'entry_hour_ist': [{'hour': row['period'], **row} for row in rows_for(dict(sorted(by_hour.items())))],
        'daily_ist': rows_for(dict(sorted(by_day.items()))),
        'monthly_ist': rows_for(dict(sorted(by_month.items()))),
        'weekday_ist': rows_for({day: by_weekday[day] for day in weekday_order if day in by_weekday}),
        'equity_curve': summary.get('equity_curve') or _read_csv(path / 'equity_curve.csv') or _read_csv(path / 'equity_curve.csv.gz'),
        'fee_model': summary.get('fee_model', {}),
    }
    analysis['observations'] = _observations(analysis)
    analysis['ai_prompt'] = _ai_prompt(run_id)
    return analysis


def _observations(a: dict[str, Any]) -> list[str]:
    out: list[str] = []
    w = a['winners']; l = a['losers']
    if w['count'] and l['count']:
        if w['avg_mfe_percent'] is not None and l['avg_mfe_percent'] is not None:
            out.append(f"Average MFE: winners {w['avg_mfe_percent']:.2f}% vs losers {l['avg_mfe_percent']:.2f}%.")
        if w['avg_mae_percent'] is not None and l['avg_mae_percent'] is not None:
            out.append(f"Average MAE: winners {w['avg_mae_percent']:.2f}% vs losers {l['avg_mae_percent']:.2f}%.")
        if w['avg_holding_minutes'] is not None and l['avg_holding_minutes'] is not None:
            out.append(f"Average hold: winners {w['avg_holding_minutes']:.1f} min vs losers {l['avg_holding_minutes']:.1f} min.")
    if a['top_failed_entry_conditions']:
        top = a['top_failed_entry_conditions'][0]
        out.append(f"Most common failed entry condition: {top['condition']} ({top['count']:,} evaluations).")
    if a['rejection_reasons']:
        reason, count = next(iter(a['rejection_reasons'].items()))
        out.append(f"Most common execution rejection: {reason} ({count:,}).")
    return out


def _ai_prompt(run_id: str) -> str:
    return f"""Analyze the attached BTC Strategy Lab analysis package for run {run_id}.

Please separate entry-quality, exit-quality, execution/liquidity, and risk-management problems. Compare winners vs losers, inspect rejection reasons and failed entry conditions, and identify changes that are supported by the data rather than by intuition. Flag possible overfitting. Recommend the next 3-5 controlled backtests, changing one factor at a time. Do not claim a strategy is profitable or robust unless the supplied out-of-sample data supports it.
"""


def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    if not rows:
        return b''
    sio = io.StringIO()
    fields = list(dict.fromkeys(k for r in rows for k in r.keys()))
    wr = csv.DictWriter(sio, fieldnames=fields)
    wr.writeheader(); wr.writerows(rows)
    return sio.getvalue().encode('utf-8')


def build_analysis_package(run_id: str) -> Path:
    path = _safe_run_dir(run_id)
    summary = _read_json(path / 'summary.json', {})
    trades = summary.get('trades') or _read_csv(path / 'trades.csv')
    winners = [t for t in trades if (_f(t.get('net_pnl_usd')) or 0) > 0]
    losers = [t for t in trades if (_f(t.get('net_pnl_usd')) or 0) < 0]
    decisions = _read_csv(path / 'decision_events.csv')
    rejected = [d for d in decisions if str(d.get('passed', '')).lower() != 'true']
    execution_rejected = [d for d in rejected if str(d.get('kind')) == 'EXECUTION']
    analysis = build_analysis(run_id)
    package_root = cache_root() / 'analysis-packages'
    package_root.mkdir(parents=True, exist_ok=True)
    zip_path = package_root / f'{run_id}-analysis.zip'
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        # V15 analysis packages intentionally avoid duplicating the potentially
        # huge raw decision trace. The package carries compact derived rejection
        # tables plus summary/trades/strategy. Raw decisions remain queryable via
        # the Strategy Lab API when the run was stored as ANALYSIS/FULL_DEBUG.
        for name in ('strategy.json', 'summary.json', 'trades.csv'):
            src = path / name
            if src.exists():
                z.write(src, arcname=name)
        z.writestr('winners.csv', _csv_bytes(winners))
        z.writestr('losers.csv', _csv_bytes(losers))
        z.writestr('rejections.csv', _csv_bytes(rejected))
        z.writestr('execution_rejections.csv', _csv_bytes(execution_rejected))
        z.writestr('analysis.json', json.dumps(analysis, indent=2, allow_nan=False))
        z.writestr('AI_PROMPT.txt', analysis['ai_prompt'])
        z.writestr('README.md', '# BTC Strategy Lab analysis package\n\nThis package contains the strategy, compact summary, trades, winners, losers, rejected decisions, execution rejects, and deterministic analysis summary for this run. V15.1 intentionally omits the full raw decision trace to avoid duplicating large result artifacts.\n')
    return zip_path
