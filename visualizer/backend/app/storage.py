from __future__ import annotations

import csv
import gzip
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable

from .config import result_root, cache_root

UTC = timezone.utc
SETTINGS_NAME = '.storage.json'
DEFAULT_SETTINGS = {
    'default_storage_mode': 'ANALYSIS',
    'auto_cleanup_enabled': False,
    'result_limit_gb': 5.0,
    'retention_days': 14,
    'keep_recent_runs': 25,
}


def _settings_path() -> Path:
    return result_root().parent / SETTINGS_NAME


def load_settings() -> dict[str, Any]:
    path = _settings_path()
    data: dict[str, Any] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                data = raw
        except Exception:
            data = {}
    out = dict(DEFAULT_SETTINGS)
    out.update(data)
    return out


def save_settings(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(load_settings())
    for key in DEFAULT_SETTINGS:
        if key in payload:
            out[key] = payload[key]
    mode = str(out.get('default_storage_mode', 'ANALYSIS')).upper()
    if mode not in {'COMPACT', 'ANALYSIS', 'FULL_DEBUG'}:
        raise ValueError('default_storage_mode must be COMPACT, ANALYSIS, or FULL_DEBUG')
    out['default_storage_mode'] = mode
    out['result_limit_gb'] = max(0.1, float(out.get('result_limit_gb', 5.0)))
    out['retention_days'] = max(0, int(out.get('retention_days', 14)))
    out['keep_recent_runs'] = max(0, int(out.get('keep_recent_runs', 25)))
    out['auto_cleanup_enabled'] = bool(out.get('auto_cleanup_enabled', False))
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(out, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)
    return out


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob('*'):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            pass
    return total


def _run_dirs() -> list[Path]:
    root = result_root()
    if not root.exists():
        return []
    return [p for p in root.iterdir() if p.is_dir() and (p / 'summary.json').exists()]


def _run_info(path: Path) -> dict[str, Any]:
    try:
        summary = json.loads((path / 'summary.json').read_text(encoding='utf-8'))
    except Exception:
        summary = {}
    try:
        modified = max((p.stat().st_mtime for p in path.rglob('*') if p.is_file()), default=path.stat().st_mtime)
    except OSError:
        modified = 0.0
    return {
        'run_id': str(summary.get('run_id') or path.name),
        'strategy_name': str((summary.get('strategy') or {}).get('name') or summary.get('strategy_name') or ''),
        'storage_mode': str(summary.get('storage_mode') or 'LEGACY'),
        'size_bytes': directory_size(path),
        'modified_at': modified,
        'pinned': (path / '.pinned').exists(),
        'path': str(path),
    }


def storage_usage() -> dict[str, Any]:
    root = result_root()
    cache = cache_root()
    quote_indexes = 0
    backtest_cache = 0
    other_cache = 0
    if cache.exists():
        for p in cache.rglob('*'):
            if not p.is_file():
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            rel = p.relative_to(cache)
            if p.name.startswith('quotes-') and p.suffix == '.sqlite3':
                quote_indexes += size
            elif rel.parts and rel.parts[0] == 'backtests':
                backtest_cache += size
            else:
                other_cache += size
    runs = sorted((_run_info(p) for p in _run_dirs()), key=lambda x: x['modified_at'], reverse=True)
    return {
        'settings': load_settings(),
        'results_bytes': directory_size(root),
        'cache_bytes': directory_size(cache),
        'quote_index_bytes': quote_indexes,
        'backtest_cache_bytes': backtest_cache,
        'other_cache_bytes': other_cache,
        'run_count': len(runs),
        'runs': runs[:200],
    }


def write_json_gz(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with gzip.open(tmp, 'wt', encoding='utf-8', compresslevel=6) as h:
        json.dump(value, h, separators=(',', ':'), allow_nan=False)
    tmp.replace(path)


def read_json_any(base: Path, default: Any) -> Any:
    plain = base
    gz = Path(str(base) + '.gz')
    try:
        if plain.exists():
            return json.loads(plain.read_text(encoding='utf-8'))
        if gz.exists():
            with gzip.open(gz, 'rt', encoding='utf-8') as h:
                return json.load(h)
    except Exception:
        return default
    return default


def write_csv_gz(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with gzip.open(tmp, 'wt', encoding='utf-8', newline='', compresslevel=6) as h:
        wr = csv.DictWriter(h, fieldnames=fields)
        wr.writeheader()
        wr.writerows(rows)
    tmp.replace(path)


def iter_csv_any(base: Path) -> Iterable[dict[str, str]]:
    plain = base
    gz = Path(str(base) + '.gz')
    if plain.exists():
        with plain.open('r', encoding='utf-8', newline='') as h:
            yield from csv.DictReader(h)
    elif gz.exists():
        with gzip.open(gz, 'rt', encoding='utf-8', newline='') as h:
            yield from csv.DictReader(h)


def read_csv_any(base: Path) -> list[dict[str, str]]:
    return list(iter_csv_any(base))


def _slim_summary(summary: dict[str, Any]) -> dict[str, Any]:
    out = dict(summary)
    for key in ('trades', 'markers', 'equity_curve', 'series_meta'):
        out.pop(key, None)
    out['artifact_manifest'] = {
        'trades': 'trades.csv' if (Path(str(summary.get('result_dir', ''))) / 'trades.csv').exists() else None,
        'markers': 'markers.json.gz',
        'equity_curve': 'equity_curve.csv.gz',
        'decisions': 'decision_events.csv.gz',
    }
    return out


def optimize_run(path: Path) -> dict[str, Any]:
    if not (path / 'summary.json').exists():
        return {'run_id': path.name, 'changed': False, 'before_bytes': directory_size(path), 'after_bytes': directory_size(path)}
    before = directory_size(path)
    changed = False

    # Compress the three historically large text artifacts. Keep trades.csv plain;
    # it is small and convenient for humans/tools.
    for name in ('decision_events.csv', 'equity_curve.csv'):
        src = path / name
        dst = path / f'{name}.gz'
        if src.exists() and not dst.exists():
            with src.open('rb') as inp, gzip.open(dst, 'wb', compresslevel=6) as out:
                shutil.copyfileobj(inp, out, length=1024 * 1024)
            src.unlink()
            changed = True
    src_json = path / 'markers.json'
    dst_json = path / 'markers.json.gz'
    if src_json.exists() and not dst_json.exists():
        with src_json.open('rb') as inp, gzip.open(dst_json, 'wb', compresslevel=6) as out:
            shutil.copyfileobj(inp, out, length=1024 * 1024)
        src_json.unlink()
        changed = True

    # Old summary.json duplicated trades/markers/equity in full. Remove those
    # copies only after their dedicated artifacts are available.
    try:
        summary_path = path / 'summary.json'
        summary = json.loads(summary_path.read_text(encoding='utf-8'))
        if any(k in summary for k in ('trades', 'markers', 'equity_curve', 'series_meta')):
            summary['storage_mode'] = summary.get('storage_mode') or 'ANALYSIS'
            for key in ('trades', 'markers', 'equity_curve', 'series_meta'):
                summary.pop(key, None)
            summary['artifact_manifest'] = {
                'trades': 'trades.csv' if (path / 'trades.csv').exists() else None,
                'markers': 'markers.json.gz' if (path / 'markers.json.gz').exists() else None,
                'equity_curve': 'equity_curve.csv.gz' if (path / 'equity_curve.csv.gz').exists() else None,
                'decisions': 'decision_events.csv.gz' if (path / 'decision_events.csv.gz').exists() else None,
            }
            tmp = summary_path.with_suffix('.json.tmp')
            tmp.write_text(json.dumps(summary, separators=(',', ':'), allow_nan=False), encoding='utf-8')
            tmp.replace(summary_path)
            changed = True
    except Exception:
        pass

    # Generated analysis packages are derived artifacts and can be rebuilt.
    for z in path.glob('*-analysis.zip'):
        try:
            z.unlink(); changed = True
        except OSError:
            pass
    after = directory_size(path)
    return {'run_id': path.name, 'changed': changed, 'before_bytes': before, 'after_bytes': after, 'saved_bytes': max(0, before-after)}


def optimize_existing(progress=None) -> dict[str, Any]:
    dirs = _run_dirs()
    before = sum(directory_size(p) for p in dirs)
    rows = []
    for i, path in enumerate(dirs, start=1):
        if progress:
            progress(f'Optimizing result {i}/{len(dirs)}: {path.name}', 5 + 90 * i / max(1, len(dirs)), 'STORAGE_OPTIMIZE', 'Compress next result')
        rows.append(optimize_run(path))
    after = sum(directory_size(p) for p in dirs)
    if progress:
        progress('Storage optimization complete', 100, 'COMPLETE', 'Complete')
    return {'runs_scanned': len(dirs), 'before_bytes': before, 'after_bytes': after, 'saved_bytes': max(0, before-after), 'rows': rows}


def pin_run(run_id: str, pinned: bool) -> dict[str, Any]:
    root = result_root().resolve()
    path = (root / run_id).resolve()
    if root not in path.parents or not path.exists():
        raise FileNotFoundError(run_id)
    marker = path / '.pinned'
    if pinned:
        marker.write_text('pinned\n', encoding='utf-8')
    elif marker.exists():
        marker.unlink()
    return _run_info(path)


def cleanup_unpinned(*, dry_run: bool = False) -> dict[str, Any]:
    settings = load_settings()
    root = result_root()
    infos = sorted((_run_info(p) for p in _run_dirs()), key=lambda x: x['modified_at'], reverse=True)
    keep_recent = int(settings['keep_recent_runs'])
    cutoff = datetime.now(UTC) - timedelta(days=int(settings['retention_days']))
    limit_bytes = int(float(settings['result_limit_gb']) * (1024 ** 3))
    current = sum(int(x['size_bytes']) for x in infos)
    candidates: list[dict[str, Any]] = []
    protected_ids = {x['run_id'] for x in infos[:keep_recent]}
    # Oldest first, never pinned and never part of recent-run protection.
    for info in reversed(infos):
        if info['pinned'] or info['run_id'] in protected_ids:
            continue
        modified = datetime.fromtimestamp(float(info['modified_at']), UTC)
        old_enough = int(settings['retention_days']) == 0 or modified < cutoff
        over_limit = current > limit_bytes
        if old_enough or over_limit:
            candidates.append(info)
            current -= int(info['size_bytes'])
    deleted = []
    if not dry_run:
        for info in candidates:
            path = root / info['run_id']
            try:
                shutil.rmtree(path)
                deleted.append(info)
            except OSError:
                pass
        # Remove cache pointers whose target result no longer exists.
        bt = cache_root() / 'backtests'
        if bt.exists():
            for idx in bt.glob('*.json'):
                try:
                    meta = json.loads(idx.read_text(encoding='utf-8'))
                    if not (root / str(meta.get('run_id', '')) / 'summary.json').exists():
                        idx.unlink()
                except Exception:
                    pass
    return {
        'dry_run': dry_run,
        'candidate_count': len(candidates),
        'candidate_bytes': sum(int(x['size_bytes']) for x in candidates),
        'deleted_count': len(deleted),
        'deleted_bytes': sum(int(x['size_bytes']) for x in deleted),
        'candidates': candidates,
        'settings': settings,
    }


def maybe_auto_cleanup() -> None:
    settings = load_settings()
    if settings.get('auto_cleanup_enabled'):
        cleanup_unpinned(dry_run=False)


def _coerce_number(value: str) -> Any:
    if value == '':
        return ''
    low = value.lower()
    if low == 'true':
        return True
    if low == 'false':
        return False
    try:
        if any(c in value for c in ('.', 'e', 'E')):
            return float(value)
        return int(value)
    except Exception:
        return value


def _typed_csv(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [{k: _coerce_number(v) for k, v in row.items()} for row in rows]


def trade_markers_from_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    for t in trades:
        direction = str(t.get('direction') or 'BOTH')
        action = str(t.get('action') or 'BUY')
        symbol = str(t.get('symbol') or '')
        if t.get('entry_time'):
            markers.append({
                'time': str(t.get('entry_time')),
                'kind': 'entry',
                'direction': direction,
                'text': f'{action} {direction} {symbol}'.strip(),
                'pnl_usd': None,
                'details': {'storage_reconstructed': True, 'entry_price': t.get('entry_price') or t.get('entry_ask')},
            })
        if t.get('exit_time'):
            pnl = t.get('net_pnl_usd')
            markers.append({
                'time': str(t.get('exit_time')),
                'kind': 'exit',
                'direction': direction,
                'text': str(t.get('exit_reason') or 'EXIT'),
                'pnl_usd': pnl,
                'details': {'storage_reconstructed': True, 'exit_price': t.get('exit_price') or t.get('exit_bid'), 'reason': t.get('exit_reason')},
            })
    return markers


def load_result(run_id: str) -> dict[str, Any] | None:
    root = result_root().resolve()
    path = (root / str(run_id)).resolve()
    if root not in path.parents or not (path / 'summary.json').exists():
        return None
    try:
        result = json.loads((path / 'summary.json').read_text(encoding='utf-8'))
    except Exception:
        return None
    trades = result.get('trades')
    if not isinstance(trades, list):
        trades = _typed_csv(read_csv_any(path / 'trades.csv'))
    markers = result.get('markers')
    if not isinstance(markers, list):
        markers = read_json_any(path / 'markers.json', None)
        if not isinstance(markers, list):
            markers = trade_markers_from_trades(trades)
    equity = result.get('equity_curve')
    if not isinstance(equity, list):
        equity = _typed_csv(read_csv_any(path / 'equity_curve.csv'))
    result['trades'] = trades
    if result.get('storage_mode') == 'COMPACT' and any(m.get('kind') == 'alert' for m in markers):
        # In COMPACT mode only alert markers are persisted; rebuild trade
        # markers separately without discarding independent alerts.
        markers = [*markers, *trade_markers_from_trades(trades)]
    result['markers'] = markers
    result['equity_curve'] = equity
    result.setdefault('series_meta', [])
    result.setdefault('decision_count', 0)
    result.setdefault('storage_mode', 'LEGACY')
    return result
