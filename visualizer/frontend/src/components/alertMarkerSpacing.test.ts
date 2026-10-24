import {describe,expect,it} from 'vitest';
import {spaceAlertMarkers} from './alertMarkerSpacing';

type Marker={id:string;kind:string;time:number;text?:string;details?:{alert_name?:string}};
const bars=[100,200,300,400,500,600,700,800,900];
const alert=(id:string,time:number,text='Warning'):Marker=>({id,kind:'alert',time,details:{alert_name:text}});
const other=(id:string,time:number):Marker=>({id,kind:'entry',time});

describe('Chart-only alert spacing',()=>{
 it('zero spacing preserves all alerts',()=>{
  const original=[alert('a',100),alert('b',100),other('entry',100)];
  expect(spaceAlertMarkers(original,bars,0)).toEqual(original);
 });
 it('globally spaces different alert rules and leaves orders visible',()=>{
  const original=[alert('a',100),alert('b',200),alert('c',400),alert('d',500),alert('e',700),other('entry',300)];
  expect(spaceAlertMarkers(original,bars,3).map(x=>x.id)).toEqual(['a','c','e','entry']);
  expect(original).toHaveLength(6);
 });
 it('prefers touch over warning on the same candle',()=>{
  const original=[alert('warning',300,'Warning: older swing low'),alert('touch',300,'Touch confirmation: older swing low'),alert('next',400)];
  expect(spaceAlertMarkers(original,bars,1).map(x=>x.id)).toEqual(['touch','next']);
 });
 it('snaps events to preceding completed candle and handles unordered input',()=>{
  const original=[alert('late',305),alert('early',205),alert('same',290)];
  expect(spaceAlertMarkers(original,bars,1).map(x=>x.id)).toEqual(['late','early']);
 });
 it('no chart bars or negative spacing preserves events',()=>{
  const original=[alert('a',100),alert('b',200)];
  expect(spaceAlertMarkers(original,[],12)).toEqual(original);
  expect(spaceAlertMarkers(original,bars,-1)).toEqual(original);
 });
});
