# Data And Fidelity

## Canonical Archive

`backtest/data/delta-history` is the logical public-history archive. Its
`catalog.json` maps date ranges to shards under `segments/`. Use
`python -m backtest.history_archive status` before assuming coverage.

The catalog presently spans 2025 through early October 2026 in multiple
segments. Treat the catalog, not folder names remembered from chat, as the
authority.

## Signal Data

BTC indicators should use completed native 5-minute Delta candles. Where a
source is one-minute only, aggregate complete groups deterministically and test
boundary handling.

## Option Data

Public-history option quotes are reconstructed from one-minute option candles
with a synthetic spread. They are useful for relative strategy research but do
not prove executable fills. Synthetic size derived from candle volume is not
order-book depth.

Imported R2 recordings may contain observed bid/ask snapshots. They cover only
their recorded sessions, can have gaps, and must not be silently extrapolated.

## Credentials

R2 settings live in `.env`, which is ignored. Never print or commit its values.
