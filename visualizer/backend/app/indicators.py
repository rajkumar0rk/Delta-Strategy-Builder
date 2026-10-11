from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import ast
import math
import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo
from .models import IndicatorInstance

IST = ZoneInfo("Asia/Kolkata")

@dataclass(frozen=True)
class IndicatorDefinition:
    kind: str
    label: str
    category: str
    placement: str
    outputs: tuple[str, ...]
    params: dict[str, dict[str, Any]]
    description: str
    display_outputs: tuple[str, ...] | None = None

CATALOG: dict[str, IndicatorDefinition] = {
    "EMA": IndicatorDefinition("EMA", "Exponential Moving Average", "Trend", "overlay", ("value",), {"period":{"type":"int","default":9,"min":1,"max":500},"source":{"type":"select","default":"close","options":["open","high","low","close"]}}, "EMA with an SMA seed."),
    "SMA": IndicatorDefinition("SMA", "Simple Moving Average", "Trend", "overlay", ("value",), {"period":{"type":"int","default":20,"min":1,"max":1000},"source":{"type":"select","default":"close","options":["open","high","low","close"]}}, "Rolling arithmetic mean."),
    "VWAP": IndicatorDefinition("VWAP", "Session VWAP", "Trend", "overlay", ("value",), {}, "HLC3 volume-weighted average reset each IST session."),
    "RSI": IndicatorDefinition("RSI", "Relative Strength Index", "Momentum", "pane", ("value",), {"period":{"type":"int","default":14,"min":2,"max":200}}, "Wilder RSI."),
    "ATR": IndicatorDefinition("ATR", "Average True Range", "Volatility", "pane", ("value",), {"period":{"type":"int","default":14,"min":2,"max":200}}, "Wilder ATR."),
    "ADX_DMI": IndicatorDefinition("ADX_DMI", "ADX / DMI", "Trend strength", "pane", ("adx","plus_di","minus_di"), {"period":{"type":"int","default":14,"min":2,"max":200}}, "Wilder ADX with +DI and -DI. Useful for separating directional expansion from chop."),
    "CANDLE_STRENGTH": IndicatorDefinition("CANDLE_STRENGTH", "Candle Strength", "Price action", "pane", ("body_size","range_size","body_range_percent","body_atr","upper_wick_ratio","lower_wick_ratio","bullish","bearish"), {"atr_period":{"type":"int","default":14,"min":2,"max":200}}, "Candle body/range/ATR strength plus upper/lower wick ratios and bullish/bearish flags.", ("body_range_percent","body_atr")),
    "ATR_EXPANSION": IndicatorDefinition("ATR_EXPANSION", "ATR Expansion", "Volatility", "pane", ("atr","atr_sma","atr_ratio","atr_slope","atr_rising"), {"atr_period":{"type":"int","default":14,"min":2,"max":200},"sma_period":{"type":"int","default":20,"min":2,"max":500},"slope_bars":{"type":"int","default":5,"min":1,"max":200}}, "ATR relative to its own average, with multi-bar slope and rising flag.", ("atr_ratio","atr_slope")),
    "OVEREXTENSION": IndicatorDefinition("OVEREXTENSION", "EMA / ATR Overextension", "Trend", "pane", ("distance_atr","abs_distance_atr","ema","atr"), {"ema_period":{"type":"int","default":20,"min":1,"max":500},"atr_period":{"type":"int","default":14,"min":2,"max":200},"source":{"type":"select","default":"close","options":["open","high","low","close"]}}, "Signed and absolute distance from EMA normalized by ATR. Use it to avoid chasing an already-extended trend.", ("distance_atr",)),
    "FORMULA": IndicatorDefinition("FORMULA", "Derived Formula", "Derived", "pane", ("value",), {"expression":{"type":"text","default":"(close - ema20) / atr14"}}, "Safe arithmetic formula over raw OHLCV and previously calculated indicator operands. Supports + - * / parentheses and abs(...)."),
    "MACD": IndicatorDefinition("MACD", "MACD", "Momentum", "pane", ("macd","signal","histogram"), {"fast":{"type":"int","default":12,"min":1,"max":200},"slow":{"type":"int","default":26,"min":2,"max":400},"signal":{"type":"int","default":9,"min":1,"max":200}}, "EMA fast minus slow with signal line."),
    "STOCHASTIC": IndicatorDefinition("STOCHASTIC", "Classic Stochastic Oscillator", "Momentum", "pane", ("k","d"), {"k_period":{"type":"int","default":14,"min":2,"max":200},"smooth_k":{"type":"int","default":3,"min":1,"max":50},"d_period":{"type":"int","default":3,"min":1,"max":50}}, "Classic high/low stochastic oscillator. Raw %K is smoothed, then %D is an SMA of smoothed %K."),
    "STOCH_RSI": IndicatorDefinition("STOCH_RSI", "Stochastic RSI", "Momentum", "pane", ("k","d"), {"rsi_period":{"type":"int","default":14,"min":2,"max":200},"stoch_period":{"type":"int","default":14,"min":2,"max":200},"k":{"type":"int","default":3,"min":1,"max":50},"d":{"type":"int","default":3,"min":1,"max":50}}, "Stochastic oscillator of RSI."),
    "BOLLINGER": IndicatorDefinition("BOLLINGER", "Bollinger Bands", "Volatility", "overlay", ("middle","upper","lower"), {"period":{"type":"int","default":20,"min":2,"max":500},"stddev":{"type":"float","default":2.0,"min":0.1,"max":10.0}}, "SMA plus/minus standard deviations."),
    "VOLUME_SMA": IndicatorDefinition("VOLUME_SMA", "Volume SMA", "Volume", "pane", ("value",), {"period":{"type":"int","default":20,"min":1,"max":500}}, "Rolling mean of volume."),
    "VOLUME_RATIO": IndicatorDefinition("VOLUME_RATIO", "Volume Ratio", "Volume", "pane", ("value",), {"period":{"type":"int","default":20,"min":1,"max":500}}, "Current volume divided by prior rolling mean volume."),
    "DONCHIAN": IndicatorDefinition("DONCHIAN", "Donchian Channel", "Breakout", "overlay", ("upper","lower","middle"), {"period":{"type":"int","default":20,"min":2,"max":500}}, "Prior N-bar highest high / lowest low channel."),
    "PIVOTS": IndicatorDefinition(
        "PIVOTS", "Swing High / Swing Low (confirmed pivots)", "Market structure", "overlay",
        ("last_swing_high","last_swing_low","swing_high_confirmed","swing_low_confirmed","confirmed_high_price","confirmed_low_price"),
        {"left":{"type":"int","default":3,"min":1,"max":50},"right":{"type":"int","default":3,"min":1,"max":50}},
        "Confirms a pivot only after the configured right-side bars have closed. Rule signals appear on the confirmation candle, so there is no look-ahead.",
        ("last_swing_high","last_swing_low"),
    ),
    "DIVERGENCE": IndicatorDefinition(
        "DIVERGENCE", "Bullish / Bearish Divergence", "Market structure", "pane",
        ("oscillator","bullish","bearish","hidden_bullish","hidden_bearish","last_bullish_price","last_bearish_price","last_hidden_bullish_price","last_hidden_bearish_price"),
        {
            "oscillator":{"type":"select","default":"RSI","options":["RSI","STOCHASTIC_K","STOCH_RSI_K","MACD_HISTOGRAM"]},
            "period":{"type":"int","default":14,"min":2,"max":200},
            "fast":{"type":"int","default":12,"min":1,"max":200},
            "slow":{"type":"int","default":26,"min":2,"max":400},
            "signal":{"type":"int","default":9,"min":1,"max":200},
            "smooth_k":{"type":"int","default":3,"min":1,"max":50},
            "smooth_d":{"type":"int","default":3,"min":1,"max":50},
            "pivot_left":{"type":"int","default":3,"min":1,"max":50},
            "pivot_right":{"type":"int","default":3,"min":1,"max":50},
            "max_pivot_gap":{"type":"int","default":80,"min":2,"max":1000},
        },
        "Confirmed regular + hidden divergence. Regular bullish = lower price low + higher oscillator low; regular bearish = higher price high + lower oscillator high; hidden bullish = higher price low + lower oscillator low; hidden bearish = lower price high + higher oscillator high. Signals are emitted only when the second price pivot is confirmed.",
        ("oscillator",),
    ),
    "MARKET_STRUCTURE": IndicatorDefinition(
        "MARKET_STRUCTURE", "Market Structure / BOS", "Market structure", "overlay",
        ("last_swing_high","last_swing_low","bos_bullish","bos_bearish","structure_state"),
        {"pivot_left":{"type":"int","default":3,"min":1,"max":50},"pivot_right":{"type":"int","default":3,"min":1,"max":50},"break_buffer_percent":{"type":"float","default":0.0,"min":0.0,"max":20.0},"break_source":{"type":"select","default":"close","options":["close","wick"]}},
        "Tracks confirmed swing levels and emits bullish/bearish Break Of Structure only on the first break of each confirmed level.",
        ("last_swing_high","last_swing_low"),
    ),
    "SUPPORT_RESISTANCE": IndicatorDefinition(
        "SUPPORT_RESISTANCE", "Pivot Support / Resistance", "Market structure", "overlay",
        ("support","resistance","support_touches","resistance_touches"),
        {"pivot_left":{"type":"int","default":3,"min":1,"max":50},"pivot_right":{"type":"int","default":3,"min":1,"max":50},"tolerance_percent":{"type":"float","default":0.25,"min":0.01,"max":10.0},"min_touches":{"type":"int","default":2,"min":1,"max":20}},
        "Clusters confirmed pivot prices into support/resistance levels. Only pivots that are already confirmed at the current candle are used.",
        ("support","resistance"),
    ),
}

def catalog_payload():
    return [
        {"kind": d.kind, "label": d.label, "category": d.category, "placement": d.placement,
         "outputs": list(d.outputs), "display_outputs": list(d.display_outputs or d.outputs),
         "params": d.params, "description": d.description}
        for d in CATALOG.values()
    ]

def _ema(values: pd.Series, period: int) -> pd.Series:
    arr = values.astype(float).to_numpy()
    out = np.full(len(arr), np.nan)
    if len(arr) < period: return pd.Series(out, index=values.index)
    seed = np.nanmean(arr[:period])
    out[period-1] = seed
    alpha = 2.0/(period+1.0)
    prev = seed
    for i in range(period, len(arr)):
        prev = alpha*arr[i] + (1-alpha)*prev
        out[i] = prev
    return pd.Series(out,index=values.index)

def _rsi(values: pd.Series, period: int) -> pd.Series:
    arr=values.astype(float).to_numpy(); out=np.full(len(arr),np.nan)
    if len(arr)<=period: return pd.Series(out,index=values.index)
    delta=np.diff(arr)
    gains=np.where(delta>0,delta,0.0); losses=np.where(delta<0,-delta,0.0)
    ag=float(np.mean(gains[:period])); al=float(np.mean(losses[:period]))
    def val(g,l): return 100.0 if l==0 and g>0 else 50.0 if l==0 else 100.0-(100.0/(1.0+g/l))
    out[period]=val(ag,al)
    for i in range(period+1,len(arr)):
        ag=(ag*(period-1)+gains[i-1])/period; al=(al*(period-1)+losses[i-1])/period
        out[i]=val(ag,al)
    return pd.Series(out,index=values.index)

def _atr(frame: pd.DataFrame, period:int)->pd.Series:
    h=frame.high.to_numpy(float); l=frame.low.to_numpy(float); c=frame.close.to_numpy(float)
    tr=np.full(len(frame),np.nan)
    if len(frame): tr[0]=h[0]-l[0]
    for i in range(1,len(frame)): tr[i]=max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1]))
    out=np.full(len(frame),np.nan)
    if len(frame)<period: return pd.Series(out,index=frame.index)
    prev=float(np.mean(tr[:period])); out[period-1]=prev
    for i in range(period,len(frame)):
        prev=(prev*(period-1)+tr[i])/period; out[i]=prev
    return pd.Series(out,index=frame.index)

def _wilder_rma(values: pd.Series, period: int) -> pd.Series:
    arr = values.astype(float).to_numpy()
    out = np.full(len(arr), np.nan)
    valid = np.where(np.isfinite(arr))[0]
    if len(valid) < period:
        return pd.Series(out, index=values.index)
    # Indicators here begin from contiguous market data; use the first period
    # values as the seed and then Wilder's recursive smoothing.
    start = int(valid[0])
    if start + period > len(arr):
        return pd.Series(out, index=values.index)
    seed_values = arr[start:start+period]
    if not np.all(np.isfinite(seed_values)):
        return pd.Series(out, index=values.index)
    prev = float(np.mean(seed_values))
    seed_index = start + period - 1
    out[seed_index] = prev
    for i in range(seed_index + 1, len(arr)):
        if not np.isfinite(arr[i]):
            continue
        prev = (prev * (period - 1) + float(arr[i])) / period
        out[i] = prev
    return pd.Series(out, index=values.index)


def _adx_dmi(frame: pd.DataFrame, period: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    high = frame.high.astype(float)
    low = frame.low.astype(float)
    close = frame.close.astype(float)
    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=frame.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=frame.index)
    prev_close = close.shift(1)
    tr = pd.concat([(high-low).abs(), (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    atr = _wilder_rma(tr, period)
    plus = 100.0 * _wilder_rma(plus_dm, period) / atr.replace(0.0, np.nan)
    minus = 100.0 * _wilder_rma(minus_dm, period) / atr.replace(0.0, np.nan)
    dx = 100.0 * (plus-minus).abs() / (plus+minus).replace(0.0, np.nan)
    adx = _wilder_rma(dx.dropna(), period).reindex(frame.index)
    return adx, plus, minus


def _candle_strength(frame: pd.DataFrame, atr_period: int) -> dict[str, pd.Series]:
    body = (frame.close-frame.open).abs()
    rng = (frame.high-frame.low).abs()
    atr = _atr(frame, atr_period)
    upper = frame.high - pd.concat([frame.open, frame.close], axis=1).max(axis=1)
    lower = pd.concat([frame.open, frame.close], axis=1).min(axis=1) - frame.low
    return {
        'body_size': body,
        'range_size': rng,
        'body_range_percent': body / rng.replace(0.0, np.nan) * 100.0,
        'body_atr': body / atr.replace(0.0, np.nan),
        'upper_wick_ratio': upper / rng.replace(0.0, np.nan) * 100.0,
        'lower_wick_ratio': lower / rng.replace(0.0, np.nan) * 100.0,
        'bullish': (frame.close > frame.open).astype(float),
        'bearish': (frame.close < frame.open).astype(float),
    }


def _atr_expansion(frame: pd.DataFrame, atr_period: int, sma_period: int, slope_bars: int) -> dict[str, pd.Series]:
    atr = _atr(frame, atr_period)
    avg = atr.rolling(sma_period, min_periods=sma_period).mean()
    slope = (atr - atr.shift(slope_bars)) / float(slope_bars)
    return {
        'atr': atr,
        'atr_sma': avg,
        'atr_ratio': atr / avg.replace(0.0, np.nan),
        'atr_slope': slope,
        'atr_rising': (slope > 0).astype(float),
    }


def _overextension(frame: pd.DataFrame, ema_period: int, atr_period: int, source: str) -> dict[str, pd.Series]:
    ema = _ema(frame[source], ema_period)
    atr = _atr(frame, atr_period)
    dist = (frame[source] - ema) / atr.replace(0.0, np.nan)
    return {'distance_atr': dist, 'abs_distance_atr': dist.abs(), 'ema': ema, 'atr': atr}


def _formula_column_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _formula_column_name(node.value) + '.' + node.attr
    raise ValueError('Formula operands must be raw fields or indicator ids/outputs')


def _formula_eval_node(node: ast.AST, frame: pd.DataFrame):
    if isinstance(node, ast.Expression):
        return _formula_eval_node(node.body, frame)
    if isinstance(node, (ast.Name, ast.Attribute)):
        name = _formula_column_name(node)
        if name not in frame.columns:
            raise ValueError(f"Formula references unknown operand '{name}'. Put dependency indicators before this formula.")
        return frame[name].astype(float)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = _formula_eval_node(node.operand, frame)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
        left = _formula_eval_node(node.left, frame); right = _formula_eval_node(node.right, frame)
        if isinstance(node.op, ast.Add): return left + right
        if isinstance(node.op, ast.Sub): return left - right
        if isinstance(node.op, ast.Mult): return left * right
        if isinstance(node.op, ast.Div):
            if isinstance(right, pd.Series): right = right.replace(0.0, np.nan)
            elif right == 0: return pd.Series(np.nan, index=frame.index)
            return left / right
        return left ** right
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'abs' and len(node.args) == 1:
        value = _formula_eval_node(node.args[0], frame)
        return abs(value)
    raise ValueError('Formula supports only operands, numeric constants, + - * / **, parentheses and abs(...)')


def _formula(frame: pd.DataFrame, expression: str) -> pd.Series:
    try:
        tree = ast.parse(expression, mode='eval')
    except SyntaxError as exc:
        raise ValueError(f'Invalid formula: {exc.msg}') from exc
    value = _formula_eval_node(tree, frame)
    if isinstance(value, pd.Series): return value.replace([np.inf, -np.inf], np.nan)
    return pd.Series(float(value), index=frame.index)


_TF_MINUTES = {'5m':5,'10m':10,'15m':15,'30m':30,'1h':60}

def _aggregate_completed(frame: pd.DataFrame, base_tf: str, target_tf: str) -> pd.DataFrame:
    """Aggregate completed candles on fixed UTC clock boundaries.

    Pandas 3 may store timezone-aware datetime integers at microsecond resolution,
    so this function intentionally never converts timestamps to raw integers or
    assumes nanoseconds.  ``resample`` operates on the DatetimeIndex directly.

    Candle timestamps in Strategy Lab are candle-close times.  With
    ``closed='right', label='right'``, 5m closes 00:05 and 00:10 form the 10m
    candle ending 00:10; 00:15 and 00:20 form the one ending 00:20.
    """
    base = _TF_MINUTES[base_tf]; target = _TF_MINUTES[target_tf]
    if target < base or target % base != 0:
        raise ValueError(f'Indicator timeframe {target_tf} must be an exact multiple of strategy timeframe {base_tf}')
    if target == base:
        return frame.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError('Indicator aggregation requires a DatetimeIndex')
    tmp = frame.sort_index().copy()
    if tmp.index.tz is None:
        tmp.index = tmp.index.tz_localize('UTC')
    else:
        tmp.index = tmp.index.tz_convert('UTC')
    rule = f'{target}min'
    expected = target // base
    rs = tmp.resample(rule, origin='epoch', label='right', closed='right')
    grouped = rs.agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'})
    counts = rs['close'].count()
    grouped = grouped[counts == expected]
    return grouped.dropna(subset=['open','high','low','close']).sort_index()


def _stochastic(frame: pd.DataFrame, k_period: int, smooth_k: int, d_period: int) -> tuple[pd.Series, pd.Series]:
    lo = frame.low.rolling(k_period, min_periods=k_period).min()
    hi = frame.high.rolling(k_period, min_periods=k_period).max()
    raw = 100.0 * (frame.close - lo) / (hi - lo).replace(0.0, np.nan)
    k = raw.rolling(smooth_k, min_periods=smooth_k).mean()
    d = k.rolling(d_period, min_periods=d_period).mean()
    return k, d

def _pivot_confirmations(frame: pd.DataFrame, left: int, right: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return confirmation-candle flags/prices without look-ahead.

    A candidate at p is known only at confirmation index p+right. The returned
    arrays are indexed by confirmation candle, not by the historical pivot bar.
    """
    n = len(frame)
    hi = frame.high.to_numpy(float); lo = frame.low.to_numpy(float)
    high_flag = np.zeros(n, dtype=float); low_flag = np.zeros(n, dtype=float)
    high_price = np.full(n, np.nan); low_price = np.full(n, np.nan)
    for confirm in range(n):
        p = confirm - right
        if p < left or p < 0 or p + right >= n:
            continue
        hs = hi[p-left:p+right+1]; ls = lo[p-left:p+right+1]
        # Require the candidate to be a unique extreme in its window. This
        # prevents a plateau from producing several adjacent "pivots".
        if np.isfinite(hi[p]) and hi[p] == np.nanmax(hs) and np.sum(np.isclose(hs, hi[p], rtol=0, atol=1e-12)) == 1:
            high_flag[confirm] = 1.0; high_price[confirm] = hi[p]
        if np.isfinite(lo[p]) and lo[p] == np.nanmin(ls) and np.sum(np.isclose(ls, lo[p], rtol=0, atol=1e-12)) == 1:
            low_flag[confirm] = 1.0; low_price[confirm] = lo[p]
    return high_flag, low_flag, high_price, low_price

def _last_levels(high_flag: np.ndarray, low_flag: np.ndarray, high_price: np.ndarray, low_price: np.ndarray) -> tuple[np.ndarray,np.ndarray]:
    n=len(high_flag); last_hi=np.full(n,np.nan); last_lo=np.full(n,np.nan); h=math.nan; l=math.nan
    for i in range(n):
        if high_flag[i] > 0: h=float(high_price[i])
        if low_flag[i] > 0: l=float(low_price[i])
        last_hi[i]=h; last_lo[i]=l
    return last_hi,last_lo

def _divergence_oscillator(frame: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    kind=str(p['oscillator'])
    period=int(p['period'])
    if kind=='RSI': return _rsi(frame.close,period)
    if kind=='STOCHASTIC_K':
        k,_=_stochastic(frame,period,int(p['smooth_k']),int(p['smooth_d'])); return k
    if kind=='STOCH_RSI_K':
        r=_rsi(frame.close,period); lo=r.rolling(period,min_periods=period).min(); hi=r.rolling(period,min_periods=period).max(); raw=100*(r-lo)/(hi-lo).replace(0,np.nan); return raw.rolling(int(p['smooth_k']),min_periods=int(p['smooth_k'])).mean()
    fast=_ema(frame.close,int(p['fast'])); slow=_ema(frame.close,int(p['slow'])); macd=fast-slow; sig=_ema(macd.dropna(),int(p['signal'])).reindex(frame.index); return macd-sig

def _divergence(frame: pd.DataFrame, p: dict[str, Any]) -> dict[str,pd.Series]:
    left=int(p['pivot_left']); right=int(p['pivot_right']); gap=int(p['max_pivot_gap'])
    osc=_divergence_oscillator(frame,p)
    high_flag,low_flag,high_price,low_price=_pivot_confirmations(frame,left,right)
    n=len(frame)
    bull=np.zeros(n,float); bear=np.zeros(n,float)
    hidden_bull=np.zeros(n,float); hidden_bear=np.zeros(n,float)
    last_bull=np.full(n,np.nan); last_bear=np.full(n,np.nan)
    last_hidden_bull=np.full(n,np.nan); last_hidden_bear=np.full(n,np.nan)
    prev_low: tuple[int,float,float] | None=None; prev_high: tuple[int,float,float] | None=None
    bull_price=math.nan; bear_price=math.nan; hidden_bull_price=math.nan; hidden_bear_price=math.nan
    osc_arr=osc.to_numpy(float)
    for i in range(n):
        pivot_index=i-right
        if low_flag[i]>0 and pivot_index>=0:
            o=osc_arr[pivot_index]
            if np.isfinite(o):
                cur=(pivot_index,float(low_price[i]),float(o))
                if prev_low and cur[0]-prev_low[0] <= gap:
                    # Regular bullish: price lower low, oscillator higher low.
                    if cur[1] < prev_low[1] and cur[2] > prev_low[2]:
                        bull[i]=1.0; bull_price=cur[1]
                    # Hidden bullish continuation: price higher low, oscillator lower low.
                    if cur[1] > prev_low[1] and cur[2] < prev_low[2]:
                        hidden_bull[i]=1.0; hidden_bull_price=cur[1]
                prev_low=cur
        if high_flag[i]>0 and pivot_index>=0:
            o=osc_arr[pivot_index]
            if np.isfinite(o):
                cur=(pivot_index,float(high_price[i]),float(o))
                if prev_high and cur[0]-prev_high[0] <= gap:
                    # Regular bearish: price higher high, oscillator lower high.
                    if cur[1] > prev_high[1] and cur[2] < prev_high[2]:
                        bear[i]=1.0; bear_price=cur[1]
                    # Hidden bearish continuation: price lower high, oscillator higher high.
                    if cur[1] < prev_high[1] and cur[2] > prev_high[2]:
                        hidden_bear[i]=1.0; hidden_bear_price=cur[1]
                prev_high=cur
        last_bull[i]=bull_price; last_bear[i]=bear_price
        last_hidden_bull[i]=hidden_bull_price; last_hidden_bear[i]=hidden_bear_price
    return {
        "oscillator":osc,
        "bullish":pd.Series(bull,index=frame.index),
        "bearish":pd.Series(bear,index=frame.index),
        "hidden_bullish":pd.Series(hidden_bull,index=frame.index),
        "hidden_bearish":pd.Series(hidden_bear,index=frame.index),
        "last_bullish_price":pd.Series(last_bull,index=frame.index),
        "last_bearish_price":pd.Series(last_bear,index=frame.index),
        "last_hidden_bullish_price":pd.Series(last_hidden_bull,index=frame.index),
        "last_hidden_bearish_price":pd.Series(last_hidden_bear,index=frame.index),
    }

def _market_structure(frame: pd.DataFrame, p: dict[str, Any]) -> dict[str,pd.Series]:
    left=int(p['pivot_left']); right=int(p['pivot_right']); buffer=float(p['break_buffer_percent'])/100.0; source=str(p['break_source'])
    hf,lf,hp,lp=_pivot_confirmations(frame,left,right); last_hi,last_lo=_last_levels(hf,lf,hp,lp)
    n=len(frame); bull=np.zeros(n,float); bear=np.zeros(n,float); state=np.zeros(n,float)
    high_generation=0; low_generation=0; broken_high=-1; broken_low=-1; current_state=0.0
    close=frame.close.to_numpy(float); high=frame.high.to_numpy(float); low=frame.low.to_numpy(float)
    for i in range(n):
        if hf[i]>0: high_generation+=1
        if lf[i]>0: low_generation+=1
        hi_level=last_hi[i]; lo_level=last_lo[i]
        up_now=high[i] if source=='wick' else close[i]; dn_now=low[i] if source=='wick' else close[i]
        up_prev=(high[i-1] if source=='wick' else close[i-1]) if i>0 else up_now
        dn_prev=(low[i-1] if source=='wick' else close[i-1]) if i>0 else dn_now
        if np.isfinite(hi_level) and high_generation!=broken_high:
            level=float(hi_level)*(1.0+buffer)
            if up_now>level and up_prev<=level:
                bull[i]=1.0; current_state=1.0; broken_high=high_generation
        if np.isfinite(lo_level) and low_generation!=broken_low:
            level=float(lo_level)*(1.0-buffer)
            if dn_now<level and dn_prev>=level:
                bear[i]=1.0; current_state=-1.0; broken_low=low_generation
        state[i]=current_state
    return {"last_swing_high":pd.Series(last_hi,index=frame.index),"last_swing_low":pd.Series(last_lo,index=frame.index),"bos_bullish":pd.Series(bull,index=frame.index),"bos_bearish":pd.Series(bear,index=frame.index),"structure_state":pd.Series(state,index=frame.index)}

def _support_resistance(frame: pd.DataFrame, p: dict[str, Any]) -> dict[str,pd.Series]:
    left=int(p['pivot_left']); right=int(p['pivot_right']); tol=float(p['tolerance_percent'])/100.0; min_touches=int(p['min_touches'])
    hf,lf,hp,lp=_pivot_confirmations(frame,left,right)
    clusters: list[dict[str,float]]=[]
    n=len(frame); support=np.full(n,np.nan); resistance=np.full(n,np.nan); st=np.zeros(n,float); rt=np.zeros(n,float)
    def add_level(price: float):
        if not math.isfinite(price) or price<=0:return
        best=None; best_dist=None
        for c in clusters:
            dist=abs(price-c['price'])/max(abs(c['price']),1e-12)
            if dist<=tol and (best_dist is None or dist<best_dist): best=c;best_dist=dist
        if best is None: clusters.append({'price':price,'touches':1.0})
        else:
            touches=best['touches']; best['price']=(best['price']*touches+price)/(touches+1.0); best['touches']=touches+1.0
    for i in range(n):
        if hf[i]>0:add_level(float(hp[i]))
        if lf[i]>0:add_level(float(lp[i]))
        close=float(frame.close.iloc[i]); eligible=[c for c in clusters if c['touches']>=min_touches]
        below=[c for c in eligible if c['price']<=close]; above=[c for c in eligible if c['price']>=close]
        if below:
            c=max(below,key=lambda x:x['price']); support[i]=c['price']; st[i]=c['touches']
        if above:
            c=min(above,key=lambda x:x['price']); resistance[i]=c['price']; rt[i]=c['touches']
    return {"support":pd.Series(support,index=frame.index),"resistance":pd.Series(resistance,index=frame.index),"support_touches":pd.Series(st,index=frame.index),"resistance_touches":pd.Series(rt,index=frame.index)}

def _instance_label(inst: IndicatorInstance, params: dict[str, Any]) -> str:
    if inst.kind in {"EMA", "SMA", "RSI", "ATR", "VOLUME_SMA", "VOLUME_RATIO", "DONCHIAN"}:
        period = params.get("period")
        return f"{inst.kind.replace('_', ' ')} {period}" if period is not None else inst.kind.replace('_', ' ')
    if inst.kind == "MACD": return f"MACD {params.get('fast')}/{params.get('slow')}/{params.get('signal')}"
    if inst.kind == "STOCHASTIC": return f"Stochastic {params.get('k_period')}/{params.get('smooth_k')}/{params.get('d_period')}"
    if inst.kind == "STOCH_RSI": return f"Stoch RSI {params.get('rsi_period')}/{params.get('stoch_period')}/{params.get('k')}/{params.get('d')}"
    if inst.kind == "BOLLINGER": return f"Bollinger {params.get('period')} × {params.get('stddev')}"
    if inst.kind == "VWAP": return "Session VWAP"
    if inst.kind == "PIVOTS": return f"Pivots L{params.get('left')} R{params.get('right')}"
    if inst.kind == "DIVERGENCE": return f"Divergence · {params.get('oscillator')}"
    if inst.kind == "MARKET_STRUCTURE": return f"Market structure L{params.get('pivot_left')} R{params.get('pivot_right')}"
    if inst.kind == "SUPPORT_RESISTANCE": return f"Support / Resistance · {params.get('min_touches')} touches"
    if inst.kind == "ADX_DMI": return f"ADX/DMI {params.get('period')}"
    if inst.kind == "CANDLE_STRENGTH": return f"Candle strength · ATR {params.get('atr_period')}"
    if inst.kind == "ATR_EXPANSION": return f"ATR expansion {params.get('atr_period')}/{params.get('sma_period')}"
    if inst.kind == "OVEREXTENSION": return f"EMA{params.get('ema_period')} distance / ATR{params.get('atr_period')}"
    if inst.kind == "FORMULA": return f"Formula · {params.get('expression')}"
    return inst.kind.replace('_', ' ')

def compute_indicators(frame: pd.DataFrame, instances: list[IndicatorInstance], strategy_timeframe: str = '5m') -> tuple[pd.DataFrame,list[dict[str,Any]]]:
    if strategy_timeframe not in _TF_MINUTES:
        raise ValueError(f'Unsupported strategy timeframe: {strategy_timeframe}')
    result=frame.copy()
    # Handy raw boolean/numeric operands for count-based rules.
    result['bullish_close']=(result.close>result.open).astype(float)
    result['bearish_close']=(result.close<result.open).astype(float)
    result['candle_body']=(result.close-result.open).abs()
    result['candle_range']=(result.high-result.low).abs()
    frames: dict[str,pd.DataFrame] = {strategy_timeframe: result}
    series_meta=[]
    for inst in instances:
        if inst.kind not in CATALOG: raise ValueError(f"Unknown indicator kind: {inst.kind}")
        d=CATALOG[inst.kind]; p={k:v["default"] for k,v in d.params.items()}; p.update(inst.params)
        tf = strategy_timeframe if getattr(inst,'timeframe','strategy') == 'strategy' else str(inst.timeframe)
        if tf not in _TF_MINUTES:
            raise ValueError(f'Unsupported indicator timeframe: {tf}')
        if _TF_MINUTES[tf] < _TF_MINUTES[strategy_timeframe] or _TF_MINUTES[tf] % _TF_MINUTES[strategy_timeframe] != 0:
            raise ValueError(f"Indicator {inst.id} timeframe {tf} must be an exact multiple of strategy timeframe {strategy_timeframe}")
        if tf not in frames:
            frames[tf]=_aggregate_completed(result[['open','high','low','close','volume']],strategy_timeframe,tf)
            frames[tf]['bullish_close']=(frames[tf].close>frames[tf].open).astype(float)
            frames[tf]['bearish_close']=(frames[tf].close<frames[tf].open).astype(float)
            frames[tf]['candle_body']=(frames[tf].close-frames[tf].open).abs()
            frames[tf]['candle_range']=(frames[tf].high-frames[tf].low).abs()
        calc=frames[tf]
        outputs: dict[str,pd.Series]={}
        if inst.kind=="EMA": outputs["value"]=_ema(calc[str(p['source'])],int(p['period']))
        elif inst.kind=="SMA": outputs["value"]=calc[str(p['source'])].rolling(int(p['period']),min_periods=int(p['period'])).mean()
        elif inst.kind=="VWAP":
            local_dates=pd.Series(calc.index.tz_convert(IST).date,index=calc.index); typical=(calc.high+calc.low+calc.close)/3.0; cv=(typical*calc.volume).groupby(local_dates).cumsum(); vv=calc.volume.groupby(local_dates).cumsum().replace(0,np.nan); outputs["value"]=cv/vv
        elif inst.kind=="RSI": outputs["value"]=_rsi(calc.close,int(p['period']))
        elif inst.kind=="ATR": outputs["value"]=_atr(calc,int(p['period']))
        elif inst.kind=="ADX_DMI":
            adx,plus,minus=_adx_dmi(calc,int(p['period'])); outputs={"adx":adx,"plus_di":plus,"minus_di":minus}
        elif inst.kind=="CANDLE_STRENGTH": outputs=_candle_strength(calc,int(p['atr_period']))
        elif inst.kind=="ATR_EXPANSION": outputs=_atr_expansion(calc,int(p['atr_period']),int(p['sma_period']),int(p['slope_bars']))
        elif inst.kind=="OVEREXTENSION": outputs=_overextension(calc,int(p['ema_period']),int(p['atr_period']),str(p['source']))
        elif inst.kind=="FORMULA": outputs['value']=_formula(calc,str(p['expression']))
        elif inst.kind=="MACD":
            fast=_ema(calc.close,int(p['fast'])); slow=_ema(calc.close,int(p['slow'])); macd=fast-slow; signal=_ema(macd.dropna(),int(p['signal'])).reindex(calc.index); outputs={"macd":macd,"signal":signal,"histogram":macd-signal}
        elif inst.kind=="STOCHASTIC":
            k,dd=_stochastic(calc,int(p['k_period']),int(p['smooth_k']),int(p['d_period'])); outputs={"k":k,"d":dd}
        elif inst.kind=="STOCH_RSI":
            r=_rsi(calc.close,int(p['rsi_period'])); n=int(p['stoch_period']); lo=r.rolling(n,min_periods=n).min(); hi=r.rolling(n,min_periods=n).max(); raw=100*(r-lo)/(hi-lo).replace(0,np.nan); k=raw.rolling(int(p['k']),min_periods=int(p['k'])).mean(); dd=k.rolling(int(p['d']),min_periods=int(p['d'])).mean(); outputs={"k":k,"d":dd}
        elif inst.kind=="BOLLINGER":
            n=int(p['period']); mid=calc.close.rolling(n,min_periods=n).mean(); sd=calc.close.rolling(n,min_periods=n).std(ddof=0); mul=float(p['stddev']); outputs={"middle":mid,"upper":mid+mul*sd,"lower":mid-mul*sd}
        elif inst.kind=="VOLUME_SMA": outputs["value"]=calc.volume.rolling(int(p['period']),min_periods=int(p['period'])).mean()
        elif inst.kind=="VOLUME_RATIO":
            n=int(p['period']); prior=calc.volume.shift(1).rolling(n,min_periods=n).mean(); outputs["value"]=calc.volume/prior.replace(0,np.nan)
        elif inst.kind=="DONCHIAN":
            n=int(p['period']); upper=calc.high.shift(1).rolling(n,min_periods=n).max(); lower=calc.low.shift(1).rolling(n,min_periods=n).min(); outputs={"upper":upper,"lower":lower,"middle":(upper+lower)/2}
        elif inst.kind=="PIVOTS":
            hf,lf,hp,lp=_pivot_confirmations(calc,int(p['left']),int(p['right'])); last_hi,last_lo=_last_levels(hf,lf,hp,lp); outputs={"last_swing_high":pd.Series(last_hi,index=calc.index),"last_swing_low":pd.Series(last_lo,index=calc.index),"swing_high_confirmed":pd.Series(hf,index=calc.index),"swing_low_confirmed":pd.Series(lf,index=calc.index),"confirmed_high_price":pd.Series(hp,index=calc.index),"confirmed_low_price":pd.Series(lp,index=calc.index)}
        elif inst.kind=="DIVERGENCE": outputs=_divergence(calc,p)
        elif inst.kind=="MARKET_STRUCTURE": outputs=_market_structure(calc,p)
        elif inst.kind=="SUPPORT_RESISTANCE": outputs=_support_resistance(calc,p)
        display=set(d.display_outputs or d.outputs)
        for output, values in outputs.items():
            key=inst.id if len(d.outputs)==1 else f"{inst.id}.{output}"
            # Keep the operand in its native timeframe frame so later derived
            # indicators on the same timeframe can reference it.
            calc[key]=values
            aligned = values if tf == strategy_timeframe else values.reindex(result.index, method='ffill')
            result[key]=aligned
            if output not in display: continue
            base_label = _instance_label(inst, p)
            if tf != strategy_timeframe: base_label += f" · {tf}"
            series_meta.append({"key":key,"instance_id":inst.id,"kind":inst.kind,"indicator_label":base_label,"label":base_label if len(display)==1 else f"{base_label} · {output}","placement":d.placement,"output":output,"visible":inst.visible,"params":p,"timeframe":tf})
    return result, series_meta

