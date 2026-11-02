from __future__ import annotations
import csv
from datetime import datetime, timezone
from pathlib import Path
import pytest

from backtest.csv_stream import iter_csv_rows, selected_rows
from backtest.data import load_dataset, timestamp_ns
from backtest.providers.delta_india import DeltaPublicClient


def _csv(path:Path, header, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f);writer.writerow(header);writer.writerows(rows)


def test_streamed_csv_reader_and_quote_row_limit(tmp_path):
    base=tmp_path/'historical'
    _csv(base/'underlying_bars.csv', ['timestamp','open','high','low','close','volume'],
         [['2026-01-01T00:05:00Z',100,105,99,103,2]])
    _csv(base/'option_instruments.csv',
        ['symbol','source_symbol','expiry','strike','option_type','activation','expiration',
         'price_precision','size_precision','price_increment','size_increment','lot_size','min_quantity','contract_value'],
        [['BTC100CE','BTC100CE','2026-01-02',100,'CE','2025-12-31T00:00:00Z',
         '2026-01-02T00:00:00Z',2,0,.1,1,1,1,.001]])
    _csv(base/'option_quotes.csv',
         ['timestamp','symbol','bid','ask','bid_size','ask_size','volume','open_interest'],
         [['2025-12-31T23:00:00Z','BTC100CE',1,2,5,5,1,10],
          ['2026-01-01T00:05:00Z','BTC100CE',1,2,5,5,1,10],
          ['2026-01-01T00:06:00Z','BTC100CE',1,2,5,5,1,10]])
    start=timestamp_ns('2026-01-01T00:00:00Z')
    end=timestamp_ns('2026-01-01T01:00:00Z')
    selected=load_dataset(base,start,end)
    assert len(selected.bars)==1
    assert len(selected.quotes)==2
    with pytest.raises(ValueError,match='BACKTEST_RECORD_LIMIT_EXCEEDED'):
        load_dataset(base,start,end,max_quote_rows=1)
    assert len(load_dataset(base,start,end,max_quote_rows=2).quotes)==2


def test_delta_retry_configuration_bounds():
    with pytest.raises(ValueError):
        DeltaPublicClient('https://example.test',max_attempts=0)
    with pytest.raises(ValueError):
        DeltaPublicClient('https://example.test',retry_base_seconds=-1)
    client=DeltaPublicClient('https://example.test',max_attempts=2,retry_base_seconds=0)
    assert client.max_attempts==2


def test_selected_row_validation(tmp_path):
    p=tmp_path/'quotes.csv'
    _csv(p,['timestamp','value'],[['2026-01-01T00:00:00Z','ok']])
    with pytest.raises(ValueError,match='end must follow start'):
        list(selected_rows(p,start_ns=1,end_ns=1,timestamp_ns=timestamp_ns))


def test_disk_backed_quotes_match_memory_and_cleanup(tmp_path):
    base=tmp_path/'source'
    _csv(base/'underlying_bars.csv',['timestamp','open','high','low','close','volume'],
         [['2026-01-01T00:05:00Z',100,105,99,103,2]])
    _csv(base/'option_instruments.csv',
         ['symbol','source_symbol','expiry','strike','option_type','activation','expiration',
          'price_precision','size_precision','price_increment','size_increment','lot_size','min_quantity','contract_value'],
         [['BTC100CE','BTC100CE','2026-01-02',100,'CE','2025-12-31T00:00:00Z',
           '2026-01-02T00:00:00Z',2,0,.1,1,1,1,.001]])
    _csv(base/'option_quotes.csv',
         ['timestamp','symbol','bid','ask','bid_size','ask_size','volume','open_interest'],
         [['2026-01-01T00:05:00Z','BTC100CE',1,2,5,5,1,10],
          ['2026-01-01T00:06:00Z','BTC100CE',1.1,2.1,5,5,1,10]])
    start=timestamp_ns('2026-01-01T00:00:00Z')
    end=timestamp_ns('2026-01-01T01:00:00Z')
    memory=load_dataset(base,start,end)
    on_disk=load_dataset(base,start,end,quote_storage='SQLITE',
                         quote_spool_directory=tmp_path/'spool',quote_batch_size=1)
    try:
        assert list(on_disk.quotes)==list(memory.quotes)
        assert on_disk.quotes[0]==memory.quotes[0]
        assert on_disk.quotes[-1]==memory.quotes[-1]
        assert on_disk.quotes[:2]==memory.quotes[:2]
    finally:
        on_disk.quotes.close()
    assert not list((tmp_path/'spool').iterdir())
