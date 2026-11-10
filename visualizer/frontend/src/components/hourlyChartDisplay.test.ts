import {describe,expect,it} from 'vitest';
import type {ChartPayload,ChartBar} from '../types';
import {displayHourStart,hourlyChartPayload} from './hourlyChartDisplay';

const bar=(time:number,price:number):ChartBar=>({
 time,open:price,high:price+10,low:price-5,close:price+2,volume:3,
});
function payload(bars:ChartBar[]):ChartPayload{
 return {bars,series:[{
  key:'ema',instance_id:'ema',kind:'EMA',label:'EMA',placement:'overlay',
  output:'value',visible:true,
  values:bars.map(b=>({time:b.time,value:b.close})),
 }],markers:[],study_markers:[],condition_states:[]};
}
const fullHour=(start:number,base:number):ChartBar[]=>Array.from({length:12},(_,index)=>
 bar(start+(index+1)*300,base+index));

describe('Chart-only UTC hourly presentation',()=>{
 it('groups twelve consecutive 5m CLOSE bars into an hourly OPEN bar',()=>{
  const source=payload([...fullHour(0,100),...fullHour(3600,200)]);
  const before=JSON.stringify(source);
  const result=hourlyChartPayload(source);
  expect(result.bars).toEqual([
   {time:0,open:100,high:121,low:95,close:113,volume:36},
   {time:3600,open:200,high:221,low:195,close:213,volume:36},
  ]);
  expect(result.series[0].values).toEqual([
   {time:0,value:113},{time:3600,value:213},
  ]);
  expect(result.partial_display_hours).toBe(0);
  expect(JSON.stringify(source)).toBe(before);
 });
 it('maps entry at 1h OPEN to the new hour, retaining the exact original UTC timestamp',()=>{
  const source=payload([...fullHour(0,100),...fullHour(3600,200)]);
  source.markers=[
   {id:'entry',kind:'entry',time:3600,direction:'PUT',text:'SHORT'},
   {id:'exit',kind:'exit',time:3900,direction:'PUT',text:'TP'},
  ];
  const result=hourlyChartPayload(source);
  expect(result.markers.map(m=>m.time)).toEqual([3600,3600]);
  expect(result.markers[0].timestamp).toBe('1970-01-01T01:00:00.000Z');
  expect(source.markers.map(m=>m.time)).toEqual([3600,3900]);
  expect(displayHourStart(3600)).toBe(0); // a 5m CLOSE at 01:00 belongs to 00:00-01:00
 });
 it('preserves completed hours and displays only the final partial hour as partial',()=>{
  const source=payload([...fullHour(0,100),...fullHour(3600,200).slice(0,3)]);
  source.markers=[{id:'entry',kind:'entry',time:3600,direction:'PUT',text:'SHORT'}];
  const result=hourlyChartPayload(source);
  expect(result.bars.map(b=>b.time)).toEqual([0,3600]);
  expect(result.partial_display_hours).toBe(1);
  expect(result.markers.map(m=>m.id)).toEqual(['entry']);
 });
 it('never invents or forward-fills missing 5m candles or missing 5m indicator values',()=>{
  const first=fullHour(0,100).filter(b=>b.time!==900);
  const second=fullHour(3600,200);
  const source=payload([...first,...second]);
  source.series[0].values=source.series[0].values.filter(v=>v.time!==7200);
  source.markers=[{id:'missingHourTrade',kind:'exit',time:1200,direction:'PUT',text:'EXIT'}];
  const result=hourlyChartPayload(source);
  expect(result.bars.map(b=>b.time)).toEqual([3600]);
  expect(result.series[0].values).toEqual([]);
  expect(result.markers).toEqual([]);
  expect(result.partial_display_hours).toBe(0);
 });
 it('keeps the latest hourly close condition snapshot and never includes a future one',()=>{
  const source=payload(fullHour(0,100));
  source.condition_states=[{time:3600,call_score:10,put_score:75} as ChartPayload['condition_states'][number],
   {time:7200,call_score:99,put_score:99} as ChartPayload['condition_states'][number]];
  const result=hourlyChartPayload(source);
  expect(result.condition_states).toEqual([{time:0,call_score:10,put_score:75}]);
 });
});
