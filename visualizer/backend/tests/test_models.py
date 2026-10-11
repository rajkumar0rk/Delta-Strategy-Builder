import pytest
from pydantic import ValidationError
from app.models import Condition, StrategyConfig

def test_condition_requires_rhs():
    with pytest.raises(ValidationError):Condition(left='close',operator='GT')

def test_default_strategy():
    s=StrategyConfig();assert s.risk.stop_loss.mode=='OPTION_PERCENT'


def test_chart_only_indicator_cannot_be_used_by_rule():
    import pytest
    from pydantic import ValidationError
    from app.models import StrategyConfig, IndicatorInstance, RuleGroup, Condition
    with pytest.raises(ValidationError):
        StrategyConfig(
            indicators=[IndicatorInstance(id='rsi14', kind='RSI', params={'period':14}, chart_only=True)],
            call_entry=RuleGroup(conditions=[Condition(id='x', left='rsi14', operator='GTE', value=55)]),
        )


def test_chart_only_indicator_is_valid_when_not_in_rules():
    from app.models import StrategyConfig, IndicatorInstance
    s=StrategyConfig(indicators=[IndicatorInstance(id='rsi14', kind='RSI', params={'period':14}, chart_only=True)])
    assert s.indicators[0].chart_only is True


def test_v2_shared_exit_migrates_to_both_directions():
    from app.models import StrategyConfig
    s = StrategyConfig.model_validate({
        'exit': {
            'mode': 'ANY',
            'min_pass': 1,
            'conditions': [{'id': 'x', 'left': 'close', 'operator': 'LT', 'value': 10}],
            'groups': [],
        }
    })
    assert len(s.call_exit.conditions) == 1
    assert len(s.put_exit.conditions) == 1
    assert s.call_exit.conditions[0].left == 'close'


def test_chart_only_indicator_cannot_be_used_by_no_trade():
    from pydantic import ValidationError
    from app.models import StrategyConfig, IndicatorInstance, RuleGroup, Condition
    with pytest.raises(ValidationError):
        StrategyConfig(
            indicators=[IndicatorInstance(id='rsi14', kind='RSI', params={'period':14}, chart_only=True)],
            no_trade=RuleGroup(conditions=[Condition(id='x', left='rsi14', operator='BETWEEN', value=45, value2=55)]),
        )

def test_entry_trigger_condition_must_exist():
    from app.models import StrategyConfig, RuleGroup, Condition, EntryBehavior
    with pytest.raises(ValidationError):
        StrategyConfig(
            call_entry=RuleGroup(conditions=[Condition(id='real',left='close',operator='GT',value=1)]),
            call_entry_behavior=EntryBehavior(trigger_condition_id='missing'),
        )


def test_v3_strategy_gets_v4_entry_behavior_defaults():
    from app.models import StrategyConfig
    s=StrategyConfig.model_validate({'name':'old'})
    assert s.call_entry_behavior.max_entries_per_activation == 1
    assert s.put_entry_behavior.delay_bars == 0
    assert s.position_policy == 'EXCLUSIVE'
