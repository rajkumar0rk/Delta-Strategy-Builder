/** Show at most one alert marker per N completed chart candles, without changing events. */
export function spaceAlertMarkers<T extends {kind:string;time:number;text?:string;details?:unknown}>(
 markers:readonly T[],barTimes:readonly number[],minimumCandles:number,
):T[]{
 if(!Number.isFinite(minimumCandles)||minimumCandles<=0||barTimes.length===0)return [...markers];
 const spacing=Math.max(1,Math.floor(minimumCandles));
 const index=(time:number)=>{
  let lo=0,hi=barTimes.length-1;
  while(lo<=hi){const mid=(lo+hi)>>1;if(barTimes[mid]<=time)lo=mid+1;else hi=mid-1}
  return Math.max(0,hi);
 };
 const rows=markers.map((m,i)=>({m,i,bar:index(m.time)})).filter(x=>x.m.kind==='alert');
 const priority=(m:T)=>{
  const details=m.details;
  const name=details && typeof details==='object' && 'alert_name' in details
   ? String(details.alert_name ?? m.text ?? '') : String(m.text ?? '');
  return /touch confirmation/i.test(name)?0:1;
 };
 rows.sort((a,b)=>a.bar-b.bar||priority(a.m)-priority(b.m)||a.i-b.i);
 const chosen=new Set<number>();let last=-Infinity;
 for(const r of rows)if(r.bar-last>=spacing){chosen.add(r.i);last=r.bar}
 return markers.filter((m,i)=>m.kind!=='alert'||chosen.has(i));
}
