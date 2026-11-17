import {describe,expect,it,vi} from 'vitest';
import {LatestRequest} from './latestRequest';

function deferred<T>() {
 let resolve!: (value:T)=>void;
 let reject!: (error:unknown)=>void;
 const promise=new Promise<T>((good,bad)=>{resolve=good;reject=bad});
 return {promise,resolve,reject};
}

describe('LatestRequest',()=>{
 it('only applies the latest chart response and releases its own loading state',async()=>{
  const manager=new LatestRequest();
  const first=deferred<string>(),second=deferred<string>();
  const seen:string[]=[],completed:string[]=[];
  let firstSignal:AbortSignal|undefined;
  const a=manager.run(signal=>{firstSignal=signal;return first.promise;},
   value=>seen.push(value),()=>seen.push('first-error'),()=>completed.push('first'));
  const b=manager.run(()=>second.promise,
   value=>seen.push(value),()=>seen.push('second-error'),()=>completed.push('second'));
  expect(firstSignal?.aborted).toBe(true);
  first.resolve('stale');await a;
  expect(seen).toEqual([]);
  expect(completed).toEqual([]);
  second.resolve('latest');await b;
  expect(seen).toEqual(['latest']);
  expect(completed).toEqual(['second']);
 });
 it('allows chart cancellation without invoking any completion callback from the stale request',async()=>{
  const manager=new LatestRequest();
  const request=deferred<string>();const good=vi.fn(),fail=vi.fn(),finish=vi.fn();
  const pending=manager.run(()=>request.promise,good,fail,finish);
  manager.cancel();request.reject(new Error('aborted'));await pending;
  expect(good).not.toHaveBeenCalled();
  expect(fail).not.toHaveBeenCalled();
  expect(finish).not.toHaveBeenCalled();
 });
 it('reports current failures and clears loading',async()=>{
  const manager=new LatestRequest();
  const fail=vi.fn(),done=vi.fn();
  await manager.run(()=>Promise.reject(new Error('preview unavailable')),vi.fn(),fail,done);
  expect(fail).toHaveBeenCalledOnce();
  expect(done).toHaveBeenCalledOnce();
 });
});
