from app.live_monitor import Bar, ema, rsi, parse_closed_bars, screen
import pytest

def candles(period, count, end_ms, close=100.0, volume=100.0):
    start = end_ms - count*period
    return [Bar(start+i*period, start+(i+1)*period-1, close, close+1, close-1, close, volume) for i in range(count)]

def test_indicator_flat_market():
    assert ema([100.0]*80, 20)==100.0
    assert rsi([100.0]*80)==50.0

def test_flat_market_rejected():
    end_ms=1000*3_600_000
    assert screen(candles(300_000,180,end_ms),candles(900_000,180,end_ms),candles(3_600_000,180,end_ms),end_ms+2000)['state']=='NO_SETUP'

def test_incomplete_candle_ignored():
    raw=[[i*300_000,'100','101','99','100','100',(i+1)*300_000-1] for i in range(81)]
    assert len(parse_closed_bars(raw,'5m',80*300_000+1000))==80

def test_missing_candle_rejected():
    raw=[[i*300_000,'100','101','99','100','100',(i+1)*300_000-1] for i in range(82)]
    raw.pop(40)
    with pytest.raises(ValueError,match='Missing'):
        parse_closed_bars(raw,'5m',82*300_000+1000)
