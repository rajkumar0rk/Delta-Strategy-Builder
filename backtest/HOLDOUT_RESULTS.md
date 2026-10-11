# Momentum Filter Holdout Result

Generated on 2026-09-23.

## Test design

- Development period: 2026-08-24 through 2026-09-23.
- Untouched reverse-chronological holdout: 2026-07-25 through 2026-08-24.
- Starting capital: USD 1,000.
- Delta public history: 8,790 BTC bars, 680 option instruments, and 2,511,569 estimated quotes.
- Baseline: existing strategy RSI windows.
- Frozen candidate: CALL RSI 60-70 and PUT RSI 40-45.
- `SAME_QUOTE` is the optimistic boundary; `NEXT_QUOTE` is the pessimistic one-minute boundary.

## Holdout result

| Strategy | Fill mode | Closed | Open | Win rate | Account P&L | Return | Profit factor | Expectancy | Max closed DD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | SAME_QUOTE | 101 | 0 | 28.71% | $101.40 | 10.14% | 1.315 | $1.003 | 5.06% |
| Momentum | SAME_QUOTE | 94 | 1 | 34.04% | $146.34 | 14.63% | 1.717 | $2.077 | 4.73% |
| Baseline | NEXT_QUOTE | 89 | 0 | 23.60% | -$60.48 | -6.05% | 0.822 | -$0.679 | 9.64% |
| Momentum | NEXT_QUOTE | 92 | 1 | 39.13% | $144.15 | 14.42% | 1.653 | $2.099 | 5.34% |

The momentum candidate improved P&L, win rate, profit factor, expectancy, and drawdown under both fill assumptions. The momentum runs ended with one open PUT; account P&L includes its approximately $49 negative end-of-period mark, while closed-trade statistics exclude it.

## Decision

Keep CALL RSI 60-70 and PUT RSI 40-45 as the leading candidate. Do not change the live defaults yet. This is a reverse-chronological holdout using synthetic bid/ask prices, not a true forward test with recorded order-book data. Confirm the candidate on future R2 `RECORDED_BBO` sessions before enabling it for live orders.

Latest reports:

- `reports/holdout/baseline-same/20260923T132720899175Z`
- `reports/holdout/baseline-next/20260923T133047791874Z`
- `reports/holdout/momentum-same/20260923T133159694130Z`
- `reports/holdout/momentum-next/20260923T133354503598Z`

## USD 100 expiry and neutral-regime research

Generated on 2026-09-26 with `CROSSOVER`, `NEXT_QUOTE`, zero configured fees,
and otherwise unchanged USD 100 risk settings. Both periods use Delta public
history with estimated one-minute option bid/ask quotes (`LOW_FIDELITY`).

| Period | Variant | Trades | Win rate | Account P&L | Profit factor | Expectancy | Max closed DD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-08-24 to 2026-09-23 | Baseline, minimum DTE 1 | 111 | 39.64% | -$8.36 | 0.817 | -$0.076 | 12.53% |
| 2026-08-24 to 2026-09-23 | Minimum DTE 2 | 7 | 42.86% | $1.78 | 1.989 | $0.251 | 1.50% |
| 2026-08-24 to 2026-09-23 | Neutral filter, DTE 1 | 110 | 39.09% | -$7.81 | 0.840 | -$0.071 | 13.35% |
| 2026-07-25 to 2026-08-24 | Baseline, minimum DTE 1 | 118 | 46.61% | -$1.73 | 0.969 | -$0.014 | 13.19% |
| 2026-07-25 to 2026-08-24 | Minimum DTE 2 | 10 | 50.00% | $0.98 | 1.678 | $0.097 | 0.86% |
| 2026-07-25 to 2026-08-24 | Neutral filter, DTE 1 | 118 | 47.46% | $1.32 | 1.028 | $0.012 | 13.00% |

Minimum DTE 2 is positive in both periods, but 17 total trades are not enough
to approve it. Minimum DTE 3 produced no executable trades in the downloaded
three-day universe and is not a viable conclusion. The neutral filter improved
the holdout and slightly reduced the development loss, but the development
period remained materially negative. Keep both live controls at their defaults
until `RECORDED_BBO` validation provides more evidence:

```ini
BTC_STRATEGY_MIN_DAYS_TO_EXPIRY=1
BTC_STRATEGY_NEUTRAL_FILTER_ENABLED=false
```

Latest research reports:

- `reports/delta-2026-08-24_09-23-usd100/20260926T133057832908Z`
- `reports/experiments/usd100-dte2-next/20260926T131438007177Z`
- `reports/experiments/usd100-neutral-filter-next/20260926T132654337689Z`
- `reports/holdout/usd100-baseline-next/20260925T151650891016Z`
- `reports/holdout/usd100-dte2-next/20260926T131704868158Z`
- `reports/holdout/usd100-neutral-filter-next/20260926T132802489092Z`

## Regime Filter V2 observation

Generated on 2026-09-27. This fixed candidate required at least three of four
conditions at the original entry decision time: Choppiness below 61.8, ADX at
least 20, EMA separation at least 0.05%, and Bollinger bandwidth at least
0.50%. Only candles which had closed before the decision were used.

| Period | Attributed group | Trades | Win rate | Gross closed P&L | Profit factor | Expectancy |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2026-08-24 to 2026-09-23 | V2 trending | 11 | 63.64% | $6.51 | 4.176 | $0.592 |
| 2026-08-24 to 2026-09-23 | V2 neutral | 100 | 37.00% | -$14.92 | 0.661 | -$0.149 |
| 2026-07-25 to 2026-08-24 | V2 trending | 14 | 50.00% | -$1.57 | 0.803 | -$0.112 |
| 2026-07-25 to 2026-08-24 | V2 neutral | 104 | 46.15% | -$0.07 | 0.998 | -$0.001 |

The development result was strong, but the untouched holdout failed. V2 must
remain observation-only. These numbers are post-run attribution rather than a
strategy rerun, so they cannot be treated as deployable performance even if
both periods had passed.

Report:

- `reports/regime-v2-research/regime_summary.json`
- `reports/regime-v2-research/regime_trades.csv`

### V2 entry-gate counterfactual

The V2 classifier was then wired into the real signal-creation and entry
preflight paths and both periods were rerun. This changes trade sequencing,
cooldowns, and session risk state, so its results differ from post-run
attribution.

| Period | Trades | Win rate | Account P&L | Profit factor | Expectancy | Max closed DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-08-24 to 2026-09-23 | 50 | 54.00% | $1.28 | 1.053 | $0.027 | 4.99% |
| 2026-07-25 to 2026-08-24 | 30 | 36.67% | -$14.13 | 0.406 | -$0.471 | 14.31% |

The entry gate improved the development month but failed the untouched month
more severely than the unfiltered baseline. Keep it disabled for Analyzer and
live orders. The implementation remains selectable for further offline
research with:

```ini
BTC_STRATEGY_NEUTRAL_FILTER_ENABLED=true
BTC_STRATEGY_REGIME_FILTER_MODE=V2
```

Reports:

- `reports/experiments/usd100-v2-filter-next/20260927T060526500127Z`
- `reports/holdout/usd100-v2-filter-next/20260927T061140902585Z`

## Zero-spread CE/PE mark-price benchmark

Generated on 2026-09-27. These runs retain the original BTC signals, selected
CE/PE contracts, one-minute `NEXT_QUOTE` delay, volume, OI, sizing, exits, and
session limits. Bid and ask are replaced with their midpoint to remove spread.
This tests mark-price signal behavior and is not executable P&L.

| Period | Price mode | Trades | Win rate | Account P&L | Profit factor | Expectancy | Max closed DD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-08-24 to 2026-09-23 | Estimated BBO | 111 | 39.64% | -$8.36 | 0.817 | -$0.076 | 12.53% |
| 2026-08-24 to 2026-09-23 | Zero-spread midpoint | 116 | 45.69% | -$1.36 | 0.969 | -$0.012 | 9.14% |
| 2026-07-25 to 2026-08-24 | Estimated BBO | 118 | 46.61% | -$1.73 | 0.969 | -$0.014 | 13.19% |
| 2026-07-25 to 2026-08-24 | Zero-spread midpoint | 121 | 50.41% | $8.22 | 1.183 | $0.068 | 9.33% |

Removing spread materially improved both periods, demonstrating that execution
cost is important. It did not make both periods profitable: the development
month remained slightly negative before fees. The different trade counts are
expected because midpoint prices also change stop, target, trailing, and daily
risk-halt timing. The evidence therefore shows a variable raw directional edge
plus a meaningful spread penalty, not a consistently profitable strategy hidden
only by bid/ask.

Reports:

- `reports/experiments/usd100-midpoint-next/20260927T053750733498Z`
- `reports/holdout/usd100-midpoint-next/20260927T054324074943Z`
