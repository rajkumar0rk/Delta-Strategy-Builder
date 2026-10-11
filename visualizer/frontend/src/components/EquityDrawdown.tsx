import {useEffect,useRef} from 'react';
import {ColorType,LineSeries,AreaSeries,createChart,type UTCTimestamp} from 'lightweight-charts';
import type {BacktestResult} from '../types';
export function EquityDrawdown({result}:{result:BacktestResult|null}){
 const ref=useRef<HTMLDivElement>(null);
 useEffect(()=>{
  if(!result?.equity_curve?.length||!ref.current)return;
  const el=ref.current;
  const chart=createChart(el,{width:el.clientWidth,height:300,layout:{background:{type:ColorType.Solid,color:'#0b0f16'},textColor:'#aab4c4'},grid:{vertLines:{color:'#18202c'},horzLines:{color:'#18202c'}},timeScale:{timeVisible:true,secondsVisible:false,borderColor:'#283244'},rightPriceScale:{borderColor:'#283244'}});
  const equity=chart.addSeries(AreaSeries,{lineWidth:2,title:'Equity',priceLineVisible:false},0);
  equity.setData(result.equity_curve.map(x=>({time:Math.floor(new Date(x.timestamp).getTime()/1000) as UTCTimestamp,value:x.equity_usd})));
  const dd=chart.addSeries(LineSeries,{lineWidth:2,title:'Drawdown %',priceLineVisible:false,lastValueVisible:true},1);
  dd.setData(result.equity_curve.map(x=>({time:Math.floor(new Date(x.timestamp).getTime()/1000) as UTCTimestamp,value:-Math.abs(x.drawdown_percent)})));
  chart.timeScale().fitContent();
  const panes=chart.panes();if(panes[0])panes[0].setHeight(190);if(panes[1])panes[1].setHeight(100);
  const ro=new ResizeObserver(()=>chart.applyOptions({width:el.clientWidth}));ro.observe(el);
  return()=>{ro.disconnect();chart.remove()};
 },[result]);
 if(!result?.equity_curve?.length)return null;
 return <section className="card"><div className="card-head"><div><h2>Equity & drawdown</h2><p>Closed-trade equity after Delta fees + GST. Drawdown is shown as a negative percentage of the prior equity peak.</p></div></div><div ref={ref} className="equity-chart"/></section>
}
