from app.analysis import _stats, _observations

def test_stats_winner_loss_metrics():
    rows=[{'return_percent':10,'mfe_percent':20,'mae_percent':-4,'holding_minutes':30,'net_pnl_usd':2},{'return_percent':5,'mfe_percent':12,'mae_percent':-2,'holding_minutes':60,'net_pnl_usd':1}]
    x=_stats(rows)
    assert x['count']==2
    assert x['avg_return_percent']==7.5
    assert x['net_pnl_usd']==3

def test_observations_compare_winners_losers():
    a={'winners':{'count':1,'avg_mfe_percent':20,'avg_mae_percent':-3,'avg_holding_minutes':30},'losers':{'count':1,'avg_mfe_percent':5,'avg_mae_percent':-15,'avg_holding_minutes':90},'top_failed_entry_conditions':[],'rejection_reasons':{}}
    out=_observations(a)
    assert any('Average MFE' in x for x in out)
    assert any('Average hold' in x for x in out)
