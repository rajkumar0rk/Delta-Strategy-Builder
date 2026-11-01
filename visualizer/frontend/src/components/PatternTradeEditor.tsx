import type {PatternTradeConfig,RuleGroup,Strategy} from '../types';
import {RuleBuilder} from './RuleBuilder';

const empty=():RuleGroup=>({mode:'ALL',min_pass:1,conditions:[],groups:[]});
const defaultPattern:PatternTradeConfig={enabled:false,confirmation_bars:6,
 pullback_patterns:['HAMMER','BULL_ENGULFING','MORNING_STAR','SHOOTING_STAR','BEAR_ENGULFING','EVENING_STAR'],
 breakout_patterns:['BULL_MARUBOZU','BEAR_MARUBOZU','BULL_ENGULFING','BEAR_ENGULFING'],
 call_pullback:empty(),call_breakout:empty(),put_pullback:empty(),put_breakout:empty(),
 min_body_range_ratio:.6,volume_lookback_bars:20,min_volume_ratio:1.25,
 breakout_buffer_points:0,stop_buffer_points:0,max_risk_usd:10,
 option_delta_assumption:null,target_1_r:2,target_2_r:3,first_exit_fraction:.5};
export function PatternTradeEditor({strategy,operands,onChange}:{strategy:Strategy;operands:string[];onChange:(s:Strategy)=>void}){
 const c=strategy.pattern_trade||defaultPattern;
 const set=(patch:Partial<PatternTradeConfig>)=>onChange({...strategy,pattern_trade:{...c,...patch}});
 const numeric=(field:keyof PatternTradeConfig,title:string,step:number)=>(
  <label key={field}>{title}<input type="number" step={step} min={0}
    value={c[field]===null?'':String(c[field])}
    onChange={e=>set({[field]:e.target.value===''?null:Number(e.target.value)} as Partial<PatternTradeConfig>)}/></label>
 );
 return <section className="card">
 <h2>15m pattern event trading · BUY options (research)</h2>
 <p>Optional separate setup/entry mode. Every completed 15m pattern stores its own high/low and expires after exactly six subsequent completed 5m candles. A breakout requires strong 5m close and volume confirmation. Keep 1H directional conditions in the ordinary CALL/PUT entry rules and 30m setup indicators below. No extra data download.</p>
 <label className="switch"><input type="checkbox" checked={c.enabled} onChange={e=>set({enabled:e.target.checked})}/><span>Enable exact pattern event mode</span></label>
 <div className="form-grid">
  {numeric('confirmation_bars','Confirmation window (completed 5m candles)',1)}
  {numeric('max_risk_usd','Maximum estimated loss per trade (USD)',.5)}
  {numeric('option_delta_assumption','Absolute option delta assumption (required)',.05)}
  {numeric('min_body_range_ratio','Minimum 5m candle body/range',.05)}
  {numeric('min_volume_ratio','Minimum 5m relative volume',.1)}
  {numeric('volume_lookback_bars','Volume lookback 5m candles',1)}
  {numeric('breakout_buffer_points','Pattern breakout buffer (BTC points)',1)}
  {numeric('stop_buffer_points','Pattern stop buffer (BTC points)',1)}
  {numeric('target_1_r','First target R',.25)}
  {numeric('target_2_r','Final target R',.25)}
  {numeric('first_exit_fraction','Fraction to exit at first target',.05)}
 </div>
 <div className="form-grid">
  {(['pullback_patterns','breakout_patterns'] as const).map(k=><fieldset key={k}><legend>{k.replace('_',' ')}</legend>
   {['HAMMER','SHOOTING_STAR','BULL_ENGULFING','BEAR_ENGULFING','MORNING_STAR','EVENING_STAR','BULL_MARUBOZU','BEAR_MARUBOZU'].map(name=>
    <label key={name}><input type="checkbox" checked={c[k].includes(name)}
      onChange={e=>set({[k]:e.target.checked?[...c[k],name]:c[k].filter(x=>x!==name)} as Partial<PatternTradeConfig>)}/>{name}</label>)}
  </fieldset>)}
 </div>
 <p>Confirmed 5m closes are used for BTC targets; actual option exits require a fresh executable quote. In ambiguous intrabar candles, protective stops take precedence. Delta-based option risk remains an estimate, not an option premium guarantee.</p>
 {(['call_pullback','call_breakout','put_pullback','put_breakout'] as const).map(k=>
  <RuleBuilder key={k} title={k.replace('_',' ').toUpperCase()+' · 30m setup'}
   value={c[k]} operands={operands} onChange={v=>set({[k]:v})}
   description="Use closed 30m indicators; these rules must be configured before enabling pattern mode."/>
 )}
 </section>
}