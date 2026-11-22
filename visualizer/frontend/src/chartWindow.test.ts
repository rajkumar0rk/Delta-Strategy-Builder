import {describe,expect,it} from 'vitest';
import type {Marker} from './types';
import {calculateChartWindow,markersInWindow,MAX_CHART_CANDLES} from './chartWindow';

describe('chart window requests',()=>{
 it('limits even a 22-month 5-minute backtest to a bounded chart request',()=>{
  const start='2025-01-01T00:00:00.000Z';
  const end='2026-11-01T00:00:00.000Z';
  const window=calculateChartWindow(start,end,5);
  expect(window.total).toBeGreaterThan(1);
  expect(window.index).toBe(0);
  expect(Date.parse(window.end)-Date.parse(window.start)).toBeLessThanOrEqual(MAX_CHART_CANDLES*5*60_000);
  expect(window.end).toBe(end);
 });
 it('paginates backwards in contiguous, nonoverlapping windows',()=>{
  const start='2026-01-01T00:00:00.000Z';
  const end='2026-07-01T00:00:00.000Z';
  const newest=calculateChartWindow(start,end,15,0);
  const older=calculateChartWindow(start,end,15,1);
  expect(older.end).toBe(newest.start);
  expect(Date.parse(older.start)).toBeGreaterThanOrEqual(Date.parse(start));
  expect(calculateChartWindow(start,end,15,99999).start).toBe(start);
 });
 it('keeps short ranges unchanged and rejects invalid ranges',()=>{
  const start='2026-06-01T00:00:00.000Z', end='2026-06-03T00:00:00.000Z';
  const window=calculateChartWindow(start,end,5);
  expect(window).toEqual({start,end,index:0,total:1});
  expect(()=>calculateChartWindow(end,start,5)).toThrow();
  expect(()=>calculateChartWindow(start,end,0)).toThrow();
 });
 it('excludes backtest markers outside the visible window',()=>{
  const window=calculateChartWindow('2026-11-01T00:00:00.000Z','2026-11-03T00:00:00.000Z',5);
  const at=(date:string):Marker=>({time:Date.parse(date)/1000,kind:'entry',direction:'CALL',text:'Entry'});
  const markers=[
   at('2026-10-31T23:59:00.000Z'),
   at('2026-11-01T00:00:00.000Z'),
   at('2026-11-02T23:55:00.000Z'),
   at('2026-11-03T00:00:00.000Z'),
  ];
  expect(markersInWindow(markers,window)).toEqual(markers.slice(1,3));
 });
});
