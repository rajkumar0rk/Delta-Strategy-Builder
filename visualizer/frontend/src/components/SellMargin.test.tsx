import {describe,expect,it} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {RiskOptions} from './RiskOptions';
import {defaultStrategy} from '../defaults';

describe('SELL margin scenario editor',()=>{
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
