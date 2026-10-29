import type {FuturesConfig,Strategy} from '../types';

const defaults:FuturesConfig={symbol:'BTCUSD',contract_btc:0.001,quantity_lots:1,leverage:5,
 margin_mode:'ISOLATED',maintenance_margin_percent:.25,taker_fee_percent:.05,
 gst_percent:18,slippage_bps:2,stop_loss_percent:1,take_profit_percent:2,
 funding_mode:'REQUIRE_CSV'};
export function FuturesSettings({value,onChange}:{value:Strategy;onChange:(s:Strategy)=>void}){
 const f=value.futures||defaults;
 const set=(patch:Partial<FuturesConfig>)=>onChange({...value,futures:{...f,...patch}});
 const number=(name:keyof FuturesConfig,label:string,step:string,min:number)=>(
  <label key={name}>{label}<input type="number" min={min} step={step} value={f[name] as number??''}
  onChange={e=>set({[name]:Number(e.target.value)} as Partial<FuturesConfig>)}/></label>
 );
 const optional=(name:'stop_loss_percent'|'take_profit_percent',label:string)=>(
  <label>{label}<input type="number" min="0.01" step="0.1" placeholder="disabled"
  value={f[name]??''} onChange={e=>set({[name]:e.target.value===''?null:Number(e.target.value)})}/></label>
 );
 return <section className="card"><h2>BTCUSD perpetual futures research</h2>
 <p>CALL rules become LONG, PUT rules become SHORT. Entries and condition exits are placed at the following candle open. Only one position at a time. No option contracts are required.</p>
 <div className="form-grid">
  <label>Direction<select value={value.direction_mode} onChange={e=>onChange({...value,direction_mode:e.target.value as Strategy['direction_mode']})}><option value="BOTH">LONG + SHORT</option><option value="CALL">LONG only</option><option value="PUT">SHORT only</option></select></label>
  {number('quantity_lots','Quantity (lots of 0.001 BTC)','1',1)}
  {number('leverage','Assumed leverage ×','1',1)}
  <label>Margin mode<select value={f.margin_mode} onChange={e=>set({margin_mode:e.target.value as FuturesConfig['margin_mode']})}><option value="ISOLATED">Isolated (research estimate)</option><option value="CROSS">Cross (research estimate)</option></select></label>
  {number('maintenance_margin_percent','Assumed maintenance margin %','0.05',0.01)}
  {number('taker_fee_percent','Taker fee % per side','0.001',0)}
  {number('gst_percent','GST % on fees','1',0)}
  {number('slippage_bps','Adverse slippage basis points','1',0)}
  {optional('stop_loss_percent','Price-based stop-loss %')}
  {optional('take_profit_percent','Price-based take-profit %')}
  <label>Funding history<select value={f.funding_mode} onChange={e=>set({funding_mode:e.target.value as FuturesConfig['funding_mode']})}><option value="REQUIRE_CSV">Require historical funding CSV</option><option value="EXCLUDE_WITH_WARNING">Exclude funding (research only)</option></select></label>
 </div>
 <div className="warning-box"><b>Accuracy limitations:</b> Futures fills use historical 5m-derived OHLC and assumed slippage, not recorded futures order-book quotes. Funding requires <code>futures_funding.csv</code> with timestamp, symbol and decimal funding_rate. Collateral and liquidation are approximations; no Delta exchange liquidation precision is claimed. Backtests never place orders.</div>
 </section>
}
