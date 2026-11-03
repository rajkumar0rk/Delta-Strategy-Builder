"""Optional, stateful, closed-candle pullback/breakout signals for futures.

One completed higher-timeframe bar arms a snapshot. Only subsequent base bars
can break its *frozen* high/low. The rolling swing window and active snapshots
are bounded; existing option/legacy futures paths are untouched.
"""
from __future__ import annotations

from collections import deque
import math
import pandas as pd

from .futures_contract import assumed_initial_margin_usd, BTCUSD_SNAPSHOT
from .indicators import _aggregate_completed, _TF_MINUTES


def _finite(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


class PullbackBreakoutPlanner:
    """O(base bars + HTF bars), O(lookback + active setups) live-state machine."""

    def __init__(self, frame, config, strategy_timeframe):
        self.config = config
        self.history = deque(maxlen=config.swing_lookback_bars)
        self.setups = {}
        self.completed = _aggregate_completed(
            frame[['open', 'high', 'low', 'close', 'volume']],
            strategy_timeframe, config.setup_timeframe)
        self.base_minutes = _TF_MINUTES[strategy_timeframe]

    def step(self, index, timestamp, candle):
        cfg = self.config
        # Aggregation is completed/UTC-aligned. Never inspect a future HTF row.
        # Expire first; a fresh HTF confirmation can then establish a new setup.
        for side, snapshot in tuple(self.setups.items()):
            if index - snapshot['setup_index'] > cfg.max_wait_bars:
                del self.setups[side]
        if timestamp in self.completed.index:
            bar = self.completed.loc[timestamp]
            high, low = _finite(bar.high), _finite(bar.low)
            opened, closed = _finite(bar.open), _finite(bar.close)
            if None not in (high, low, opened, closed):
                self.history.append((low, high))
                ema = _finite(candle.get(cfg.ema_indicator_id))
                atr = _finite(candle.get(cfg.atr_indicator_id))
                if len(self.history) == cfg.swing_lookback_bars and ema is not None and atr is not None and atr > 0:
                    bullish = closed > ema and (not cfg.require_touch or low <= ema)
                    bearish = closed < ema and (not cfg.require_touch or high >= ema)
                    if cfg.require_confirmation_color:
                        bullish = bullish and closed > opened
                        bearish = bearish and closed < opened
                    if bullish and 'LONG' not in self.setups:
                        stop = min(x[0] for x in self.history) - cfg.stop_buffer_atr * atr
                        if stop > 0 and stop < closed:
                            self.setups['LONG'] = {'setup_index': index, 'stop_price': stop,
                                'level': high, 'setup_time': timestamp.isoformat()}
                    if bearish and 'SHORT' not in self.setups:
                        stop = max(x[1] for x in self.history) + cfg.stop_buffer_atr * atr
                        if stop > closed:
                            self.setups['SHORT'] = {'setup_index': index, 'stop_price': stop,
                                'level': low, 'setup_time': timestamp.isoformat()}
        volume = _finite(candle.get('volume'))
        volume_average = _finite(candle.get(cfg.volume_indicator_id))
        last_close = _finite(candle.get('close'))
        last_open = _finite(candle.get('open'))
        signals = {}
        for direction, setup in tuple(self.setups.items()):
            age = index - setup['setup_index']
            if age > cfg.max_wait_bars:
                del self.setups[direction]
                continue
            if age <= 0 or last_close is None or last_open is None:
                continue
            if cfg.require_confirmation_color and ((direction == 'LONG' and last_close <= last_open)
                                                   or (direction == 'SHORT' and last_close >= last_open)):
                continue
            if cfg.require_volume and (volume is None or volume_average is None or
                                       volume_average <= 0 or volume <= volume_average * cfg.volume_multiplier):
                continue
            passed = (last_close > setup['level'] + cfg.breakout_buffer_points) if direction == 'LONG' else (
                     last_close < setup['level'] - cfg.breakout_buffer_points)
            if passed:
                signals[direction] = {
                    'setup_time': setup['setup_time'], 'setup_age_bars': age,
                    'setup_breakout_level': setup['level'], 'stop_price': setup['stop_price'],
                    'setup_max_wait_bars': cfg.max_wait_bars,
                }
                del self.setups[direction]   # one signal per setup
        return signals


def risk_sized_lots(entry_price, stop_fill_price, direction, equity, futures_cfg, setup_cfg):
    """Risk includes round-trip taker fees + GST and adverse stop fill.

    Uses integer lot arithmetic and logarithmic search for the affordable size;
    never rounds *up* beyond the risk budget. A price gap can exceed this bound.
    """
    sign = 1 if direction == 'LONG' else -1
    if entry_price <= 0 or stop_fill_price <= 0 or (entry_price - stop_fill_price) * sign <= 0:
        return (0, 'STOP_NOT_PROTECTIVE', 0.0)
    fraction = futures_cfg.taker_fee_percent / 100 * (1 + futures_cfg.gst_percent / 100)
    per_lot = futures_cfg.contract_btc
    per_lot_loss = ((entry_price - stop_fill_price) * sign +
                    (entry_price + stop_fill_price) * fraction) * per_lot
    if not math.isfinite(per_lot_loss) or per_lot_loss <= 0:
        return (0, 'INVALID_PER_LOT_RISK', 0.0)
    if setup_cfg.size_mode == 'FIXED':
        requested = futures_cfg.quantity_lots
    else:
        requested = min(setup_cfg.max_lots, int(math.floor(
            max(0.0, equity) * setup_cfg.equity_risk_percent / 100 / per_lot_loss + 1e-12)))
    if requested < 1:
        return (0, 'RISK_BUDGET_BELOW_MIN_LOT', per_lot_loss)
    requested = min(requested, setup_cfg.max_lots)
    if futures_cfg.margin_tier_mode == 'DELTA_PUBLISHED_SNAPSHOT':
        requested = min(requested, int(BTCUSD_SNAPSHOT['position_limit_usd'] //
                         (entry_price * per_lot)))
    if requested < 1:
        return (0, 'PUBLISHED_POSITION_LIMIT', per_lot_loss)

    def affordable(lots):
        quantity = lots * per_lot
        margin = assumed_initial_margin_usd(entry_price, quantity, futures_cfg)
        fee = entry_price * quantity * fraction
        return margin + fee <= equity + 1e-10

    lo, hi = 0, requested
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if affordable(mid):
            lo = mid
        else:
            hi = mid - 1
    if lo < 1:
        return (0, 'INSUFFICIENT_MARGIN', per_lot_loss)
    return (lo, '', per_lot_loss)


def target_at_r(entry_price, stop_price, direction, r_multiple, tick_size):
    """Round the target toward entry so the result never exaggerates reward."""
    distance = (entry_price - stop_price) if direction == 'LONG' else (stop_price - entry_price)
    if distance <= 0:
        return None
    raw = entry_price + (distance * r_multiple if direction == 'LONG' else -distance * r_multiple)
    if raw <= 0:
        return None
    ticks = raw / tick_size
    price = (math.floor(ticks + 1e-10) if direction == 'LONG' else math.ceil(ticks - 1e-10)) * tick_size
    if (price - entry_price) * (1 if direction == 'LONG' else -1) <= 0:
        return None
    return round(price, 10)
