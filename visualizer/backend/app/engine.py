from __future__ import annotations
import csv, json, math, re, hashlib, uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
from .models import BacktestRequest, StrategyConfig
from .data_store import DataStore, parse_time, iso
from .indicators import compute_indicators
from .warmup import required_warmup_candles, historical_bar_sources, warmup_diagnostics
from .alerts import alert_markers
from .rules import evaluate_group, evaluate_condition, find_condition
from .config import result_root, cache_root
from .storage import write_json_gz, write_csv_gz, load_result, maybe_auto_cleanup
from .archive_sync import ensure_archive_data

UTC = timezone.utc


def _new_result_dir(strategy_name: str) -> tuple[str, Any]:
    """Create a collision-proof result directory using exclusive mkdir."""
    slug = re.sub(r'[^a-zA-Z0-9_-]+', '-', strategy_name).strip('-').lower() or 'strategy'
    root = result_root()
    root.mkdir(parents=True, exist_ok=True)
    for _ in range(8):
        stamp = datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')[:-3]
        run_id = f"{stamp}-{slug[:40]}-{uuid.uuid4().hex[:8]}"
        out = root / run_id
        try:
            out.mkdir(parents=False, exist_ok=False)
            return run_id, out
        except FileExistsError:
            continue
    raise RuntimeError('Could not allocate a unique result directory after 8 attempts')

@dataclass
class Position:
    direction: str
    action: str
    symbol: str
    spec: dict[str, Any]
    entry_time: str
    signal_time: str
    entry_spot: float
    entry_price: float
    quantity: float
    entry_fee: float
    entry_fee_details: dict[str, float]
    entry_atr: float | None
    entry_rule: dict[str, Any]
    entry_lifecycle_id: str = ''
    entry_lifecycle_name: str = ''
    peak_return: float = 0.0
    worst_return: float = 0.0


def _finite(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _session_allowed(ts: pd.Timestamp, cfg) -> bool:
    local = ts.to_pydatetime().astimezone(ZoneInfo(cfg.timezone))
    if local.weekday() in cfg.blocked_weekdays:
        return False
    minute = local.hour * 60 + local.minute
    windows = list(getattr(cfg, "windows", []) or [])
    if not windows:
        windows = [SimpleNamespace(start=getattr(cfg, "start", "00:00"), end=getattr(cfg, "end", "23:59"))]
    for window in windows:
        sh, sm = map(int, window.start.split(':'))
        eh, em = map(int, window.end.split(':'))
        a = sh * 60 + sm
        b = eh * 60 + em
        allowed = a <= minute <= b if a <= b else (minute >= a or minute <= b)
        if allowed:
            return True
    return False


def _direction_type(direction: str) -> str:
    return 'CE' if direction == 'CALL' else 'PE'


def _select_candidates(inst: pd.DataFrame, ts: pd.Timestamp, spot: float, direction: str, cfg) -> pd.DataFrame:
    x = inst[(inst.activation <= ts) & (inst.expiration > ts) & (inst.option_type == _direction_type(direction))].copy()
    if x.empty:
        return x
    x['dte'] = (x.expiration - ts).dt.total_seconds() / 86400.0
    x = x[(x.dte >= cfg.min_dte_days) & (x.dte <= cfg.max_dte_days)]
    if x.empty:
        return x
    ranked = []
    for _, g in x.groupby('expiration'):
        strikes = sorted(g.strike.unique())
        atm_i = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
        if cfg.strike_mode == 'ATM':
            target_i = atm_i
        else:
            sign = (-1 if direction == 'CALL' else 1) if cfg.strike_mode == 'ITM' else (1 if direction == 'CALL' else -1)
            target_i = max(0, min(len(strikes) - 1, atm_i + sign * cfg.strike_steps))
        target = strikes[target_i]
        gg = g.copy()
        gg['strike_distance'] = abs(gg.strike - target)
        ranked.append(gg)
    out = pd.concat(ranked)
    out['expiry_rank'] = (out.expiration - ts).dt.total_seconds()
    return out.sort_values(['expiry_rank', 'strike_distance', 'strike'])


def _quote_stats(q: dict[str, Any]) -> dict[str, float | None]:
    bid = _finite(q.get('bid'))
    ask = _finite(q.get('ask'))
    mid = ((bid + ask) / 2.0) if bid is not None and ask is not None else None
    spread = ((ask - bid) / mid * 100.0) if mid and mid > 0 and bid is not None and ask is not None else None
    return {
        'bid': bid,
        'ask': ask,
        'mid': mid,
        'spread_percent': spread,
        'volume': _finite(q.get('volume')),
        'open_interest': _finite(q.get('open_interest')),
    }


def _quote_ok(q, cfg, action: str = 'BUY') -> tuple[bool, str]:
    stats = _quote_stats(q)
    premium = stats['ask'] if action == 'BUY' else stats['bid']
    spread = stats['spread_percent']
    assert premium is not None
    if cfg.min_premium is not None and premium < cfg.min_premium:
        return False, 'PREMIUM_TOO_LOW'
    if cfg.max_premium is not None and premium > cfg.max_premium:
        return False, 'PREMIUM_TOO_HIGH'
    if cfg.max_spread_percent is not None and (spread is None or spread > cfg.max_spread_percent):
        return False, 'SPREAD_TOO_WIDE'
    if cfg.min_volume is not None and (stats['volume'] is None or stats['volume'] < cfg.min_volume):
        return False, 'VOLUME_TOO_LOW'
    if cfg.min_open_interest is not None and (stats['open_interest'] is None or stats['open_interest'] < cfg.min_open_interest):
        return False, 'OPEN_INTEREST_TOO_LOW'
    return True, ''


def _select_option(store, parts, inst, ts, spot, direction, strategy, action: str = 'BUY') -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
    candidates = _select_candidates(inst, ts, spot, direction, strategy.option)
    last = 'NO_OPTION_CANDIDATE'
    for _, row in candidates.head(30).iterrows():
        q = store.first_quote_many(parts, str(row.symbol), ts.isoformat(), strategy.execution.max_entry_quote_delay_seconds)
        if not q:
            last = 'NO_FRESH_QUOTE'
            continue
        ok, why = _quote_ok(q, strategy.option, action)
        if not ok:
            last = why
            continue
        return row.to_dict(), q, ''
    return None, None, last


def _delta_fee(spot: float, premium: float, qty: float, cv: float, execution) -> dict[str, float]:
    """Delta options fee model requested by the user.

    Per side:
      notional fee = spot * qty * contract value * 0.01%
      premium cap  = premium * qty * contract value * 3.5%
      base fee     = min(notional fee, premium cap)
      GST          = base fee * 18%
      total fee    = base fee + GST
    """
    notional_fee = float(spot) * float(qty) * float(cv) * (float(execution.option_notional_fee_rate_percent) / 100.0)
    premium_cap = float(premium) * float(qty) * float(cv) * (float(execution.premium_fee_cap_percent) / 100.0)
    base_fee = min(notional_fee, premium_cap)
    gst = base_fee * (float(execution.gst_percent) / 100.0)
    return {
        'notional_fee_usd': notional_fee,
        'premium_cap_usd': premium_cap,
        'base_fee_usd': base_fee,
        'gst_usd': gst,
        'total_fee_usd': base_fee + gst,
    }


def _quantity_is_increment_aligned(quantity: float, increment: float) -> bool:
    if not math.isfinite(quantity) or not math.isfinite(increment) or increment <= 0:
        return False
    units = quantity / increment
    return abs(units - round(units)) <= 1e-9 * max(1.0, abs(units))


def _quantity(strategy, spec, entry_price, entry_spot, balance, action: str = 'BUY'):
    """Return (quantity, required_cash_or_budget, rejection_reason).

    Exchange quantity validity is mandatory.  Budget enforcement is configurable:
    when ``enforce_trade_budget_strict`` is false, BUDGET mode may step up to the
    minimum valid quantity even if its premium-notional + entry fee exceeds the
    configured budget.  This does not model short-option margin.
    """
    cv = float(spec['contract_value'])
    increment = float(spec.get('size_increment') or 1)
    minimum = float(spec.get('min_quantity') or increment)
    if increment <= 0 or minimum <= 0:
        return 0.0, 0.0, 'INVALID_CONTRACT_QUANTITY_RULES'
    valid_minimum = math.ceil((minimum / increment) - 1e-12) * increment
    strict_budget = bool(getattr(strategy.risk, 'enforce_trade_budget_strict', True))

    def budget_cost(qty: float) -> float:
        fee = _delta_fee(entry_spot, entry_price, qty, cv, strategy.execution)['total_fee_usd']
        return entry_price * qty * cv + fee

    if strategy.risk.quantity_mode == 'FIXED':
        qty = float(strategy.risk.quantity)
        if qty + 1e-12 < minimum or not _quantity_is_increment_aligned(qty, increment):
            return 0.0, budget_cost(max(qty, 0.0)), 'INVALID_FIXED_QUANTITY'
        configured_cost = budget_cost(qty)
        if strict_budget and configured_cost > float(strategy.risk.budget_usd) + 1e-9:
            return 0.0, configured_cost, 'FIXED_QUANTITY_EXCEEDS_BUDGET'
    else:
        one_fee = _delta_fee(entry_spot, entry_price, 1.0, cv, strategy.execution)['total_fee_usd']
        one_total = entry_price * cv + one_fee
        raw_units = math.floor(float(strategy.risk.budget_usd) / max(one_total, 1e-12) / increment)
        qty = raw_units * increment
        if qty + 1e-12 < valid_minimum:
            required = budget_cost(valid_minimum)
            if strict_budget:
                return 0.0, required, 'MIN_QUANTITY_EXCEEDS_BUDGET'
            qty = valid_minimum
        configured_cost = budget_cost(qty)
        if strict_budget and configured_cost > float(strategy.risk.budget_usd) + 1e-9:
            return 0.0, configured_cost, 'TRADE_BUDGET_EXCEEDED'

    premium_cost = entry_price * qty * cv
    entry_fee = _delta_fee(entry_spot, entry_price, qty, cv, strategy.execution)['total_fee_usd']
    # Long options require premium + fee cash. Short-option margin is venue/account
    # specific and is intentionally not invented here; SELL checks entry fees only.
    cash_required = premium_cost + entry_fee if action == 'BUY' else entry_fee
    if strategy.risk.enforce_cash and cash_required > balance + 1e-9:
        return 0.0, cash_required, 'INSUFFICIENT_CASH'
    return qty, cash_required, None


def _dataset_fingerprint(paths) -> dict[str, Any]:
    items = paths if isinstance(paths, (list, tuple)) else [paths]
    out: dict[str, Any] = {}
    for item in items:
        entry: dict[str, Any] = {}
        for name in ('bars', 'instruments', 'quotes'):
            path = getattr(item, name, None)
            if path and path.exists():
                stat = path.stat()
                entry[name] = {'path': str(path.resolve()), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
        out[str(getattr(item, 'id', len(out)))] = entry
    return out


def _backtest_cache_key(req: BacktestRequest, paths) -> str:
    payload = {
        'engine_version': 156,  # orthogonal order/alert signal modes and existing-rule references
        'warmup_candles': req.warmup_candles,
        'warmup_policy': req.warmup_policy,
        'dataset': _dataset_fingerprint(paths),
        'dataset_id': getattr(req, 'dataset_id', None),
        'dataset_ids': [x.id for x in (paths if isinstance(paths, (list, tuple)) else [paths])],
        'dataset_mode': getattr(req, 'dataset_mode', 'SINGLE'),
        'start': req.start,
        'end': req.end,
        'strategy': req.strategy.model_dump(mode='json'),
        'storage_mode': getattr(req, 'storage_mode', 'ANALYSIS'),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _cached_result(key: str) -> dict[str, Any] | None:
    index = cache_root() / 'backtests' / f'{key}.json'
    if not index.exists():
        return None
    try:
        meta = json.loads(index.read_text(encoding='utf-8'))
        result = load_result(str(meta['run_id']))
        if result is None:
            return None
        result['cache_hit'] = True
        result['cache_key'] = key
        return result
    except Exception:
        return None


def _write_cache(key: str, run_id: str) -> None:
    root = cache_root() / 'backtests'
    root.mkdir(parents=True, exist_ok=True)
    (root / f'{key}.json').write_text(json.dumps({'run_id': run_id}), encoding='utf-8')


def _executable_exit_price(pos: Position, q: dict[str, Any], strategy) -> float:
    inc = float(pos.spec.get('price_increment') or 0.0)
    ticks = float(strategy.execution.slippage_ticks) * inc
    # Long option exits SELL at bid; short option exits BUY-to-close at ask.
    return max(0.0, float(q['bid']) - ticks) if pos.action == 'BUY' else float(q['ask']) + ticks


def _position_return_percent(pos: Position, exit_price: float) -> float:
    if pos.entry_price <= 0:
        return 0.0
    return ((exit_price - pos.entry_price) / pos.entry_price * 100.0) if pos.action == 'BUY' else ((pos.entry_price - exit_price) / pos.entry_price * 100.0)


def _stop_reason(pos: Position, q: dict[str, Any], strategy) -> tuple[str | None, float]:
    exit_price = _executable_exit_price(pos, q, strategy)
    ret = _position_return_percent(pos, exit_price)
    pos.peak_return = max(pos.peak_return, ret)
    pos.worst_return = min(pos.worst_return, ret)
    sl = strategy.risk.stop_loss
    if sl.mode == 'OPTION_PERCENT' and ret <= -abs(sl.value):
        return 'STOP_LOSS', ret
    if sl.mode == 'OPTION_POINTS':
        hit = exit_price <= pos.entry_price - abs(sl.value) if pos.action == 'BUY' else exit_price >= pos.entry_price + abs(sl.value)
        if hit:
            return 'STOP_LOSS', ret
    tp = strategy.risk.take_profit
    if tp.mode == 'OPTION_PERCENT' and ret >= abs(tp.value):
        return 'TAKE_PROFIT', ret
    if tp.mode == 'OPTION_POINTS':
        hit = exit_price >= pos.entry_price + abs(tp.value) if pos.action == 'BUY' else exit_price <= pos.entry_price - abs(tp.value)
        if hit:
            return 'TAKE_PROFIT', ret
    pp = strategy.risk.profit_protection
    if pp.mode != 'NONE' and pos.peak_return >= pp.activation_percent:
        floor = pos.peak_return * (pp.retain_peak_percent / 100.0) if pp.mode == 'PEAK_RETENTION' else pos.peak_return - pp.trail_percent_points
        if ret <= floor:
            return 'PROFIT_PROTECTION', ret
    return None, ret


def _flatten_decision(event_id: str, direction, ts, kind, tree, extra=None):
    return {
        'event_id': event_id,
        'timestamp': ts.isoformat(),
        'direction': direction,
        'kind': kind,
        'passed': bool(tree.get('passed')),
        'passed_count': tree.get('passed_count', 0),
        'total': tree.get('total', 0),
        'reason': (extra or {}).get('reason', ''),
        'details': json.dumps(tree, separators=(',', ':'), allow_nan=False),
        **(extra or {}),
    }


def _json_safe(obj):
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return None if not np.isfinite(obj) else float(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def _event_details(title: str, reason: str, **kwargs) -> dict[str, Any]:
    return _json_safe({'title': title, 'reason': reason, **kwargs})


@dataclass
class EntryCycleState:
    active: bool = False
    start_index: int | None = None
    entries: int = 0
    last_entry_index: int | None = None
    expired: bool = False

    def reset(self) -> None:
        self.active = False
        self.start_index = None
        self.entries = 0
        self.last_entry_index = None
        self.expired = False


def _trigger_tree(frame: pd.DataFrame, index: int, group, behavior) -> dict[str, Any]:
    if behavior.trigger_condition_id:
        condition = find_condition(group, behavior.trigger_condition_id)
        if condition is None:
            return {
                'mode': 'TRIGGER', 'passed': False, 'passed_count': 0, 'total': 1,
                'conditions': [], 'groups': [], 'reason': 'TRIGGER_CONDITION_NOT_FOUND',
            }
        evaluated = evaluate_condition(frame, index, condition)
        return {
            'mode': 'TRIGGER_CONDITION',
            'passed': bool(evaluated['passed']),
            'passed_count': 1 if evaluated['passed'] else 0,
            'total': 1,
            'conditions': [evaluated],
            'groups': [],
        }
    return evaluate_group(frame, index, group)


def _update_cycle(frame: pd.DataFrame, index: int, group, behavior, state: EntryCycleState) -> tuple[dict[str, Any], int, bool]:
    trigger = _trigger_tree(frame, index, group, behavior)
    if not behavior.enabled:
        state.reset()
        return trigger, 0, False
    if not trigger['passed']:
        state.reset()
        return trigger, 0, False
    if not state.active:
        state.active = True
        state.start_index = index
        state.entries = 0
        state.last_entry_index = None
        state.expired = False
    age = index - int(state.start_index if state.start_index is not None else index)
    if behavior.max_wait_bars is not None and age > behavior.max_wait_bars:
        state.expired = True
    delay_ready = age >= behavior.delay_bars
    return trigger, age, delay_ready


def _cycle_eligible(index: int, behavior, state: EntryCycleState, delay_ready: bool) -> tuple[bool, str]:
    if not behavior.enabled:
        return False, 'LIFECYCLE_DISABLED'
    if not state.active:
        return False, 'TRIGGER_INACTIVE'
    if state.expired:
        return False, 'ENTRY_WAIT_WINDOW_EXPIRED'
    if not delay_ready:
        return False, 'WAITING_ENTRY_DELAY'
    if state.entries >= behavior.max_entries_per_activation:
        return False, 'MAX_ENTRIES_FOR_ACTIVATION'
    if state.last_entry_index is not None and index - state.last_entry_index <= behavior.cooldown_bars:
        return False, 'ENTRY_COOLDOWN'
    return True, ''


def _entry_behaviors(strategy, direction: str):
    items = strategy.call_entry_lifecycles if direction == 'CALL' else strategy.put_entry_lifecycles
    if items:
        return [item for item in items if item.enabled]
    legacy = strategy.call_entry_behavior if direction == 'CALL' else strategy.put_entry_behavior
    return [legacy] if legacy.enabled else []


def _cycle_states(behaviors) -> dict[str, EntryCycleState]:
    return {behavior.id: EntryCycleState() for behavior in behaviors}


def _update_lifecycles(frame: pd.DataFrame, index: int, group, behaviors, states: dict[str, EntryCycleState]):
    rows = []
    for behavior in behaviors:
        state = states.setdefault(behavior.id, EntryCycleState())
        trigger, age, delay_ready = _update_cycle(frame, index, group, behavior, state)
        eligible, reason = _cycle_eligible(index, behavior, state, delay_ready)
        rows.append({
            'behavior': behavior, 'state': state, 'trigger': trigger, 'age': age,
            'delay_ready': delay_ready, 'eligible': eligible, 'reason': reason,
        })
    return rows


def _lifecycle_summary(rows) -> dict[str, Any]:
    active = [x for x in rows if x['state'].active]
    eligible = [x for x in rows if x['eligible']]
    return {
        'trigger_passed': any(bool(x['trigger'].get('passed')) for x in rows),
        'activation_age_bars': max((int(x['age']) for x in active), default=0),
        'entry_delay_bars': min((int(x['behavior'].delay_bars) for x in rows), default=0),
        'entries_in_activation': sum(int(x['state'].entries) for x in active),
        'max_entries_per_activation': sum(int(x['behavior'].max_entries_per_activation) for x in rows),
        'lifecycle_reason': '' if eligible else (';'.join(dict.fromkeys(x['reason'] for x in rows if x['reason'])) or 'NO_ENABLED_LIFECYCLE'),
        'eligible_lifecycle_ids': ','.join(x['behavior'].id for x in eligible),
        'active_lifecycle_ids': ','.join(x['behavior'].id for x in active),
        'lifecycle_states': json.dumps([
            {
                'id': x['behavior'].id, 'name': x['behavior'].name,
                'trigger_passed': bool(x['trigger'].get('passed')),
                'age_bars': int(x['age']), 'delay_bars': int(x['behavior'].delay_bars),
                'max_wait_bars': x['behavior'].max_wait_bars,
                'entries': int(x['state'].entries),
                'max_entries': int(x['behavior'].max_entries_per_activation),
                'expired': bool(x['state'].expired), 'eligible': bool(x['eligible']),
                'reason': x['reason'],
            } for x in rows
        ], separators=(',', ':')),
    }


def _component_fraction(evaluated: dict[str, Any], component) -> float:
    if getattr(component, 'scoring_mode', 'BINARY') != 'CONTINUOUS':
        return 1.0 if evaluated.get('passed') else 0.0
    value = _finite(evaluated.get('left_actual'))
    zero = _finite(getattr(component, 'zero_at', None))
    full = _finite(getattr(component, 'full_at', None))
    if value is None or zero is None or full is None or math.isclose(zero, full):
        return 0.0
    # Works for both higher-is-better (full > zero) and lower-is-better
    # (full < zero), then clamps beyond either endpoint.
    return max(0.0, min(1.0, (value - zero) / (full - zero)))


def _big_trend_raw_score(frame: pd.DataFrame, index: int, group, cfg) -> dict[str, Any]:
    if not cfg.enabled:
        return {'enabled': False, 'score': None, 'threshold': cfg.threshold, 'passed': True, 'components': []}
    rows=[]; total=0.0; earned=0.0
    for component in cfg.components:
        condition=find_condition(group, component.condition_id)
        if condition is None:
            continue
        evaluated=evaluate_condition(frame,index,condition)
        weight=float(component.weight)
        fraction=_component_fraction(evaluated, component)
        contribution=weight*fraction
        total += weight
        earned += contribution
        rows.append({
            'condition_id':component.condition_id,
            'weight':weight,
            'scoring_mode':getattr(component,'scoring_mode','BINARY'),
            'zero_at':getattr(component,'zero_at',None),
            'full_at':getattr(component,'full_at',None),
            'fraction':fraction,
            'earned_weight':contribution,
            'passed':bool(evaluated['passed']),
            'details':evaluated,
        })
    score=(earned/total*100.0) if total>0 else 0.0
    return {'enabled':True,'score':score,'threshold':float(cfg.threshold),'passed':score>=float(cfg.threshold),'components':rows}


def _prepare_big_trend_columns(frame: pd.DataFrame, strategy) -> None:
    """Materialize directional scores so score itself can be a rule operand.

    This happens before the main strategy tree is evaluated. Score components are
    validated to avoid circular references back into these derived strategy-state
    columns. Persistence is based only on completed strategy candles.
    """
    for side, group, cfg in (
        ('call', strategy.call_entry, strategy.call_big_trend_score),
        ('put', strategy.put_entry, strategy.put_big_trend_score),
    ):
        score_key=f'{side}_big_trend_score'
        hit_key=f'{side}_big_trend_score_hit'
        count_key=f'{side}_big_trend_score_persistence_count'
        pass_key=f'{side}_big_trend_score_persisted'
        if not cfg.enabled:
            frame[score_key]=0.0
            frame[hit_key]=0.0
            frame[count_key]=0.0
            frame[pass_key]=0.0
            continue
        scores=[]
        for i in range(len(frame)):
            scores.append(float(_big_trend_raw_score(frame,i,group,cfg)['score'] or 0.0))
        score_series=pd.Series(scores,index=frame.index,dtype=float)
        hit=(score_series >= float(cfg.threshold)).astype(float)
        count=hit.rolling(window=int(cfg.persistence_window),min_periods=1).sum()
        persisted=(count >= int(cfg.persistence_hits))
        if cfg.require_current_threshold:
            persisted = persisted & (hit > 0.5)
        frame[score_key]=score_series
        frame[hit_key]=hit
        frame[count_key]=count.astype(float)
        frame[pass_key]=persisted.astype(float)


def _big_trend_score(frame: pd.DataFrame, index: int, group, cfg, side: str | None = None) -> dict[str, Any]:
    raw=_big_trend_raw_score(frame,index,group,cfg)
    if not cfg.enabled:
        return raw
    if side:
        prefix=side.lower()
        score_key=f'{prefix}_big_trend_score'
        count_key=f'{prefix}_big_trend_score_persistence_count'
        pass_key=f'{prefix}_big_trend_score_persisted'
        if score_key in frame.columns:
            raw['score']=_finite(frame.iloc[index][score_key]) or 0.0
            raw['persistence_count']=int(_finite(frame.iloc[index][count_key]) or 0) if count_key in frame.columns else 0
            raw['persistence_hits']=int(cfg.persistence_hits)
            raw['persistence_window']=int(cfg.persistence_window)
            raw['require_current_threshold']=bool(cfg.require_current_threshold)
            raw['passed']=bool((_finite(frame.iloc[index][pass_key]) or 0.0) > 0.5) if pass_key in frame.columns else raw['passed']
    return raw


@dataclass
class BreakoutMemory:
    active: bool = False
    waiting_rearm: bool = False
    trigger_prev: bool = False
    breakout_index: int | None = None
    breakout_level: float | None = None
    breakout_price: float | None = None
    retest_seen: bool = False
    retest_ready: bool = False
    hold_count: int = 0


def _strategy_operand(frame: pd.DataFrame, index: int, operand: str | None) -> float | None:
    if not operand or operand not in frame.columns or index < 0 or index >= len(frame):
        return None
    return _finite(frame.iloc[index][operand])


def _breakout_tolerance(frame: pd.DataFrame, index: int, cfg, level: float) -> float | None:
    if cfg.tolerance_mode == 'POINTS':
        return float(cfg.tolerance_value)
    if cfg.tolerance_mode == 'PERCENT':
        return abs(float(level)) * float(cfg.tolerance_value) / 100.0
    atr=_strategy_operand(frame,index,cfg.atr_operand)
    return None if atr is None else abs(atr) * float(cfg.tolerance_value)


def _prepare_breakout_columns(frame: pd.DataFrame, strategy, side: str) -> None:
    direction=side.upper()
    group=strategy.call_entry if direction=='CALL' else strategy.put_entry
    cfg=strategy.call_breakout_retest if direction=='CALL' else strategy.put_breakout_retest
    prefix=side.lower()
    keys={
        'level':f'{prefix}_breakout_level',
        'price':f'{prefix}_breakout_price',
        'age':f'{prefix}_bars_since_breakout',
        'active':f'{prefix}_breakout_active',
        'retest_seen':f'{prefix}_retest_seen',
        'retest_ready':f'{prefix}_retest_ready',
        'false':f'{prefix}_false_breakout',
        'blocked':f'{prefix}_breakout_blocked',
        'too_old':f'{prefix}_trend_too_old',
    }
    if not cfg.enabled:
        frame[keys['level']]=np.nan; frame[keys['price']]=np.nan; frame[keys['age']]=np.nan
        for k in ('active','retest_seen','retest_ready','false','blocked','too_old'):
            frame[keys[k]]=0.0
        return
    condition=find_condition(group,cfg.breakout_condition_id or '')
    if condition is None:
        raise ValueError(f'{direction} breakout condition {cfg.breakout_condition_id!r} was not found')
    if cfg.breakout_level_operand not in frame.columns:
        raise ValueError(f'{direction} breakout level operand {cfg.breakout_level_operand!r} is unavailable in the computed frame')
    if cfg.tolerance_mode=='ATR' and cfg.atr_operand not in frame.columns:
        raise ValueError(f'{direction} breakout ATR operand {cfg.atr_operand!r} is unavailable in the computed frame')

    state=BreakoutMemory()
    out={name:[] for name in keys}
    for i in range(len(frame)):
        trigger=bool(evaluate_condition(frame,i,condition).get('passed'))
        false_now=False
        # A false breakout blocks fresh snapshots until the trigger has actually
        # reset false. Once reset, the next fresh trigger may arm a new breakout.
        if state.waiting_rearm and not trigger:
            state.waiting_rearm=False
            state.active=False
            state.breakout_index=None
            state.breakout_level=None
            state.breakout_price=None
            state.retest_seen=False
            state.retest_ready=False
            state.hold_count=0

        fresh_trigger=trigger and not state.trigger_prev and not state.waiting_rearm
        if fresh_trigger:
            level=_strategy_operand(frame,i,cfg.breakout_level_operand)
            price=_strategy_operand(frame,i,'close')
            if level is not None and price is not None:
                state.active=True
                state.breakout_index=i
                state.breakout_level=level
                state.breakout_price=price
                state.retest_seen=False
                state.retest_ready=False
                state.hold_count=0

        age=(i-state.breakout_index) if state.active and state.breakout_index is not None else None
        level=state.breakout_level
        if state.active and level is not None and age is not None and age >= 1:
            close=_strategy_operand(frame,i,'close')
            high=_strategy_operand(frame,i,'high')
            low=_strategy_operand(frame,i,'low')
            buffer=float(cfg.false_breakout_buffer_points)
            if close is not None and age <= int(cfg.false_breakout_window_bars):
                false_now=(close < level-buffer) if direction=='CALL' else (close > level+buffer)
            if false_now:
                state.retest_ready=False
                state.retest_seen=False
                state.hold_count=0
                if cfg.block_false_breakout_until_rearm:
                    state.waiting_rearm=True
                    state.active=False
            elif age <= int(cfg.max_retest_wait_bars) and not state.retest_ready:
                tol=_breakout_tolerance(frame,i,cfg,level)
                if tol is not None and None not in (close,high,low):
                    touched=(low <= level+tol and close >= level-tol) if direction=='CALL' else (high >= level-tol and close <= level+tol)
                    if touched:
                        state.retest_seen=True
                    if state.retest_seen:
                        held=(close >= level-buffer) if direction=='CALL' else (close <= level+buffer)
                        state.hold_count = state.hold_count + 1 if held else 0
                        if state.hold_count >= int(cfg.hold_bars):
                            state.retest_ready=True

        age=(i-state.breakout_index) if state.active and state.breakout_index is not None else None
        too_old=bool(age is not None and cfg.max_trend_age_bars is not None and age > int(cfg.max_trend_age_bars))
        values={
            'level':state.breakout_level if state.breakout_level is not None else np.nan,
            'price':state.breakout_price if state.breakout_price is not None else np.nan,
            'age':float(age) if age is not None else np.nan,
            'active':1.0 if state.active else 0.0,
            'retest_seen':1.0 if state.retest_seen else 0.0,
            'retest_ready':1.0 if state.retest_ready else 0.0,
            'false':1.0 if false_now else 0.0,
            'blocked':1.0 if state.waiting_rearm else 0.0,
            'too_old':1.0 if too_old else 0.0,
        }
        for name in keys: out[name].append(values[name])
        state.trigger_prev=trigger
    for name,key in keys.items(): frame[key]=out[name]


def _prepare_trend_phase_columns(frame: pd.DataFrame, strategy, side: str) -> None:
    cfg=strategy.call_trend_phase if side.upper()=='CALL' else strategy.put_trend_phase
    prefix=side.lower()
    score_key=f'{prefix}_big_trend_score'
    phase_key=f'{prefix}_trend_phase_code'
    names=['compression','ignition','confirmation','big_trend','exhaustion']
    if not cfg.enabled:
        frame[phase_key]=0.0
        for name in names: frame[f'{prefix}_phase_{name}']=0.0
        return
    if score_key not in frame.columns:
        raise ValueError(f'{side.upper()} trend phase requires Big Trend Score columns')
    phase='COMPRESSION'; phases=[]; prev_score=0.0
    for i in range(len(frame)):
        score=_finite(frame.iloc[i][score_key]) or 0.0
        persisted=bool((_finite(frame.iloc[i].get(f'{prefix}_big_trend_score_persisted',0.0)) or 0.0)>0.5)
        too_old=bool((_finite(frame.iloc[i].get(f'{prefix}_trend_too_old',0.0)) or 0.0)>0.5)
        if phase=='COMPRESSION':
            if score >= float(cfg.ignition_min_score): phase='IGNITION'
        elif phase=='IGNITION':
            if score <= float(cfg.compression_max_score): phase='COMPRESSION'
            elif score >= float(cfg.confirmation_min_score): phase='CONFIRMATION'
        elif phase=='CONFIRMATION':
            if score <= float(cfg.exhaustion_below_score) or too_old: phase='EXHAUSTION'
            elif score >= float(cfg.big_trend_min_score) and persisted: phase='BIG_TREND'
        elif phase=='BIG_TREND':
            if score <= float(cfg.exhaustion_below_score) or too_old: phase='EXHAUSTION'
        elif phase=='EXHAUSTION':
            if score <= float(cfg.compression_max_score): phase='COMPRESSION'
            elif score >= float(cfg.ignition_min_score) and prev_score < float(cfg.ignition_min_score): phase='IGNITION'
        phases.append(phase); prev_score=score
    code={'COMPRESSION':0.0,'IGNITION':1.0,'CONFIRMATION':2.0,'BIG_TREND':3.0,'EXHAUSTION':4.0}
    frame[phase_key]=[code[x] for x in phases]
    for name in names:
        target=name.upper()
        frame[f'{prefix}_phase_{name}']=[1.0 if x==target else 0.0 for x in phases]


def _prepare_strategy_state(frame: pd.DataFrame, strategy) -> None:
    _prepare_big_trend_columns(frame,strategy)
    _prepare_breakout_columns(frame,strategy,'call')
    _prepare_breakout_columns(frame,strategy,'put')
    _prepare_trend_phase_columns(frame,strategy,'call')
    _prepare_trend_phase_columns(frame,strategy,'put')


def _breakout_gate_reason(frame: pd.DataFrame, index: int, direction: str, strategy) -> str:
    cfg=strategy.call_breakout_retest if direction=='CALL' else strategy.put_breakout_retest
    if not cfg.enabled:
        return ''
    prefix=direction.lower()
    def flag(name): return bool((_strategy_operand(frame,index,f'{prefix}_{name}') or 0.0)>0.5)
    age=_strategy_operand(frame,index,f'{prefix}_bars_since_breakout')
    if cfg.block_false_breakout_until_rearm and flag('breakout_blocked'):
        return 'FALSE_BREAKOUT_BLOCKED'
    if cfg.max_trend_age_bars is not None and age is not None and age > int(cfg.max_trend_age_bars):
        return 'TREND_TOO_OLD'
    if cfg.require_retest_for_entry and not flag('retest_ready'):
        return 'WAITING_FOR_RETEST'
    return ''


def _fee_edge_check(strategy, spec: dict[str, Any], quote: dict[str, Any], spot: float, entry: float, qty: float) -> tuple[bool,str,dict[str,Any]]:
    cfg=strategy.execution.fee_edge_filter
    if not cfg.enabled:
        return True,'',{}
    stats=_quote_stats(quote); bid=stats['bid']; ask=stats['ask']; mid=stats['mid']
    if None in (bid,ask,mid) or mid is None or mid <= 0:
        return False,'EDGE_FILTER_NO_BBO',{}
    cv=float(spec['contract_value'])
    expected_move_usd=float(mid)*float(cfg.expected_option_move_percent)/100.0*float(qty)*cv
    spread_cost_usd=max(0.0,float(ask)-float(bid))*float(qty)*cv
    entry_fee=_delta_fee(spot,entry,qty,cv,strategy.execution)['total_fee_usd']
    # Estimate the exit fee at a premium after the user's assumed favorable move.
    exit_premium=max(float(spec.get('price_increment') or 1e-9), float(entry)*(1.0+float(cfg.expected_option_move_percent)/100.0))
    exit_fee=_delta_fee(spot,exit_premium,qty,cv,strategy.execution)['total_fee_usd']
    friction=spread_cost_usd+entry_fee+exit_fee
    required=friction*float(cfg.min_edge_multiple)+float(cfg.min_net_edge_usd)
    details={
        'expected_option_move_percent':float(cfg.expected_option_move_percent),
        'expected_move_usd':expected_move_usd,
        'spread_cost_usd':spread_cost_usd,
        'estimated_entry_fee_usd':entry_fee,
        'estimated_exit_fee_usd':exit_fee,
        'estimated_friction_usd':friction,
        'min_edge_multiple':float(cfg.min_edge_multiple),
        'min_net_edge_usd':float(cfg.min_net_edge_usd),
        'required_expected_move_usd':required,
    }
    return (expected_move_usd+1e-12 >= required),('' if expected_move_usd+1e-12>=required else 'INSUFFICIENT_FEE_ADJUSTED_EDGE'),details

def _score_entry_pass(tree: dict[str, Any], score: dict[str, Any], cfg) -> bool:
    if not cfg.enabled:
        return bool(tree.get('passed'))
    if cfg.mode == 'SCORE_ONLY':
        return bool(score['passed'])
    return bool(tree.get('passed')) and bool(score['passed'])


def _entry_ignore_ids(strategy, direction: str) -> set[str] | None:
    cfg=strategy.call_breakout_retest if direction=='CALL' else strategy.put_breakout_retest
    if cfg.enabled and cfg.require_retest_for_entry and cfg.breakout_condition_id:
        return {cfg.breakout_condition_id}
    return None


def _mark_to_market_value(pos: Position, q: dict[str, Any], cash_balance: float, strategy, spot: float) -> float:
    """Quote-observed liquidation equity, including spread, slippage and modeled fees.

    Synthetic quote sizes / liquidity are NOT validated by this diagnostic.
    """
    px = _executable_exit_price(pos, q, strategy)
    cv = float(pos.spec['contract_value'])
    direction = 1.0 if pos.action == 'BUY' else -1.0
    pnl = direction * (px - pos.entry_price) * pos.quantity * cv
    exit_fee = _delta_fee(spot, px, pos.quantity, cv, strategy.execution)['total_fee_usd']
    return cash_balance + pnl - pos.entry_fee - exit_fee


def run_backtest(req: BacktestRequest, progress: Callable[..., None] | None = None) -> dict[str, Any]:
    store = DataStore()

    def report(message: str, percent: float | None = None, stage: str | None = None, next_step: str | None = None):
        if not progress:
            return
        try:
            progress(message, percent, stage, next_step)
        except TypeError:
            progress(message)

    if parse_time(req.end) <= parse_time(req.start):
        raise ValueError('Backtest end must be after start')

    if getattr(req, 'dataset_mode', 'SINGLE') == 'ARCHIVE' and getattr(req, 'auto_download_missing_data', False):
        report('Checking unified archive for missing completed history…', 2, 'DATA_SYNC', 'Resolve archive segments')
        ensure_archive_data(req.start, req.end, report)
        # Catalog/files may have changed, so use a fresh store after sync.
        store.close()
        store = DataStore()

    report('Resolving downloaded datasets…', 9 if getattr(req, 'auto_download_missing_data', False) else 2, 'DATA_SELECTION', 'Preflight data validation')
    needs_options = any(
        direction in {'CALL', 'PUT'} and
        (req.strategy.call_signal_mode if direction == 'CALL' else req.strategy.put_signal_mode) != 'ALERT_ONLY'
        for direction in (['CALL', 'PUT'] if req.strategy.direction_mode == 'BOTH' else [req.strategy.direction_mode])
    )
    parts = store.resolve_request(req, require_options=needs_options)

    # Cache lookup happens before expensive CSV preflight. The key fingerprints
    # every selected source file, so a cached result is reused only while the
    # downloaded inputs remain byte/mtime-identical.
    warmup_count = required_warmup_candles(
        req.strategy.indicators, req.strategy.timeframe,
        minimum=getattr(req, 'warmup_candles', 500), strategy=req.strategy,
    )
    bar_parts = historical_bar_sources(
        store, parts, req.start, req.strategy.timeframe, warmup_count,
        archive_neighbors=getattr(req, 'dataset_mode', 'SINGLE') in {'ARCHIVE', 'AUTO'},
    )
    cache_key = _backtest_cache_key(req, bar_parts)
    cached = _cached_result(cache_key)
    if cached is not None:
        report(f"Cache hit — reused identical V15.1 backtest {cached.get('run_id', '')}.", 100, 'CACHE_HIT', 'Complete')
        return cached

    report('Checking bars, option instruments and quote files before backtesting…', 5, 'PREFLIGHT', 'Load bars')
    preflight = store.preflight(
        parts, req.start, req.end, req.strategy,
        lambda msg: report(msg, 7, 'PREFLIGHT', 'Load bars'),
    )
    if not preflight['ok']:
        raise ValueError('Preflight failed: ' + '; '.join(preflight['errors']))

    report('Loading and merging underlying bars…', 12, 'LOAD_BARS', 'Load option instruments')
    bars = store.load_bars_many(bar_parts, req.start, req.end, req.strategy.timeframe, warmup_candles=warmup_count)
    warmup = warmup_diagnostics(bars, req.start, req.strategy.timeframe, warmup_count)
    if not warmup['contiguous']:
        if getattr(req, 'warmup_policy', 'WARN') == 'REQUIRE':
            raise ValueError(f"Insufficient contiguous warm-up: need {warmup_count} "
                             f"{req.strategy.timeframe} candles before {req.start}")
        preflight.setdefault('warnings', []).append(
            f"Incomplete indicator warm-up: {warmup['available_candles']} earlier candles "
            f"(need {warmup_count} contiguous). Early values/signals can vary with selected range."
        )
    report('Loading and de-duplicating option instruments…', 18, 'LOAD_INSTRUMENTS', 'Calculate indicators')
    inst = store.load_instruments_many(parts) if needs_options else pd.DataFrame()
    report('Calculating selected indicators and V15.1 trend state…', 25, 'INDICATORS', 'Prepare option quote indexes')
    strategy = req.strategy
    frame, series_meta = compute_indicators(bars, strategy.indicators, strategy.timeframe)
    _prepare_strategy_state(frame, strategy)
    report('Preparing reusable option quote indexes…', 32, 'QUOTE_INDEX', 'Evaluate strategy candles')
    if needs_options:
        store.ensure_indexes(parts, lambda msg: report(msg, 32, 'QUOTE_INDEX', 'Evaluate strategy candles'))

    balance = float(strategy.risk.starting_balance_usd)
    equity = balance
    peak_equity = equity
    max_dd = 0.0
    max_dd_percent = 0.0
    mtm_peak = balance
    mtm_max_dd = 0.0
    mtm_max_dd_percent = 0.0
    mtm_low = balance
    mtm_samples = 0
    equity_curve: list[dict[str, Any]] = [{
        'timestamp': req.start,
        'equity_usd': equity,
        'peak_equity_usd': peak_equity,
        'drawdown_usd': 0.0,
        'drawdown_percent': 0.0,
    }]
    trades: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    alert_events = alert_markers(frame, strategy, req.start, req.end)
    markers: list[dict[str, Any]] = list(alert_events)
    pos: Position | None = None
    pos_quotes = None
    q_cursor = 0
    end_dt = parse_time(req.end)
    atr_keys = sorted(
        m['key'] for m in series_meta
        if m['kind'] == 'ATR'
        and not next((i.chart_only for i in strategy.indicators if i.id == m['instance_id']), False)
    )
    event_counter = 0
    call_enabled = strategy.direction_mode in {'CALL', 'BOTH'} and strategy.call_signal_mode != 'ALERT_ONLY'
    put_enabled = strategy.direction_mode in {'PUT', 'BOTH'} and strategy.put_signal_mode != 'ALERT_ONLY'
    call_behaviors = _entry_behaviors(strategy, 'CALL') if call_enabled else []
    put_behaviors = _entry_behaviors(strategy, 'PUT') if put_enabled else []
    call_cycles = _cycle_states(call_behaviors)
    put_cycles = _cycle_states(put_behaviors)
    consumed_breakout_origin: dict[str, int | None] = {'CALL': None, 'PUT': None}
    daily_state = {
        'date': None, 'start_balance': balance, 'realized_pnl': 0.0,
        'entries': 0, 'consecutive_losses': 0, 'blocked_count': 0,
    }

    def ensure_daily_state(ts_like):
        dt = parse_time(ts_like) if isinstance(ts_like, str) else ts_like.to_pydatetime() if hasattr(ts_like, 'to_pydatetime') else ts_like
        local = dt.astimezone(ZoneInfo(strategy.session.timezone))
        key = local.date().isoformat()
        if daily_state['date'] != key:
            daily_state.update({'date': key, 'start_balance': balance, 'realized_pnl': 0.0, 'entries': 0, 'consecutive_losses': 0})
        return key

    def daily_block_reason() -> str:
        r = strategy.risk
        if r.max_trades_per_day is not None and int(daily_state['entries']) >= int(r.max_trades_per_day):
            return 'MAX_TRADES_PER_DAY'
        if r.max_consecutive_losses is not None and int(daily_state['consecutive_losses']) >= int(r.max_consecutive_losses):
            return 'MAX_CONSECUTIVE_LOSSES'
        if r.max_daily_loss_percent is not None and r.stop_trading_after_daily_loss_limit:
            limit = float(daily_state['start_balance']) * float(r.max_daily_loss_percent) / 100.0
            if float(daily_state['realized_pnl']) <= -limit:
                return 'MAX_DAILY_LOSS'
        return ''

    def next_event(prefix: str) -> str:
        nonlocal event_counter
        event_counter += 1
        return f'{prefix}-{event_counter}'

    def add_marker(ts_text: str, kind: str, direction: str, text: str, details: dict[str, Any], pnl_usd: float | None = None):
        markers.append({
            'id': next_event(kind),
            'time': int(parse_time(ts_text).timestamp()),
            'timestamp': ts_text,
            'kind': kind,
            'direction': direction,
            'text': text,
            'pnl_usd': pnl_usd,
            'details': _json_safe(details),
        })

    def spot_at(timestamp_text: str) -> float:
        target = pd.Timestamp(parse_time(timestamp_text))
        eligible = frame.loc[frame.index <= target, 'close']
        if len(eligible):
            return float(eligible.iloc[-1])
        return float(frame.iloc[0].close)

    def record_mtm_value(marked: float):
        nonlocal mtm_peak, mtm_max_dd, mtm_max_dd_percent, mtm_low, mtm_samples
        mtm_peak = max(mtm_peak, marked)
        dd = max(0.0, mtm_peak - marked)
        mtm_max_dd = max(mtm_max_dd, dd)
        if mtm_peak > 0:
            mtm_max_dd_percent = max(mtm_max_dd_percent, dd / mtm_peak * 100.0)
        mtm_low = min(mtm_low, marked)
        mtm_samples += 1

    def record_mtm(q: dict[str, Any], stamp: str):
        if pos is not None:
            record_mtm_value(_mark_to_market_value(pos, q, balance, strategy, spot_at(stamp)))

    def close_position(exit_time: str, exit_price: float, reason: str, exit_rule: dict[str, Any] | None = None):
        nonlocal pos, balance, equity, peak_equity, max_dd, max_dd_percent, pos_quotes, q_cursor
        assert pos
        cv = float(pos.spec['contract_value'])
        exit_spot = spot_at(exit_time)
        exit_fee_details = _delta_fee(exit_spot, exit_price, pos.quantity, cv, strategy.execution)
        exit_fee = exit_fee_details['total_fee_usd']
        gross = ((exit_price - pos.entry_price) if pos.action == 'BUY' else (pos.entry_price - exit_price)) * pos.quantity * cv
        net = gross - pos.entry_fee - exit_fee
        record_mtm_value(balance + net)
        balance += net
        equity = balance
        peak_equity = max(peak_equity, equity)
        current_dd = peak_equity - equity
        current_dd_percent = (current_dd / peak_equity * 100.0) if peak_equity > 0 else 0.0
        max_dd = max(max_dd, current_dd)
        max_dd_percent = max(max_dd_percent, current_dd_percent)
        equity_curve.append({
            'timestamp': exit_time,
            'equity_usd': equity,
            'peak_equity_usd': peak_equity,
            'drawdown_usd': current_dd,
            'drawdown_percent': current_dd_percent,
        })
        ret = _position_return_percent(pos, exit_price)
        holding_minutes = (parse_time(exit_time) - parse_time(pos.entry_time)).total_seconds() / 60.0
        trade = {
            'id': len(trades) + 1,
            'direction': pos.direction,
            'action': pos.action,
            'symbol': pos.symbol,
            'signal_time': pos.signal_time,
            'entry_time': pos.entry_time,
            'exit_time': exit_time,
            'entry_spot': pos.entry_spot,
            'exit_spot': exit_spot,
            'entry_price': pos.entry_price,
            'exit_price': exit_price,
            'entry_execution_side': 'ASK' if pos.action == 'BUY' else 'BID',
            'exit_execution_side': 'BID' if pos.action == 'BUY' else 'ASK',
            # Legacy aliases kept for existing V1-V8 analysis/UI imports.
            'entry_ask': pos.entry_price,
            'exit_bid': exit_price,
            'quantity': pos.quantity,
            'contract_value': cv,
            'gross_pnl_usd': gross,
            'entry_notional_fee_usd': pos.entry_fee_details['notional_fee_usd'],
            'entry_premium_cap_usd': pos.entry_fee_details['premium_cap_usd'],
            'entry_base_fee_usd': pos.entry_fee_details['base_fee_usd'],
            'entry_gst_usd': pos.entry_fee_details['gst_usd'],
            'entry_fee_usd': pos.entry_fee,
            'exit_notional_fee_usd': exit_fee_details['notional_fee_usd'],
            'exit_premium_cap_usd': exit_fee_details['premium_cap_usd'],
            'exit_base_fee_usd': exit_fee_details['base_fee_usd'],
            'exit_gst_usd': exit_fee_details['gst_usd'],
            'exit_fee_usd': exit_fee,
            'base_fees_usd': pos.entry_fee_details['base_fee_usd'] + exit_fee_details['base_fee_usd'],
            'gst_usd': pos.entry_fee_details['gst_usd'] + exit_fee_details['gst_usd'],
            'fees_usd': pos.entry_fee + exit_fee,
            'net_pnl_usd': net,
            'return_percent': ret,
            'mfe_percent': pos.peak_return,
            'mae_percent': pos.worst_return,
            'holding_minutes': holding_minutes,
            'exit_reason': reason,
            'entry_lifecycle_id': pos.entry_lifecycle_id,
            'entry_lifecycle_name': pos.entry_lifecycle_name,
        }
        trades.append(trade)
        ensure_daily_state(exit_time)
        daily_state['realized_pnl'] = float(daily_state['realized_pnl']) + net
        daily_state['consecutive_losses'] = (int(daily_state['consecutive_losses']) + 1) if net < 0 else 0
        add_marker(
            exit_time,
            'exit',
            pos.direction,
            f'EXIT {pos.action} {reason} {net:+.2f}',
            _event_details(
                'Exit', reason,
                action=pos.action,
                symbol=pos.symbol,
                entry_price=pos.entry_price,
                exit_price=exit_price,
                entry_ask=pos.entry_price,  # legacy visualizer tooltip alias
                exit_bid=exit_price,       # legacy visualizer tooltip alias
                entry_execution_side='ASK' if pos.action == 'BUY' else 'BID',
                exit_execution_side='BID' if pos.action == 'BUY' else 'ASK',
                entry_spot=pos.entry_spot,
                exit_spot=exit_spot,
                gross_pnl_usd=gross,
                entry_fee_usd=pos.entry_fee,
                exit_fee_usd=exit_fee,
                gst_usd=pos.entry_fee_details['gst_usd'] + exit_fee_details['gst_usd'],
                total_fees_usd=pos.entry_fee + exit_fee,
                return_percent=ret,
                net_pnl_usd=net,
                mfe_percent=pos.peak_return,
                mae_percent=pos.worst_return,
                holding_minutes=holding_minutes,
                exit_rule=exit_rule,
            ),
            net,
        )
        pos = None
        pos_quotes = None
        q_cursor = 0

    measured_start = pd.Timestamp(parse_time(req.start))
    for i, (ts, row) in enumerate(frame.iterrows()):
        # Warm-up initializes indicators/strategy state; never trades before From.
        if ts < measured_start:
            continue
        ensure_daily_state(ts)
        if i and i % max(250, len(frame)//100 or 1) == 0:
            pct = 35.0 + (i / max(1, len(frame))) * 50.0
            report(f'Evaluated {i:,}/{len(frame):,} candles…', pct, 'BACKTEST_LOOP', 'Finalize metrics and write result files')

        closed_this_candle = False

        # V8 explicit exclusivity: while a position is open, the opposite entry
        # side is not evaluated. All lifecycles belonging to the active side are
        # still updated so each trigger can independently reset/rearm.
        if pos is not None:
            if pos.direction == 'CALL':
                _update_lifecycles(frame, i, strategy.call_entry, call_behaviors, call_cycles)
            else:
                _update_lifecycles(frame, i, strategy.put_entry, put_behaviors, put_cycles)

        # Quote-driven protective exits up to this completed candle.
        if pos is not None and pos_quotes is not None:
            while q_cursor < len(pos_quotes) and pos_quotes.iloc[q_cursor].timestamp <= ts:
                q = pos_quotes.iloc[q_cursor].to_dict()
                q_cursor += 1
                record_mtm(q, pd.Timestamp(q['timestamp']).isoformat())
                reason, _ = _stop_reason(pos, q, strategy)
                if reason:
                    close_position(pd.Timestamp(q['timestamp']).isoformat(), _executable_exit_price(pos, q, strategy), reason)
                    closed_this_candle = True
                    break

        if pos is not None:
            sl = strategy.risk.stop_loss
            if sl.mode == 'UNDERLYING_ATR' and pos.entry_atr and pos.entry_atr > 0:
                distance = sl.value * pos.entry_atr
                if pos.direction == 'CALL':
                    hit = row.close <= pos.entry_spot - distance if pos.action == 'BUY' else row.close >= pos.entry_spot + distance
                else:
                    hit = row.close >= pos.entry_spot + distance if pos.action == 'BUY' else row.close <= pos.entry_spot - distance
                if hit:
                    q = store.first_quote_many(parts, pos.symbol, ts.isoformat(), strategy.execution.max_exit_quote_delay_seconds)
                    if q:
                        close_position(q['timestamp'], _executable_exit_price(pos, q, strategy), 'UNDERLYING_ATR_STOP')
                        closed_this_candle = True

            if pos is not None and strategy.risk.max_hold_minutes is not None:
                if (ts.to_pydatetime() - parse_time(pos.entry_time)).total_seconds() >= strategy.risk.max_hold_minutes * 60:
                    q = store.first_quote_many(parts, pos.symbol, ts.isoformat(), strategy.execution.max_exit_quote_delay_seconds)
                    if q:
                        close_position(q['timestamp'], _executable_exit_price(pos, q, strategy), 'TIME_STOP')
                        closed_this_candle = True

            if pos is not None:
                exit_group = strategy.call_exit if pos.direction == 'CALL' else strategy.put_exit
                if exit_group.configured() and (strategy.call_exit_signal_mode if pos.direction == 'CALL' else strategy.put_exit_signal_mode) != 'ALERT_ONLY':
                    tree = evaluate_group(frame, i, exit_group)
                    if strategy.execution.decision_log_mode == 'FULL' or tree['passed']:
                        decisions.append(_flatten_decision(next_event('decision'), pos.direction, ts, 'EXIT', tree, {'close': _finite(row.close)}))
                    if tree['passed']:
                        q = store.first_quote_many(parts, pos.symbol, ts.isoformat(), strategy.execution.max_exit_quote_delay_seconds)
                        if q:
                            close_position(q['timestamp'], _executable_exit_price(pos, q, strategy), 'CONDITION_EXIT', tree)
                            closed_this_candle = True

        if pos is not None or closed_this_candle:
            continue

        # When flat, update every independent lifecycle for CALL and PUT. Each
        # lifecycle can arm from a different condition. The full directional entry
        # tree must still pass on the execution candle. A max_wait_bars window makes
        # "A happened, wait up to N bars for B" deterministic and no-look-ahead.
        disabled_tree = {'mode': 'DISABLED', 'passed': False, 'passed_count': 0, 'total': 0, 'conditions': [], 'groups': []}
        call = evaluate_group(frame, i, strategy.call_entry, _entry_ignore_ids(strategy,'CALL')) if call_enabled else disabled_tree
        put = evaluate_group(frame, i, strategy.put_entry, _entry_ignore_ids(strategy,'PUT')) if put_enabled else disabled_tree
        call_score = _big_trend_score(frame, i, strategy.call_entry, strategy.call_big_trend_score, 'CALL') if call_enabled else {'enabled':False,'score':None,'passed':True,'components':[]}
        put_score = _big_trend_score(frame, i, strategy.put_entry, strategy.put_big_trend_score, 'PUT') if put_enabled else {'enabled':False,'score':None,'passed':True,'components':[]}
        call_lifecycle_rows = _update_lifecycles(
            frame, i, strategy.call_entry, call_behaviors, call_cycles
        ) if call_enabled else []
        put_lifecycle_rows = _update_lifecycles(
            frame, i, strategy.put_entry, put_behaviors, put_cycles
        ) if put_enabled else []
        call_summary = _lifecycle_summary(call_lifecycle_rows)
        put_summary = _lifecycle_summary(put_lifecycle_rows)
        call_ready = [x for x in call_lifecycle_rows if x['eligible']]
        put_ready = [x for x in put_lifecycle_rows if x['eligible']]
        def retest_override(direction: str) -> tuple[bool,int|None]:
            cfg=strategy.call_breakout_retest if direction=='CALL' else strategy.put_breakout_retest
            if not (cfg.enabled and cfg.require_retest_for_entry): return False,None
            prefix=direction.lower(); ready=bool((_strategy_operand(frame,i,f'{prefix}_retest_ready') or 0.0)>0.5)
            age=_strategy_operand(frame,i,f'{prefix}_bars_since_breakout')
            if not ready or age is None: return False,None
            origin=i-int(age)
            return consumed_breakout_origin[direction] != origin, origin
        call_override, call_breakout_origin = retest_override('CALL') if call_enabled else (False,None)
        put_override, put_breakout_origin = retest_override('PUT') if put_enabled else (False,None)
        call_eligible = bool(call_ready) or call_override
        put_eligible = bool(put_ready) or put_override

        if strategy.execution.decision_log_mode == 'FULL':
            if call_enabled:
                decisions.append(_flatten_decision(next_event('decision'), 'CALL', ts, 'ENTRY', call, {
                    'close': _finite(row.close), 'big_trend_score': call_score.get('score'), 'big_trend_score_passed': call_score.get('passed'), **call_summary,
                }))
            if put_enabled:
                decisions.append(_flatten_decision(next_event('decision'), 'PUT', ts, 'ENTRY', put, {
                    'close': _finite(row.close), 'big_trend_score': put_score.get('score'), 'big_trend_score_passed': put_score.get('passed'), **put_summary,
                }))

        if not _session_allowed(ts, strategy.session):
            continue

        # V12: shared NO-TRADE applies to both directions; directional NO-TRADE
        # filters can independently block only CALL or only PUT.
        empty_no_trade = {'mode':'DISABLED','passed':False,'passed_count':0,'total':0,'conditions':[],'groups':[]}
        shared_no_trade = evaluate_group(frame, i, strategy.no_trade) if strategy.no_trade.configured() else empty_no_trade
        call_no_trade = evaluate_group(frame, i, strategy.call_no_trade) if call_enabled and strategy.call_no_trade.configured() else empty_no_trade
        put_no_trade = evaluate_group(frame, i, strategy.put_no_trade) if put_enabled and strategy.put_no_trade.configured() else empty_no_trade
        for ndir, tree in (('BOTH',shared_no_trade),('CALL',call_no_trade),('PUT',put_no_trade)):
            if tree is empty_no_trade:
                continue
            if strategy.execution.decision_log_mode == 'FULL' or tree['passed']:
                decisions.append(_flatten_decision(
                    next_event('decision'), ndir, ts, 'NO_TRADE', tree,
                    {'close': _finite(row.close), 'reason': 'NO_TRADE_ACTIVE' if tree['passed'] else ''},
                ))

        call_entry_pass = _score_entry_pass(call, call_score, strategy.call_big_trend_score) if call_enabled else False
        put_entry_pass = _score_entry_pass(put, put_score, strategy.put_big_trend_score) if put_enabled else False
        call_candidate = bool(call_entry_pass and call_eligible and not shared_no_trade['passed'] and not call_no_trade['passed'])
        put_candidate = bool(put_entry_pass and put_eligible and not shared_no_trade['passed'] and not put_no_trade['passed'])

        blocked_no_trade=[]
        if call_entry_pass and call_eligible and (shared_no_trade['passed'] or call_no_trade['passed']): blocked_no_trade.append('CALL')
        if put_entry_pass and put_eligible and (shared_no_trade['passed'] or put_no_trade['passed']): blocked_no_trade.append('PUT')
        if blocked_no_trade:
            add_marker(ts.isoformat(), 'reject', 'BOTH' if len(blocked_no_trade)>1 else blocked_no_trade[0], 'NO TRADE', _event_details(
                'No-trade filter','NO_TRADE_CONDITION',btc_close=_finite(row.close),blocked_directions=blocked_no_trade,
                shared_no_trade_rule=shared_no_trade,call_no_trade_rule=call_no_trade,put_no_trade_rule=put_no_trade,
            ))

        # Breakout/retest memory is a second directional gate. It can require a
        # remembered-level retest, block a false breakout until trigger reset, and
        # reject late trend-chasing after max_trend_age_bars.
        if call_candidate:
            reason=_breakout_gate_reason(frame,i,'CALL',strategy)
            if reason:
                call_candidate=False
                add_marker(ts.isoformat(),'reject','CALL',reason,_event_details('Breakout/retest gate',reason,btc_close=_finite(row.close),
                    breakout_level=_strategy_operand(frame,i,'call_breakout_level'),bars_since_breakout=_strategy_operand(frame,i,'call_bars_since_breakout'),
                    retest_ready=_strategy_operand(frame,i,'call_retest_ready'),false_breakout=_strategy_operand(frame,i,'call_false_breakout')))
        if put_candidate:
            reason=_breakout_gate_reason(frame,i,'PUT',strategy)
            if reason:
                put_candidate=False
                add_marker(ts.isoformat(),'reject','PUT',reason,_event_details('Breakout/retest gate',reason,btc_close=_finite(row.close),
                    breakout_level=_strategy_operand(frame,i,'put_breakout_level'),bars_since_breakout=_strategy_operand(frame,i,'put_bars_since_breakout'),
                    retest_ready=_strategy_operand(frame,i,'put_retest_ready'),false_breakout=_strategy_operand(frame,i,'put_false_breakout')))
        risk_reason = daily_block_reason()
        if risk_reason and (call_candidate or put_candidate):
            daily_state['blocked_count'] = int(daily_state['blocked_count']) + 1
            blocked_dirs = (["CALL"] if call_candidate else []) + (["PUT"] if put_candidate else [])
            add_marker(ts.isoformat(), 'reject', 'BOTH', risk_reason, _event_details(
                'Daily risk control', risk_reason, btc_close=_finite(row.close), blocked_directions=blocked_dirs,
                daily_realized_pnl_usd=daily_state['realized_pnl'], daily_entries=daily_state['entries'],
                consecutive_losses=daily_state['consecutive_losses'],
            ))
            continue

        direction = None
        chosen_tree = None
        chosen_cycle: EntryCycleState | None = None
        chosen_behavior = None
        def choose_side(chosen_direction: str):
            ready = call_ready if chosen_direction=='CALL' else put_ready
            tree = call if chosen_direction=='CALL' else put
            origin = call_breakout_origin if chosen_direction=='CALL' else put_breakout_origin
            if ready:
                chosen=ready[0]; return tree,chosen['state'],chosen['behavior'],origin
            # First-class retest path: once a remembered breakout has pulled back
            # and held, the retest state itself can satisfy lifecycle eligibility.
            # One entry is allowed per breakout snapshot.
            cfg=strategy.call_breakout_retest if chosen_direction=='CALL' else strategy.put_breakout_retest
            synthetic=SimpleNamespace(id=f'{chosen_direction.lower()}-retest',name=f'{chosen_direction} breakout retest',max_entries_per_activation=1,delay_bars=0,max_wait_bars=cfg.max_retest_wait_bars,trigger_condition_id=cfg.breakout_condition_id)
            state=EntryCycleState(active=True,start_index=origin,entries=0)
            return tree,state,synthetic,origin

        chosen_breakout_origin=None
        if call_candidate and put_candidate:
            direction = {'PREFER_CALL': 'CALL', 'PREFER_PUT': 'PUT'}.get(strategy.conflict_policy)
            if direction:
                chosen_tree,chosen_cycle,chosen_behavior,chosen_breakout_origin=choose_side(direction)
        elif call_candidate:
            direction='CALL'; chosen_tree,chosen_cycle,chosen_behavior,chosen_breakout_origin=choose_side('CALL')
        elif put_candidate:
            direction='PUT'; chosen_tree,chosen_cycle,chosen_behavior,chosen_breakout_origin=choose_side('PUT')
        if not direction or chosen_tree is None or chosen_cycle is None or chosen_behavior is None:
            continue

        action = strategy.call_action if direction == 'CALL' else strategy.put_action
        spec, q, why = _select_option(store, parts, inst, ts, float(row.close), direction, strategy, action)
        if not spec or not q:
            decision_tree = {'mode': 'EXECUTION', 'passed': False, 'passed_count': 0, 'total': 1, 'conditions': [], 'groups': []}
            decisions.append(_flatten_decision(next_event('decision'), direction, ts, 'EXECUTION', decision_tree, {'close': _finite(row.close), 'reason': why}))
            add_marker(
                ts.isoformat(), 'reject', direction, why,
                _event_details('Rejected after signal', why, btc_close=_finite(row.close), entry_rule=chosen_tree)
            )
            continue

        inc = float(spec['price_increment'])
        slip = strategy.execution.slippage_ticks * inc
        entry = float(q['ask']) + slip if action == 'BUY' else max(0.0, float(q['bid']) - slip)
        qty, cost, quantity_reject = _quantity(strategy, spec, entry, float(row.close), balance, action)
        if qty <= 0:
            why = quantity_reject or 'INSUFFICIENT_CASH'
            decision_tree = {'mode': 'EXECUTION', 'passed': False, 'passed_count': 0, 'total': 1, 'conditions': [], 'groups': []}
            decisions.append(_flatten_decision(next_event('decision'), direction, ts, 'EXECUTION', decision_tree, {'close': _finite(row.close), 'reason': why}))
            add_marker(
                ts.isoformat(), 'reject', direction, why,
                _event_details('Rejected after signal', why, btc_close=_finite(row.close), requested_cost_usd=cost, balance_usd=balance, entry_rule=chosen_tree)
            )
            continue

        edge_ok, edge_reason, edge_details = _fee_edge_check(strategy, spec, q, float(row.close), entry, qty)
        if not edge_ok:
            decision_tree = {'mode': 'EXECUTION', 'passed': False, 'passed_count': 0, 'total': 1, 'conditions': [], 'groups': []}
            decisions.append(_flatten_decision(next_event('decision'), direction, ts, 'EXECUTION', decision_tree, {'close': _finite(row.close), 'reason': edge_reason, **edge_details}))
            add_marker(ts.isoformat(),'reject',direction,edge_reason,_event_details('Fee-aware edge filter',edge_reason,btc_close=_finite(row.close),symbol=str(spec['symbol']),**edge_details))
            continue

        entry_fee_details = _delta_fee(float(row.close), entry, qty, float(spec['contract_value']), strategy.execution)
        fee = entry_fee_details['total_fee_usd']
        atr = _finite(row[atr_keys[0]]) if atr_keys else None
        pos = Position(
            direction, action, str(spec['symbol']), spec, q['timestamp'], ts.isoformat(), float(row.close),
            entry, qty, fee, entry_fee_details, atr, chosen_tree,
            entry_lifecycle_id=chosen_behavior.id, entry_lifecycle_name=chosen_behavior.name,
        )
        chosen_cycle.entries += 1
        chosen_cycle.last_entry_index = i
        if chosen_breakout_origin is not None:
            consumed_breakout_origin[direction] = int(chosen_breakout_origin)
        daily_state['entries'] = int(daily_state['entries']) + 1
        record_mtm(q, pos.entry_time)  # immediately price liquidation against spread + fees
        pos_quotes = store.quotes_between_many(parts, pos.symbol, pos.entry_time, iso(end_dt))
        q_cursor = 0
        while q_cursor < len(pos_quotes) and pos_quotes.iloc[q_cursor].timestamp <= pd.Timestamp(parse_time(pos.entry_time)):
            q_cursor += 1

        qs = _quote_stats(q)
        dte = (pd.Timestamp(spec['expiration']) - ts).total_seconds() / 86400.0
        decision_tree = {'mode': 'EXECUTION', 'passed': True, 'passed_count': 1, 'total': 1, 'conditions': [], 'groups': []}
        decisions.append(_flatten_decision(next_event('decision'), direction, ts, 'EXECUTION', decision_tree, {
            'close': _finite(row.close), 'reason': 'TRADE_ACCEPTED', 'symbol': pos.symbol, 'action': action,
            'activation_entry_number': chosen_cycle.entries,
            'max_entries_per_activation': chosen_behavior.max_entries_per_activation,
            'activation_age_bars': i - int(chosen_cycle.start_index if chosen_cycle.start_index is not None else i),
            'entry_lifecycle_id': chosen_behavior.id,
            'entry_lifecycle_name': chosen_behavior.name,
            'max_wait_bars': chosen_behavior.max_wait_bars,
            'big_trend_score': call_score.get('score') if direction == 'CALL' else put_score.get('score'),
        }))
        add_marker(
            pos.entry_time, 'entry', direction, f'{action} {direction} {pos.symbol}',
            _event_details(
                f'{action} {direction} entry', 'ALL_ENTRY_AND_EXECUTION_CONDITIONS_PASSED',
                signal_time=ts.isoformat(), btc_close=_finite(row.close), symbol=pos.symbol, action=action,
                entry_price=entry, entry_ask=entry, entry_execution_side='ASK' if action == 'BUY' else 'BID', quantity=qty, estimated_cost_usd=cost, dte_days=dte,
                entry_fee_usd=fee, entry_base_fee_usd=entry_fee_details['base_fee_usd'],
                entry_gst_usd=entry_fee_details['gst_usd'], fee_model='DELTA_OPTIONS',
                spread_percent=qs['spread_percent'], volume=qs['volume'], open_interest=qs['open_interest'],
                activation_entry_number=chosen_cycle.entries,
                max_entries_per_activation=chosen_behavior.max_entries_per_activation,
                activation_age_bars=i - int(chosen_cycle.start_index if chosen_cycle.start_index is not None else i),
                entry_delay_bars=chosen_behavior.delay_bars,
                trigger_condition_id=chosen_behavior.trigger_condition_id,
                entry_lifecycle_id=chosen_behavior.id, entry_lifecycle_name=chosen_behavior.name,
                max_wait_bars=chosen_behavior.max_wait_bars,
                entry_rule=chosen_tree,
                big_trend_score=call_score if direction == 'CALL' else put_score,
            )
        )

    # Process remaining historical quotes up to the requested end. This also
    # detects protective exits after the last completed strategy candle.
    if pos is not None and pos_quotes is not None:
        while q_cursor < len(pos_quotes) and pd.Timestamp(pos_quotes.iloc[q_cursor].timestamp) <= pd.Timestamp(end_dt):
            last_q = pos_quotes.iloc[q_cursor].to_dict()
            q_cursor += 1
            stamp = pd.Timestamp(last_q['timestamp']).isoformat()
            record_mtm(last_q, stamp)
            reason, _ = _stop_reason(pos, last_q, strategy)
            if reason:
                close_position(stamp, _executable_exit_price(pos, last_q, strategy), reason)
                break

    unresolved_position = None
    if pos is not None:
        last = pos_quotes.iloc[-1] if pos_quotes is not None and len(pos_quotes) else None
        last_ts = pd.Timestamp(last.timestamp) if last is not None else None
        quote_age = (pd.Timestamp(end_dt) - last_ts).total_seconds() if last_ts is not None else None
        allowed_age = strategy.execution.end_of_data_quote_max_age_seconds
        if last is not None and quote_age is not None and 0 <= quote_age <= allowed_age:
            record_mtm(last.to_dict(), last_ts.isoformat())
            close_position(last_ts.isoformat(), _executable_exit_price(pos, last.to_dict(), strategy), 'END_OF_DATA')
        else:
            unresolved_position = {
                'symbol': pos.symbol, 'direction': pos.direction, 'action': pos.action,
                'entry_time': pos.entry_time, 'entry_price': pos.entry_price,
                'quantity': pos.quantity,
                'last_quote_timestamp': last_ts.isoformat() if last_ts is not None else None,
                'quote_age_seconds': quote_age,
                'max_allowed_quote_age_seconds': allowed_age,
                'reason': 'NO_FRESH_FINAL_QUOTE',
            }

    wins = sum(t['net_pnl_usd'] > 0 for t in trades)
    losses = sum(t['net_pnl_usd'] < 0 for t in trades)
    gp = sum(max(0, t['net_pnl_usd']) for t in trades)
    gl = -sum(min(0, t['net_pnl_usd']) for t in trades)
    metrics = {
        'trades': len(trades),
        'alerts_triggered': len(alert_events),
        'wins': wins,
        'losses': losses,
        'win_rate_percent': (wins / len(trades) * 100 if trades else 0),
        'gross_pnl_usd': sum(t['gross_pnl_usd'] for t in trades),
        'net_pnl_usd': sum(t['net_pnl_usd'] for t in trades),
        'base_fees_usd': sum(t['base_fees_usd'] for t in trades),
        'gst_usd': sum(t['gst_usd'] for t in trades),
        'fees_usd': sum(t['fees_usd'] for t in trades),
        'profit_factor': (gp / gl if gl > 0 else None),
        'ending_balance_usd': balance,
        'return_percent': (balance / strategy.risk.starting_balance_usd - 1) * 100,
        'max_closed_trade_drawdown_usd': max_dd,
        'max_closed_trade_drawdown_percent': max_dd_percent,
        'max_mark_to_market_drawdown_usd': mtm_max_dd,
        'max_mark_to_market_drawdown_percent': mtm_max_dd_percent,
        'minimum_mark_to_market_equity_usd': mtm_low,
        'mark_to_market_quote_samples': mtm_samples,
        'unresolved_position_count': int(unresolved_position is not None),
        'avg_mfe_percent': (sum(t['mfe_percent'] for t in trades) / len(trades) if trades else 0),
        'avg_mae_percent': (sum(t['mae_percent'] for t in trades) / len(trades) if trades else 0),
        'daily_risk_blocks': int(daily_state['blocked_count']),
    }

    run_id, out = _new_result_dir(strategy.name)
    result = {
        'run_id': run_id,
        'result_dir': str(out),
        'dataset_id': getattr(req, 'dataset_id', None),
        'dataset_ids': [x.id for x in parts],
        'dataset_mode': getattr(req, 'dataset_mode', 'SINGLE'),
        'start': req.start,
        'end': req.end,
        'strategy': strategy.model_dump(),
        'metrics': metrics,
        'trades': trades,
        'markers': markers,
        'series_meta': series_meta,
        'equity_curve': equity_curve,
        'decision_count': len(decisions),
        'cache_hit': False,
        'cache_key': cache_key,
        'storage_mode': getattr(req, 'storage_mode', 'ANALYSIS'),
        'preflight': preflight,
        'warmup': warmup,
        'unresolved_position': unresolved_position,
        'reliability': {
            'grade': 'RESEARCH_ONLY',
            'quote_fidelity': str((store.archive_catalog() or {}).get('fidelity') or 'UNVERIFIED'),
            'execution_model': 'TOP_OF_BOOK_NO_DEPTH_OR_PARTIAL_FILLS',
            'limitations': [
                'Synthetic/unverified quotes cannot confirm real fills',
                'SELL margin, liquidation and actual depth are not modeled',
                'MTM drawdown is sampled only at available historical quotes',
            ] + (['Warm-up incomplete'] if not warmup['contiguous'] else [])
              + (['Open position unresolved at end'] if unresolved_position else []),
        },
        'fee_model': {
            'name': 'DELTA_OPTIONS',
            'option_notional_fee_rate_percent': strategy.execution.option_notional_fee_rate_percent,
            'premium_fee_cap_percent': strategy.execution.premium_fee_cap_percent,
            'gst_percent': strategy.execution.gst_percent,
            'personal_income_tax_included': False,
        },
    }
    storage_mode = str(getattr(req, 'storage_mode', 'ANALYSIS')).upper()
    (out / 'strategy.json').write_text(json.dumps(strategy.model_dump(), indent=2), encoding='utf-8')
    if trades:
        with (out / 'trades.csv').open('w', newline='', encoding='utf-8') as h:
            wr = csv.DictWriter(h, fieldnames=list(trades[0]))
            wr.writeheader()
            wr.writerows(trades)

    # V15 deliberately keeps summary.json small. V1-V14 embedded trades, markers
    # and the entire equity curve inside summary.json while also writing dedicated
    # files, multiplying storage for every run. The in-memory API result remains
    # rich; only persistence changes.
    summary = dict(_json_safe(result))
    for heavy_key in ('trades', 'markers', 'equity_curve', 'series_meta'):
        summary.pop(heavy_key, None)
    manifest = {'trades': 'trades.csv' if trades else None, 'markers': None, 'equity_curve': None, 'decisions': None}

    if storage_mode == 'FULL_DEBUG':
        if markers:
            (out / 'markers.json').write_text(json.dumps(_json_safe(markers), indent=2, allow_nan=False), encoding='utf-8')
            manifest['markers'] = 'markers.json'
        if equity_curve:
            with (out / 'equity_curve.csv').open('w', newline='', encoding='utf-8') as h:
                wr = csv.DictWriter(h, fieldnames=list(equity_curve[0]))
                wr.writeheader(); wr.writerows(equity_curve)
            manifest['equity_curve'] = 'equity_curve.csv'
        if decisions:
            fields = list(dict.fromkeys(k for d in decisions for k in d))
            with (out / 'decision_events.csv').open('w', newline='', encoding='utf-8') as h:
                wr = csv.DictWriter(h, fieldnames=fields)
                wr.writeheader(); wr.writerows(decisions)
            manifest['decisions'] = 'decision_events.csv'
    elif storage_mode == 'ANALYSIS':
        if markers:
            write_json_gz(out / 'markers.json.gz', _json_safe(markers))
            manifest['markers'] = 'markers.json.gz'
        if equity_curve:
            write_csv_gz(out / 'equity_curve.csv.gz', equity_curve)
            manifest['equity_curve'] = 'equity_curve.csv.gz'
        if decisions:
            write_csv_gz(out / 'decision_events.csv.gz', decisions)
            manifest['decisions'] = 'decision_events.csv.gz'
    # COMPACT normally drops diagnostics; keep historical alerts as they cannot
    # be reconstructed from the option trades.
    if storage_mode == 'COMPACT' and alert_events:
        write_json_gz(out / 'markers.json.gz', alert_events)
        manifest['markers'] = 'markers.json.gz'
    # COMPACT keeps only summary + strategy + trades. Cache replays reconstruct
    # trade entry/exit markers; detailed reject markers and decision traces are
    # intentionally not retained.
    summary['artifact_manifest'] = manifest
    (out / 'summary.json').write_text(json.dumps(summary, separators=(',', ':'), allow_nan=False), encoding='utf-8')

    _write_cache(cache_key, run_id)
    maybe_auto_cleanup()
    report('Backtest complete. Result cached for identical reruns.', 100, 'COMPLETE', 'Complete')
    store.close()
    return _json_safe(result)

def _score(tree: dict[str, Any]) -> tuple[int, int, bool]:
    return int(tree.get('passed_count', 0)), int(tree.get('total', 0)), bool(tree.get('passed'))


def chart_payload(req, run_result=None):
    store = DataStore()
    parts = store.resolve_request(req, require_options=False)
    strategy = getattr(req, 'strategy', None)
    timeframe = strategy.timeframe if strategy is not None else getattr(req, 'timeframe', '5m')
    instances = strategy.indicators if strategy is not None else req.indicators
    warmup_count = required_warmup_candles(
        instances, timeframe, minimum=getattr(req, 'warmup_candles', 500), strategy=strategy,
    )
    bar_parts = historical_bar_sources(
        store, parts, req.start, timeframe, warmup_count,
        archive_neighbors=getattr(req, 'dataset_mode', 'SINGLE') in {'ARCHIVE', 'AUTO'},
    )
    bars = store.load_bars_many(bar_parts, req.start, req.end, timeframe, warmup_candles=warmup_count)
    warmup = warmup_diagnostics(bars, req.start, timeframe, warmup_count)
    frame, meta = compute_indicators(bars, instances, timeframe)
    if strategy is not None:
        _prepare_strategy_state(frame, strategy)
    cutoff = pd.Timestamp(parse_time(req.start))
    until = pd.Timestamp(parse_time(req.end))
    # Alerts use the same complete/warmed frame for chart preview and backtest.
    preview_alerts = alert_markers(frame, strategy, req.start, req.end) if strategy is not None else []
    # Keep earlier rows during computation, then exclude them from displayed data.
    frame = frame.loc[(frame.index >= cutoff) & (frame.index < until)].copy()
    if len(frame) > 30000:
        raise ValueError(
            f'Chart range contains {len(frame):,} source candles. Narrow the chart date range below 30,000 candles; '
            'the backtest itself may use longer ranges.'
        )
    chart_bars = [
        {'time': int(ts.timestamp()), 'open': float(r.open), 'high': float(r.high), 'low': float(r.low), 'close': float(r.close), 'volume': float(r.volume)}
        for ts, r in frame.iterrows()
    ]
    series = []
    for m in meta:
        vals = []
        for ts, v in frame[m['key']].items():
            fv = _finite(v)
            if fv is not None:
                vals.append({'time': int(ts.timestamp()), 'value': fv})
        series.append({**m, 'values': vals})

    study_markers: list[dict[str, Any]] = []
    for inst_item in instances:
        prefix = inst_item.id + '.'
        def add_study(column: str, text: str, direction: str, title: str, study_type: str, price_column: str | None = None):
            key = prefix + column
            if key not in frame.columns:
                return
            for ts, value in frame[key].items():
                fv = _finite(value)
                if fv is None or fv <= 0:
                    continue
                details: dict[str, Any] = {'title': title, 'reason': study_type, 'study_type': study_type, 'indicator_id': inst_item.id}
                if price_column and prefix + price_column in frame.columns:
                    details['level'] = _finite(frame.loc[ts, prefix + price_column])
                study_markers.append({'id': f'study-{inst_item.id}-{column}-{int(ts.timestamp())}', 'time': int(ts.timestamp()), 'timestamp': ts.isoformat(), 'kind': 'study', 'direction': direction, 'text': text, 'pnl_usd': None, 'details': details})
        if inst_item.kind == 'PIVOTS':
            add_study('swing_high_confirmed','SH','BEAR','Swing high confirmed','SWING_HIGH','confirmed_high_price')
            add_study('swing_low_confirmed','SL','BULL','Swing low confirmed','SWING_LOW','confirmed_low_price')
        elif inst_item.kind == 'DIVERGENCE':
            add_study('bullish','BULL DIV','BULL','Bullish divergence confirmed','BULLISH_DIVERGENCE','last_bullish_price')
            add_study('bearish','BEAR DIV','BEAR','Bearish divergence confirmed','BEARISH_DIVERGENCE','last_bearish_price')
            add_study('hidden_bullish','H BULL DIV','BULL','Hidden bullish divergence confirmed','HIDDEN_BULLISH_DIVERGENCE','last_hidden_bullish_price')
            add_study('hidden_bearish','H BEAR DIV','BEAR','Hidden bearish divergence confirmed','HIDDEN_BEARISH_DIVERGENCE','last_hidden_bearish_price')
        elif inst_item.kind == 'MARKET_STRUCTURE':
            add_study('bos_bullish','BOS ↑','BULL','Bullish break of structure','BULLISH_BOS','last_swing_high')
            add_study('bos_bearish','BOS ↓','BEAR','Bearish break of structure','BEARISH_BOS','last_swing_low')

    # V12 strategy-state markers: these are diagnostics only and never move an
    # event backward to the historical breakout/retest candle.
    if strategy is not None:
        phase_names={0:'COMPRESSION',1:'IGNITION',2:'CONFIRMATION',3:'BIG_TREND',4:'EXHAUSTION'}
        phase_text={'IGNITION':'IGN','CONFIRMATION':'CONF','BIG_TREND':'BIG','EXHAUSTION':'EXH','COMPRESSION':'CMP'}
        for side in ('call','put'):
            direction=side.upper(); bull='BULL' if direction=='CALL' else 'BEAR'
            active_key=f'{side}_breakout_active'; retest_key=f'{side}_retest_ready'; false_key=f'{side}_false_breakout'; level_key=f'{side}_breakout_level'; phase_key=f'{side}_trend_phase_code'
            prev_active=0.0; prev_retest=0.0; prev_phase=None
            for ts,row in frame.iterrows():
                active=_finite(row.get(active_key)) or 0.0; retest=_finite(row.get(retest_key)) or 0.0; false=_finite(row.get(false_key)) or 0.0
                level=_finite(row.get(level_key))
                if active>0.5 and prev_active<=0.5:
                    study_markers.append({'id':f'study-{side}-breakout-{int(ts.timestamp())}','time':int(ts.timestamp()),'timestamp':ts.isoformat(),'kind':'study','direction':bull,'text':'BO','pnl_usd':None,'details':{'title':f'{direction} breakout remembered','reason':'BREAKOUT_SNAPSHOT','study_type':'BREAKOUT_SNAPSHOT','level':level}})
                if retest>0.5 and prev_retest<=0.5:
                    study_markers.append({'id':f'study-{side}-retest-{int(ts.timestamp())}','time':int(ts.timestamp()),'timestamp':ts.isoformat(),'kind':'study','direction':bull,'text':'RETEST','pnl_usd':None,'details':{'title':f'{direction} retest held','reason':'RETEST_READY','study_type':'RETEST_READY','level':level}})
                if false>0.5:
                    study_markers.append({'id':f'study-{side}-false-{int(ts.timestamp())}','time':int(ts.timestamp()),'timestamp':ts.isoformat(),'kind':'study','direction':'BEAR' if bull=='BULL' else 'BULL','text':'FALSE BO','pnl_usd':None,'details':{'title':f'{direction} false breakout','reason':'FALSE_BREAKOUT','study_type':'FALSE_BREAKOUT','level':level}})
                code=_finite(row.get(phase_key))
                if code is not None:
                    phase=phase_names.get(int(code),'COMPRESSION')
                    if prev_phase is not None and phase!=prev_phase and phase!='COMPRESSION':
                        study_markers.append({'id':f'study-{side}-phase-{int(ts.timestamp())}','time':int(ts.timestamp()),'timestamp':ts.isoformat(),'kind':'study','direction':bull,'text':phase_text[phase],'pnl_usd':None,'details':{'title':f'{direction} trend phase → {phase}','reason':'TREND_PHASE','study_type':'TREND_PHASE','phase':phase}})
                    prev_phase=phase
                prev_active=active; prev_retest=retest

    condition_states: list[dict[str, Any]] = []
    if strategy is not None:
        call_enabled = strategy.direction_mode in {'CALL', 'BOTH'}
        put_enabled = strategy.direction_mode in {'PUT', 'BOTH'}
        call_behaviors = _entry_behaviors(strategy, 'CALL') if call_enabled else []
        put_behaviors = _entry_behaviors(strategy, 'PUT') if put_enabled else []
        call_cycles = _cycle_states(call_behaviors)
        put_cycles = _cycle_states(put_behaviors)
        disabled_tree = {'mode': 'DISABLED', 'passed': False, 'passed_count': 0, 'total': 0, 'conditions': [], 'groups': []}
        for i, (ts, _) in enumerate(frame.iterrows()):
            call = evaluate_group(frame, i, strategy.call_entry, _entry_ignore_ids(strategy,'CALL')) if call_enabled else disabled_tree
            put = evaluate_group(frame, i, strategy.put_entry, _entry_ignore_ids(strategy,'PUT')) if put_enabled else disabled_tree
            call_bt = _big_trend_score(frame, i, strategy.call_entry, strategy.call_big_trend_score, 'CALL') if call_enabled else {'enabled':False,'score':None,'passed':True}
            put_bt = _big_trend_score(frame, i, strategy.put_entry, strategy.put_big_trend_score, 'PUT') if put_enabled else {'enabled':False,'score':None,'passed':True}
            call_rows = _update_lifecycles(frame, i, strategy.call_entry, call_behaviors, call_cycles) if call_enabled else []
            put_rows = _update_lifecycles(frame, i, strategy.put_entry, put_behaviors, put_cycles) if put_enabled else []
            call_summary = _lifecycle_summary(call_rows)
            put_summary = _lifecycle_summary(put_rows)
            no_trade = evaluate_group(frame, i, strategy.no_trade) if strategy.no_trade.configured() else {'passed_count': 0, 'total': 0, 'passed': False}
            call_nt = evaluate_group(frame, i, strategy.call_no_trade) if call_enabled and strategy.call_no_trade.configured() else {'passed_count':0,'total':0,'passed':False}
            put_nt = evaluate_group(frame, i, strategy.put_no_trade) if put_enabled and strategy.put_no_trade.configured() else {'passed_count':0,'total':0,'passed':False}
            cp, ct, cpass = _score(call)
            pp, pt, ppass = _score(put)
            np, nt, nactive = _score(no_trade)
            condition_states.append({
                'time': int(ts.timestamp()),
                'call_passed_count': cp,
                'call_total': ct,
                'call_score': (float(call_bt['score']) if call_bt.get('enabled') else (cp / ct * 100.0 if ct else 0.0)),
                'call_passed': _score_entry_pass(call, call_bt, strategy.call_big_trend_score) if call_enabled else False,
                'call_big_trend_score': call_bt.get('score'),
                'call_big_trend_score_passed': call_bt.get('passed'),
                'call_big_trend_persistence_count': _finite(frame.iloc[i].get('call_big_trend_score_persistence_count')),
                'call_trend_phase': {0:'COMPRESSION',1:'IGNITION',2:'CONFIRMATION',3:'BIG_TREND',4:'EXHAUSTION'}.get(int(_finite(frame.iloc[i].get('call_trend_phase_code')) or 0),'COMPRESSION'),
                'call_breakout_level': _finite(frame.iloc[i].get('call_breakout_level')),
                'call_bars_since_breakout': _finite(frame.iloc[i].get('call_bars_since_breakout')),
                'call_retest_ready': bool((_finite(frame.iloc[i].get('call_retest_ready')) or 0)>0.5),
                'call_false_breakout': bool((_finite(frame.iloc[i].get('call_false_breakout')) or 0)>0.5),
                'call_no_trade_active': bool(call_nt.get('passed')),
                'call_trigger_passed': bool(call_summary['trigger_passed']),
                'call_activation_age_bars': call_summary['activation_age_bars'],
                'call_delay_ready': bool([x for x in call_rows if x['eligible']]),
                'call_active_lifecycles': len([x for x in call_rows if x['state'].active]),
                'call_eligible_lifecycles': len([x for x in call_rows if x['eligible']]),
                'put_passed_count': pp,
                'put_total': pt,
                'put_score': (float(put_bt['score']) if put_bt.get('enabled') else (pp / pt * 100.0 if pt else 0.0)),
                'put_passed': _score_entry_pass(put, put_bt, strategy.put_big_trend_score) if put_enabled else False,
                'put_big_trend_score': put_bt.get('score'),
                'put_big_trend_score_passed': put_bt.get('passed'),
                'put_big_trend_persistence_count': _finite(frame.iloc[i].get('put_big_trend_score_persistence_count')),
                'put_trend_phase': {0:'COMPRESSION',1:'IGNITION',2:'CONFIRMATION',3:'BIG_TREND',4:'EXHAUSTION'}.get(int(_finite(frame.iloc[i].get('put_trend_phase_code')) or 0),'COMPRESSION'),
                'put_breakout_level': _finite(frame.iloc[i].get('put_breakout_level')),
                'put_bars_since_breakout': _finite(frame.iloc[i].get('put_bars_since_breakout')),
                'put_retest_ready': bool((_finite(frame.iloc[i].get('put_retest_ready')) or 0)>0.5),
                'put_false_breakout': bool((_finite(frame.iloc[i].get('put_false_breakout')) or 0)>0.5),
                'put_no_trade_active': bool(put_nt.get('passed')),
                'put_trigger_passed': bool(put_summary['trigger_passed']),
                'put_activation_age_bars': put_summary['activation_age_bars'],
                'put_delay_ready': bool([x for x in put_rows if x['eligible']]),
                'put_active_lifecycles': len([x for x in put_rows if x['state'].active]),
                'put_eligible_lifecycles': len([x for x in put_rows if x['eligible']]),
                'no_trade_passed_count': np,
                'no_trade_total': nt,
                'no_trade_score': (np / nt * 100.0 if nt else 0.0),
                'no_trade_active': nactive,
            })

    return {
        'bars': chart_bars,
        'series': series,
        'markers': [
            *(m for m in (run_result or {}).get('markers', []) if m.get('kind') != 'alert'),
            *preview_alerts,
        ],
        'study_markers': study_markers,
        'condition_states': condition_states,
        'warmup': warmup,
    }
