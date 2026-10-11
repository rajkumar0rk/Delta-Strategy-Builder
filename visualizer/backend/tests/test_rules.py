import pandas as pd
from app.models import Condition, RuleGroup
from app.rules import evaluate_group

def frame():
    return pd.DataFrame({'close':[1.,2.,3.],'ema':[1.5,1.5,2.5]})

def test_gt():
    g=RuleGroup(conditions=[Condition(left='close',operator='GT',right='ema')])
    assert evaluate_group(frame(),2,g)['passed'] is True

def test_cross_above():
    g=RuleGroup(conditions=[Condition(left='close',operator='CROSSES_ABOVE',right='ema')])
    assert evaluate_group(frame(),1,g)['passed'] is True

def test_between():
    g=RuleGroup(conditions=[Condition(left='close',operator='BETWEEN',value=2.5,value2=3.5)])
    assert evaluate_group(frame(),2,g)['passed'] is True

def test_any():
    g=RuleGroup(mode='ANY',conditions=[Condition(left='close',operator='LT',value=0),Condition(left='close',operator='GT',value=2)])
    assert evaluate_group(frame(),2,g)['passed'] is True

def test_gt_by_points_reports_distance():
    f = pd.DataFrame({'fast':[100.0,105.0], 'slow':[100.0,102.0]})
    g = RuleGroup(conditions=[Condition(left='fast',operator='GT_BY_POINTS',right='slow',value=2.0)])
    out = evaluate_group(f,1,g)
    assert out['passed'] is True
    row = out['conditions'][0]
    assert row['delta_points'] == 3.0


def test_gt_by_percent():
    f = pd.DataFrame({'fast':[100.0,103.0], 'slow':[100.0,100.0]})
    g = RuleGroup(conditions=[Condition(left='fast',operator='GT_BY_PERCENT',right='slow',value=2.0)])
    assert evaluate_group(f,1,g)['passed'] is True
