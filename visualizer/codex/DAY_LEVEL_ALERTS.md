# Historical previous-day swing alerts

Use **Previous-day swing alerts** in the strategy toolbar, or import
`examples/previous-day-swing-alerts.strategy.json`. This creates an alert-only
strategy with eight independent NEUTRAL chart alerts and no option orders.
Defaults: strategy/pivots 5m, Asia/Kolkata days, left/right confirmation 3/3,
30 older calendar days, warning distance 100 BTC price points. Change them in
**Indicators & chart order**. The preset leaves entry/exit trees empty; eight
conditions in Shared NO TRADE serve only as sources for the custom alerts.

## Exact level definitions

`DAY_LEVELS` displays six levels:

- `previous_day_high`, `previous_day_low`: previous local calendar day's full
  range, calculated from complete underlying **5m** candles, including when
  strategy/native pivot candles are 10m, 15m, 30m or 1h.
- `previous_day_swing_high`, `previous_day_swing_low`: highest/lowest confirmed
  native-timeframe pivots whose candle **opened** yesterday and whose right-side
  confirmation completed by today's local midnight.
- `older_swing_high`, `older_swing_low`: search the configured calendar days
  **before yesterday**, newest pivot first. High must be strictly above
  yesterday's full-day high; low strictly below yesterday's full-day low.
  High and low are searched independently and may come from different dates.
  This selects chronological matches, not nearest prices or extreme prices.

Each day's snapshot uses only confirmations available at its midnight and
stays fixed all day. A pivot confirming later today cannot rewrite that snapshot.
Candles use close timestamps. Daily 5m grouping is by candle OPEN date, so the
close at midnight is the last candle of the ending day. Strategy candles also
use their OPEN date: a UTC-aligned 1h candle spanning midnight IST retains the
old snapshot; the first candle opening after midnight uses the new snapshot.
This avoids testing a level against price action before it was available.
DST days use actual local midnights (23/25-hour days where applicable).

## Warning and confirmation rules

For each of the four swing levels, `_distance` is the shortest distance from
that candle's `[low, high]` interval to the level. `_near` is 1 when distance
is greater than 0 and at most `warning_points`. `_touch` is 1 when
`low <= level <= high`, including wick/equality touches. Touch takes precedence:
a candle touching the level cannot also warn for that same level. Separate
levels can trigger simultaneously. Warning is allowed from either side.

The eight alerts reference individual condition IDs in the existing rule tree;
no new independent rule builder is required. Each has its own editable name,
message, enabled flag, ON_ENTER/EVERY_BAR setting and cooldown.
`reset_operand=daily.day_id` rearms its transition and clears its cooldown when
the snapshot day changes. Without that optional field, existing alert semantics
are unchanged. Warm-up seeds transitions/identities but emits no pre-range alert.
ON_ENTER can fire again after the condition goes false and subsequently true;
it is not a once-per-day quota.

## History and unavailable levels

`previous_day_ready` and `older_history_ready` expose coverage. A previous day
with any missing/off-grid/invalid 5m candle is unavailable; its range, swings and
older-level flags remain missing. Incomplete older search history disables only
the older levels. No confirmed pivot or no strictly qualifying older pivot also
leaves that level missing. Missing flags fail rules. Chart whitespace preserves
gaps instead of drawing a fabricated continuous level.

Warm-up automatically requests the older calendar window, yesterday, a partial
current day, DST allowance and native pivot padding (existing 20,000 strategy-bar
cap). ARCHIVE/AUTO include older catalog segments as underlying-only context;
SINGLE/MULTI stay scoped to selected files. `warmup_policy=REQUIRE` rejects
insufficient contiguous history. WARN permits research with unavailable levels;
it never substitutes rolling Donchian or latest swings. No new market data
source is required: enough existing 5m OHLCV suffices. The feature does not
silently download or modify the archive.

## Compatibility and verification

Strategy JSON stays schema version 15. DAY_LEVELS uses the existing indicator
instance/parameter contract; alert `reset_operand` is optional. API chart series
may contain `{time}` whitespace points for unavailable daily levels. Engine cache
version is 172; previous stored results remain readable, but fresh requests do
not reuse old engine calculations. Chart, backtest and daily-level trend research
share the same source/indicator semantics. Ablation removes dependent alert
conditions and reset references.

Run backend tests and frontend build/tests documented in COMMANDS.md. Focused
coverage is in `backend/tests/test_day_levels.py` and
`frontend/src/components/DayLevelAlerts.test.tsx`.

These are completed-candle historical observations. A touch confirms reaching a
level, not a reversal or trade. OHLC does not prove an exact fill at the level,
intrabar ordering, or that a warning occurred on an earlier candle.
