import {describe,expect,it} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {defaultStrategy} from '../defaults';
import {RiskOptions} from './RiskOptions';

describe('explicit execution safety caps',()=>{
 it('retains optional caps and renders their actual values',()=>{
  const s=defaultStrategy();
  s.execution.safety_caps={max_spread_percent:2,per_trade_premium_usd:8,account_budget_usd:80};
  const html=renderToStaticMarkup(<RiskOptions value={s} onChange={()=>{}}/>);
  expect(html).toContain('Maximum spread %');expect(html).toContain('value="2"');
  expect(html).toContain('Maximum entry premium $');expect(html).toContain('value="8"');
  expect(html).toContain('Maximum cash per entry $');expect(html).toContain('value="80"');
  expect(s.risk.stop_loss.value).toBe(15);
 });
});
