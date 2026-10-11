# EMA/VWAP Session Study

This package contains a self-contained session-timing study used alongside the
main manual-combination engine.

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m backtest.ema_vwap_research.btc_options_ist_session_backtest
```

The package also provides the import bridge that exposes the main matrix engine
through `backtest.ema_vwap_research`. Keep `__init__.py` and the sibling
`backtest/ema_vwap_research.py` in sync when changing public symbols.

Like the main engine, this is research code. Report fees, execution fidelity,
drawdown, trade count, and sensitivity to exceptional trades with every result.
