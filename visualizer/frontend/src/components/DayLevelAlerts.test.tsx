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
  for(const text of ['day_boundary_mode','timezone','pivot_right','lookback_days','warning_points','confirmed by the next session start'])expect(markup).toContain(text);
  expect(markup).toContain('max="60"');
  expect(markup).toContain('CALENDAR');
  expect(markup).toContain('SYMBOL_SESSION');
  expect(markup).toContain('CUSTOM_SESSION');
 }); 
 it('shows symbol session fields without unrelated custom settings',()=>{
  const s=strategy();
  s.indicators[0].params.day_boundary_mode='SYMBOL_SESSION';
  const d:IndicatorDefinition={kind:'DAY_LEVELS',label:'Daily levels',category:'Market structure',
   placement:'overlay',outputs:['day_id'],description:'Daily levels',params:{
    day_boundary_mode:{type:'select',default:'CALENDAR',options:['CALENDAR','SYMBOL_SESSION','CUSTOM_SESSION']},
    timezone:{type:'text',default:'Asia/Kolkata'},
    symbol:{type:'select',default:'BTCUSD',options:['BTCUSD']},
    session_timezone:{type:'text',default:'UTC'},
    session_open:{type:'text',default:'00:00'},session_close:{type:'text',default:'00:00'},
    session_weekdays:{type:'text',default:'0,1,2,3,4,5,6'},
  }};
  let html=renderToStaticMarkup(<IndicatorManager catalog={[d]} value={s.indicators} onChange={()=>{}}/>);
  expect(html).toContain('BTCUSD trades 24/7');
  expect(html).toContain('>symbol</span>');
  expect(html).not.toContain('>session_weekdays</span>');
  s.indicators[0].params.day_boundary_mode='CUSTOM_SESSION';
  html=renderToStaticMarkup(<IndicatorManager catalog={[d]} value={s.indicators} onChange={()=>{}}/>);
  expect(html).toContain('>session_open</span>');
  expect(html).toContain('>session_weekdays</span>');
  expect(html).not.toContain('>symbol</span>');
 });
});
