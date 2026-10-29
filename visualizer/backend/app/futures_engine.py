"""Separate research-only BTCUSD perpetual backtest using completed candles.

Signals evaluated only on completed bar i; entries/exits fill at the next bar
OPEN with user-set slippage. Stops/targets use later OHLC; stop wins when both
are touched. Candle OHLC cannot prove orderbook fills or intrabar paths.
"""
from __future__ import annotations
import csv
import json
import math
from pathlib import Path
import pandas as pd
from zoneinfo import ZoneInfo
from .data_store import DataStore, parse_time, iso
from .warmup import required_warmup_candles, historical_bar_sources, warmup_diagnostics, load_daily_source
from .indicators import compute_indicators
from .alerts import alert_markers
from .rules import evaluate_group
from .storage import write_json_gz, write_csv_gz, maybe_auto_cleanup
from .config import result_root
from .engine import (_new_result_dir, _backtest_cache_key, _cached_result, _write_cache,
                     _prepare_strategy_state, _session_allowed, _session_end_due,
                     _entry_behaviors, _cycle_states, _update_lifecycles, _big_trend_score,
                     _entry_ignore_ids, _json_safe)


def _funding_files(parts):
    seen=set()
    for part in parts:
        roots=[part.root]
        if part.root.parent.name=='segments':
            roots.append(part.root.parent.parent)
        for root in roots:
            p=root/'futures_funding.csv'
            if p.is_file() and str(p.resolve()) not in seen:
                seen.add(str(p.resolve()))
                yield p


def funding_events(parts, start, end, *, required):
    """Import settlement-time BTCUSD funding rates. Never infer missing rates."""
    events={}
    files=list(_funding_files(parts))
    if required and not files:
        raise ValueError('FUTURES_FUNDING_MISSING: import futures_funding.csv or select EXCLUDE_WITH_WARNING')
    for p in files:
        with p.open(newline='',encoding='utf-8-sig') as f:
            reader=csv.DictReader(f)
            if not {'timestamp','symbol','funding_rate'}.issubset(reader.fieldnames or []):
                raise ValueError(f'{p}: funding requires timestamp,symbol,funding_rate')
            for row in reader:
                if row['symbol']!='BTCUSD':
                    continue
                t=pd.Timestamp(row['timestamp'])
                if t.tzinfo is None:
                    raise ValueError('Funding timestamps must have UTC offset')
                t=t.tz_convert('UTC')
                rate=float(row['funding_rate'])
                if not math.isfinite(rate) or abs(rate)>1:
                    raise ValueError('Invalid futures funding rate: expected decimal fraction')
                if t in events and events[t]!=rate:
                    raise ValueError(f'Conflicting futures funding rate for {t}')
                events[t]=rate
    first=pd.Timestamp(start);last=pd.Timestamp(end)
    first=first.tz_localize('UTC') if first.tzinfo is None else first.tz_convert('UTC')
    last=last.tz_localize('UTC') if last.tzinfo is None else last.tz_convert('UTC')
    # Funding settlement clock is 00:00, 08:00, 16:00 UTC research assumption.
    # Require ALL schedule records in requested range, not merely during a position.
    expected=pd.date_range(first.ceil('8h'),last-pd.Timedelta(nanoseconds=1),freq='8h',tz='UTC')
    missing=[t for t in expected if t not in events]
    if required and missing:
        raise ValueError('FUTURES_FUNDING_GAP: missing '+', '.join(t.isoformat() for t in missing[:5]))
    return events,missing


def _slipped(price, direction, entry, bps):
    # LONG buys entry / sells exit; SHORT sells entry / buys exit.
    adverse=1 if (direction=='LONG')==entry else -1
    return price*(1+adverse*bps/10000)


def _exit_level(pos, bar, config):
    """Adverse stop first on ambiguous stop+target; gaps fill at open."""
    long=pos['direction']=='LONG'
    entry=pos['entry_price']
    sl=(entry*(1-config.stop_loss_percent/100) if long else entry*(1+config.stop_loss_percent/100)) if config.stop_loss_percent else None
    tp=(entry*(1+config.take_profit_percent/100) if long else entry*(1-config.take_profit_percent/100)) if config.take_profit_percent else None
    opened=float(bar.open);high=float(bar.high);low=float(bar.low)
    if sl is not None and ((low<=sl) if long else (high>=sl)):
        return ('STOP_LOSS',min(opened,sl) if long else max(opened,sl))
    if tp is not None and ((high>=tp) if long else (low<=tp)):
        return ('TAKE_PROFIT',min(opened,tp) if not long else max(opened,tp))
    return None


def run_futures_backtest(req, progress=None):
    strategy=req.strategy;cfg=strategy.futures
    if strategy.risk.profit_protection.mode!='NONE':
        raise ValueError('Futures mode does not yet support option premium profit protection. Set profit_protection.mode=NONE; use futures price stop/target instead.')
    if ((strategy.call_breakout_retest.enabled and strategy.call_breakout_retest.require_retest_for_entry)
       or (strategy.put_breakout_retest.enabled and strategy.put_breakout_retest.require_retest_for_entry)):
        raise ValueError('Futures retest entry override is not implemented; disable require_retest_for_entry or express it with normal indicator conditions.')
    store=DataStore()
    if parse_time(req.end)<=parse_time(req.start):
        raise ValueError('Backtest end must exceed start')
    if getattr(req,'dataset_mode','SINGLE')=='ARCHIVE' and getattr(req,'auto_download_missing_data',False):
        from .archive_sync import ensure_archive_data
        ensure_archive_data(req.start,req.end,progress)
        store.close();store=DataStore()
    parts=store.resolve_request(req,require_options=False)
    warmup_count=required_warmup_candles(strategy.indicators,strategy.timeframe,
       minimum=getattr(req,'warmup_candles',500),strategy=strategy)
    bar_parts=historical_bar_sources(store,parts,req.start,strategy.timeframe,warmup_count,
       archive_neighbors=getattr(req,'dataset_mode','SINGLE') in {'ARCHIVE','AUTO'})
    # cache fingerprint includes funding file signature, separate from option engine.
    import hashlib,json
    from .engine import _dataset_fingerprint
    fingerprint=_dataset_fingerprint(bar_parts)
    funding_sigs=[]
    for p in _funding_files(parts):
        st=p.stat();funding_sigs.append((str(p.resolve()),st.st_size,st.st_mtime_ns))
    key=hashlib.sha256(json.dumps({'futures_engine':2,'request':req.model_dump(mode='json'),
          'bars':fingerprint,'funding':funding_sigs},sort_keys=True,default=str).encode()).hexdigest()
    cached=_cached_result(key)
    if cached is not None:
        return cached
    store._bar_gap_policy=req.bar_gap_policy
    preflight=store.preflight(parts,req.start,req.end,strategy)
    if not preflight['ok']:
        raise ValueError('Preflight failed: '+'; '.join(preflight['errors']))
    if progress: progress('Loading futures candles, indicators and funding',20,'LOAD_BARS','Signals')
    bars=store.load_bars_many(bar_parts,req.start,req.end,strategy.timeframe,warmup_candles=warmup_count)
    warmup=warmup_diagnostics(bars,req.start,strategy.timeframe,warmup_count)
    if not warmup['contiguous'] and getattr(req,'warmup_policy','WARN')=='REQUIRE':
        raise ValueError('Insufficient contiguous indicator warmup')
    daily_source=load_daily_source(store,bar_parts,req.start,req.end,strategy.timeframe,warmup_count,strategy.indicators)
    frame,meta=compute_indicators(bars,strategy.indicators,strategy.timeframe,daily_source=daily_source)
    _prepare_strategy_state(frame,strategy)
    rates,missing_funding=funding_events(parts,req.start,req.end,
        required=cfg.funding_mode=='REQUIRE_CSV')
    if progress: progress('Evaluating LONG and SHORT futures signals',45,'BACKTEST','Results')
    balance=float(strategy.risk.starting_balance_usd)
    initial=balance;peak=balance;max_dd=0.0;max_dd_pct=0.0
    qty=cfg.quantity_lots*cfg.contract_btc
    markers=list(alert_markers(frame,strategy,req.start,req.end))
    trades=[];equity_curve=[{'timestamp':req.start,'equity_usd':balance,'peak_equity_usd':balance,'drawdown_usd':0.0,'drawdown_percent':0.0}]
    position=None;pending=None;fee_total=0.0;fund_total=0.0
    risk_rejects=0;ambiguous=0;unresolved=None
    daily={'day':None,'start_balance':initial,'entries':0,'consecutive_losses':0,'realized':0.0,'blocks':0}
    # Reuse existing CALL-side bullish and PUT-side bearish rule trees, gates,
    # score and lifecycle readiness. No option instruments are loaded.
    call_enabled=strategy.direction_mode in ('CALL','BOTH') and strategy.call_signal_mode!='ALERT_ONLY'
    put_enabled=strategy.direction_mode in ('PUT','BOTH') and strategy.put_signal_mode!='ALERT_ONLY'
    cycles={'LONG':_cycle_states(_entry_behaviors(strategy,'CALL')) if call_enabled else {},
            'SHORT':_cycle_states(_entry_behaviors(strategy,'PUT')) if put_enabled else {}}
    tf={'5m':5,'10m':10,'15m':15,'30m':30,'1h':60}[strategy.timeframe]
    def fee(price):
        return price*qty*cfg.taker_fee_percent/100*(1+cfg.gst_percent/100)
    def close(pos,exit_time,price,reason):
        nonlocal balance,fee_total,fund_total,peak,max_dd,max_dd_pct
        exit_px=_slipped(price,pos['direction'],False,cfg.slippage_bps)
        sign=1 if pos['direction']=='LONG' else -1
        gross=(exit_px-pos['entry_price'])*qty*sign
        exit_fee=fee(exit_px)
        cost=pos['entry_fee']+exit_fee
        net=gross-cost+pos['funding_usd']
        balance+=gross-exit_fee
        fee_total+=exit_fee
        trade={'id':len(trades)+1,'symbol':cfg.symbol,'direction':pos['direction'],
          'action':'BUY' if sign==1 else 'SELL','entry_time':pos['entry_time'],
          'exit_time':pd.Timestamp(exit_time).isoformat(),
          'entry_price':pos['entry_price'],'exit_price':exit_px,'quantity':qty,
          'gross_pnl_usd':gross,'entry_fee_usd':pos['entry_fee'],'exit_fee_usd':exit_fee,
          'base_fees_usd':cost/(1+cfg.gst_percent/100),'gst_usd':cost-cost/(1+cfg.gst_percent/100),
          'fees_usd':cost,'net_pnl_usd':net,'funding_usd':pos['funding_usd'],
          'return_percent':net/max(pos['margin'],1e-12)*100,
          'holding_minutes':(pd.Timestamp(exit_time)-pd.Timestamp(pos['entry_time'])).total_seconds()/60,
          'mfe_percent':pos['mfe']*100,'mae_percent':pos['mae']*100,
          'exit_reason':reason,'entry_execution_side':'ASK_PROXY' if sign==1 else 'BID_PROXY',
          'exit_execution_side':'BID_PROXY' if sign==1 else 'ASK_PROXY'}
        trades.append(trade)
        daily['realized']+=net
        daily['consecutive_losses']=daily['consecutive_losses']+1 if net<0 else 0
        markers.append({'id':f"future-exit-{len(trades)}",'time':int(pd.Timestamp(exit_time).timestamp()),
          'kind':'exit','direction':'CALL' if sign==1 else 'PUT','text':reason,'pnl_usd':net,
          'details':{'title':reason,'net_pnl_usd':net,'symbol':cfg.symbol}})
        peak=max(peak,balance);max_dd=max(max_dd,peak-balance)
        max_dd_pct=max(max_dd_pct,(peak-balance)/max(peak,1e-12)*100)
        equity_curve.append({'timestamp':pd.Timestamp(exit_time).isoformat(),'equity_usd':balance,
            'peak_equity_usd':peak,'drawdown_usd':peak-balance,'drawdown_percent':(peak-balance)/max(peak,1e-12)*100})
    for i,(ts,row) in enumerate(frame.iterrows()):
        if ts<pd.Timestamp(req.start) or ts>=pd.Timestamp(req.end):continue
        if progress and i%500==0:
            progress(f'Backtesting futures candle {i+1}/{len(frame)}',min(95,45+50*i/max(len(frame),1)),'BACKTEST','Evaluate signals')
        at_open=ts-pd.Timedelta(minutes=tf)
        day=at_open.tz_convert(ZoneInfo(strategy.session.timezone)).date()
        if daily['day']!=day:
            daily.update(day=day,start_balance=balance,entries=0,consecutive_losses=0,realized=0.0)
        # Exits signalled on a prior completed bar fill at this bar OPEN.
        closed=False
        if isinstance(pending,tuple) and pending[0]=='CLOSE' and position is not None:
            close(position,at_open,float(row.open),pending[1])
            position=None;pending=None;closed=True
        # Pending signal from previous completed candle fills at the current
        # bar open, not on the signal bar close.
        if pending is not None and position is None:
            direction=pending;pending=None
            px=_slipped(float(row.open),direction,True,cfg.slippage_bps)
            margin=px*qty/cfg.leverage
            start_fee=fee(px)
            if ((strategy.risk.max_trades_per_day is not None and daily['entries']>=strategy.risk.max_trades_per_day)
              or (strategy.risk.max_consecutive_losses is not None and daily['consecutive_losses']>=strategy.risk.max_consecutive_losses)
              or (strategy.risk.max_daily_loss_percent is not None and strategy.risk.stop_trading_after_daily_loss_limit
                  and daily['realized']<=-daily['start_balance']*strategy.risk.max_daily_loss_percent/100)
              or not _session_allowed(at_open,strategy.session)):
                risk_rejects+=1;daily['blocks']+=1
            elif balance<margin+start_fee:
                risk_rejects+=1
            else:
                balance-=start_fee;fee_total+=start_fee;daily['entries']+=1
                position={'direction':direction,'entry_time':at_open.isoformat(),'entry_price':px,
                    'entry_fee':start_fee,'margin':margin,'funding_usd':0.0,
                    'mfe':0.0,'mae':0.0}
                markers.append({'id':f"future-entry-{len(trades)+1}",'time':int(at_open.timestamp()),
                    'kind':'entry','direction':'CALL' if direction=='LONG' else 'PUT',
                    'text':direction,'details':{'title':direction+' future','entry_ask':px,'symbol':cfg.symbol}})
        if position:
            # Funding is evaluated at scheduled UTC candle closes. If a stop
            # happens intrabar in that candle, true funding eligibility cannot
            # be reconstructed from OHLC; the result stays research only.
            rate=rates.get(ts)
            if rate is not None and ts>pd.Timestamp(position['entry_time']):
                funding_sign=1 if position['direction']=='LONG' else -1
                funding=-funding_sign*float(row.close)*qty*rate
                position['funding_usd']+=funding
                balance+=funding
                fund_total+=funding
            sign=1 if position['direction']=='LONG' else -1
            favorable=(float(row.high)-position['entry_price'])/position['entry_price'] if sign==1 else (position['entry_price']-float(row.low))/position['entry_price']
            adverse=(float(row.low)-position['entry_price'])/position['entry_price'] if sign==1 else (position['entry_price']-float(row.high))/position['entry_price']
            position['mfe']=max(position['mfe'],favorable)
            position['mae']=min(position['mae'],adverse)
            # Insolvency check is deliberately approximate, NOT Delta's engine.
            worst=(float(row.low) if sign==1 else float(row.high))
            maintenance=worst*qty*cfg.maintenance_margin_percent/100
            unrealized=(worst-position['entry_price'])*qty*sign
            stressed=((position['margin']+unrealized+position['funding_usd']-position['entry_fee'])
                      if cfg.margin_mode=='ISOLATED' else balance+unrealized)
            if stressed<=maintenance:
                close(position,ts,worst,'ESTIMATED_MARGIN_BREACH')
                position=None;closed=True
            else:
                hit=_exit_level(position,row,cfg)
                if hit:
                    if cfg.stop_loss_percent and cfg.take_profit_percent:
                        stop=position['entry_price']*(1-cfg.stop_loss_percent/100*sign)
                        target=position['entry_price']*(1+cfg.take_profit_percent/100*sign)
                        if (float(row.low)<=min(stop,target) and float(row.high)>=max(stop,target)):
                            ambiguous+=1
                    close(position,ts,hit[1],hit[0]);position=None;closed=True
                elif strategy.risk.max_hold_minutes is not None and (ts-pd.Timestamp(position['entry_time'])).total_seconds()/60>=strategy.risk.max_hold_minutes:
                    pending=('CLOSE','TIME_STOP')
                elif strategy.risk.close_at_session_end and _session_end_due(ts,strategy.session,tf):
                    pending=('CLOSE','SESSION_END_EXIT')
                elif ((position['direction']=='LONG' and strategy.call_exit_signal_mode!='ALERT_ONLY' and evaluate_group(frame,i,strategy.call_exit)['passed'] and strategy.call_exit.configured())
                   or (position['direction']=='SHORT' and strategy.put_exit_signal_mode!='ALERT_ONLY' and evaluate_group(frame,i,strategy.put_exit)['passed'] and strategy.put_exit.configured())):
                    # Condition known at this candle's close: cannot execute
                    # at this candle's close. Next bar open is required.
                    pending=('CLOSE','CONDITION_EXIT')
        if closed or position or pending is not None or not _session_allowed(ts,strategy.session):continue
        if strategy.risk.close_at_session_end and _session_end_due(ts,strategy.session,tf):continue
        if strategy.no_trade.configured() and evaluate_group(frame,i,strategy.no_trade)['passed']:continue
        if (strategy.risk.max_trades_per_day is not None and daily['entries']>=strategy.risk.max_trades_per_day
          or strategy.risk.max_consecutive_losses is not None and daily['consecutive_losses']>=strategy.risk.max_consecutive_losses
          or strategy.risk.max_daily_loss_percent is not None and strategy.risk.stop_trading_after_daily_loss_limit
             and daily['realized']<=-daily['start_balance']*strategy.risk.max_daily_loss_percent/100):
            daily['blocks']+=1
            continue
        eligible=[]
        for direction,enabled,group,nt,side in (
            ('LONG',call_enabled,strategy.call_entry,strategy.call_no_trade,'CALL'),
            ('SHORT',put_enabled,strategy.put_entry,strategy.put_no_trade,'PUT')):
            if not enabled or not group.configured():continue
            if nt.configured() and evaluate_group(frame,i,nt)['passed']:continue
            state=_update_lifecycles(frame,i,group,_entry_behaviors(strategy,side),cycles[direction])
            if not any(x['eligible'] for x in state):continue
            tree=evaluate_group(frame,i,group,_entry_ignore_ids(strategy,side))
            score=_big_trend_score(frame,i,group,
                strategy.call_big_trend_score if side=='CALL' else strategy.put_big_trend_score,side)
            if tree['passed'] and score['passed']:
                eligible.append(direction)
        if eligible:
            if len(eligible)==2:
                if strategy.conflict_policy=='PREFER_CALL':pending='LONG'
                elif strategy.conflict_policy=='PREFER_PUT':pending='SHORT'
            else:pending=eligible[0]
    if position:
        unresolved={'reason':'END_OF_RANGE_FUTURES_EXPOSURE','entry_time':position['entry_time'],
            'entry_price':position['entry_price'],'direction':position['direction'],
            'marked_not_realized':True}
    wins=sum(t['net_pnl_usd']>0 for t in trades)
    gp=sum(max(0,t['net_pnl_usd']) for t in trades);gl=-sum(min(0,t['net_pnl_usd']) for t in trades)
    metrics={'trades':len(trades),'wins':wins,'losses':sum(t['net_pnl_usd']<0 for t in trades),
      'win_rate_percent':wins/max(len(trades),1)*100,
      'gross_pnl_usd':sum(t['gross_pnl_usd'] for t in trades),
      'net_pnl_usd':sum(t['net_pnl_usd'] for t in trades),
      'fees_usd':fee_total,'base_fees_usd':fee_total/(1+cfg.gst_percent/100),
      'gst_usd':fee_total-fee_total/(1+cfg.gst_percent/100),
      'funding_usd':fund_total,'profit_factor':gp/gl if gl else None,
      'return_percent':(balance/initial-1)*100,'ending_balance_usd':balance,
      'max_closed_trade_drawdown_usd':max_dd,'max_closed_trade_drawdown_percent':max_dd_pct,
      'max_mark_to_market_drawdown_usd':None,'max_mark_to_market_drawdown_percent':None,
      'avg_mfe_percent':sum(t['mfe_percent'] for t in trades)/len(trades) if trades else 0,
      'avg_mae_percent':sum(t['mae_percent'] for t in trades)/len(trades) if trades else 0,
      'estimated_margin_breaches':sum(t['exit_reason']=='ESTIMATED_MARGIN_BREACH' for t in trades),
      'unresolved_position_count':int(unresolved is not None),
      'alerts_triggered':sum(m['kind']=='alert' for m in markers),'daily_risk_blocks':daily['blocks'],
      'insufficient_margin_rejections':risk_rejects,
      'ambiguous_intrabar_stop_target':ambiguous}
    run_id,out=_new_result_dir(strategy.name)
    result={'run_id':run_id,'result_dir':str(out),'start':req.start,'end':req.end,
      'dataset_id':getattr(req,'dataset_id',None),'dataset_ids':[p.id for p in parts],
      'dataset_mode':getattr(req,'dataset_mode','SINGLE'),'storage_mode':req.storage_mode,
      'cache_key':key,'cache_hit':False,'strategy':strategy.model_dump(),
      'metrics':metrics,'trades':trades,'markers':markers,'equity_curve':equity_curve,
      'decision_count':0,'preflight':preflight,'warmup':warmup,'series_meta':meta,
      'unresolved_position':unresolved,
      'reliability':{'grade':'RESEARCH_ONLY','execution_model':'UNDERLYING_OHLC_PROXY',
        'limitations':['No historical futures orderbook/spread or fills',
           'Intrabar stops/targets, slippage and margin breaches are estimates',
           'True mark-to-market drawdown not computed without historical futures mark/executable quotes',
           'Funding excluded' if cfg.funding_mode=='EXCLUDE_WITH_WARNING' else 'Funding rates supplied externally and settlement notional approximated']},
      'fee_model':{'name':'DELTA_FUTURES_ASSUMED_TAKER','taker_fee_percent':cfg.taker_fee_percent,'gst_percent':cfg.gst_percent},
      'futures_research':{'symbol':cfg.symbol,'leverage':cfg.leverage,'margin_mode':cfg.margin_mode,
        'funding_mode':cfg.funding_mode,'funding_missing_intervals':len(missing_funding),
        'venue_verified_liquidation':False,'volume_fill_verified':False}}
    (out/'strategy.json').write_text(json.dumps(strategy.model_dump(),indent=2),encoding='utf-8')
    if trades:
        with (out/'trades.csv').open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=list(trades[0]));writer.writeheader();writer.writerows(trades)
    from .engine import _json_safe
    summary=_json_safe(result)
    for k in ('trades','markers','equity_curve','series_meta'):summary.pop(k,None)
    manifest={'trades':'trades.csv' if trades else None,'markers':None,'equity_curve':None,'decisions':None}
    if markers:
        write_json_gz(out/'markers.json.gz',markers);manifest['markers']='markers.json.gz'
    if req.storage_mode!='COMPACT' and equity_curve:
        write_csv_gz(out/'equity_curve.csv.gz',equity_curve);manifest['equity_curve']='equity_curve.csv.gz'
    summary['artifact_manifest']=manifest
    (out/'summary.json').write_text(json.dumps(summary,separators=(',',':'),allow_nan=False),encoding='utf-8')
    _write_cache(key,run_id);maybe_auto_cleanup();store.close()
    if progress:progress('Futures backtest finished (research only)',100,'COMPLETE','Complete')
    return _json_safe(result)
