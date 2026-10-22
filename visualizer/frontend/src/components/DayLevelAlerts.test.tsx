import {describe,expect,it} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import {AlertEditor} from './AlertEditor';
import {IndicatorManager} from './IndicatorManager';
import template from '../../../examples/previous-day-swing-alerts.strategy.json';
import type {Strategy,IndicatorDefinition} from '../types';

const strategy=()=>structuredClone(template.strategy) as Strategy;
describe('historical daily level alert preset',()=>{
 it('imports eight separate alert-only rules with daily identities',()=>{
  const s=strategy();
  expect(template.schema_version).toBe(15);
  expect(s.call_signal_mode).toBe('ALERT_ONLY');
  expect(s.put_signal_mode).toBe('ALERT_ONLY');
  expect(s.call_entry.conditions).toHaveLength(0);
  expect(s.put_entry.conditions).toHaveLength(0);
  expect(s.alerts).toHaveLength(8);
  expect(new Set(s.alerts!.map(a=>a.id)).size).toBe(8);
  for(const a of s.alerts!){
   expect(a.reset_operand).toBe('daily.day_id');
   expect(s.no_trade.conditions.some(c=>c.id===a.condition_id)).toBe(true);
  }
  expect(s.indicators[0].chart_only).toBe(false);
  expect(s.indicators[0].params.warning_points).toBe(100);
 });
 it('renders saved messages, references and optional daily rearm setting',()=>{
  const s=strategy();
  const markup=renderToStaticMarkup(<AlertEditor value={s.alerts!} strategy={s}
   operands={['daily.day_id']} onChange={()=>{}}/>);
  expect(markup).toContain('Touch confirmation');
  expect(markup).toContain('Warning');
  expect(markup).toContain('Rearm when value changes');
  expect(markup).toContain('value="daily.day_id" selected');
 });
 it('exposes calendar, swing and warning controls from the indicator catalog',()=>{
  const d:IndicatorDefinition={kind:'DAY_LEVELS',label:'Daily levels',category:'Market structure',
   placement:'overlay',outputs:['day_id'],description:'Daily levels',params:{
    timezone:{type:'text',default:'Asia/Kolkata'},pivot_right:{type:'int',default:3,min:1,max:50},
    lookback_days:{type:'int',default:30,min:1,max:60},warning_points:{type:'float',default:100,min:0}}};
  const markup=renderToStaticMarkup(<IndicatorManager catalog={[d]} value={strategy().indicators} onChange={()=>{}}/>);
  for(const text of ['timezone','pivot_right','lookback_days','warning_points','confirmed by day start'])expect(markup).toContain(text);
  expect(markup).toContain('max="60"');
 });
});
