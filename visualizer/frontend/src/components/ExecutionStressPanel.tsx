import type {ExecutionStressReport} from '../types';

const usd=(v:number)=>Number.isFinite(v)?'$'+v.toFixed(2):'—';
export function ExecutionStressPanel({report}:{report?:ExecutionStressReport}){
 if(!report)return null;
 return <section className="execution-stress">
   <h3>V16 execution-cost sensitivity</h3>
   <p>Research only · {report.data_fidelity} · {report.eligible_trades}/{report.all_trades} eligible trades.
      Extra adverse option premium applied at entry and exit; original fills/signals unchanged.</p>
   <div className="table-wrap"><table>
    <thead><tr><th>Adverse / side</th><th>Net P&amp;L</th><th>Extra cost</th><th>Win rate</th><th>Profit factor</th><th>Profitable months</th></tr></thead>
    <tbody>{report.scenarios.map(s=><tr key={s.adverse_premium_percent_per_side}>
     <td>{s.adverse_premium_percent_per_side}%</td><td>{usd(s.net_pnl_usd)}</td>
     <td>{usd(s.extra_execution_cost_usd)}</td>
     <td>{s.win_rate_percent==null?'—':s.win_rate_percent+'%'}</td>
     <td>{s.profit_factor==null?'—':s.profit_factor}</td>
     <td>{s.profitable_months}/{s.months}</td>
    </tr>)}</tbody></table></div>
   <small>{report.note} {report.excluded_trades} excluded trades.</small>
 </section>;
}
