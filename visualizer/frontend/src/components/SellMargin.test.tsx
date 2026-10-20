import {describe,expect,it} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {mergeSellMargin,RiskOptions} from './RiskOptions';
import {defaultStrategy} from '../defaults';

describe('SELL margin scenario editor',()=>{
 it('fills required fields when a legacy strategy has no sell_margin',()=>{
  const s=defaultStrategy();
  s.call_action='SELL';
  delete s.risk.sell_margin;
  const merged=mergeSellMargin(s.risk.sell_margin,{enabled:true});
  expect(merged.enabled).toBe(true);
  expect(merged.margin_mode).toBe('ISOLATED_ESTIMATE');
  expect(merged.initial_margin_percent).toBeNull();
  expect(merged.reserve_exit_fee).toBe(true);
  expect(merged.check_margin_on_quotes).toBe(true);
 });
 it('preserves collateral rates when editing the margin mode',()=>{
  const saved=mergeSellMargin(undefined,{
   enabled:true,initial_margin_percent:20,maintenance_margin_percent:10,
  });
  const changed=mergeSellMargin(saved,{margin_mode:'CROSS_ESTIMATE'});
  expect(changed.enabled).toBe(true);
  expect(changed.margin_mode).toBe('CROSS_ESTIMATE');
  expect(changed.initial_margin_percent).toBe(20);
  expect(changed.maintenance_margin_percent).toBe(10);
 });

 it('supports portfolio margin as a distinct mode without a fixed leverage control',()=>{
  const s=defaultStrategy();
  s.call_action='SELL';
  s.risk.sell_margin=mergeSellMargin(s.risk.sell_margin,{
   margin_mode:'PORTFOLIO_ESTIMATE',enabled:true,
   initial_margin_percent:20,maintenance_margin_percent:10,max_notional_leverage:null,
  });
  const html=renderToStaticMarkup(<RiskOptions value={s} onChange={()=>{}}/>);
  expect(html).toContain('Portfolio Margin — manual research proxy');
  expect(html).toContain('Portfolio Margin selected');
  expect(html).toContain('Assumed portfolio stress IM');
  expect(html).not.toContain('Maximum assumed notional leverage');
  expect(html).toContain('NOT exchange IM/MM');
 });
 it('is absent when both directions BUY',()=>{
  const html=renderToStaticMarkup(<RiskOptions value={defaultStrategy()} onChange={()=>{}}/>);
  expect(html).not.toContain('SELL collateral &amp; leverage');
 });
 it('displays research-only leverage controls for SELL',()=>{
  const s=defaultStrategy();s.call_action='SELL';
  const html=renderToStaticMarkup(<RiskOptions value={s} onChange={()=>{}}/>);
  expect(html).toContain('SELL collateral &amp; leverage');
  expect(html).toContain('Initial margin %');
  expect(html).toContain('Maximum assumed notional leverage');
  expect(html).toContain('NOT Delta Exchange verified');
 });
});
