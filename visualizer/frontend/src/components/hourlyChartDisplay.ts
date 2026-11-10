/** Presentation-only 5m-close -> UTC 1h-open chart aggregation.
 *
 * IMPORTANT: Never use this function to generate entry/exit decisions. The
 * original 5m chart payload, engine inputs, result trades and saved strategy
 * remain untouched. Include only contiguous 5m candles beginning at an hour
 * boundary; the final partly observed hour is tagged as partial.
 */
import type {ChartBar,ChartPayload,Marker} from '../types';

const FIVE_MINUTES=300;
const HOUR=3600;

export const displayHourStart=(closeTimestamp:number):number=>
 Math.floor((closeTimestamp-1)/HOUR)*HOUR;

export function hourlyChartPayload(source:ChartPayload):ChartPayload & {partial_display_hours:number}{
 const buckets:{start:number;bars:ChartBar[];lastClose:number;complete:boolean}[]=[];
 let current:{start:number;bars:ChartBar[]}|null=null;
 const finish=()=>{
  if(!current)return;
  const rows=current.bars;
  // Disallow missing, duplicate or off-grid 5m OHLC observations. A full
  // historical hour must contain 12 consecutive bars.
  const contiguous=rows.length>0&&rows.length<=12&&rows.every((bar,index)=>
   bar.time===current!.start+(index+1)*FIVE_MINUTES&&
   Number.isFinite(bar.open)&&Number.isFinite(bar.high)&&
   Number.isFinite(bar.low)&&Number.isFinite(bar.close)&&Number.isFinite(bar.volume));
  if(contiguous)buckets.push({start:current.start,bars:rows,lastClose:rows[rows.length-1].time,complete:rows.length===12});
 };
 for(const bar of source.bars){
  const start=displayHourStart(bar.time);
  if(!current||current.start!==start){finish();current={start,bars:[]}}
  current.bars.push(bar);
 }
 finish();
 // Never show incomplete historical groups as fully confirmed 1h bars.
 // Only the trailing range-end group may be a visibly partial hour.
 const finalStart=buckets.at(-1)?.start;
 const visible=buckets.filter(b=>b.complete||b.start===finalStart);
 const allowed=new Set(visible.map(b=>b.start));
 const bars=visible.map(b=>{
  const last=b.bars[b.bars.length-1];
  return {time:b.start,open:b.bars[0].open,high:Math.max(...b.bars.map(x=>x.high)),
   low:Math.min(...b.bars.map(x=>x.low)),close:last.close,
   volume:b.bars.reduce((sum,x)=>sum+x.volume,0)};
 });
 const series=source.series.map(s=>{
  const byTimestamp=new Map(s.values.map(v=>[v.time,v]));
  return {...s,values:visible.flatMap(b=>{
   const sample=byTimestamp.get(b.lastClose);
   // Missing 5m indicator at the observed end stays missing. No
   // forward-filling of an unavailable or future indicator value.
   return sample?[{...sample,time:b.start}]:[];
  })};
 });
 const states=new Map(source.condition_states.map(s=>[s.time,s]));
 const condition_states=visible.flatMap(b=>{
  const sample=states.get(b.lastClose);
  return sample?[{...sample,time:b.start}]:[];
 });
 const markers=(events:Marker[]):Marker[]=>events.flatMap(m=>{
  // Event timestamps are real execution times; map to the 1h candle
  // whose OPEN owns that time, rather than snapping to a prior close.
  const hour=Math.floor(m.time/HOUR)*HOUR;
  if(!allowed.has(hour))return [];
  return [{...m,time:hour,
   timestamp:m.timestamp||new Date(m.time*1000).toISOString()}];
 });
 return {...source,bars,series,condition_states,markers:markers(source.markers),
  study_markers:markers(source.study_markers||[]),
  partial_display_hours:visible.filter(b=>!b.complete).length};
}
