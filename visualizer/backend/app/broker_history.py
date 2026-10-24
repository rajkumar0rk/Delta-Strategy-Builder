"""Historical observed Delta account risk and liquidation replay.

Does not simulate hypothetical Delta margin requirements, counterfactual orders,
or liquidation executions. Every event is derived from supplied broker records.
"""
from __future__ import annotations

from collections import defaultdict
import math
import pandas as pd
from .settlement import _csv_locations

SNAPSHOT_FIELDS = {'timestamp','account_id','currency','wallet_balance','im_w_ucf',
                   'mm_w_ucf','blocked_margin','risk_margin','margin_floor','ucf',
                   'commission','under_liquidation','source'}
FILL_FIELDS = {'fill_id','timestamp','account_id','currency','product_symbol',
               'fill_type','side','size','price','commission','source'}


def _num(value, field, nonnegative=False):
    try:
        x=float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'Invalid {field}: {value!r}') from exc
    if not math.isfinite(x) or (nonnegative and x<0):
        raise ValueError(f'Invalid {field}: {value!r}')
    return x


def _utc(raw):
    ts=pd.Timestamp(raw)
    if ts.tzinfo is None:
        raise ValueError('Broker timestamps must have an explicit timezone')
    return ts.tz_convert('UTC')


def _read(parts, filename, required):
    rows=[]; count=0
    for path in _csv_locations(parts,filename):
        frame=pd.read_csv(path,dtype=str,keep_default_na=False)
        if not required.issubset(frame.columns):
            raise ValueError(f'{path}: missing {sorted(required-set(frame.columns))}')
        rows.extend(frame.to_dict('records'))
        count+=1
    return rows,count


def read_observed_account(parts):
    snapshots,sc=_read(parts,'portfolio_margin_history.csv',SNAPSHOT_FIELDS)
    raw_fills,fc=_read(parts,'account_fills_history.csv',FILL_FIELDS)
    snaps={};fills={}
    for x in snapshots:
        if x['source']!='DELTA_PORTFOLIO_MARGINS_CAPTURE':
            raise ValueError('Invalid margin snapshot provenance')
        flag=str(x['under_liquidation']).strip().lower()
        if flag not in ('true','false','0','1','yes','no'):
            raise ValueError('Invalid broker under_liquidation flag')
        r={'timestamp':_utc(x['timestamp']),
           'account_id':str(x['account_id']).strip(),'currency':str(x['currency']).strip(),
           'under_liquidation':flag in ('true','1','yes')}
        for field in ('wallet_balance','im_w_ucf','mm_w_ucf','blocked_margin',
                      'risk_margin','margin_floor','ucf','commission'):
            r[field]=_num(x[field],field,field in ('blocked_margin','risk_margin','margin_floor','commission'))
        if not r['account_id'] or not r['currency']:
            raise ValueError('Missing account_id or currency')
        key=(r['account_id'],r['currency'],r['timestamp'])
        if key in snaps and snaps[key]!=r:
            raise ValueError(f'Conflicting account margin observations: {key}')
        snaps[key]=r
    for x in raw_fills:
        if x['source']!='DELTA_FILLS_HISTORY':
            raise ValueError('Invalid broker fill provenance')
        kind=str(x['fill_type']).strip().lower()
        side=str(x['side']).strip().lower()
        if kind not in ('normal','liquidation','settlement','adl','otc') or side not in ('buy','sell'):
            raise ValueError('Unsupported fill type or side')
        r={'timestamp':_utc(x['timestamp']),
           'account_id':str(x['account_id']).strip(),'currency':str(x['currency']).strip(),
           'fill_id':str(x['fill_id']).strip(),'symbol':str(x['product_symbol']).strip(),
           'fill_type':kind,'side':side,'size':_num(x['size'],'size',True),
           'price':_num(x['price'],'price',True),
           'commission':_num(x['commission'],'commission'),
           'realized_pnl':_num(x['realized_pnl'],'realized_pnl') if str(x.get('realized_pnl','')).strip() else None}
        if not all(r[k] for k in ('account_id','currency','fill_id','symbol')) or r['size']==0:
            raise ValueError('Missing fill identifier, account, currency, symbol or size')
        key=(r['account_id'],r['fill_id'])
        if key in fills and fills[key]!=r:
            raise ValueError(f'Conflicting broker fills: {key}')
        fills[key]=r
    return {'snapshots':sorted(snaps.values(),key=lambda r:r['timestamp']),
            'fills':sorted(fills.values(),key=lambda r:r['timestamp']),
            'snapshot_files':sc,'fill_files':fc}


def replay_broker_account(parts, start, end, simulated_trades):
    """Output only historical observations; no execution/P&L changes."""
    data=read_observed_account(parts)
    start,end=_utc(start),_utc(end)
    if end<start:
        raise ValueError('Backtest end before start')
    snaps=[r for r in data['snapshots'] if start<=r['timestamp']<=end]
    fills=[r for r in data['fills'] if start<=r['timestamp']<=end]
    groups=defaultdict(list)
    for r in snaps:
        groups[(r['account_id'],r['currency'])].append(r)
    accounts=[]; discrepancies=0;timeline=[]
    for (account,currency),rows in sorted(groups.items()):
        rows.sort(key=lambda r:r['timestamp'])
        onsets=0;previous=None
        for i,r in enumerate(rows):
            ref=max(r['risk_margin'],r['margin_floor'])
            im_ok=math.isclose(ref-r['ucf'],r['im_w_ucf'],rel_tol=1e-6,abs_tol=.02)
            mm_ok=math.isclose(.8*ref-r['ucf'],r['mm_w_ucf'],rel_tol=1e-6,abs_tol=.02)
            discrepancies+=int(not(im_ok and mm_ok))
            breached=r['blocked_margin']<r['mm_w_ucf']
            if previous is not None and breached and not previous:
                onsets+=1
            previous=breached
            if len(timeline)<60 and (breached or r['under_liquidation'] or not(im_ok and mm_ok)):
                timeline.append({'timestamp':r['timestamp'].isoformat(),
                                 'account_id':account,'currency':currency,
                                 'blocked_margin':r['blocked_margin'],
                                 'maintenance_margin':r['mm_w_ucf'],
                                 'observed_breach':breached,
                                 'exchange_under_liquidation':r['under_liquidation'],
                                 'im_formula_agrees':im_ok,'mm_formula_agrees':mm_ok})
        gaps=[(b['timestamp']-a['timestamp']).total_seconds() for a,b in zip(rows,rows[1:])]
        accounts.append({'account_id':account,'currency':currency,'snapshots':len(rows),
                         'first':rows[0]['timestamp'].isoformat(),
                         'last':rows[-1]['timestamp'].isoformat(),
                         'max_gap_seconds':max(gaps) if gaps else None,
                         'observed_breaches':sum(r['blocked_margin']<r['mm_w_ucf'] for r in rows),
                         'broker_liquidation_flags':sum(r['under_liquidation'] for r in rows),
                         'breach_onsets_after_first_snapshot':onsets})
    liquidations=[r for r in fills if r['fill_type']=='liquidation']
    adls=[r for r in fills if r['fill_type']=='adl']
    actual_settlements=[r for r in fills if r['fill_type']=='settlement']
    comparisons=[]
    for t in simulated_trades:
        if t.get('exit_reason')!='EXPIRY_SETTLEMENT':
            continue
        ts=_utc(t['exit_time'])
        same=[f for f in actual_settlements if f['symbol']==str(t['symbol']) and f['timestamp']==ts]
        if not same:
            comparisons.append({'trade_id':t.get('id'),'symbol':t['symbol'],
                                'status':'NO_MATCH','net_pnl_comparable':False})
            continue
        by_account=defaultdict(list)
        for f in same:
            by_account[(f['account_id'],f['currency'])].append(f)
        for (account,currency),items in by_account.items():
            prices={f['price'] for f in items}
            price=next(iter(prices)) if len(prices)==1 else None
            comparisons.append({'trade_id':t.get('id'),'symbol':t['symbol'],
                                'account_id':account,'currency':currency,
                                'status':'SAME_CONTRACT_TIME',
                                'recorded_settlement_price':price,
                                'simulated_settlement_price':float(t['exit_price']),
                                'price_matches':price is not None and math.isclose(price,float(t['exit_price']),abs_tol=.0001),
                                'actual_commission':sum(f['commission'] for f in items),
                                'actual_size':sum(f['size'] for f in items),
                                'net_pnl_comparable':False})
    return {'status':'OBSERVED' if snaps or fills else 'NO_RECORDS',
            'snapshot_files':data['snapshot_files'],'fill_files':data['fill_files'],
            'snapshots':len(snaps),'total_fills':len(fills),
            'liquidation_fills':len(liquidations),'adl_fills':len(adls),
            'settlement_fills':len(actual_settlements),
            'observed_breach_snapshots':sum(r['blocked_margin']<r['mm_w_ucf'] for r in snaps),
            'broker_liquidation_flags':sum(r['under_liquidation'] for r in snaps),
            'formula_discrepancies':discrepancies,
            'accounts':accounts[:60],'risk_events':timeline,
            'forced_fills':[{**r,'timestamp':r['timestamp'].isoformat()} for r in (liquidations+adls)[:60]],
            'settlement_checks':comparisons[:60],
            'truncated':len(accounts)>60 or len(liquidations)+len(adls)>60 or len(comparisons)>60,
            'execution_impact':'NONE',
            'accuracy_scope':'RECORDED_ACCOUNT_ONLY',
            'hypothetical_liquidation_accuracy':'NOT_VERIFIED',
            'limitations':'Historical account states, not hypothetical portfolio simulations. Missing snapshots remain unknown. Delta portfolio stress, hedging, position reductions and exchange fill prices cannot be reconstructed from BTC OHLCV.'}
