import pandas as pd
from app.indicators import compute_indicators
from app.models import IndicatorInstance

def bars(n=80):
    idx=pd.date_range('2026-01-01',periods=n,freq='5min',tz='UTC');close=pd.Series(range(100,100+n),index=idx,dtype=float)
    return pd.DataFrame({'open':close-1,'high':close+1,'low':close-2,'close':close,'volume':100.0},index=idx)

def test_ema():
    f,m=compute_indicators(bars(),[IndicatorInstance(id='ema9',kind='EMA',params={'period':9,'source':'close'})]);assert 'ema9' in f and f.ema9.notna().sum()>0

def test_rsi():
    f,m=compute_indicators(bars(),[IndicatorInstance(id='rsi',kind='RSI',params={'period':14})]);assert f.rsi.dropna().iloc[-1]>90

def test_macd_outputs():
    f,m=compute_indicators(bars(),[IndicatorInstance(id='macd',kind='MACD')]);assert {'macd.macd','macd.signal','macd.histogram'}<=set(f.columns)

def test_vwap():
    f,m=compute_indicators(bars(),[IndicatorInstance(id='vwap',kind='VWAP')]);assert f.vwap.notna().all()
