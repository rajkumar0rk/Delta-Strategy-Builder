import {describe,expect,it} from 'vitest';
import {defaultStrategy} from './defaults';
import type {BacktestResult} from './types';
import {backtestOverlayCurrent} from './backtestOverlay';

describe('chart never reuses an old trade overlay on changed settings',()=>{
 const scope=JSON.stringify({
  dataset_mode:'ARCHIVE',dataset_id:null,dataset_ids:[],
  start:'2026-01-01T00:00',end:'2026-01-03T00:00',barGapPolicy:'REQUIRE'
 });
 const make=()=>{
  const strategy=defaultStrategy();
  strategy.market_type='FUTURES';
  strategy.futures={...strategy.futures!,supertrend_ema_first_touch:{
   enabled:true,supertrend_indicator_id:'supertrend_1h',
   ema_indicator_id:'ema20_1h',exit_mode:'FLIP_ONLY'
  }};
  const result={strategy,markers:[],trades:[]} as unknown as BacktestResult;
  return {strategy,result};
 };

 it('shows markers from exactly the completed run',()=>{
  const {strategy,result}=make();
  expect(backtestOverlayCurrent(result,strategy,scope,scope)).toBe(true);
 });

 it('hides a prior CALL OPEN after selecting a 200-point trailing exit',()=>{
  const {strategy,result}=make();
  const edited={...strategy,futures:{...strategy.futures!,
   supertrend_ema_first_touch:{...strategy.futures!.supertrend_ema_first_touch!,
    exit_mode:'POINT_TRAIL' as const,trailing_distance_points:200}}};
  expect(backtestOverlayCurrent(result,edited,scope,scope)).toBe(false);
 });

 it('hides prior trades when dataset, dates or gap policy change',()=>{
  const {strategy,result}=make();
  for(const modifiedScope of [
   scope.replace('ARCHIVE','SINGLE'),
   scope.replace('2026-01-01','2026-02-01'),
   scope.replace('REQUIRE','WARN')
  ])expect(backtestOverlayCurrent(result,strategy,scope,modifiedScope)).toBe(false);
 });

 it('does not show trade markers without a completed run',()=>{
  const {strategy,result}=make();
  expect(backtestOverlayCurrent(null,strategy,scope,scope)).toBe(false);
  expect(backtestOverlayCurrent(result,strategy,null,scope)).toBe(false);
 });
});
