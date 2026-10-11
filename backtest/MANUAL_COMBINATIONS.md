# Manual BT1-BT3 Combination Backtests

This runner combines entry filters, one exit policy, several IST entry windows,
and optional no-trade weekdays. Time and weekday restrictions affect new
entries only; an open position can always exit.

## Run One Experiment

1. Open `backtest/config.manual-combination.toml`.
2. Enable the filters for only that experiment. The `name` value is only an
   optional report label; it does not need to change between runs.
3. Choose `PLAIN` or `ALL_FAIL` and set the IST windows/no-trade days.
4. From the repository root, run:

   ```powershell
   .\.venv\Scripts\python.exe -m backtest.manual_combination
   ```

5. Read the automatically named scenario folder printed by the command:

   ```text
   backtest/reports/manual-combinations/<scenario-name>/results.md
   ```

The same folder contains `monthly_summary.csv`, `trades.csv`, and
`summary.json`. Existing results are never overwritten. Repeating the same
scenario creates `<scenario-name>_v2`, then `_v3`, and so on. A run containing
multiple BT families uses a shared prefix such as `BT1-BT2-BT3`.

## Choose Dates, Months, Or R2 L1

The `[backtest]` table controls the data source and test period. Dates are UTC
calendar dates and `end_date` is inclusive.

Run one continuous date range from the built-in Delta public-history catalog:

```toml
[backtest]
source = "PUBLIC_HISTORY"
start_date = "2026-06-01"
end_date = "2026-08-31"
months = []
directory = ""
```

Run one or more complete calendar months instead. Clear both date fields because
the two selection methods are mutually exclusive:

```toml
[backtest]
source = "PUBLIC_HISTORY"
start_date = ""
end_date = ""
months = ["2026-06", "2026-08"]
directory = ""
```

Use one custom downloaded public-history dataset by setting `directory` to its
normalized folder containing `sync_manifest.json`, `underlying_bars.csv`,
`option_instruments.csv`, and `option_quotes.csv`:

```toml
[backtest]
source = "PUBLIC_HISTORY"
start_date = "2025-01-01"
end_date = "2025-12-31"
months = []
directory = "backtest/data/delta-2025-01-01_2026-01-01"
```

Use imported R2 recordings by pointing to a normalized `recorded-*` folder:

```toml
[backtest]
source = "R2_L1"
start_date = "2026-09-23"
end_date = "2026-10-03"
months = []
directory = "backtest/data/recorded-2026-09-23-to-10-03"
```

R2 selection is clipped to the actual recorded-session coverage. The runner
does not claim that gaps between sessions contain L1 data. `R2_L1` expects data
already downloaded and converted with `python -m backtest.recorded`; it does not
download from R2 during every strategy run.

To use a shorter custom folder name, pass only the name:

```powershell
.\.venv\Scripts\python.exe -m backtest.manual_combination --output 02_zigzag_full_bbo
```

This creates
`backtest/reports/manual-combinations/02_zigzag_full_bbo`. Repeating it creates
`02_zigzag_full_bbo_v2`, then `_v3`. An absolute `--output` path is respected
as written.

## First Three Runs

### 1. MACD Only

```toml
name = "macd-only"
exit_policy = "PLAIN"

[filters]
macd = true
h6 = false
fee_aware_multiplier = 0.0
m30 = false
stoch_momentum = false
```

### 2. H6 Only

```toml
name = "h6-only"
exit_policy = "PLAIN"

[filters]
macd = false
h6 = true
h6_true_ranges = 6
fee_aware_multiplier = 0.0
m30 = false
stoch_momentum = false
```

### 3. MACD And H6

```toml
name = "macd-h6"
exit_policy = "PLAIN"

[filters]
macd = true
h6 = true
h6_true_ranges = 6
fee_aware_multiplier = 0.0
m30 = false
stoch_momentum = false
```

Keep `bt_families = [1, 2, 3]` and the `[session]` section from the complete
template when using these snippets.

## Exit Policy

Use exactly one exit policy per run:

```toml
exit_policy = "PLAIN"
```

- `PLAIN`: BT1/BT2/BT3 exit when any condition required by that family fails.
- `ALL_FAIL`: BT2 exits only when EMA and VWAP both fail; BT3 exits only when
  EMA, VWAP, and RSI all fail. BT1 is unchanged.

Use different names when comparing them, for example `macd-plain` and
`macd-all-fail`.

### EMA Exit Rule

The default exit rule preserves the strict directional EMA ordering:

```toml
[exit]
ema_rule = "STRICT_ORDER"
```

To keep the strict entry ordering but ignore EMA9/EMA20 crossovers during an
open trade, use:

```toml
[exit]
ema_rule = "FAST_AND_MID_VS_SLOW"
```

With `FAST_AND_MID_VS_SLOW`:

- A CALL EMA exit condition remains valid while EMA9 and EMA20 are both above
  EMA50.
- A PUT EMA exit condition remains valid while EMA9 and EMA20 are both below
  EMA50.
- EMA9 crossing EMA20 does not by itself trigger an exit.
- BT2 VWAP and BT3 VWAP/RSI exit conditions continue to follow the selected
  `exit_policy`.

For a looser EMA exit that remains valid while either EMA9 or EMA20 stays on
the directional side of EMA50, use:

```toml
[exit]
ema_rule = "FAST_OR_MID_VS_SLOW"
```

With `FAST_OR_MID_VS_SLOW`, a CALL's EMA condition fails only when EMA9 and
EMA20 are both at or below EMA50. A PUT's EMA condition fails only when both
are at or above EMA50. Other BT-family conditions remain active.

### Maximum Holding Time

Set one maximum holding time per run under `[exit]`:

```toml
[exit]
ema_rule = "STRICT_ORDER"
max_hold_hours = 1.5
```

Common comparisons are `1.5`, `2.0`, `3.0`, and `4.0`. To run without a
time-based exit:

```toml
max_hold_hours = "NONE"
```

`NONE` disables only `MAX_HOLD`. The hard stop, configured BT condition exit,
and any enabled protection exit still apply. If none of those exits occurs
before option data ends or the contract expires, the backtest closes at the
last available pre-expiry quote and records `OPTION_EXPIRY_OR_DATA_END`.

To disable the hourly timeout but automatically exit as an option approaches
expiry, configure both controls:

```toml
[exit]
ema_rule = "STRICT_ORDER"
max_hold_hours = "NONE"
exit_days_to_expiry = 1.3
```

Common expiry-exit comparisons are `1.0`, `1.3`, and `1.5` days remaining.
The trade exits at the first available option quote at or below that remaining
time and records `DTE_EXIT`. Strategy-condition exits, hard stops, and profit
protection may still close the position earlier. An entry is rejected with
`OPTION_DTE_EXIT_REACHED_AT_ENTRY` when the chosen option has already reached
the boundary. Set `exit_days_to_expiry = "NONE"` to disable this exit.

## IST Entry Windows And No-Trade Days

The template contains:

```toml
[session]
entry_windows_ist = [
    "13:30-17:00",
    "18:30-19:00",
    "19:00-21:30",
    "21:30-23:30",
]
no_trade_days = ["Saturday", "Sunday"]
```

- Times are IST, not UTC.
- Every end time is exclusive. For example, `13:30-17:00` accepts `16:59` but
  not `17:00`.
- Both the completed signal candle and actual next-quote fill must be inside an
  allowed window.
- Saturday and Sunday block new entries according to the IST calendar.
- Existing positions can exit outside the windows and on weekends.
- Use `entry_windows_ist = []` for all-day entries.
- Use `no_trade_days = []` to allow entries every day.
- To test one window by itself, keep only that one string in the array and use
  a unique experiment name.

## Filter Values

| Filter | Configuration | Meaning |
|---|---|---|
| MACD | `macd = true` | Directional MACD entry confirmation |
| H6 | `h6 = true` | Requires six valid option True Range observations |
| FA125 | `h6 = true`, `fee_aware_multiplier = 1.25` | Expected movement must cover 1.25 times estimated fees |
| FA150 | `h6 = true`, `fee_aware_multiplier = 1.50` | Expected movement must cover 1.50 times estimated fees |
| FA200 | `h6 = true`, `fee_aware_multiplier = 2.00` | Expected movement must cover 2.00 times estimated fees |
| M30 | `m30 = true` | BTC must confirm the direction over 30 minutes |
| Stoch | `stoch_momentum = true` | CALL K > D; PUT D > K on the original signal candle |

FA cannot be tested without H6 because the fee-aware movement estimate uses
the option True Range history loaded by H6.

## Pullback Reversal (ZigZag-Like) Entry

This mode does not read a ZigZag indicator or repainting pivot. It detects a
potential pullback reversal from completed native Delta 5-minute BTC candles.
Select it with:

```toml
[entry]
mode = "ZIGZAG"

[zigzag]
pullback_lookback_candles = 4
touch_ema20 = true
touch_vwap = true
require_ema_slope = true
allow_flat_ema50 = true
max_touch_close_distance_atr = 0.2
use_actual_pullback_sequence = true

rsi_enabled = true
bull_rsi_min = 40.0
bull_rsi_max = 55.0
bear_rsi_min = 45.0
bear_rsi_max = 60.0

atr_enabled = true
atr_reversal_multiplier = 0.4
```

The confirmation candle always requires:

- CALL: `EMA9 > EMA20 > EMA50`, close above VWAP and EMA9, and close above
  the previous candle high.
- PUT: `EMA9 < EMA20 < EMA50`, close below VWAP and EMA9, and close below
  the previous candle low.
- At least one of the previous `pullback_lookback_candles` must touch an
  enabled pullback level. When both EMA20 and VWAP touch are enabled, either
  one qualifies.
- `require_ema_slope = true` requires EMA9 and EMA20 to slope strictly with
  the trade versus the previous candle. EMA50 must slope with the trade or,
  when `allow_flat_ema50 = true`, may remain flat.
- With ATR enabled, `max_touch_close_distance_atr = 0.2` rejects a supposed
  CALL pullback that closes more than 0.2 ATR below its touched EMA20/VWAP
  level, and applies the inverse rule to PUT. Use `"NONE"` to disable this
  breakdown check.
- `use_actual_pullback_sequence = true` starts RSI and ATR measurements from
  the latest qualifying touch sequence, preventing an unrelated older extreme
  in the lookback window from qualifying the signal.

When `rsi_enabled = true`, a prior pullback candle must enter the configured
directional RSI band and RSI must turn with the trade on the confirmation
candle. When false, both the band and RSI-turn checks are skipped.

When `atr_enabled = true`, the confirmation close must reverse from the
lowest/highest pullback-window price by at least
`atr_reversal_multiplier * ATR(14)`. When false, this distance check is
skipped, along with the ATR-based touch tolerance.

Use four runs with unique names to isolate the RSI and ATR effects:

| Run | `rsi_enabled` | `atr_enabled` |
|---|---:|---:|
| Base confirmation | `false` | `false` |
| RSI only | `true` | `false` |
| ATR only | `false` | `true` |
| RSI + ATR | `true` | `true` |

Keep every other setting identical between these four runs. BT1, BT2, and BT3
still refer to the selected exit family; `entry.mode = "ZIGZAG"` replaces
their normal trend-start entry signal with the pullback-reversal entry.

## Option Expiry Range

Use the `[option]` section to control days remaining at entry. To reject all
options with 1.5 days or less remaining and trade only options with more than
1.5 days through 3 days remaining:

```toml
[option]
min_days_to_expiry = 1.5
min_days_to_expiry_inclusive = false
max_days_to_expiry = 3.0
```

- `min_days_to_expiry_inclusive = false` means exactly 1.5 DTE is rejected.
- The upper boundary is inclusive, so exactly 3 DTE remains eligible.
- This setting controls contract selection and is independent of H6 and FA.
- For no H6/FA filtering, also use `h6 = false` and
  `fee_aware_multiplier = 0.0` under `[filters]`.

There is currently no filter named `F1` in this project. Do not put `F1` in
the configuration until its exact rule is defined.

## Suggested Manual Order

Run the baseline first, then isolated filters, pairs, and larger combinations:

1. Baseline: every filter disabled.
2. MACD only.
3. H6 only.
4. M30 only.
5. Stoch only.
6. H6 + FA125, H6 + FA150, and H6 + FA200.
7. MACD + H6.
8. MACD + M30.
9. MACD + Stoch.
10. H6 + M30.
11. H6 + Stoch.
12. MACD + H6 + FA150.
13. MACD + H6 + FA150 + M30.
14. MACD + H6 + FA150 + M30 + Stoch.

Use a new `name` for every run. Compare net P&L, profit factor, maximum
drawdown, trade count, monthly consistency, and the exceptional-event-free
columns. A combination should not be selected from total P&L alone.

## Entry Modes

Choose one entry architecture per run:

```toml
[entry]
mode = "BASELINE" # BASELINE, ZIGZAG, MOMENTUM, or BOTH
```

- `BASELINE` uses the original strict EMA/VWAP/RSI signal.
- `ZIGZAG` uses the completed-candle pullback reversal rules.
- `MOMENTUM` requires a trend-aligned breakout without an EMA20/VWAP pullback.
- `BOTH` allows either ZigZag or Momentum and writes `entry_type` into every
  trade row, so their results can be separated later.

Momentum settings are independent:

```toml
[momentum_breakout]
lookback_candles = 6
breakout_buffer_atr = 0.0
min_volume_ratio = 1.25
min_vwap_displacement_atr = 1.0
min_ema_strength_atr = 0.0
max_ema_strength_atr = 0.75 # or "NONE"
```

The breakout close must exceed the preceding range in the trade direction.
All enabled volume, VWAP displacement, and EMA-strength bounds must also pass.

## Early Failure Exit

This exit is checked only during the first configured number of completed
5-minute BTC candles after entry. A trigger exits on the next available option
quote, which avoids pretending the strategy filled at the already-completed BTC
candle price.

```toml
[early_failure]
enabled = true
monitor_candles = 3
condition_mode = "ANY" # ANY or ALL
exit_on_vwap_failure = true
vwap_reclaim_candles = 1
exit_on_structure_break = true
structure_lookback_candles = 4
exit_on_ema9_ema20_cross = true
```

For CALL, failure means close below VWAP, close below the preceding structure
low, or EMA9 at/below EMA20. PUT uses the reverse. `ANY` exits when one enabled
condition fails; `ALL` waits until all enabled conditions fail on the same
candle. `vwap_reclaim_candles = 0` exits after the first failed close.
`vwap_reclaim_candles = 1` requires two consecutive failed closes, giving the
next completed candle one opportunity to reclaim VWAP. A successful reclaim
resets the consecutive-failure count. Test each condition alone before testing
a combined `ANY` rule.

## Partial-Fill Execution

Legacy reports assume the complete order fills at the first best bid or ask:

```toml
[execution]
mode = "FULL_BBO"
max_entry_quote_delay_seconds = 60.0
max_exit_quote_delay_seconds = 60.0
```

The optional quote-delay limits apply to recorded BBO data. The entry limit is
measured from the BTC signal timestamp to the first recorded option quote. The
exit limit is measured from the strategy's exit trigger to the first option
fill quote. Use `"NONE"` to disable either limit. Recorded-data trades are
reported as incomplete when coverage ends before a legitimate exit; the final
available quote is not silently treated as an expiry exit.

Use displayed L1 sizes for a stricter execution study:

```toml
[execution]
mode = "SIZE_AWARE"
max_entry_quote_delay_seconds = 60.0
max_exit_quote_delay_seconds = 60.0
size_participation_rate = 1.0
size_capacity_multiplier = 1.0
entry_fill_timeout_seconds = 0.0
minimum_entry_fill_percent = 0.0
exit_fill_timeout_seconds = 300.0
unfilled_exit_policy = "ZERO" # ZERO or LAST_BID
```

`SIZE_AWARE` consumes `ask_size` for entry and `bid_size` for exit across
successive quotes within each timeout. The trade output reports requested and
filled entry quantity, entry fill percentage, exit filled/unfilled quantity,
and the weighted execution prices. `ZERO` values any unfilled exit remainder
at zero. `LAST_BID` marks that remainder at the last observed bid while keeping
it explicitly classified as unfilled.

Recorded L1 sizes are suitable only when the source events actually contain
size. The R2 converter reports inferred-size counts in its manifest; a run with
inferred sizes is an execution stress test, not proof of historical fillability.

## Profit Protection Modes

Trailing protection retains a percentage of the highest open option profit:

```toml
[profit_protection]
enabled = true
mode = "TRAILING"
activation_percent = 30.0
protect_percent = 50.0
```

Fixed protection activates from the highest observed bid but protects a fixed
return above entry:

```toml
[profit_protection]
enabled = true
mode = "FIXED"
activation_percent = 10.0
protect_percent = 0.0 # breakeven
```

The three requested fixed tests are `10/0`, `15/5`, and `20/10`. Test trailing
protection separately at activation `30`, using coarse retention values such as
`50`, `75`, and `90`.

## Trend Quality Bounds

These filters apply to every selected entry mode and use the completed BTC
signal candle:

```toml
[filters]
min_signal_volume_ratio = 0.5
min_vwap_displacement_atr = 1.0
min_ema_strength_atr = 0.0
max_ema_strength_atr = 0.75 # or "NONE"
```

- Volume ratio is signal volume divided by the median of the previous 20 bars.
- VWAP displacement is directional distance from VWAP divided by ATR14.
- EMA strength is `abs(EMA9 - EMA50) / ATR14`.
- The maximum EMA bound is the anti-chasing control.

## Risk And Liquidity

```toml
[risk]
hard_stop_percent = -15.0
hard_stop_fill_mode = "NEXT_QUOTE" # or SAME_QUOTE

[liquidity]
max_spread_percent = 3.0
min_volume = 30.0
volume_quantity_multiplier = 5.0
```

`NEXT_QUOTE` is the more conservative stop model because a fast option may gap
through the threshold. `SAME_QUOTE` is useful as an optimistic comparison, not
as proof that a live fill is achievable. The liquidity checks use the synthetic
BBO dataset unless recorded L1 is available, so their absolute results remain
low fidelity.

## Recommended Test Matrix

Change one family of settings at a time and keep all other values identical.

| Stage | Runs |
|---|---|
| Control | `BASELINE`, existing exit/risk settings, all new filters disabled |
| Fixed protection | `10/0`, `15/5`, `20/10` |
| Trailing protection | activation `30`, retention `50`, `75`, `90` |
| Early window | `2`, `3`, `4` candles with VWAP-only failure |
| Early cause | structure-only, EMA-only, then all three with `ANY` |
| Early logic | best `ANY` candidate versus the same settings with `ALL` |
| Volume | minimum ratio `0`, `0.5`, `0.75`, `1.0`, `1.25` |
| VWAP distance | `0`, `0.5`, `1.0`, `1.5` ATR |
| EMA anti-chase | maximum `NONE`, `0.5`, `0.75`, `1.0` ATR |
| Trend zone | best VWAP minimum plus best EMA maximum |
| Hard stop | `-10`, `-12.5`, `-15`, `-17.5`; compare fill modes separately |
| Entry architecture | `BASELINE`, `ZIGZAG`, `MOMENTUM`, `BOTH` |
| Momentum lookback | `3`, `6`, `9`, `12` candles |
| Momentum quality | volume `1.0/1.25/1.5`, VWAP `0.5/1.0/1.5` |
| Liquidity stress | spread `1/2/3%`, volume multiplier `1/3/5` |
| Final candidate | only combine controls that helped in both time periods |

For every run compare:

```text
Net P&L
Profit Factor
Max Drawdown
Average Win
Average Loss
Largest Win
P&L per Trade
Profitable Months
CALL P&L
PUT P&L
Results without the exceptional August event
```

Use January-June for development and July-September for confirmation. A setting
is promising only when it improves the development and confirmation periods
without relying on the exceptional August winner. Do not choose a configuration
from win rate or total P&L alone.
