import {describe,expect,it} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {defaultStrategy} from '../defaults';
import {FuturesSettings} from './FuturesSettings';
import {Results} from './Results';
import type {BacktestResult} from '../types';

describe('BTCUSD perpetual futures market editor',()=>{
 it('keeps existing strategy files defaulting to OPTIONS',()=>{
  expect(defaultStrategy().market_type).toBe('OPTIONS');
 });
 it('shows futures contract sizing, leverage, costs, funding and margin risk controls',()=>{
  const s=defaultStrategy();s.market_type='FUTURES';
  const html=renderToStaticMarkup(<FuturesSettings value={s} onChange={()=>{}}/>);
  for(const field of ['LONG + SHORT','Quantity (lots of 0.001 BTC)',
     'Assumed leverage','Isolated','Cross','Taker fee','GST','Adverse slippage',
     'Funding history','Require historical funding CSV','Starting balance',
     'Daily max loss','Maximum hold','session boundary','Add session window']){
    expect(html).toContain(field);
  }
  expect(html).not.toContain('SELL collateral &amp; leverage');
 });
 it('clearly labels simulated futures fills in result report',()=>{
  const s=defaultStrategy();s.market_type='FUTURES';
  const result={run_id:'test',storage_mode:'COMPACT',strategy:s,
    decision_count:0,trades:[],metrics:{trades:0,wins:0,losses:0,win_rate_percent:0,
      gross_pnl_usd:0,net_pnl_usd:0,fees_usd:0,gst_usd:0,
      profit_factor:null,return_percent:0,max_closed_trade_drawdown_usd:0,
      max_closed_trade_drawdown_percent:0,avg_mfe_percent:0,avg_mae_percent:0,
      funding_usd:0,estimated_margin_breaches:0,ambiguous_intrabar_stop_target:0}
  } as BacktestResult;
  const html=renderToStaticMarkup(<Results r={result}/>);
  expect(html).toContain('FUTURES OHLC RESEARCH ONLY');
  expect(html).toContain('funding');
  expect(html).not.toContain('Delta option trading cost model');
 });
});
