"""Completed 15m pattern events, six *subsequent* completed 5m confirmations.

This is an opt-in execution mode; ordinary strategy/lifecycle logic is unchanged.
Pattern ranges are taken from the complete formation, not a rolling Donchian
proxy. Setup compatibility comes from explicitly configured 30m rule trees.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import math
import pandas as pd

from .indicators import _aggregate_completed
from .rules import evaluate_group


@dataclass(frozen=True)
class PatternEvent:
    id: str
    side: str
    kind: str
    setup: str
    formed_at: pd.Timestamp
    high: float
    low: float


def _detect(window: pd.DataFrame) -> list[tuple[str, str, int]]:
    """(pattern name, side, formation length), using only completed 15m OHLC."""
    if len(window) < 1:
        return []
    x=window.iloc[-1]
    o,h,l,c=(float(x[k]) for k in ("open","high","low","close"))
    rng=h-l
    if not (math.isfinite(rng) and rng > 0 and l <= min(o,c) <= max(o,c) <= h):
        return []
    body=abs(c-o)
    upper=h-max(o,c);lower=min(o,c)-l
    bullish=c>o;bearish=c<o
    signals=[]
    if body/rng >= .85:
        signals.append(("BULL_MARUBOZU" if bullish else "BEAR_MARUBOZU",
                        "CALL" if bullish else "PUT",1))
    if lower/rng >= .55 and upper/rng <= .20 and body/rng <= .40 and bullish:
        signals.append(("HAMMER","CALL",1))
    if upper/rng >= .55 and lower/rng <= .20 and body/rng <= .40 and bearish:
        signals.append(("SHOOTING_STAR","PUT",1))
    if len(window)>=2:
        p=window.iloc[-2]
        po,pc=float(p.open),float(p.close)
        if po>pc and bullish and o<=pc and c>=po and body>0:
            signals.append(("BULL_ENGULFING","CALL",2))
        if po<pc and bearish and o>=pc and c<=po and body>0:
            signals.append(("BEAR_ENGULFING","PUT",2))
    if len(window)>=3:
        a,b=window.iloc[-3],window.iloc[-2]
        a_body=abs(float(a.close)-float(a.open))
        b_body=abs(float(b.close)-float(b.open))
        if a_body>0 and b_body <= a_body*.5:
            midpoint=(float(a.open)+float(a.close))/2
            if a.close<a.open and bullish and c>midpoint:
                signals.append(("MORNING_STAR","CALL",3))
            if a.close>a.open and bearish and c<midpoint:
                signals.append(("EVENING_STAR","PUT",3))
    return signals


class PatternTracker:
    """State per qualified pattern, not per sustained boolean condition.

    Events are formed once, only at the 15m close. Confirmation is permitted
    on exactly the next 1..max_wait_bars completed 5m candles; stop breach
    invalidates first. Multiple events are independent.
    """
    def __init__(self, frame: pd.DataFrame, config: Any):
        self.cfg=config
        if frame.empty:
            self.events_by_close={}
        else:
            daily=_aggregate_completed(frame[["open","high","low","close","volume"]],"5m","15m")
            self.events_by_close={}
            for j,(ts,_) in enumerate(daily.iterrows()):
                for name,side,n in _detect(daily.iloc[max(0,j-2):j+1]):
                    rng=daily.iloc[j-n+1:j+1]
                    event=PatternEvent(f"{side}:{name}:{ts.isoformat()}",side,name,"",ts,
                        float(rng.high.max()),float(rng.low.min()))
                    self.events_by_close.setdefault(ts,[]).append(event)
        self.active: dict[str,PatternEvent]={}
        self.consumed: set[str]=set()
        self.last_index: dict[str,int]={}
        self.signal_frame=frame

    def at_close(self, i:int, side:str, setup_passed:dict[str,bool]) -> PatternEvent | None:
        ts=self.signal_frame.index[i]
        # Qualify new event by the configured 30m pullback/breakout rules at
        # the time of formation. Do not retroactively qualify old patterns.
        for ev in self.events_by_close.get(ts,[]):
            if ev.side!=side:
                continue
            allowed=[]
            if ev.kind in self.cfg.pullback_patterns and setup_passed.get("PULLBACK"):
                allowed.append("PULLBACK")
            if ev.kind in self.cfg.breakout_patterns and setup_passed.get("BREAKOUT"):
                allowed.append("BREAKOUT")
            if not allowed:
                continue
            setup=allowed[0]  # deterministic tie: pullback before breakout
            qualified=PatternEvent(ev.id+":"+setup,ev.side,ev.kind,setup,ev.formed_at,ev.high,ev.low)
            self.active[qualified.id]=qualified
            self.last_index[qualified.id]=i
        current=self.signal_frame.iloc[i]
        c=float(current.close);o=float(current.open)
        hi=float(current.high);lo=float(current.low);volume=float(current.volume)
        candle_range=hi-lo
        body=abs(c-o)/candle_range if candle_range>0 else 0
        lookback=int(self.cfg.volume_lookback_bars)
        prev=self.signal_frame.iloc[max(0,i-lookback):i]
        avg=float(prev.volume.mean()) if len(prev)==lookback else 0
        volume_ok=avg>0 and volume>=avg*self.cfg.min_volume_ratio
        strong=(body>=self.cfg.min_body_range_ratio and
                ((c>o) if side=="CALL" else (c<o)))
        eligible=[]
        for key,event in list(self.active.items()):
            age=i-self.last_index[key]
            if age>self.cfg.confirmation_bars or key in self.consumed:
                del self.active[key];continue
            # No confirmation on the 15m pattern candle itself. All following
            # bars require no stop breach; 15m event range remains frozen.
            if event.side != side:
                continue
            if age>0 and ((lo<=event.low) if event.side=="CALL" else (hi>=event.high)):
                del self.active[key];continue
            if (age in range(1,self.cfg.confirmation_bars+1) and strong and volume_ok and
                ((c>event.high+self.cfg.breakout_buffer_points) if side=="CALL"
                 else (c<event.low-self.cfg.breakout_buffer_points))):
                eligible.append(event)
        return sorted(eligible,key=lambda e:(e.formed_at,e.id))[0] if eligible else None

    def consume(self, event:PatternEvent) -> None:
        self.consumed.add(event.id)
        self.active.pop(event.id,None)


def levels(event:PatternEvent, entry:float, buffer_points:float,
           target_1_r:float, target_2_r:float) -> dict[str,float]:
    stop=event.low-buffer_points if event.side=="CALL" else event.high+buffer_points
    distance=(entry-stop) if event.side=="CALL" else (stop-entry)
    if not all(map(math.isfinite,(entry,stop,distance))) or entry<=0 or distance<=0:
        raise ValueError("INVALID_PATTERN_STOP_DISTANCE")
    sign=1 if event.side=="CALL" else -1
    return {"stop":stop,"risk_points":distance,
            "target_1":entry+sign*distance*target_1_r,
            "target_2":entry+sign*distance*target_2_r,
            "pattern_high":event.high,"pattern_low":event.low,
            "pattern_time":event.formed_at.isoformat(),
            "pattern_type":event.kind,"setup_type":event.setup,"pattern_id":event.id}



def configured_exit_stages(config) -> list[dict[str, float]]:
    """Legacy two-stage parameters remain canonical when stages are omitted."""
    if config.take_profit_stages:
        return [{"r_multiple":float(s.r_multiple),"fraction":float(s.quantity_fraction)}
                for s in config.take_profit_stages]
    return [{"r_multiple":float(config.target_1_r),"fraction":float(config.first_exit_fraction)},
            {"r_multiple":float(config.target_2_r),"fraction":1.0-float(config.first_exit_fraction)}]


def plan_stage_quantities(quantity: float, spec:dict, config) -> list[float] | None:
    """Never invent fractional contract fills; last stage receives roundoff."""
    stages=configured_exit_stages(config)
    inc=float(spec.get("size_increment") or 1)
    minimum=float(spec.get("min_quantity") or inc)
    if inc<=0 or minimum<=0 or quantity<=0:
        return None
    valid_minimum=math.ceil(minimum/inc-1e-12)*inc
    planned=[]
    for stage in stages[:-1]:
        proposed=math.floor(quantity*stage["fraction"]/inc+1e-12)*inc
        if proposed+1e-9<valid_minimum:
            return None
        planned.append(proposed)
    remaining=quantity-sum(planned)
    if remaining+1e-9<valid_minimum:
        return None
    if abs(remaining/inc-round(remaining/inc))>1e-8*max(1,remaining/inc):
        return None
    planned.append(round(remaining,10))
    return planned


def option_risk_quantity(strategy,spec,entry_option_price,spot,stop,quote,balance):
    """Explicit approximate option premium downside, never 'exact Delta risk'.

    Assume an absolute option delta supplied by the user. Include entry
    spread loss and round-trip Delta fee/GST. If quantized risk is too high,
    reject instead of stepping up to exchange minimum.
    """
    from .engine import _delta_fee,_quantity
    risk=strategy.pattern_trade
    cv=float(spec["contract_value"])
    increment=float(spec.get("size_increment") or 1)
    minimum=float(spec.get("min_quantity") or increment)
    delta=risk.option_delta_assumption
    if delta is None:
        return 0.,0.,"OPTION_DELTA_ASSUMPTION_REQUIRED"
    premium_move=abs(spot-stop)*delta
    bid=float(quote["bid"])
    spread_loss=max(0.0,entry_option_price-bid)
    estimated_exit=max(0.0,entry_option_price-premium_move)
    one_entry=_delta_fee(spot,entry_option_price,1,cv,strategy.execution)["total_fee_usd"]
    one_exit=_delta_fee(stop,estimated_exit,1,cv,strategy.execution)["total_fee_usd"]
    per_contract=(premium_move+spread_loss)*cv+one_entry+one_exit
    if per_contract<=0 or not math.isfinite(per_contract):
        return 0.,0.,"INVALID_OPTION_RISK_ESTIMATE"
    units=math.floor(risk.max_risk_usd/per_contract/increment+1e-12)
    quantity=units*increment
    if quantity+1e-9<minimum:
        return 0.,quantity*per_contract,"RISK_LIMIT_BELOW_MINIMUM_LOT"
    # Delegate exchange size, budget, cash, and SELL-margin constraints to
    # the existing quantity checker. Pattern mode is BUY-only.
    changed=strategy.model_copy(update={"risk":strategy.risk.model_copy(
        update={"quantity_mode":"FIXED","quantity":quantity})})
    valid,cost,reject=_quantity(changed,spec,entry_option_price,spot,balance,"BUY")
    return valid,cost,reject
