from __future__ import annotations
import numpy as np
import pandas as pd

from app.indicators import compute_indicators, _divergence
from app.models import IndicatorInstance, Condition
from app.rules import evaluate_condition


def frame_from(high, low=None, close=None, volume=None):
    n=len(high)
    low=low if low is not None else [x-2 for x in high]
    close=close if close is not None else [(h+l)/2 for h,l in zip(high,low)]
    volume=volume if volume is not None else [100]*n
    idx=pd.date_range('2026-01-01',periods=n,freq='5min',tz='UTC')
    return pd.DataFrame({'open':close,'high':high,'low':low,'close':close,'volume':volume},index=idx,dtype=float)


def test_classic_stochastic_is_available_and_bounded():
    f=frame_from(list(range(11,41)), list(range(9,39)), list(range(10,40)))
    out,meta=compute_indicators(f,[IndicatorInstance(id='stoch',kind='STOCHASTIC',params={'k_period':5,'smooth_k':2,'d_period':2})])
    assert 'stoch.k' in out and 'stoch.d' in out
    valid=out['stoch.k'].dropna()
    assert len(valid)>0
    assert valid.between(0,100).all()
    assert {m['output'] for m in meta}=={'k','d'}


def test_pivot_is_emitted_only_on_confirmation_candle():
    f=frame_from([10,11,15,12,11,10],[8,9,10,9,8,7],[9,10,12,10,9,8])
    out,_=compute_indicators(f,[IndicatorInstance(id='p',kind='PIVOTS',params={'left':2,'right':2})])
    assert out['p.swing_high_confirmed'].iloc[:4].sum()==0
    assert out['p.swing_high_confirmed'].iloc[4]==1
    assert out['p.confirmed_high_price'].iloc[4]==15
    assert out['p.last_swing_high'].iloc[4]==15


def test_market_structure_bos_waits_for_confirmed_swing_then_break():
    high=[10,11,15,12,11,14,17,16]
    low =[8,9,10,9,8,10,12,11]
    close=[9,10,12,10,9,14,16,15]
    f=frame_from(high,low,close)
    out,_=compute_indicators(f,[IndicatorInstance(id='ms',kind='MARKET_STRUCTURE',params={'pivot_left':2,'pivot_right':2,'break_buffer_percent':0,'break_source':'close'})])
    assert out['ms.last_swing_high'].iloc[4]==15
    assert out['ms.bos_bullish'].iloc[:6].sum()==0
    assert out['ms.bos_bullish'].iloc[6]==1
    assert out['ms.structure_state'].iloc[6]==1


def test_divergence_logic_uses_confirmed_second_pivot(monkeypatch):
    # Price pivot lows at p=2 (10) and p=6 (8). Oscillator lows rise 20 -> 30.
    high=[14,13,12,13,14,12,11,12,13]
    low =[12,11,10,11,12,10,8,10,11]
    close=[13,12,11,12,13,11,9,11,12]
    f=frame_from(high,low,close)
    osc=pd.Series([50,35,20,40,55,40,30,45,55],index=f.index,dtype=float)
    import app.indicators as ind
    monkeypatch.setattr(ind,'_divergence_oscillator',lambda frame,p: osc)
    out=_divergence(f,{'oscillator':'RSI','period':14,'fast':12,'slow':26,'signal':9,'smooth_k':3,'smooth_d':3,'pivot_left':1,'pivot_right':1,'max_pivot_gap':20})
    # Second low at p=6 becomes known at confirmation candle 7.
    assert out['bullish'].iloc[:7].sum()==0
    assert out['bullish'].iloc[7]==1
    assert out['bearish'].sum()==0


def test_support_resistance_uses_confirmed_pivots_only():
    high=[10,15,10,15.05,10,12,10]
    low =[8,9,8,9,8,9,8]
    close=[9,11,9,11,9,10,9]
    f=frame_from(high,low,close)
    out,_=compute_indicators(f,[IndicatorInstance(id='sr',kind='SUPPORT_RESISTANCE',params={'pivot_left':1,'pivot_right':1,'tolerance_percent':1.0,'min_touches':2})])
    # Two confirmed highs around 15 form a resistance cluster after second confirmation.
    assert out['sr.resistance'].iloc[:4].isna().all()
    assert np.isfinite(out['sr.resistance'].iloc[4])
    assert out['sr.resistance_touches'].iloc[4]>=2


def test_was_oversold_within_last_n_bars_and_offset():
    idx=pd.date_range('2026-01-01',periods=5,freq='5min',tz='UTC')
    f=pd.DataFrame({'rsi':[20,25,35,50,60]},index=idx)
    c=Condition(id='recent-os',left='rsi',operator='WAS_LTE',value=30,lookback_bars=3)
    r=evaluate_condition(f,3,c)
    assert r['passed'] is True
    assert r['matched_count']==1
    assert r['last_match_bars_ago']==2
    c2=Condition(id='recent-os',left='rsi',operator='WAS_LTE',value=30,lookback_bars=2)
    assert evaluate_condition(f,3,c2)['passed'] is False
    c3=Condition(id='prior-only',left='rsi',operator='WAS_LTE',value=30,lookback_bars=2,left_offset=1)
    r3=evaluate_condition(f,3,c3)
    assert r3['passed'] is True
    assert r3['last_match_bars_ago']==2


def test_crossed_within_lookback():
    idx=pd.date_range('2026-01-01',periods=5,freq='5min',tz='UTC')
    f=pd.DataFrame({'a':[1,1,3,4,4],'b':[2,2,2,2,2]},index=idx)
    c=Condition(id='recent-cross',left='a',operator='CROSSED_ABOVE_WITHIN',right='b',lookback_bars=3)
    r=evaluate_condition(f,4,c)
    assert r['passed'] is True
    assert r['last_match_bars_ago']==2


def test_hidden_bullish_divergence_uses_confirmed_higher_price_low_lower_oscillator_low(monkeypatch):
    # Price pivot lows rise 10 -> 12 while oscillator lows fall 30 -> 20.
    high=[16,15,14,15,16,16,15,16,17]
    low =[14,12,10,12,14,14,12,14,15]
    close=[15,14,12,14,15,15,13,15,16]
    f=frame_from(high,low,close)
    osc=pd.Series([50,40,30,45,55,40,20,45,55],index=f.index,dtype=float)
    import app.indicators as ind
    monkeypatch.setattr(ind,'_divergence_oscillator',lambda frame,p: osc)
    out=_divergence(f,{'oscillator':'RSI','period':14,'fast':12,'slow':26,'signal':9,'smooth_k':3,'smooth_d':3,'pivot_left':1,'pivot_right':1,'max_pivot_gap':20})
    assert out['hidden_bullish'].iloc[:7].sum()==0
    assert out['hidden_bullish'].iloc[7]==1
    assert out['bullish'].sum()==0


def test_hidden_bearish_divergence_uses_confirmed_lower_price_high_higher_oscillator_high(monkeypatch):
    high=[10,12,15,12,10,11,13,11,10]
    low =[8,9,11,9,8,9,10,9,8]
    close=[9,11,13,10,9,10,12,10,9]
    f=frame_from(high,low,close)
    osc=pd.Series([45,60,70,55,40,60,80,55,45],index=f.index,dtype=float)
    import app.indicators as ind
    monkeypatch.setattr(ind,'_divergence_oscillator',lambda frame,p: osc)
    out=_divergence(f,{'oscillator':'RSI','period':14,'fast':12,'slow':26,'signal':9,'smooth_k':3,'smooth_d':3,'pivot_left':1,'pivot_right':1,'max_pivot_gap':20})
    assert out['hidden_bearish'].iloc[:7].sum()==0
    assert out['hidden_bearish'].iloc[7]==1
    assert out['bearish'].sum()==0
