from __future__ import annotations
import math
from typing import Any
import pandas as pd
from .models import Condition, RuleGroup


def _num(value: Any) -> float | None:
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _at(frame: pd.DataFrame, index: int, operand: str | None, offset: int = 0) -> float | None:
    if not operand:
        return None
    pos = index - offset
    if pos < 0 or operand not in frame.columns:
        return None
    return _num(frame.iloc[pos][operand])


def find_condition(group: RuleGroup, condition_id: str) -> Condition | None:
    for condition in group.conditions:
        if condition.id == condition_id:
            return condition
    for child in group.groups:
        found = find_condition(child, condition_id)
        if found is not None:
            return found
    return None


def _simple_compare(op: str, left: float | None, right: float | None) -> bool:
    if left is None or right is None: return False
    if op in {"GT","WAS_GT"}: return left > right
    if op in {"GTE","WAS_GTE"}: return left >= right
    if op in {"LT","WAS_LT"}: return left < right
    if op in {"LTE","WAS_LTE"}: return left <= right
    if op == "EQ": return math.isclose(left,right,rel_tol=1e-9,abs_tol=1e-12)
    return False


def _lookback_eval(frame: pd.DataFrame, index: int, c: Condition) -> tuple[bool,int,int|None,str]:
    """Evaluate a recent-history condition on completed bars only.

    left_offset shifts the entire window back. Example: lookback_bars=10 and
    left_offset=1 means "within the previous 10 completed bars, excluding the
    current candle". right_offset is shifted in parallel for right operands.
    """
    matches=0; last_match: int|None=None; lookback=max(1,int(c.lookback_bars))
    for age in range(lookback):
        lo=c.left_offset+age; ro=c.right_offset+age
        left=_at(frame,index,c.left,lo)
        if c.operator=="WAS_BETWEEN":
            ok=left is not None and c.value is not None and c.value2 is not None and float(c.value)<=left<=float(c.value2)
        elif c.operator in {"CROSSED_ABOVE_WITHIN","CROSSED_BELOW_WITHIN"}:
            right=_at(frame,index,c.right,ro) if c.right else c.value
            lp=_at(frame,index,c.left,lo+1); rp=_at(frame,index,c.right,ro+1) if c.right else c.value
            ok=False
            if None not in (left,right,lp,rp):
                ok=(lp<=rp and left>right) if c.operator=="CROSSED_ABOVE_WITHIN" else (lp>=rp and left<right)
        else:
            right=_at(frame,index,c.right,ro) if c.right else c.value
            ok=_simple_compare(c.operator,left,right)
        if ok:
            matches+=1
            bars_ago=c.left_offset+age
            if last_match is None or bars_ago<last_match: last_match=bars_ago
    return matches>0,matches,last_match,f"matched {matches}/{lookback} bars; most recent match {last_match} bars ago"


def _count_condition(frame: pd.DataFrame, index: int, c: Condition) -> tuple[bool,int,str]:
    lookback=max(1,int(c.lookback_bars)); count=0
    if c.operator == 'COUNT_TRUE_GTE':
        for age in range(lookback):
            value=_at(frame,index,c.left,c.left_offset+age)
            if value is not None and value > 0.5: count += 1
    else:
        for age in range(lookback):
            lo=c.left_offset+age; ro=c.right_offset+age
            left=_at(frame,index,c.left,lo); right=_at(frame,index,c.right,ro)
            lp=_at(frame,index,c.left,lo+1); rp=_at(frame,index,c.right,ro+1)
            if None in (left,right,lp,rp): continue
            above=lp<=rp and left>right
            below=lp>=rp and left<right
            if c.operator == 'COUNT_CROSS_ABOVE_GTE' and above: count += 1
            elif c.operator == 'COUNT_CROSS_BELOW_GTE' and below: count += 1
            elif c.operator == 'COUNT_CROSS_EITHER_GTE' and (above or below): count += 1
    required=int(c.value or 0)
    return count>=required,count,f'count {count}/{lookback} bars; required >= {required}'


def _slope_condition(frame: pd.DataFrame, index: int, c: Condition) -> tuple[bool,float|None,str]:
    bars=max(1,int(c.lookback_bars))
    current=_at(frame,index,c.left,c.left_offset)
    previous=_at(frame,index,c.left,c.left_offset+bars)
    if current is None or previous is None:
        return False,None,f'slope unavailable over {bars} bars'
    slope=(current-previous)/bars
    threshold=float(c.value or 0.0)
    if c.operator=='SLOPE_GT': passed=slope>threshold
    elif c.operator=='SLOPE_GTE': passed=slope>=threshold
    elif c.operator=='SLOPE_LT': passed=slope<threshold
    else: passed=slope<=threshold
    return passed,slope,f'slope {slope} points/bar over {bars} bars vs {threshold}'


def evaluate_condition(frame: pd.DataFrame, index: int, c: Condition) -> dict[str, Any]:
    left = _at(frame, index, c.left, c.left_offset)
    right = _at(frame, index, c.right, c.right_offset) if c.right else c.value
    passed = False
    details = ""
    delta_points: float | None = None
    delta_percent: float | None = None
    matched_count: int | None = None
    last_match_bars_ago: int | None = None
    slope_points_per_bar: float | None = None

    if left is not None and right is not None:
        delta_points = left - right
        if right != 0:
            delta_percent = delta_points / abs(right) * 100.0

    if c.operator in {"COUNT_TRUE_GTE","COUNT_CROSS_ABOVE_GTE","COUNT_CROSS_BELOW_GTE","COUNT_CROSS_EITHER_GTE"}:
        passed,matched_count,details=_count_condition(frame,index,c)
    elif c.operator in {"SLOPE_GT","SLOPE_GTE","SLOPE_LT","SLOPE_LTE"}:
        passed,slope_points_per_bar,details=_slope_condition(frame,index,c)
    elif c.operator in {"WAS_GT","WAS_GTE","WAS_LT","WAS_LTE","WAS_BETWEEN","CROSSED_ABOVE_WITHIN","CROSSED_BELOW_WITHIN"}:
        passed,matched_count,last_match_bars_ago,details=_lookback_eval(frame,index,c)
    elif c.operator == "BETWEEN":
        passed = left is not None and c.value is not None and c.value2 is not None and float(c.value) <= left <= float(c.value2)
        details = f"{left} between {c.value} and {c.value2}"
    elif c.operator in {"RISING", "FALLING"}:
        prev = _at(frame, index, c.left, c.left_offset + 1)
        passed = left is not None and prev is not None and (left > prev if c.operator == "RISING" else left < prev)
        right = prev
        if left is not None and prev is not None:
            delta_points = left - prev
            delta_percent = None if prev == 0 else delta_points / abs(prev) * 100.0
        details = f"{left} vs previous {prev}"
    elif c.operator in {"CROSSES_ABOVE", "CROSSES_BELOW"}:
        lp = _at(frame, index, c.left, c.left_offset + 1)
        rp = _at(frame, index, c.right, c.right_offset + 1) if c.right else c.value
        if None not in (left, right, lp, rp):
            passed = (lp <= rp and left > right) if c.operator == "CROSSES_ABOVE" else (lp >= rp and left < right)
        details = f"previous {lp} vs {rp}; current {left} vs {right}"
    elif c.operator in {"GT_BY_POINTS", "LT_BY_POINTS", "GT_BY_PERCENT", "LT_BY_PERCENT"}:
        margin = float(c.value or 0.0)
        if left is not None and right is not None:
            if c.operator == "GT_BY_POINTS":
                passed = left > right + margin; details = f"{left} > {right} + {margin}; difference={delta_points}"
            elif c.operator == "LT_BY_POINTS":
                passed = left < right - margin; details = f"{left} < {right} - {margin}; difference={delta_points}"
            elif c.operator == "GT_BY_PERCENT":
                passed = delta_percent is not None and delta_points is not None and delta_points > 0 and delta_percent > margin; details = f"{left} above {right} by {delta_percent}% > {margin}%"
            else:
                passed = delta_percent is not None and delta_points is not None and delta_points < 0 and abs(delta_percent) > margin; details = f"{left} below {right} by {abs(delta_percent) if delta_percent is not None else None}% > {margin}%"
    elif left is not None and right is not None:
        passed=_simple_compare(c.operator,left,right); details = f"{left} {c.operator} {right}"

    return {
        "id": c.id,"left": c.left,"operator": c.operator,"right": c.right,"value": c.value,"value2": c.value2,
        "left_offset": c.left_offset,"right_offset": c.right_offset,"lookback_bars": c.lookback_bars,
        "left_actual": left,"right_actual": right,"delta_points": delta_points,"delta_percent": delta_percent,
        "matched_count": matched_count,"last_match_bars_ago": last_match_bars_ago,
        "slope_points_per_bar": slope_points_per_bar,
        "passed": bool(passed),"details": details,
    }


def evaluate_group(frame: pd.DataFrame, index: int, g: RuleGroup, ignore_condition_ids: set[str] | None = None) -> dict[str, Any]:
    ignored=ignore_condition_ids or set()
    cond = [evaluate_condition(frame, index, c) for c in g.conditions if c.id not in ignored]
    groups = [evaluate_group(frame, index, x, ignored) for x in g.groups]
    # If an entire child subtree contained only setup-only conditions, omit it as
    # a neutral branch instead of turning an ALL group false at retest time.
    groups = [x for x in groups if not (ignored and x.get('total',0)==0 and x.get('ignored_only'))]
    states = [x["passed"] for x in cond] + [x["passed"] for x in groups]
    ignored_here=bool(ignored and not states and any(c.id in ignored for c in g.conditions))
    if not states: passed = True if ignored_here else False
    elif g.mode == "ALL": passed = all(states)
    elif g.mode == "ANY": passed = any(states)
    else: passed = sum(bool(x) for x in states) >= min(g.min_pass,len(states))
    return {"mode":g.mode,"min_pass":g.min_pass,"passed":passed,"passed_count":sum(bool(x) for x in states),"total":len(states),"conditions":cond,"groups":groups,"ignored_only":ignored_here}
