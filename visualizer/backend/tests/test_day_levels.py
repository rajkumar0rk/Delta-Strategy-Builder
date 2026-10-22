from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.alerts import alert_markers
from app.day_levels import LEVELS
from app.engine import chart_payload, run_backtest
from app.indicators import _aggregate_completed, compute_indicators
from app.models import (AlertRule, BacktestRequest, Condition, IndicatorInstance,
                        PreviewRequest, RuleGroup, StrategyConfig)
from app.warmup import required_warmup_candles


def history(zone='UTC', start='2026-01-01', end='2026-01-08'):
    index = pd.date_range(pd.Timestamp(start, tz=zone) + pd.Timedelta(minutes=5),
                          pd.Timestamp(end, tz=zone), freq='5min').tz_convert('UTC')
    frame = pd.DataFrame({'open':100., 'high':110., 'low':90., 'close':100., 'volume':100.}, index=index)
    for day, high, low in [(2,170,30),(3,141,64),(4,155,50),(5,125,75)]:
        ts = pd.Timestamp(f'2026-01-{day:02} 12:00', tz=zone).tz_convert('UTC')
        if ts in frame.index:
            frame.loc[ts, ['high','low']] = [high,low]
    ts = pd.Timestamp('2026-01-05 23:55', tz=zone).tz_convert('UTC')
    if ts in frame.index:
        frame.loc[ts, ['high','low']] = [140,65]  # confirmation occurs AFTER new day starts
    for time, high, low in [('00:05',124,123),('00:10',125,124),('00:15',160,150)]:
        ts = pd.Timestamp('2026-01-06 '+time, tz=zone).tz_convert('UTC')
        if ts in frame.index:
            frame.loc[ts, ['open','high','low','close']] = [(high+low)/2,high,low,(high+low)/2]
    return frame


def indicator(zone='UTC', **params):
    return IndicatorInstance(id='daily',kind='DAY_LEVELS',params={
        'timezone':zone,'pivot_left':3,'pivot_right':3,'lookback_days':3,'warning_points':2,**params})


def at(zone='UTC', time='00:05'):
    return pd.Timestamp('2026-01-06 '+time,tz=zone).tz_convert('UTC')


@pytest.mark.parametrize('zone', ['UTC','Asia/Kolkata'])
def test_daily_range_confirmed_extremes_and_first_older_pivots(zone):
    f=history(zone)
    out,_=compute_indicators(f,[indicator(zone)])
    row=out.loc[at(zone)]
    assert row['daily.previous_day_high']==140
    assert row['daily.previous_day_low']==65
    assert row['daily.previous_day_swing_high']==125
    assert row['daily.previous_day_swing_low']==75
    # First backward chronologically, not nearest price (141/64) or extreme (170/30).
    assert row['daily.older_swing_high']==155
    assert row['daily.older_swing_low']==50
    assert row['daily.previous_day_ready']==row['daily.older_history_ready']==1
    for level in ('previous_day_high','previous_day_low',*LEVELS):
        values=out.loc[at(zone):pd.Timestamp('2026-01-07',tz=zone).tz_convert('UTC'),f'daily.{level}']
        assert values.nunique()==1  # late pivot confirmation never rewrites today's snapshot


def test_near_touch_wick_equality_and_touch_precedence():
    out,_=compute_indicators(history(),[indicator()])
    prefix='daily.previous_day_swing_high'
    assert out.loc[at(),prefix+'_near']==1
    assert out.loc[at(),prefix+'_distance']==1
    assert out.loc[at(),prefix+'_touch']==0
    assert out.loc[at(time='00:10'),prefix+'_touch']==1
    assert out.loc[at(time='00:10'),prefix+'_near']==0
    assert out.loc[at(time='00:15'),'daily.older_swing_high_touch']==1
    # Both-sided candle interval logic: near from above, no close-only miss.
    f=history();f.loc[at(),['open','high','low','close']]=[127,128,126,127]
    out,_=compute_indicators(f,[indicator()])
    assert out.loc[at(),prefix+'_near']==1


def test_midnight_close_belongs_to_ending_day_and_late_confirmation_is_excluded():
    f=history();midnight=pd.Timestamp('2026-01-06T00:00:00Z')
    f.loc[midnight,['high','low']]=[180,20]
    out,_=compute_indicators(f,[indicator()])
    assert out.loc[at(),'daily.previous_day_high']==180
    assert out.loc[at(),'daily.previous_day_low']==20
    assert out.loc[midnight,'daily.day_id'] < out.loc[at(),'daily.day_id']
    assert out.loc[at(),'daily.previous_day_swing_high']==125
    # No qualifying older levels; do not fall back to any latest pivot.
    assert np.isnan(out.loc[at(),'daily.older_swing_high'])
    assert np.isnan(out.loc[at(),'daily.older_swing_low'])


def test_missing_previous_day_and_missing_older_history_are_distinct():
    f=history().drop(pd.Timestamp('2026-01-05T08:00:00Z'))
    out,_=compute_indicators(f,[indicator()])
    assert out.loc[at(),'daily.previous_day_ready']==0
    assert all(np.isnan(out.loc[at(),f'daily.{level}_touch']) for level in LEVELS)
    f=history().drop(pd.Timestamp('2026-01-02T08:00:00Z'))
    out,_=compute_indicators(f,[indicator()])
    assert out.loc[at(),'daily.previous_day_ready']==1
    assert out.loc[at(),'daily.previous_day_swing_high']==125
    assert out.loc[at(),'daily.older_history_ready']==0
    assert np.isnan(out.loc[at(),'daily.older_swing_high'])


def test_short_history_missing_pivots_and_strict_boundaries():
    f=history();f.loc[pd.Timestamp('2026-01-04T12:00:00Z'),['high','low']]=[140,65]
    out,_=compute_indicators(f,[indicator(lookback_days=1)])
    # Equal to yesterday's boundary does not qualify, and older days are outside lookback.
    assert np.isnan(out.loc[at(),'daily.older_swing_high'])
    assert np.isnan(out.loc[at(),'daily.older_swing_low'])
    out,_=compute_indicators(history().loc['2026-01-05T00:05Z':],[indicator()])
    assert out.loc[at(),'daily.previous_day_swing_high']==125
    assert out.loc[at(),'daily.older_history_ready']==0


def test_future_changes_and_prefixes_do_not_repaint():
    f=history();cut=at(time='00:05');ind=indicator()
    original,_=compute_indicators(f,[ind])
    prefix,_=compute_indicators(f.loc[:cut],[ind])
    cols=[c for c in original if c.startswith('daily.')]
    pd.testing.assert_frame_equal(original.loc[:cut,cols],prefix[cols])
    changed=f.copy();changed.loc[changed.index>cut,'high']+=10000
    changed.loc[changed.index>cut,'low']-=10000
    future,_=compute_indicators(changed,[ind])
    pd.testing.assert_frame_equal(original.loc[:cut,cols],future.loc[:cut,cols])


def test_pivot_confirming_exactly_at_midnight_is_usable():
    f=history();f.loc[pd.Timestamp('2026-01-05T23:55Z'),['high','low']]=[110,90]
    f.loc[pd.Timestamp('2026-01-05T23:45Z'),['high','low']]=[135,70]
    out,_=compute_indicators(f,[indicator()])
    assert out.loc[at(),'daily.previous_day_swing_high']==135
    assert out.loc[at(),'daily.previous_day_swing_low']==70


def test_microseconds_and_different_history_starts_match():
    f=history();ind=indicator()
    full,_=compute_indicators(f,[ind])
    f.index=f.index.as_unit('us')
    other,_=compute_indicators(f.loc['2026-01-01T08:05Z':],[ind])
    cols=[c for c in full if c.startswith('daily.')]
    np.testing.assert_allclose(full.loc[at():,cols],other.loc[at():,cols],equal_nan=True)


@pytest.mark.parametrize('start,end,zone', [('2026-03-06','2026-03-10','America/New_York'),
                                          ('2026-10-30','2026-11-03','America/New_York')])
def test_dst_calendar_days_are_complete(start,end,zone):
    f=history(zone,start,end)
    out,_=compute_indicators(f,[indicator(zone,lookback_days=1)])
    assert out['daily.previous_day_ready'].iloc[-1]==1
    assert out['daily.older_history_ready'].iloc[-1]==1


@pytest.mark.parametrize('tf', ['10m','15m','30m','1h'])
def test_daily_ranges_use_raw_5m_source_for_higher_strategy_timeframes(tf):
    source=history('Asia/Kolkata');bars=_aggregate_completed(source,'5m',tf)
    out,_=compute_indicators(bars,[indicator('Asia/Kolkata')],tf,daily_source=source)
    # The 20:00Z close opened at 00:30 IST, so uses today's snapshot.
    ts=pd.Timestamp('2026-01-05T20:00:00Z')
    assert out.loc[ts,'daily.previous_day_high']==140
    assert out.loc[ts,'daily.previous_day_low']==65
    assert out.loc[ts,'daily.previous_day_ready']==1
    if tf=='1h':
        crossing=pd.Timestamp('2026-01-05T19:00Z')  # opens 23:30 IST, straddles midnight
        assert out.loc[crossing,'daily.day_id'] < out.loc[ts,'daily.day_id']


def test_higher_native_pivots_still_roll_snapshots_on_strategy_day():
    f=history('Asia/Kolkata');i=indicator('Asia/Kolkata');i.timeframe='1h'
    out,_=compute_indicators(f,[i])
    assert out.loc[at('Asia/Kolkata'),'daily.previous_day_high']==140
    assert out.loc[at('Asia/Kolkata'),'daily.day_id'] > out.loc[at('Asia/Kolkata')-pd.Timedelta(minutes=5),'daily.day_id']


def test_warmup_covers_days_native_confirmation_and_validates_params():
    need=required_warmup_candles([indicator(lookback_days=30)],'5m')
    assert need>=32*288
    for invalid in ({'timezone':'not/a-zone'},{'lookback_days':0},{'pivot_right':0},
                    {'warning_points':-1},{'warning_points':float('nan')},{'lookback_days':1.5}):
        with pytest.raises(ValueError): indicator(**invalid)


def test_cancellation_checkpoints_in_daily_calculation():
    def cancel(message): raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError,match='cancelled'):
        compute_indicators(history(),[indicator()],progress=cancel)


def test_reset_identity_rearms_true_alert_and_cooldown_without_warmup_emission():
    f=pd.DataFrame({'close':[100.,100.,100.,100.,100.], 'daily.day_id':[1.,1.,2.,2.,np.nan]},
                   index=pd.date_range('2026-01-01',periods=5,freq='5min',tz='UTC'))
    s=StrategyConfig(indicators=[indicator()],no_trade=RuleGroup(conditions=[
        Condition(id='yes',left='close',operator='GT',value=0)]),alerts=[
        AlertRule(id='a',name='Touch',source='NO_TRADE',condition_id='yes',
                  reset_operand='daily.day_id',cooldown_bars=100)])
    events=alert_markers(f,s,f.index[1].isoformat(),(f.index[-1]+pd.Timedelta(minutes=5)).isoformat())
    assert [e['time'] for e in events]==[int(f.index[2].timestamp())]
    s.alerts[0].reset_operand=None
    assert alert_markers(f,s,f.index[1].isoformat(),(f.index[-1]+pd.Timedelta(minutes=5)).isoformat())==[]


def preset():
    path=Path(__file__).resolve().parents[2]/'examples/previous-day-swing-alerts.strategy.json'
    return StrategyConfig.model_validate(json.loads(path.read_text())['strategy'])


@pytest.mark.parametrize('tf', ['5m','1h'])
def test_alert_only_backtest_preview_cache_and_saved_markers_without_options(tmp_path,monkeypatch,tf):
    from app.storage import load_result
    root=tmp_path/'data';part=root/'sample';part.mkdir(parents=True)
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT',str(root))
    monkeypatch.setenv('STRATEGY_LAB_RESULT_ROOT',str(tmp_path/'results'))
    monkeypatch.setenv('STRATEGY_LAB_CACHE_ROOT',str(tmp_path/'cache'))
    source=history('Asia/Kolkata',start='2025-12-10' if tf=='1h' else '2025-12-30')
    source.reset_index(names='timestamp').to_csv(part/'underlying_bars.csv',index=False)
    s=preset();s.timeframe=tf;s.indicators[0].params.update(lookback_days=3,warning_points=2)
    start=at('Asia/Kolkata').ceil('1h')+pd.Timedelta(hours=1) if tf=='1h' else at('Asia/Kolkata')
    end=start+pd.Timedelta(hours=4)
    req=BacktestRequest(dataset_id='sample',start=start.isoformat(),end=end.isoformat(),strategy=s,
                        storage_mode='ANALYSIS',warmup_policy='REQUIRE')
    result=run_backtest(req)
    assert result['metrics']['trades']==0
    assert result['metrics']['net_pnl_usd']==0
    chart=chart_payload(PreviewRequest(dataset_id='sample',start=req.start,end=req.end,strategy=s))
    assert chart['markers']==result['markers']
    if tf=='5m':
        assert len(result['markers'])>=3
        assert any('Warning' in m['text'] for m in result['markers'])
        assert any('Touch confirmation' in m['text'] for m in result['markers'])
    assert run_backtest(req)['cache_hit']
    saved=load_result(Path(result['result_dir']))
    assert saved['markers']==result['markers']
    assert chart['warmup']['contiguous']
    # Preview and full-history snapshot values match, and NaNs serialize as chart gaps.
    series=next(row for row in chart['series'] if row['key']=='daily.previous_day_high')
    assert all(point.get('value')==140 for point in series['values'])


def test_ablation_removes_dependent_alert_identities_and_conditions(monkeypatch):
    from app.models import AblationRequest
    from app.research import run_ablation
    calls=[]
    def fake(req):
        calls.append(req.strategy)
        return {'run_id':'test','metrics':{'net_pnl_usd':0},'trades':[]}
    monkeypatch.setattr('app.research.run_backtest',fake)
    run_ablation(AblationRequest(dataset_id='sample',start='2026-01-06',end='2026-01-07',strategy=preset()))
    assert len(calls)==2
    assert calls[1].alerts==[]
    assert calls[1].indicators==[]


def test_older_high_and_low_can_come_from_different_days():
    f=history()
    f.loc[pd.Timestamp('2026-01-04T12:00Z'),'low']=90
    out,_=compute_indicators(f,[indicator()])
    assert out.loc[at(),'daily.older_swing_high']==155  # Jan 4
    assert out.loc[at(),'daily.older_swing_low']==64   # Jan 3


def test_archive_loads_earlier_segments_and_preserves_missing_chart_gaps(tmp_path,monkeypatch):
    root=tmp_path/'archive';root.mkdir()
    monkeypatch.setenv('STRATEGY_LAB_DATA_ROOT',str(root))
    source=history(start='2025-12-30')
    boundary=pd.Timestamp('2026-01-05T00:00Z')
    segments=[]
    for name,start,end,part in (
        ('older','2025-12-30T00:00:00Z','2026-01-05T00:00:00Z',source.loc[source.index<boundary]),
        ('current','2026-01-05T00:00:00Z','2026-01-08T00:05:00Z',source.loc[source.index>=boundary]),
    ):
        folder=root/'segments'/name;folder.mkdir(parents=True)
        part.reset_index(names='timestamp').to_csv(folder/'underlying_bars.csv',index=False)
        segments.append({'name':name,'directory':f'segments/{name}','start':start,'end_exclusive':end})
    (root/'catalog.json').write_text(json.dumps({'format_version':1,'segments':segments}))
    s=preset();s.indicators=[indicator()]
    kwargs=dict(start=at().isoformat(),end=(at()+pd.Timedelta(hours=1)).isoformat(),strategy=s)
    full=chart_payload(PreviewRequest(dataset_mode='ARCHIVE',**kwargs))
    assert full['warmup']['contiguous']
    old=next(row for row in full['series'] if row['key']=='daily.older_swing_high')
    assert old['values'][0]['value']==155
    # Explicit dataset scope must not silently import the older archive part.
    limited=chart_payload(PreviewRequest(dataset_id='segments/current',**kwargs))
    missing=next(row for row in limited['series'] if row['key']=='daily.older_swing_high')
    assert all('value' not in v for v in missing['values'])
    assert not any('older swing' in m['text'] for m in limited['markers'])


def test_preset_validation_and_catalog_are_available_through_api():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        response=client.post('/api/strategies/validate',json={'strategy':preset().model_dump()})
        assert response.status_code==200
        assert response.json()['strategy']['alerts'][0]['reset_operand']=='daily.day_id'
        catalog=client.get('/api/indicators').json()
        assert any(row['kind']=='DAY_LEVELS' for row in catalog)
