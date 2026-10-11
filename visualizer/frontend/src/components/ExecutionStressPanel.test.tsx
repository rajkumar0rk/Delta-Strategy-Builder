import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ExecutionStressPanel } from './ExecutionStressPanel';
import type { ExecutionStressReport } from '../types';

const sampleReport: ExecutionStressReport = {
  kind: 'ADVERSE_OPTION_PREMIUM_FILL_STRESS',
  mode: 'POST_TRADE_SENSITIVITY_ONLY',
  data_fidelity: 'LOW_FIDELITY_SYNTHETIC_BBO',
  research_only: true,
  note: 'Research-only adverse premium estimate; not a fill simulator.',
  all_trades: 3,
  eligible_trades: 2,
  excluded_trades: 1,
  excluded_reasons: { MISSING_OR_INVALID_TRADE_FIELDS: 1 },
  coverage_percent: 66.67,
  all_trades_original_net_pnl_usd: 11,
  eligible_baseline_net_pnl_usd: 10,
  fee_model: {},
  scenarios: [
    {
      adverse_premium_percent_per_side: 0,
      trades: 2,
      wins: 1,
      win_rate_percent: 50,
      net_pnl_usd: 10,
      extra_execution_cost_usd: 0,
      profit_factor: 2.5,
      profitable_months: 1,
      months: 2,
    },
    {
      adverse_premium_percent_per_side: 2,
      trades: 2,
      wins: 0,
      win_rate_percent: 0,
      net_pnl_usd: -2.5,
      extra_execution_cost_usd: 12.5,
      profit_factor: 0,
      profitable_months: 0,
      months: 2,
    },
  ],
};

const render = (report?: ExecutionStressReport) =>
  renderToStaticMarkup(<ExecutionStressPanel report={report} />);

describe('V16 execution stress panel', () => {
  it('renders nothing when the saved analysis has no execution stress report', () => {
    expect(render()).toBe('');
  });

  it('renders baseline and adverse scenarios without changing the saved trade results', () => {
    const html = render(sampleReport);
    expect(html).toContain('V16 execution-cost sensitivity');
    expect(html).toContain('0%');
    expect(html).toContain('2%');
    expect(html).toContain('$10.00');
    expect(html).toContain('$-2.50');
    expect(html).toContain('$12.50');
    expect(html).toContain('50%');
  });

  it('labels historical fidelity, excluded trades and the research-only limitation', () => {
    const html = render(sampleReport);
    expect(html).toContain('LOW_FIDELITY_SYNTHETIC_BBO');
    expect(html).toContain('2/3 eligible trades');
    expect(html).toContain('1 excluded trades');
    expect(html).toContain('Research only');
    expect(html).toContain('not a fill simulator');
  });

  it('renders unknown win-rate and profit-factor values without inventing zeros', () => {
    const report: ExecutionStressReport = {
      ...sampleReport,
      eligible_trades: 0,
      excluded_trades: 3,
      scenarios: [{
        ...sampleReport.scenarios[0],
        trades: 0,
        wins: 0,
        win_rate_percent: null,
        profit_factor: null,
        months: 0,
        profitable_months: 0,
      }],
    };
    const html = render(report);
    expect(html).toContain('0/3 eligible trades');
    expect(html).toContain('—');
  });
});
