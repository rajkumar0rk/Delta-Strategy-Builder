from pathlib import Path
import pytest
from backtest.event_quote_store import EventQuoteStore
from backtest.ema_vwap_research import capture_quotes


def test_disk_event_quote_replay_matches_in_memory(tmp_path):
    from dataclasses import dataclass,field
    from types import SimpleNamespace
    from backtest.data import timestamp_ns
    @dataclass
    class Event:
        timestamp_ns:int
        option:object
        quotes:list=field(default_factory=list)
    when=timestamp_ns('2026-11-01T00:00:00Z')
    one=Event(when,SimpleNamespace(symbol='BTC-CE',expiration_ns=when+600*10**9))
    two=Event(when,SimpleNamespace(symbol='BTC-CE',expiration_ns=when+600*10**9))
    file=tmp_path/'quotes.csv'
    file.write_text('timestamp,symbol,bid,ask,bid_size,ask_size,volume,open_interest\n'
                    '2026-11-01T00:01:00Z,BTC-CE,5,6,10,10,3,7\n'
                    '2026-11-01T00:02:00Z,BTC-CE,6,7,10,10,4,7\n')
    capture_quotes(file,[one],horizon_minutes=5)
    store=EventQuoteStore(directory=tmp_path/'spool',batch_size=1)
    try:
        capture_quotes(file,[two],horizon_minutes=5,quote_store=store)
        assert list(two.quotes)==one.quotes
        assert list(reversed(two.quotes))==list(reversed(one.quotes))
        assert two.quotes[0]==one.quotes[0]
        assert two.quotes[-1]==one.quotes[-1]
        assert two.quotes[:2]==tuple(one.quotes)
    finally:
        store.close()
    assert not list((tmp_path/'spool').iterdir())


def test_capture_quota_and_cleanup(tmp_path):
    store=EventQuoteStore(directory=tmp_path/'spool',max_captured=1)
    try:
        store.append(1,{'bid':1.})
        with pytest.raises(ValueError,match='CAPTURED_QUOTE_LIMIT_EXCEEDED'):
            store.append(1,{'bid':2.})
    finally:
        store.close()
    assert not list((tmp_path/'spool').iterdir())


def test_sweep_matches_legacy_with_overlapping_events_and_disk(tmp_path):
    from dataclasses import dataclass, field
    from types import SimpleNamespace
    from backtest.data import timestamp_ns
    from backtest.ema_vwap_research import capture_quotes_sweep
    @dataclass
    class Event:
        timestamp_ns:int
        option:object
        quotes:list=field(default_factory=list)
    start=timestamp_ns('2026-11-01T00:00:00Z')
    expiry=start+600*10**9
    csv_path=tmp_path/'quotes.csv'
    csv_path.write_text('timestamp,symbol,bid,ask,bid_size,ask_size,volume,open_interest\n'
      '2026-11-01T00:01:00Z,BTC-CE,5,6,10,10,3,7\n'
      '2026-11-01T00:02:00Z,BTC-CE,6,7,10,10,4,7\n'
      '2026-11-01T00:03:00Z,BTC-CE,7,8,10,10,5,7\n')
    def events():
        return [Event(start,SimpleNamespace(symbol='BTC-CE',expiration_ns=expiry)),
                Event(start+60*10**9,SimpleNamespace(symbol='BTC-CE',expiration_ns=expiry))]
    legacy=events()
    capture_quotes(csv_path,legacy,horizon_minutes=5)
    streamed=events()
    store=EventQuoteStore(directory=tmp_path/'spool')
    try:
        capture_quotes_sweep(csv_path,streamed,horizon_minutes=5,quote_store=store)
        assert [list(e.quotes) for e in streamed]==[e.quotes for e in legacy]
    finally:
        store.close()


def test_sweep_rejects_unsorted_quotes(tmp_path):
    from dataclasses import dataclass,field
    from types import SimpleNamespace
    from backtest.data import timestamp_ns
    from backtest.ema_vwap_research import capture_quotes_sweep
    @dataclass
    class Event:
        timestamp_ns:int
        option:object
        quotes:list=field(default_factory=list)
    start=timestamp_ns('2026-11-01T00:00:00Z')
    path=tmp_path/'quotes.csv'
    path.write_text('timestamp,symbol,bid,ask,bid_size,ask_size,volume,open_interest\n'
      '2026-11-01T00:02:00Z,BTC-CE,5,6,10,10,3,7\n'
      '2026-11-01T00:01:00Z,BTC-CE,6,7,10,10,4,7\n')
    with pytest.raises(ValueError,match='QUOTE_TIMESTAMP_OUT_OF_ORDER'):
        capture_quotes_sweep(path,[Event(start,SimpleNamespace(symbol='BTC-CE',
            expiration_ns=start+600*10**9))])
