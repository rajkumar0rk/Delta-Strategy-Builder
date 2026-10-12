import pandas as pd
import pytest
from pydantic import ValidationError

from app.alerts import alert_markers
from app.models import AlertRule, Condition, RuleGroup, StrategyConfig


def group(value=100):
    return RuleGroup(conditions=[Condition(id='condition_x', left='close', operator='GT', value=value)])


def frame():
    idx = pd.date_range("2026-01-01T00:05:00Z", periods=8, freq="5min")
    return pd.DataFrame({"close": [90, 105, 108, 96, 110, 111, 99, 120]}, index=idx)


def strategy(*alerts, **actions):
    return StrategyConfig(alerts=list(alerts), **actions)


def test_two_alerts_same_timestamp_keep_different_messages():
    s = strategy(
        AlertRule(id='above100', name='Breakout', message='BTC broke 100', conditions=group(100)),
        AlertRule(id='above102', name='Confirmation', message='Bullish confirmed', conditions=group(102)),
    )
    f = frame()
    events = alert_markers(f, s, f.index[0].isoformat(), (f.index[-1] + pd.Timedelta(minutes=5)).isoformat())
    same = [m for m in events if m['time'] == int(f.index[1].timestamp())]
    assert len(same) == 2
    assert {m['details']['message'] for m in same} == {'BTC broke 100', 'Bullish confirmed'}
    assert len({m['id'] for m in same}) == 2
    assert all(m['kind'] == 'alert' for m in same)


def test_on_enter_fires_once_per_true_run():
    f = frame()
    s = strategy(AlertRule(id='rise', name='Rise', message='Rise', conditions=group()))
    events = alert_markers(f, s, f.index[0].isoformat(), (f.index[-1]+pd.Timedelta(minutes=5)).isoformat())
    assert [m['time'] for m in events] == [int(f.index[i].timestamp()) for i in (1, 4, 7)]


def test_every_bar_cooldown_is_independent():
    f = frame()
    s = strategy(
        AlertRule(id='repeat', name='Every Bar', trigger_mode='EVERY_BAR',
                  cooldown_bars=1, conditions=group(100)),
        AlertRule(id='once', name='Enter', trigger_mode='ON_ENTER', conditions=group(100)),
    )
    events = alert_markers(f, s, f.index[0].isoformat(), (f.index[-1]+pd.Timedelta(minutes=5)).isoformat())
    repeat = [m for m in events if m['details']['alert_id'] == 'repeat']
    once = [m for m in events if m['details']['alert_id'] == 'once']
    assert len(repeat) == 3
    assert len(once) == 3


def test_warmup_does_not_retrigger_on_start_boundary():
    f = frame()
    s = strategy(AlertRule(id='rise', name='Rise', conditions=group()))
    events = alert_markers(f, s, f.index[2].isoformat(), (f.index[-1]+pd.Timedelta(minutes=5)).isoformat())
    assert all(m['time'] != int(f.index[2].timestamp()) for m in events)
    assert [m['time'] for m in events] == [int(f.index[i].timestamp()) for i in (4,7)]


def test_direction_action_alert_uses_its_own_message():
    f = frame()
    s = strategy(call_action='ALERT', direction_mode='CALL',
                 call_alert_message='CALL signal - no trade', call_entry=group())
    events = alert_markers(f, s, f.index[0].isoformat(), (f.index[-1]+pd.Timedelta(minutes=5)).isoformat())
    assert len(events) == 3
    assert all(m['direction'] == 'CALL' and m['details']['message'] == 'CALL signal - no trade' for m in events)


def test_disabled_and_unconfigured_alerts_do_not_fire():
    f = frame()
    s = strategy(AlertRule(id='disabled', name='Disabled', enabled=False, conditions=group()),
                 AlertRule(id='empty', name='Empty'))
    assert alert_markers(f, s, f.index[0].isoformat(), (f.index[-1]+pd.Timedelta(minutes=5)).isoformat()) == []


def test_old_strategy_import_gets_empty_alerts():
    s = StrategyConfig.model_validate({'name':'old strategy'})
    assert s.alerts == []


def test_duplicate_alert_ids_and_overlong_message_fail_validation():
    with pytest.raises(ValidationError):
        strategy(AlertRule(id='dupe',name='One'),AlertRule(id='dupe',name='Two'))
    with pytest.raises(ValidationError):
        AlertRule(id='a',name='A',message='x'*501)


def test_chart_only_indicator_references_disallowed():
    from app.models import IndicatorInstance
    with pytest.raises(ValidationError, match='Chart-only indicator'):
        StrategyConfig(
            indicators=[IndicatorInstance(id='hidden',kind='EMA',chart_only=True)],
            alerts=[AlertRule(id='a',name='A',conditions=RuleGroup(
                conditions=[Condition(left='hidden',operator='GT',value=1)]
            ))],
        )
