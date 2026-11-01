from __future__ import annotations

import csv
from datetime import datetime, timezone

import pytest

from backtest.futures_history import (
    SERIES, _day_file, _normalize, sync_futures_observations,
)

UTC=timezone.utc
DAY=int(datetime(2026,10,1,tzinfo=UTC).timestamp())


class FakeDelta:
    def __init__(self):
        self.calls=[]

    def candles(self,symbol,start,end,resolution):
        self.calls.append((symbol,start,end,resolution))
        rows=[]
        for t in range(start,end,60):
            price=(100 if symbol=="FUNDING:BTCUSD" else 100000)
            rows.append({"time":t,"open":price,"high":price+1,
                         "low":price-1,"close":price,"volume":0})
        return rows


def test_free_futures_observation_history_downloads_and_reuses_valid_daily_shards(tmp_path):
    client=FakeDelta()
    start="2026-10-01T00:00:00Z"
    end="2026-10-02T00:00:00Z"
    now=datetime(2026,10,3,tzinfo=UTC)
    first=sync_futures_observations(tmp_path,start,end,client=client,now=now)
    assert first["downloaded_days_by_series"]=={"mark":1,"index":1,"funding_rate":1}
    assert len(client.calls)==3
    assert {c[0] for c in client.calls}==set(SERIES.values())
    for kind in SERIES:
        path=_day_file(tmp_path,kind,DAY)
        assert path.is_file()
        with path.open(newline="",encoding="utf-8") as handle:
            rows=list(csv.DictReader(handle))
        assert rows[0]["timestamp"]=="2026-10-01T00:01:00Z"
        assert len(rows)==1440
    second=sync_futures_observations(tmp_path,start,end,client=client,now=now)
    assert second["downloaded_days_by_series"]=={"mark":0,"index":0,"funding_rate":0}
    assert len(client.calls)==3
    assert not (tmp_path/"futures_funding.csv").exists()
    assert not (tmp_path/"catalog.json").exists()


def test_missing_dense_candle_aborts_without_partial_files(tmp_path):
    class Truncated(FakeDelta):
        def candles(self,symbol,start,end,resolution):
            return super().candles(symbol,start,end,resolution)[:-1]

    with pytest.raises(RuntimeError,match="incomplete"):
        sync_futures_observations(tmp_path,
            "2026-10-01T00:00:00Z","2026-10-02T00:00:00Z",
            client=Truncated(),now=datetime(2026,10,3,tzinfo=UTC))
    assert not _day_file(tmp_path,"mark",DAY).exists()


def test_refuses_partial_utc_day_and_forged_ohlc(tmp_path):
    with pytest.raises(ValueError,match="fully completed UTC days"):
        sync_futures_observations(tmp_path,
            "2026-10-01T00:00:00Z","2026-10-02T01:00:00Z",
            client=FakeDelta(),now=datetime(2026,10,2,2,tzinfo=UTC))
    with pytest.raises(RuntimeError,match="Invalid"):
        _normalize([{"time":DAY,"open":100,"high":98,"low":99,
                     "close":101,"volume":0}],symbol="MARK:BTCUSD",day=DAY,dense=True)
