# Options execution parity follow-up

Source update only. No server deployment or account operation is performed.
Strategy schema remains 15; options cache identity is 181. Existing reports are
retained, and an old run must be rerun to use corrected behavior.

`execution.safety_caps` is optional. Its fields are `max_spread_percent`,
`per_trade_premium_usd` and `account_budget_usd`, all positive finite values or
null. The execution editor imports/exports these values. Omitted/null caps keep
existing research behavior. To compare with the existing Demo ceilings, use the
same explicit 3%/$10/$100 caps in the strategy JSON on both sides. These are
additional entry restrictions; no quantity shrinking or stop-rule change occurs.
The Rust adapter cannot use JSON to raise a server ceiling and rejects a
conflicting cap rather than silently substituting another value.

Quote/contract eligibility can fall back to another candidate. A selected
contract's quantity, cash or cap failure ends the entry signal. Actual broker
eligibility and account margin remain independent real venue requirements.

Stop decisions compare option executable bid/ask before fill slippage. Slippage
still affects the simulated execution price, fees and P&L. Completed exits block
re-entry through the candle containing the actual final fill timestamp. This
includes fills seconds or microseconds after a strategy candle close.

No historical order-book depth or broker margin is invented. Recorded and
reconstructed quote fidelity labels remain. Matching engine rules cannot force
Live/Demo quotes, contract availability, actual fills or account evidence to be
identical. Real Demo expiry observation remains a separate verification item.

Primary files changed: `backend/app/engine.py`, `backend/app/models.py`.

Related files changed: backend regression cases, execution editor, frontend caps
test/types, AI prompt, this note and linked project documentation.

Related files inspected (no change needed): account margin/settlement research,
existing fee calculation, frontend API transport and saved-result storage.

Strategy JSON / API compatibility: additive optional caps, schema 15 retained.

Cache and historical result implications: options cache 181; saved reports stay.

Tests/builds run (with actual result): nine focused Python cases passed. Cloud
Build verified 410 Python tests (three existing warnings), frontend tests and
the TypeScript/Vite build. Successful follow-up
`f474cf29-ebb2-4992-9223-324575a23fa4` verified their unchanged source hashes and
passed 634 Rust tests (four ignored), formatting and strict Clippy, including
the default-stack protective-exit regression. No production image or deployment.

Known limitations: external broker/feed differences and real expiry observation
are not replaced by simulated tests.
