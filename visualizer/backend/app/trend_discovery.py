from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Callable

import numpy as np
import pandas as pd

from .data_store import DataStore
from .indicators import compute_indicators
from .engine import _prepare_strategy_state


def _finite(value: Any) -> float | None:
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _forward_extremes(frame: pd.DataFrame, horizon: int) -> tuple[pd.Series, pd.Series]:
    """Future max/min over the next N completed candles, excluding current.

    These values are used only to label historical outcomes for research. They are
    never written back into the strategy frame and can never participate in entry
    rules, preserving the engine's no-look-ahead semantics.
    """
    future_high = frame['high'].shift(-1).iloc[::-1].rolling(horizon, min_periods=1).max().iloc[::-1]
    future_low = frame['low'].shift(-1).iloc[::-1].rolling(horizon, min_periods=1).min().iloc[::-1]
    return future_high, future_low


def _phase_name(value: Any) -> str:
    code = int(_finite(value) or 0)
    return {0: 'COMPRESSION', 1: 'IGNITION', 2: 'CONFIRMATION', 3: 'BIG_TREND', 4: 'EXHAUSTION'}.get(code, 'COMPRESSION')


def _candidate_feature_columns(frame: pd.DataFrame, strategy) -> list[str]:
    wanted: list[str] = ['volume']
    for inst in strategy.indicators:
        prefix = inst.id + '.'
        if inst.id in frame.columns:
            wanted.append(inst.id)
        wanted.extend(c for c in frame.columns if c.startswith(prefix))
    wanted.extend([
        'call_big_trend_score', 'put_big_trend_score',
        'call_big_trend_score_persistence_count', 'put_big_trend_score_persistence_count',
        'call_bars_since_breakout', 'put_bars_since_breakout',
        'call_retest_ready', 'put_retest_ready',
        'call_false_breakout', 'put_false_breakout',
    ])
    out: list[str] = []
    for key in wanted:
        if key in out or key not in frame.columns:
            continue
        # Only numeric columns are useful in feature comparison.
        if pd.api.types.is_numeric_dtype(frame[key]):
            out.append(key)
    return out


def _snapshot(frame: pd.DataFrame, i: int, direction: str, prelude: int, feature_columns: list[str]) -> dict[str, Any]:
    row = frame.iloc[i]
    start = max(0, i - prelude + 1)
    window = frame.iloc[start:i + 1]
    close = _finite(row.get('close')) or 0.0
    old_close = _finite(window.iloc[0].get('close')) if len(window) else None
    prelude_return = ((close / old_close - 1.0) * 100.0) if old_close not in (None, 0) else None
    body = abs((_finite(row.get('close')) or 0.0) - (_finite(row.get('open')) or 0.0))
    high = _finite(row.get('high')); low = _finite(row.get('low'))
    candle_range = (high - low) if high is not None and low is not None else None
    body_range_pct = (body / candle_range * 100.0) if candle_range and candle_range > 0 else None
    volume = _finite(row.get('volume'))
    avg_volume = float(pd.to_numeric(window['volume'], errors='coerce').mean()) if len(window) and 'volume' in window else None
    volume_ratio = (volume / avg_volume) if volume is not None and avg_volume and avg_volume > 0 else None
    side = direction.lower()
    score = _finite(row.get(f'{side}_big_trend_score')) or 0.0
    phase = _phase_name(row.get(f'{side}_trend_phase_code'))

    features: dict[str, float | None] = {
        'prelude_return_percent': prelude_return,
        'candle_body_range_percent': body_range_pct,
        'volume_vs_prelude_average': volume_ratio,
        'big_trend_score': score,
    }
    for key in feature_columns:
        value = _finite(row.get(key))
        if value is not None:
            features[key] = value
    # Score slope is useful even if the user has no explicit slope condition.
    score_col = f'{side}_big_trend_score'
    if score_col in frame.columns and len(window) >= 2:
        a = _finite(window.iloc[0].get(score_col)); b = _finite(window.iloc[-1].get(score_col))
        if a is not None and b is not None:
            features['big_trend_score_slope_per_bar'] = (b - a) / max(1, len(window) - 1)
    return {'score': score, 'phase': phase, 'features': features}


def _event_stats(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        by[(event['direction'], event['label'])].append(event)
    rows = []
    for direction in ('CALL', 'PUT'):
        big = by.get((direction, 'BIG'), [])
        fake = by.get((direction, 'FAKE'), [])
        keys: set[str] = set()
        for e in big + fake:
            keys.update(e.get('features', {}).keys())
        for key in sorted(keys):
            bvals = [float(e['features'][key]) for e in big if _finite(e.get('features', {}).get(key)) is not None]
            fvals = [float(e['features'][key]) for e in fake if _finite(e.get('features', {}).get(key)) is not None]
            if len(bvals) < 2 or len(fvals) < 2:
                continue
            bmean = float(np.mean(bvals)); fmean = float(np.mean(fvals))
            pooled = float(np.std(bvals + fvals))
            separation = (bmean - fmean) / pooled if pooled > 1e-12 else 0.0
            rows.append({
                'direction': direction, 'feature': key,
                'big_count': len(bvals), 'fake_count': len(fvals),
                'big_mean': bmean, 'big_median': float(np.median(bvals)),
                'fake_mean': fmean, 'fake_median': float(np.median(fvals)),
                'mean_delta': bmean - fmean,
                'standardized_separation': separation,
            })
    rows.sort(key=lambda x: abs(float(x['standardized_separation'])), reverse=True)
    return rows


def _score_calibration(frame: pd.DataFrame, call_move: pd.Series, put_move: pd.Series, threshold: float, horizon: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    valid_end = max(0, len(frame) - horizon)
    buckets = [(0, 20), (20, 40), (40, 60), (60, 70), (70, 80), (80, 90), (90, 101)]
    for direction, score_key, move in (
        ('CALL', 'call_big_trend_score', call_move),
        ('PUT', 'put_big_trend_score', put_move),
    ):
        if score_key not in frame.columns:
            continue
        scores = pd.to_numeric(frame[score_key].iloc[:valid_end], errors='coerce')
        moves = pd.to_numeric(move.iloc[:valid_end], errors='coerce')
        for lo, hi in buckets:
            mask = (scores >= lo) & (scores < hi)
            count = int(mask.sum())
            if not count:
                continue
            hits = int((moves[mask] >= threshold).sum())
            rows.append({
                'direction': direction, 'bucket': f'{lo}-{100 if hi == 101 else hi}',
                'min_score': lo, 'max_score': 100 if hi == 101 else hi,
                'samples': count, 'big_move_hits': hits,
                'hit_rate_percent': hits / count * 100.0,
                'average_forward_mfe_percent': float(moves[mask].mean()),
            })
    return rows


def run_trend_discovery(req, progress: Callable[..., None] | None = None) -> dict[str, Any]:
    def emit(message: str, percent: float, stage: str, next_step: str = ''):
        if progress:
            progress(message, percent, stage, next_step)

    emit('Selecting unified history segments…', 5, 'DATA_SELECTION', 'Load candles')
    store = DataStore()
    parts = store.resolve_request(req, require_options=False)
    emit(f'Loading {req.strategy.timeframe} candles from {len(parts)} archive segment(s)…', 15, 'LOAD_BARS', 'Calculate indicators')
    frame = store.load_bars_many(parts, req.start, req.end, req.strategy.timeframe)
    if len(frame) < req.lookahead_bars + req.prelude_bars + 2:
        raise ValueError(
            f'Trend discovery needs at least {req.lookahead_bars + req.prelude_bars + 2} completed {req.strategy.timeframe} candles; found {len(frame)}.'
        )

    emit(f'Calculating {len(req.strategy.indicators)} configured indicator(s)…', 30, 'INDICATORS', 'Build stateful Big Trend features')
    frame, _ = compute_indicators(frame, req.strategy.indicators, req.strategy.timeframe)
    _prepare_strategy_state(frame, req.strategy)
    emit('Labeling future big moves (research labels only)…', 48, 'LABEL_OUTCOMES', 'Sample big and fake trend events')

    future_high, future_low = _forward_extremes(frame, int(req.lookahead_bars))
    close = pd.to_numeric(frame['close'], errors='coerce')
    call_move = (future_high / close - 1.0) * 100.0
    put_move = (1.0 - future_low / close) * 100.0
    feature_columns = _candidate_feature_columns(frame, req.strategy)

    big_indices: dict[str, list[int]] = {'CALL': [], 'PUT': []}
    events: list[dict[str, Any]] = []
    last_big = {'CALL': -10**9, 'PUT': -10**9}
    end_i = len(frame) - int(req.lookahead_bars)
    prelude = int(req.prelude_bars)
    separation = int(req.min_separation_bars)
    threshold = float(req.big_move_percent)

    # BIG labels are price-outcome labels and do not require the current strategy
    # score to already be high. That is what lets this research discover which
    # pre-move features were actually present before genuine moves.
    for i in range(prelude, end_i):
        cm = _finite(call_move.iloc[i]) or 0.0
        pm = _finite(put_move.iloc[i]) or 0.0
        candidates = []
        if cm >= threshold:
            candidates.append(('CALL', cm))
        if pm >= threshold:
            candidates.append(('PUT', pm))
        if not candidates:
            continue
        direction, mfe = max(candidates, key=lambda x: x[1])
        if i - last_big[direction] < separation:
            continue
        snap = _snapshot(frame, i, direction, prelude, feature_columns)
        adverse = (_finite(put_move.iloc[i]) or 0.0) if direction == 'CALL' else (_finite(call_move.iloc[i]) or 0.0)
        ts = frame.index[i]
        event = {
            'timestamp': ts.isoformat(), 'time': int(ts.timestamp()), 'index': i,
            'direction': direction, 'label': 'BIG', 'close': float(close.iloc[i]),
            'future_mfe_percent': float(mfe), 'future_mae_percent': float(adverse),
            'score': snap['score'], 'phase': snap['phase'], 'features': snap['features'],
        }
        events.append(event); big_indices[direction].append(i); last_big[direction] = i
        if len(events) >= int(req.max_events):
            break

    emit(f'Found {sum(len(x) for x in big_indices.values())} separated big-move labels; finding fake strong-trend candidates…', 65, 'SAMPLE_EVENTS', 'Compare features')
    big_near = {direction: set() for direction in ('CALL', 'PUT')}
    for direction in ('CALL', 'PUT'):
        for i in big_indices[direction]:
            big_near[direction].update(range(max(0, i - separation), min(end_i, i + separation + 1)))

    last_fake = {'CALL': -10**9, 'PUT': -10**9}
    for i in range(prelude, end_i):
        if len(events) >= int(req.max_events):
            break
        for direction, move, score_key, phase_key in (
            ('CALL', call_move, 'call_big_trend_score', 'call_trend_phase_code'),
            ('PUT', put_move, 'put_big_trend_score', 'put_trend_phase_code'),
        ):
            if i in big_near[direction] or i - last_fake[direction] < separation:
                continue
            score = _finite(frame.iloc[i].get(score_key)) or 0.0
            phase = _phase_name(frame.iloc[i].get(phase_key))
            candidate = score >= float(req.candidate_score_threshold) or phase in {'IGNITION', 'CONFIRMATION', 'BIG_TREND'}
            mfe = _finite(move.iloc[i]) or 0.0
            if not candidate or mfe >= threshold:
                continue
            snap = _snapshot(frame, i, direction, prelude, feature_columns)
            adverse = (_finite(put_move.iloc[i]) or 0.0) if direction == 'CALL' else (_finite(call_move.iloc[i]) or 0.0)
            ts = frame.index[i]
            events.append({
                'timestamp': ts.isoformat(), 'time': int(ts.timestamp()), 'index': i,
                'direction': direction, 'label': 'FAKE', 'close': float(close.iloc[i]),
                'future_mfe_percent': float(mfe), 'future_mae_percent': float(adverse),
                'score': snap['score'], 'phase': snap['phase'], 'features': snap['features'],
            })
            last_fake[direction] = i

    events.sort(key=lambda x: x['time'])
    emit('Comparing pre-trend feature distributions…', 82, 'COMPARE_FEATURES', 'Build score calibration')
    feature_stats = _event_stats(events)
    calibration = _score_calibration(frame, call_move, put_move, threshold, int(req.lookahead_bars))

    monthly: dict[str, dict[str, int]] = {}
    for event in events:
        month = event['timestamp'][:7]
        row = monthly.setdefault(month, {'BIG_CALL': 0, 'BIG_PUT': 0, 'FAKE_CALL': 0, 'FAKE_PUT': 0})
        row[f"{event['label']}_{event['direction']}"] += 1

    counts = {key: 0 for key in ('BIG_CALL', 'BIG_PUT', 'FAKE_CALL', 'FAKE_PUT')}
    for event in events:
        counts[f"{event['label']}_{event['direction']}"] += 1

    warnings: list[str] = []
    if not req.strategy.call_big_trend_score.enabled:
        warnings.append('CALL Big Trend Score is disabled; CALL fake-trend sampling relies on trend phase only and may be sparse.')
    if not req.strategy.put_big_trend_score.enabled:
        warnings.append('PUT Big Trend Score is disabled; PUT fake-trend sampling relies on trend phase only and may be sparse.')
    if len(events) >= int(req.max_events):
        warnings.append(f'Event output reached max_events={req.max_events}; increase it for a wider sample.')

    emit('Trend discovery complete.', 100, 'COMPLETE', '')
    return {
        'dataset_mode': req.dataset_mode,
        'dataset_ids': [p.id for p in parts],
        'start': req.start, 'end': req.end, 'timeframe': req.strategy.timeframe,
        'config': {
            'lookahead_bars': req.lookahead_bars, 'big_move_percent': req.big_move_percent,
            'candidate_score_threshold': req.candidate_score_threshold, 'prelude_bars': req.prelude_bars,
            'min_separation_bars': req.min_separation_bars,
        },
        'bars_analyzed': len(frame), 'counts': counts,
        'events': events,
        'feature_comparison': feature_stats[:80],
        'score_calibration': calibration,
        'monthly': [{'month': month, **row} for month, row in sorted(monthly.items())],
        'warnings': warnings,
        'research_note': 'BIG/FAKE labels use future candles only for historical outcome labeling. Strategy indicators/state snapshots use information available at the labeled candle or earlier.',
    }
