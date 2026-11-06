"""Opt-in Adaptive Market Regime Strategy (AMRS) research execution planner.

State is advanced strictly on closed 1h/15m/5m bars. No vectorized future
slices, no current-candle volatility percentile lookahead. Legacy strategies
never instantiate this planner. At most one candidate per side and one pending
retest per side; the futures engine owns the exclusive pending stop/order.
"""
from __future__ import annotations

import math
from collections import deque

import pandas as pd

from .indicators import _aggregate_completed


def finite(row, name):
    try:
        value = float(row[name])
        return value if math.isfinite(value) else None
    except (KeyError, TypeError, ValueError):
        return None


class AdaptiveBreakoutPlanner:
    """Constant-amortized-time state machine per completed 5m candle."""

    def __init__(self, frame, config, timeframe="5m"):
        if timeframe != "5m":
            raise ValueError("AMRS requires closed 5m candle inputs")
        self.config = config
        self.new_setups = {}
        self.setups = {}  # retained for shared pending-order cancellation
        self.retests = {}
        self.last_breakout = {}
        self.completed = _aggregate_completed(
            frame[["open", "high", "low", "close", "volume"]], "5m", "15m")
        self.stops = deque(maxlen=max(config.trend.stop_lookback_bars,
                                     config.compression.stop_lookback_bars))
        self.hourly = deque(maxlen=config.regime.ema_slope_bars+1)
        self.raw_state = "TRANSITION"
        self.regime = "TRANSITION"
        self._candidate = None
        self._hits = 0
        self.regime_log = []
        self.last_hour = None
        self.trade_candidate = {}

    def _classify(self, row):
        c = self.config.regime
        pct = finite(row,c.atr_percentile_id)
        adx = finite(row,c.adx_id+".adx")
        fast = finite(row,c.fast_ema_id)
        slow = finite(row,c.slow_ema_id)
        close = finite(row,c.close_ema_id)
        plus = finite(row,c.adx_id+".plus_di")
        minus = finite(row,c.adx_id+".minus_di")
        if None in (pct,adx,fast,slow,close,plus,minus):
            return "TRANSITION"
        if pct >= c.atr_extreme_min:
            return "EXTREME_VOLATILITY"
        if pct <= c.atr_compression_max and adx <= c.adx_range_max:
            return "COMPRESSION"
        if adx < c.adx_range_max:
            return "RANGE"
        if adx < c.adx_trend_min:
            return "TRANSITION"
        if c.require_ema_slope:
            if len(self.hourly) < self.hourly.maxlen:
                return "TRANSITION"
            slope = fast-self.hourly[0]
        else:
            slope = 0
        if fast > slow and close > fast and plus > minus and (
                not c.require_ema_slope or slope > 0):
            return "TREND_UP"
        if fast < slow and close < fast and minus > plus and (
                not c.require_ema_slope or slope < 0):
            return "TREND_DOWN"
        return "TRANSITION"

    def _update_hour(self, timestamp, row):
        stamp=pd.Timestamp(timestamp)
        if stamp.minute != 0 or stamp.second:
            return
        if self.last_hour is not None and stamp <= self.last_hour:
            raise ValueError("AMRS received nonmonotonic completed 1h bars")
        self.last_hour = stamp
        self.hourly.append(finite(row,self.config.regime.fast_ema_id))
        raw = self._classify(row)
        if raw == self._candidate:
            self._hits += 1
        else:
            self._candidate = raw
            self._hits = 1
        # Reject ambiguous regimes immediately; don't allow stale trend
        # orders to survive a newly detected volatility shock.
        if raw in ("EXTREME_VOLATILITY","TRANSITION"):
            self.regime = raw
        elif self._hits >= self.config.regime.confirmations:
            self.regime = raw
        else:
            self.regime = "TRANSITION"
        self.raw_state = raw
        self.regime_log.append((stamp.isoformat(),self.regime,raw))

    def valid_pending(self, setup):
        if setup.get("regime") != self.regime:
            return False
        return self.regime in ("TREND_UP","TREND_DOWN","COMPRESSION")

    def _candidate_for_side(self, row, bar, side, module, module_name):
        level = finite(row, module.donchian_id + (".upper" if side=="LONG" else ".lower"))
        atr = finite(row,module.atr_id)
        vr = finite(row,module.volume_ratio_id)
        if None in (level,atr,vr) or atr <= 0 or vr < module.volume_ratio_min:
            return None
        close = float(bar.close)
        opened = float(bar.open)
        passed = close > level+module.breakout_buffer_points if side=="LONG" else (
            close < level-module.breakout_buffer_points)
        if module.require_confirmation_color:
            passed = passed and (close > opened if side=="LONG" else close < opened)
        if not passed:
            return None
        # The range includes this completed 15m candle, but its structure
        # extreme must be conservative and never inferred from future bars.
        recent=list(self.stops)[-module.stop_lookback_bars:]
        if len(recent)<module.stop_lookback_bars:
            return None
        extreme=min(x[0] for x in recent) if side=="LONG" else max(x[1] for x in recent)
        structure_stop=(extreme-module.stop_atr_multiple*atr if side=="LONG"
                        else extreme+module.stop_atr_multiple*atr)
        if structure_stop <= 0 or ((close-structure_stop)*(1 if side=="LONG" else -1)) <= 0:
            return None
        return {"side":side,"module":module_name,"level":level,
                "stop_price":structure_stop,"atr":atr,
                "reward_r_multiple":module.reward_r_multiple,
                "regime":self.regime,
                "confirmed_time":self.last_15m.isoformat()}

    def _handle_retest(self, timestamp, bar, row):
        for side,state in list(self.retests.items()):
            mod=self.config.compression if state["module"]=="COMPRESSION" else self.config.trend
            age=(pd.Timestamp(timestamp)-pd.Timestamp(state["confirmed_time"])).total_seconds()/300
            if age > mod.retest_max_wait_bars or self.regime != state["regime"]:
                del self.retests[side]
                continue
            level=state["level"]
            tolerance=state["atr"]*mod.retest_tolerance_atr
            close=float(bar.close)
            touched=(float(bar.low)<=level+tolerance if side=="LONG"
                     else float(bar.high)>=level-tolerance)
            held=(close>=level if side=="LONG" else close<=level)
            if touched and held:
                # Retest is a completed 15m candle, so only later 5m OHLC
                # can trigger the resulting stop-market entry.
                proposed=dict(state)
                proposed["level"]=(float(bar.high) if side=="LONG" else float(bar.low))
                proposed["setup_time"]=pd.Timestamp(timestamp).isoformat()
                self._emit(side,proposed)
                del self.retests[side]

    def _emit(self, side, item):
        if side in self.new_setups or side in self.setups:
            return
        snapshot={"level":item["level"],"stop_price":item["stop_price"],
                  "setup_time":item.get("setup_time",item["confirmed_time"]),
                  "module":item["module"],"regime":item["regime"],
                  "reward_r_multiple":item["reward_r_multiple"]}
        self.new_setups[side]=snapshot
        self.setups[side]=snapshot

    def step(self,index,timestamp,row):
        self.new_setups={}
        self._update_hour(timestamp,row)
        if timestamp not in self.completed.index:
            return {}
        self.last_15m=pd.Timestamp(timestamp)
        bar=self.completed.loc[timestamp]
        self.stops.append((float(bar.low),float(bar.high)))
        self._handle_retest(timestamp,bar,row)
        if self.regime=="EXTREME_VOLATILITY" or self.regime in ("RANGE","TRANSITION"):
            self.retests.clear()
            return {}
        if self.regime=="COMPRESSION":
            module=self.config.compression
            sides=("LONG","SHORT")
            mode="COMPRESSION"
        else:
            module=self.config.trend
            sides=("LONG",) if self.regime=="TREND_UP" else ("SHORT",)
            mode="TREND"
        if not module.enabled:
            return {}
        for side in sides:
            if side in self.retests or side in self.setups:
                continue
            proposal=self._candidate_for_side(row,bar,side,module,mode)
            if proposal is None:
                continue
            # Do not repeatedly arm on a stale Donchian breakout.
            signature=(side,mode,round(proposal["level"],10))
            if self.last_breakout.get(side)==signature:
                continue
            self.last_breakout[side]=signature
            if module.require_retest:
                self.retests[side]=proposal
            else:
                proposal["setup_time"]=pd.Timestamp(timestamp).isoformat()
                self._emit(side,proposal)
        return {}


def trail_stop(position, previous_bar, cfg, tick_size):
    """Update at current candle OPEN using only the preceding completed bar.

    Stops are never loosened and are never computed from same-bar high/low.
    Returns the new stop or None; caller enforces protective stop ordering.
    """
    if not cfg.enabled or not position.get("adaptive_module"):
        return None
    sign=1 if position["direction"]=="LONG" else -1
    initial_r=position.get("initial_r")
    if not initial_r or initial_r <= 0:
        return None
    close=float(previous_bar.close)
    entry=float(position["entry_price"])
    peak=float(position.get("favorable_close",entry))
    peak=max(peak,close) if sign==1 else min(peak,close)
    position["favorable_close"]=peak
    if (peak-entry)*sign < cfg.activation_r*initial_r:
        return None
    atr=finite(previous_bar,cfg.atr_id)
    if atr is None or atr<=0:
        return None
    raw=(peak-cfg.atr_multiple*atr if sign==1 else peak+cfg.atr_multiple*atr)
    # Protective rounding does not overstate how tightly the trailing stop
    # could be placed based on already-completed bars.
    units=raw/tick_size
    target=(math.floor(units+1e-10) if sign==1 else math.ceil(units-1e-10))*tick_size
    current=position.get("stop_price")
    if current is None:
        return None
    tightened=max(current,target) if sign==1 else min(current,target)
    if (tightened-current)*sign <= 1e-10 or tightened<=0:
        return None
    position["stop_price"]=round(tightened,10)
    return position["stop_price"]
