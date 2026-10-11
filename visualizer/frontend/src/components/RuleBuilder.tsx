import type {Condition,RuleGroup} from '../types';

const operators=[
 'GT','GTE','LT','LTE','EQ','GT_BY_POINTS','LT_BY_POINTS','GT_BY_PERCENT','LT_BY_PERCENT','BETWEEN',
 'CROSSES_ABOVE','CROSSES_BELOW','RISING','FALLING',
 'WAS_GT','WAS_GTE','WAS_LT','WAS_LTE','WAS_BETWEEN','CROSSED_ABOVE_WITHIN','CROSSED_BELOW_WITHIN',
 'COUNT_TRUE_GTE','COUNT_CROSS_ABOVE_GTE','COUNT_CROSS_BELOW_GTE','COUNT_CROSS_EITHER_GTE',
 'SLOPE_GT','SLOPE_GTE','SLOPE_LT','SLOPE_LTE'
];
const opLabel:Record<string,string>={
 GT:'>',GTE:'≥',LT:'<',LTE:'≤',EQ:'=',GT_BY_POINTS:'> by points',LT_BY_POINTS:'< by points',GT_BY_PERCENT:'> by %',LT_BY_PERCENT:'< by %',BETWEEN:'between',
 CROSSES_ABOVE:'crosses above',CROSSES_BELOW:'crosses below',RISING:'rising',FALLING:'falling',
 WAS_GT:'was > within',WAS_GTE:'was ≥ within',WAS_LT:'was < within',WAS_LTE:'was ≤ within',WAS_BETWEEN:'was between within',
 CROSSED_ABOVE_WITHIN:'crossed above within',CROSSED_BELOW_WITHIN:'crossed below within',
 COUNT_TRUE_GTE:'true count ≥',COUNT_CROSS_ABOVE_GTE:'cross-above count ≥',COUNT_CROSS_BELOW_GTE:'cross-below count ≥',COUNT_CROSS_EITHER_GTE:'cross count ≥',
 SLOPE_GT:'slope >',SLOPE_GTE:'slope ≥',SLOPE_LT:'slope <',SLOPE_LTE:'slope ≤'
};
const uid=()=>`c-${Date.now()}-${Math.random().toString(36).slice(2,8)}`;
const emptyGroup=():RuleGroup=>({mode:'ALL',min_pass:1,conditions:[],groups:[]});
const isMargin=(op:string)=>['GT_BY_POINTS','LT_BY_POINTS','GT_BY_PERCENT','LT_BY_PERCENT'].includes(op);
const noRhs=(op:string)=>['RISING','FALLING','COUNT_TRUE_GTE','SLOPE_GT','SLOPE_GTE','SLOPE_LT','SLOPE_LTE'].includes(op);
const isLookback=(op:string)=>['WAS_GT','WAS_GTE','WAS_LT','WAS_LTE','WAS_BETWEEN','CROSSED_ABOVE_WITHIN','CROSSED_BELOW_WITHIN','COUNT_TRUE_GTE','COUNT_CROSS_ABOVE_GTE','COUNT_CROSS_BELOW_GTE','COUNT_CROSS_EITHER_GTE','SLOPE_GT','SLOPE_GTE','SLOPE_LT','SLOPE_LTE'].includes(op);
const isBetween=(op:string)=>['BETWEEN','WAS_BETWEEN'].includes(op);
const isCount=(op:string)=>op.startsWith('COUNT_');
const isCrossCount=(op:string)=>['COUNT_CROSS_ABOVE_GTE','COUNT_CROSS_BELOW_GTE','COUNT_CROSS_EITHER_GTE'].includes(op);
const isSlope=(op:string)=>op.startsWith('SLOPE_');

function move<T>(items:T[],index:number,delta:number){const next=[...items];const to=index+delta;if(to<0||to>=next.length)return items;[next[index],next[to]]=[next[to],next[index]];return next}

function GroupEditor({value,operands,onChange,depth=0,onRemove}:{value:RuleGroup;operands:string[];onChange:(g:RuleGroup)=>void;depth?:number;onRemove?:()=>void}){
 const patch=(i:number,p:Partial<Condition>)=>onChange({...value,conditions:value.conditions.map((c,n)=>n===i?{...c,...p}:c)});
 const add=()=>onChange({...value,conditions:[...value.conditions,{id:uid(),left:'close',operator:'GT',right:null,value:0,left_offset:0,right_offset:0,lookback_bars:5}]});
 const addGroup=()=>onChange({...value,groups:[...value.groups,emptyGroup()]});
 const boxClass=depth===0?'rule-group-root':'rule-subgroup';
 return <div className={boxClass}>
  <div className="rule-group-head">
   <div className="inline"><span className="group-label">{depth===0?'ROOT':`GROUP ${depth}`}</span><select value={value.mode} onChange={e=>onChange({...value,mode:e.target.value as RuleGroup['mode']})}><option>ALL</option><option>ANY</option><option>AT_LEAST</option></select>{value.mode==='AT_LEAST'&&<input className="small" type="number" min="1" value={value.min_pass} onChange={e=>onChange({...value,min_pass:Number(e.target.value)})}/>}</div>
   <div className="inline"><button onClick={add}>+ Condition</button>{depth<3&&<button onClick={addGroup}>+ Nested group</button>}{onRemove&&<button className="danger ghost" onClick={onRemove}>Remove group</button>}</div>
  </div>
  <div className="rule-list">{value.conditions.map((c,i)=><div className="rule-row" key={c.id||i}>
   <div className="move-buttons"><button className="mini ghost" disabled={i===0} onClick={()=>onChange({...value,conditions:move(value.conditions,i,-1)})}>↑</button><button className="mini ghost" disabled={i===value.conditions.length-1} onClick={()=>onChange({...value,conditions:move(value.conditions,i,1)})}>↓</button></div>
   <span className="condition-id" title="Use this condition as an entry activation trigger or Big Trend Score component">#{c.id||'condition'}</span>
   <select value={c.left} onChange={e=>patch(i,{left:e.target.value})}>{operands.map(o=><option key={o}>{o}</option>)}</select>
   <select value={c.operator} onChange={e=>{const op=e.target.value;if(isBetween(op))patch(i,{operator:op,right:null,value:c.value??0,value2:c.value2??1,lookback_bars:c.lookback_bars??5});else if(isCrossCount(op))patch(i,{operator:op,right:c.right||operands[0],value:c.value??1,value2:null,lookback_bars:c.lookback_bars??10});else if(isCount(op))patch(i,{operator:op,right:null,value:c.value??1,value2:null,lookback_bars:c.lookback_bars??10});else if(isSlope(op))patch(i,{operator:op,right:null,value:c.value??0,value2:null,lookback_bars:c.lookback_bars??5});else if(noRhs(op))patch(i,{operator:op,right:null,value:null,value2:null});else if(isMargin(op))patch(i,{operator:op,right:c.right||operands[0],value:c.value??0,value2:null});else patch(i,{operator:op,lookback_bars:c.lookback_bars??5})}}>{operators.map(o=><option key={o} value={o}>{opLabel[o]||o}</option>)}</select>
   {isCount(c.operator)?<>{isCrossCount(c.operator)&&<select value={c.right||operands[0]} onChange={e=>patch(i,{right:e.target.value})}>{operands.map(o=><option key={o}>{o}</option>)}</select>}<label className="margin-input"><span>min count</span><input type="number" min="0" step="1" value={c.value??1} onChange={e=>patch(i,{value:Number(e.target.value)})}/></label></>:isSlope(c.operator)?<label className="margin-input"><span>slope pts/bar</span><input type="number" step="any" value={c.value??0} onChange={e=>patch(i,{value:Number(e.target.value)})}/></label>:isMargin(c.operator)?<><select value={c.right||operands[0]} onChange={e=>patch(i,{right:e.target.value})}>{operands.map(o=><option key={o}>{o}</option>)}</select><label className="margin-input"><span>{c.operator.endsWith('PERCENT')?'margin %':'margin pts'}</span><input type="number" min="0" step="any" value={c.value??0} onChange={e=>patch(i,{value:Number(e.target.value)})}/></label></>:!noRhs(c.operator)&&<><select value={c.right?'operand':'value'} onChange={e=>patch(i,e.target.value==='operand'?{right:operands[0],value:null}:{right:null,value:0})}><option value="operand">indicator / price</option><option value="value">number</option></select>{c.right?<select value={c.right} onChange={e=>patch(i,{right:e.target.value})}>{operands.map(o=><option key={o}>{o}</option>)}</select>:<input type="number" step="any" value={c.value??0} onChange={e=>patch(i,{value:Number(e.target.value)})}/>} {isBetween(c.operator)&&<input type="number" step="any" value={c.value2??0} onChange={e=>patch(i,{value2:Number(e.target.value)})}/>}</>}
   {isLookback(c.operator)&&<label className="offset-input lookback-input" title={isSlope(c.operator)?'Slope compares current value with the value N completed bars ago.':'Window length in completed candles.'}><span>{isSlope(c.operator)?'slope bars':'last N bars'}</span><input type="number" min="1" max="1000" value={c.lookback_bars??5} onChange={e=>patch(i,{lookback_bars:Number(e.target.value)})}/></label>}
   <label className="offset-input"><span>L offset</span><input type="number" min="0" max="100" value={c.left_offset??0} onChange={e=>patch(i,{left_offset:Number(e.target.value)})}/></label>
   {c.right&&<label className="offset-input"><span>R offset</span><input type="number" min="0" max="100" value={c.right_offset??0} onChange={e=>patch(i,{right_offset:Number(e.target.value)})}/></label>}
   <button className="danger ghost" onClick={()=>onChange({...value,conditions:value.conditions.filter((_,n)=>n!==i)})}>×</button>
  </div>)}</div>
  {value.groups.map((g,i)=><GroupEditor key={`g-${depth}-${i}`} value={g} operands={operands} depth={depth+1} onChange={next=>onChange({...value,groups:value.groups.map((x,n)=>n===i?next:x)})} onRemove={()=>onChange({...value,groups:value.groups.filter((_,n)=>n!==i)})}/>) }
 </div>
}

export function RuleBuilder({title,value,operands,onChange,description}:{title:string;value:RuleGroup;operands:string[];onChange:(g:RuleGroup)=>void;description?:string}){
 return <section className="card"><div className="card-head"><div><h2>{title}</h2><p>{description||'Conditions use completed candles only. V14 supports nested AND/OR, recent-history checks, cross counts, bullish/bearish candle counts and multi-bar slopes.'}</p></div></div><GroupEditor value={value} operands={operands} onChange={onChange}/></section>
}
