# Workflow

## Run One Experiment

1. Edit `backtest/config.manual-combination.toml`.
2. Change only the variable being tested.
3. Run `python -m backtest.manual_combination` from the project environment.
4. Record the generated scenario folder.
5. Review `results.md`, `summary.json`, `monthly_summary.csv`, and `trades.csv`.
6. Compare rejection counts and removed winners/losses when testing a filter.

Use `--output <name>` for a readable folder. The runner versions duplicate
names automatically.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Maintain Data

```powershell
.\.venv\Scripts\python.exe -m backtest.history_archive status
.\.venv\Scripts\python.exe -m backtest.history_archive sync --through-yesterday
```

Download only completed UTC dates. Preserve raw caches so interrupted downloads
can resume.

## Change Policy

Keep engine changes narrowly scoped, add regression tests, and avoid silently
changing historical assumptions. When semantics change, create a new scenario
instead of rewriting old results.
