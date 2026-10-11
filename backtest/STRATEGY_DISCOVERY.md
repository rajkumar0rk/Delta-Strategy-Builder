# Strategy discovery log

Generated on 2026-09-27. This document records hypotheses before option-level
implementation so rejected ideas are not quietly retuned against the same
history.

## Baseline diagnosis

The existing EMA/RSI strategy was evaluated on two adjacent 30-day periods
using Delta public option history and conservative next-quote execution.

| Period | Trades | Account P&L | Direction correct | Option win rate when direction correct |
| --- | ---: | ---: | ---: | ---: |
| 2026-08-24 to 2026-09-23 | 111 | -$8.36 | 34.2% | 89.5% |
| 2026-07-25 to 2026-08-24 | 118 | -$1.73 | 46.6% | 94.5% |

The primary failure is signal direction. When BTC moved in the signaled
direction between entry and exit, the option trade usually won. Contract and
exit improvements may still help, but they cannot repair a directional signal
which is wrong more often than right.

## Rejected hypothesis 1: five-minute trend expansion

Frozen rules:

- Completed five-minute candles only.
- Close breaks the preceding 12-candle high or low.
- Breakout true range is at least ATR(14).
- Volume is at least the preceding 20-candle median.
- Close is in the directional outer 25% of the candle.
- Completed one-hour close and EMA(20)/EMA(50) trend agree with direction.
- One-hour EMA(20) slope over three bars agrees with direction.
- Twelve-candle signal cooldown.

At a 60-minute horizon, directional accuracy was 34.4% in development and
48.7% in the comparison period. Rejected before option simulation.

## Rejected hypothesis 2: five-minute compression breakout

Frozen rules:

- Recent Bollinger bandwidth is in the lowest 20% of its prior daily window.
- Close breaks the preceding 20-candle high or low.
- Breakout true range is at least 1.2 times ATR(14).
- Volume is at least the preceding 20-candle median.
- Close is in the directional outer 25% of the candle.
- Twelve-candle signal cooldown.

At a 60-minute horizon, directional accuracy was 36.1% in development and
38.2% in the comparison period. Rejected before option simulation.

## Rejected hypothesis 3: fifteen-minute trend breakout

Frozen rules:

- Completed fifteen-minute candles only.
- Close breaks the preceding eight-candle high or low.
- EMA(20)/EMA(50) and the four-bar EMA(20) slope agree with direction.
- Breakout true range is at least ATR(14).
- Volume is at least the preceding 20-candle median.
- Close is in the directional outer 25% of the candle.
- Four-candle signal cooldown.

At a 60-minute horizon, directional accuracy was 38.0% in development and
46.7% in the comparison period. Rejected before option simulation.

## Rejected hypothesis 4: neutral exhaustion reversal

Frozen rules:

- One-hour EMA(20)/EMA(50) separation is at most 0.20%.
- Absolute three-hour EMA(20) slope is at most 0.15%.
- The previous five-minute candle closes beyond a 20-period, two-standard-
  deviation Bollinger band with RSI(14) below 30 or above 70.
- The next completed candle re-enters the band and confirms the reversal.
- Six-candle signal cooldown.

Fifteen-minute directional accuracy was 56.2% in development and 55.0% in the
comparison period, but average signed BTC returns were -0.0183% and +0.0152%.
The move is too small and inconsistent to justify paying option spread.

## Decision

None of the four frozen hypotheses qualifies for option-level backtesting. Do
do not add them to the maintained strategy and do not tune their thresholds against these
same periods.

## Twelve-month validation

After the rules above were frozen, 49,601 BTC five-minute bars were downloaded
for 2025-09-27 through 2026-09-27. The data was divided chronologically into an
eight-month discovery segment, a two-month validation segment, and a final
two-month holdout. Values below are average signed BTC returns at each
hypothesis's fixed evaluation horizon.

| Hypothesis | Horizon | Discovery | Validation | Final holdout |
| --- | ---: | ---: | ---: | ---: |
| Five-minute trend expansion | 60m | -0.0230% | -0.0416% | +0.0778% |
| Five-minute compression breakout | 60m | +0.0188% | -0.0181% | -0.0462% |
| Fifteen-minute trend breakout | 60m | +0.0143% | -0.0180% | +0.0652% |
| Neutral exhaustion reversal | 15m | -0.1135% | -0.0303% | +0.0114% |

None is consistently positive across all three chronological segments.

One additional slow hypothesis was frozen after this result: a completed
one-hour close beyond the preceding 24-hour high or low, aligned with one-hour
EMA(20)/EMA(50), EMA slope, ATR, volume, and candle-close location. It produced
an average eight-hour signed return of -0.3075% across 50 discovery signals,
-0.0028% across 12 validation signals, and +0.5947% across 13 final-holdout
signals. The attractive recent result is a regime-specific reversal of the
longer history, not evidence of a stable edge, so this hypothesis is also
rejected before option simulation.

The next discovery dataset should contain at least twelve months of BTC
underlying candles spanning rising, falling, volatile, and quiet conditions.
Candidate selection should use chronological development and validation
segments. Option history and recorded BBO are introduced only after an
underlying signal demonstrates stable directional magnitude out of sample.

The reproducible underlying-only download configuration is
`config.delta.discovery.2025-09-27_2026-09-27.toml`. It intentionally excludes
the much larger option-product and option-candle sync stage.

## Pre-registered second discovery pass

The following hypotheses add time-of-day or abnormal-volume information rather
than another transformation of the same closing prices. Their rules were fixed
before examining the twelve-month results.

### Abnormal-volume impulse continuation

- Completed five-minute candles only.
- True range is at least 1.5 times ATR(14).
- Volume is at least twice the median for the same five-minute UTC slot over
  the preceding 20 occurrences.
- Candle body is at least 60% of its range.
- Close is in the directional outer 20% of the candle.
- Enter in the candle direction with a six-candle signal cooldown.
- Evaluate signed BTC movement after 15, 30, and 60 minutes.

### Failed-impulse reversal

- The preceding candle satisfies the abnormal-volume impulse rules.
- The next completed candle closes through the impulse candle midpoint in the
  opposite direction.
- Enter opposite the original impulse with a six-candle signal cooldown.
- Evaluate signed BTC movement after 15, 30, and 60 minutes.

### Session opening-range breakout

- Construct a 30-minute opening range using completed candles.
- Test New York 09:30-10:00 local time and London 08:00-08:30 local time as
  separate hypotheses with daylight-saving-aware time zones.
- Take only the first close outside the range during the following two hours.
- Breakout candle closes in the directional outer 25% of its range.
- At most one signal per local session and date.
- Evaluate signed BTC movement after 30, 60, and 120 minutes.

## Second discovery pass results

The second pass was run over the same chronological eight-month discovery,
two-month validation, and two-month final-holdout segments. The values below
are average signed BTC returns at the listed horizon.

| Hypothesis | Horizon | Discovery | Validation | Final holdout |
| --- | ---: | ---: | ---: | ---: |
| Abnormal-volume impulse continuation | 60m | -0.0481% | -0.0487% | -0.0215% |
| Failed-impulse reversal | 30m | +0.0075% | -0.0757% | +0.0408% |
| New York opening-range breakout | 60m | -0.0635% | -0.0507% | +0.1004% |
| London opening-range breakout | 60m | +0.0059% | +0.0592% | +0.1202% |

The London result is not accepted: its discovery average is effectively zero
and its discovery median is negative. The other three hypotheses change sign
or are consistently negative. All four are rejected before option simulation.

Further searches using only five-minute OHLCV would now be threshold mining.
The next pass therefore uses independent market-state inputs: Delta BTC open
interest and funding history.

The initial year-long download used 30-day requests which Delta silently
truncated. It contained only 49,601 of the expected candles and eleven hidden
16-day gaps, so the twelve-month OHLCV results above are provisional and must
be rerun. The downloader now uses five-day requests and rejects missing long-
range coverage. The corrected BTC and OI files each contain 105,270 continuous
five-minute bars including warm-up. Delta's funding archive begins on 2025-10-12;
its separate reproducible configuration begins on 2025-10-13 after warm-up.

## Pre-registered market-context pass

These rules are frozen before inspecting OI and funding results. Rolling
standardization uses only observations available before each signal.

### Rising-OI momentum confirmation

- Start with a completed one-hour BTC candle.
- The one-hour return is in the top or bottom 10% of the preceding 30 days.
- Open interest changes in the same direction as price participation: its
  one-hour percentage change has a rolling 30-day z-score of at least +1.
- Enter in the direction of the BTC move.
- Evaluate signed BTC movement after 1, 4, and 8 hours.

### Falling-OI liquidation continuation

- Start with the same extreme completed one-hour BTC return.
- Open-interest percentage change has a rolling 30-day z-score at most -1.
- Enter in the direction of the BTC move, treating the event as forced-position
  liquidation rather than new-position confirmation.
- Evaluate signed BTC movement after 1, 4, and 8 hours.

### Falling-OI exhaustion reversal

- Use exactly the same events as falling-OI liquidation continuation.
- Enter opposite the completed one-hour BTC move.
- Evaluate signed BTC movement after 1, 4, and 8 hours.

### Extreme-funding mean reversion

- Use completed funding observations only.
- Funding has a rolling 90-day z-score of at least +2 or at most -2.
- Positive extremes signal bearish; negative extremes signal bullish.
- Allow only one signal until funding leaves the extreme region.
- Evaluate signed BTC movement after 4, 8, and 24 hours.

## Market-context pass results

The complete source contained 105,270 BTC bars, 105,270 OI bars, and 100,167
funding bars representing 431 funding-rate changes. The fixed chronological
segments and shifted rolling windows were applied by
`market_context_discovery.py`.

| Hypothesis | Horizon | Discovery | Validation | Final holdout |
| --- | ---: | ---: | ---: | ---: |
| Rising-OI momentum | 1h | -0.0520% (102) | -0.0232% (40) | +0.2103% (39) |
| Falling-OI continuation | 1h | +0.0620% (272) | -0.0055% (99) | -0.0079% (81) |
| Falling-OI reversal | 8h | +0.0225% (272) | +0.2413% (99) | -0.1591% (81) |
| Extreme-funding reversal | 24h | +0.0414% (15) | no signals | +0.1459% (2) |

Parentheses show signal counts. Every OI hypothesis changes sign across the
chronological segments. Funding has no validation sample and only two final-
holdout signals. All four are rejected before option simulation; none supports
a live-strategy change.

## Candidate advanced to option calculation

After correcting the incomplete OHLCV download and the close-time boundary of
the session range, only the London 08:00-08:30 local opening-range breakout
had positive 30-minute average signed BTC movement in every chronological
segment: +0.0271% across 222 discovery signals, +0.0130% across 58 validation
signals, and +0.0641% across 60 final-holdout signals. Win rates were about 48%
and medians were slightly negative, so the candidate depends on asymmetric
large winners and is not itself evidence of a tradable edge.

The first option calculation is frozen as next-quote entry into the nearest
ATM CE or PE with one to three days remaining, a $6.67 premium budget, the
existing liquidity constraints, and exit after 30 minutes. A second fixed
calculation uses the live strategy's existing exit rules within that window:
-15% hard stop, +25% target, profit protection at +10%, 40% peak giveback, two
confirming profit-exit quotes, and a 30-minute timeout. No exit threshold will
be optimized on these samples.

### Corrected OHLCV conclusions

The continuity-validated rerun supersedes the earlier provisional tables.
Representative fixed-horizon average signed returns were:

| Hypothesis | Horizon | Discovery | Validation | Final holdout |
| --- | ---: | ---: | ---: | ---: |
| Five-minute trend expansion | 60m | -0.0156% | +0.0191% | -0.0135% |
| Five-minute compression breakout | 60m | -0.0171% | +0.0529% | -0.0513% |
| Fifteen-minute trend breakout | 60m | +0.0128% | -0.0161% | +0.0106% |
| Neutral exhaustion reversal | 15m | -0.0102% | +0.0065% | +0.0010% |
| Abnormal-volume continuation | 60m | -0.0274% | -0.0386% | -0.0213% |
| Failed-impulse reversal | 15m | +0.0381% | -0.0190% | +0.0222% |
| One-hour structure breakout | 8h | +0.0327% | -0.2177% | +0.2299% |

All remain rejected. The reproducible full report is
`reports/ohlcv-discovery-2025-09-27_2026-09-27/summary.json`.

### Option calculation results

The London candidate was evaluated on two adjacent 30-day Delta option-candle
datasets using synthetic 1% BBO and next-quote execution.

| Period | Exit | Trades | Net P&L on $100 | Profit factor | Max drawdown |
| --- | --- | ---: | ---: | ---: | ---: |
| 2026-07-25 to 2026-08-24 | Fixed 30m | 28 | +$2.04 | 1.14 | -$9.74 |
| 2026-08-24 to 2026-09-23 | Fixed 30m | 30 | +$3.61 | 1.23 | -$8.52 |
| 2026-07-25 to 2026-08-24 | Existing protection + timeout | 28 | -$1.48 | 0.89 | -$9.41 |
| 2026-08-24 to 2026-09-23 | Existing protection + timeout | 30 | +$4.96 | 1.40 | -$5.67 |

The fixed exit is positive in both option samples, but the edge is small and
drawdown is large relative to return. Existing profit protection is unstable
across the two periods. The candidate remains research-only and must not be
added to the live strategy yet. It needs validation using recorded BBO on a
meaningful independent sample, followed by analyzer forward testing without
changing its rules.

## Pre-registered session discovery pass

The following rules are frozen before examining their results. Every signal
uses completed five-minute candles, permits at most one entry per local session
or UTC day, and is evaluated after 30, 60, and 120 minutes.

### Tokyo opening-range breakout

- Build the 09:00-09:30 Asia/Tokyo opening range.
- During the following two hours, select the first close outside the range.
- Require the breakout close to be in the directional outer 25% of its candle.

### Previous UTC-day high/low breakout

- Use the completed previous UTC day's high and low; never the current day.
- Select the first close beyond either level during the next UTC day.
- Require volume at least the preceding 20-candle median and a close in the
  directional outer 25% of the candle.

### London false-break reversal

- Build the 08:00-08:30 Europe/London opening range.
- During the following two hours, identify the first candle that trades beyond
  a range boundary but closes back inside it.
- A low-side failure must be bullish and close in the upper half of its candle;
  a high-side failure must be bearish and close in the lower half.
- Enter toward the range, opposite the failed break.

### New York breakout aligned with London morning

- Build the 09:30-10:00 America/New_York opening range.
- During the following two hours, select the first qualifying outer-25% close
  beyond that range.
- Keep it only when its direction agrees with BTC's return from the first
  completed candle after 08:00 Europe/London through the breakout candle.

## Session discovery results

Representative 30-minute average signed BTC returns are shown below. Counts in
parentheses are signals.

| Hypothesis | Discovery | Validation | Final holdout |
| --- | ---: | ---: | ---: |
| Tokyo opening range | +0.0288% (222) | -0.0712% (59) | -0.0144% (58) |
| Previous UTC-day breakout | -0.0079% (179) | -0.0222% (47) | +0.0020% (48) |
| London false-break reversal | +0.0045% (183) | -0.0587% (52) | +0.0517% (47) |
| New York breakout, London aligned | -0.0251% (162) | -0.0459% (42) | +0.0808% (45) |

The 60- and 120-minute horizons also fail to remain positive across all three
segments. All four hypotheses are rejected before option simulation. The
recent strength of the London-aligned New York setup is not accepted because
both discovery and validation are negative at 30 minutes, and validation is
negative at every tested horizon.

No additional threshold variants will be tested on this year. The frozen
London opening-range candidate remains the only research candidate and now
requires independent recorded-BBO or forward analyzer evidence.
