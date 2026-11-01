from __future__ import annotations

import pandas as pd
import pytest
from pydantic import ValidationError

from app.data_store import DataStore
from app.indicators import _aggregate_completed, compute_indicators
from app.models import IndicatorInstance, StrategyConfig


def sample(n=288*5):
    index=pd.date_range("2026-01-01T00:05:00Z",periods=n,freq="5min")
    prices=[100+i*.1 for i in range(n)]
    return pd.DataFrame({"open":prices,"high":[p+1 for p in prices],
        "low":[p-1 for p in prices],"close":prices,
        "volume":[2.] * n},index=index)


def test_utc_daily_candle_aggregates_only_288_complete_5m_closes():
    raw=sample()
    daily=_aggregate_completed(raw,"5m","1D")
    assert len(daily)==5
    assert daily.index[0]==pd.Timestamp("2026-01-02T00:00:00Z")
    assert daily.iloc[0]["open"]==pytest.approx(raw.iloc[0]["open"])
    assert daily.iloc[0]["close"]==pytest.approx(raw.iloc[287]["close"])
    assert daily.iloc[0]["volume"]==pytest.approx(576)
    missing=raw.drop(raw.index[120])
    no_partial=_aggregate_completed(missing,"5m","1D")
    assert pd.Timestamp("2026-01-02T00:00:00Z") not in no_partial.index
    assert len(no_partial)==4


def test_daily_ema_has_no_intraday_lookahead():
    raw=sample()
    inst=IndicatorInstance(id="dailyema",kind="EMA",params={"period":2},timeframe="1D")
    out,_=compute_indicators(raw,[inst],"5m")
    before=pd.Timestamp("2026-01-03T12:00:00Z")
    modified=raw.copy()
    modified.loc[modified.index>before,"close"]+=1000
    check,_=compute_indicators(modified,[inst],"5m")
    pd.testing.assert_series_equal(out.loc[:before,"dailyema"],check.loc[:before,"dailyema"])
    first=raw.index[287]
    assert pd.isna(out.at[first,"dailyema"])


def test_daily_strategy_schema_and_lower_tf_rejected():
    strategy=StrategyConfig(timeframe="1D")
    assert strategy.timeframe=="1D"
    with pytest.raises(ValidationError,match="exact multiple"):
        StrategyConfig(timeframe="1D",indicators=[
            IndicatorInstance(id="fast",kind="EMA",timeframe="1h")])
