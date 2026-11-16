"""Quote lookups must order event times, including old variable-precision indexes."""
import sqlite3
from types import SimpleNamespace

import pytest

from app.data_store import DataStore, parse_time


@pytest.fixture
def indexed_store():
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    connection.execute('CREATE TABLE quotes(timestamp TEXT,symbol TEXT,bid REAL,ask REAL)')
    connection.execute('CREATE INDEX lookup ON quotes(symbol,timestamp)')
    store = object.__new__(DataStore)
    store.metadata = lambda part: {}
    store._query = lambda part, sql, values: [dict(row) for row in connection.execute(sql, values)]
    yield store, connection, SimpleNamespace(quotes=True)
    connection.close()


@pytest.mark.parametrize('stamp,accepted', [
    ('2026-11-11T14:00:00Z', True),
    ('2026-11-11T14:00:00.000001Z', True),
    ('2026-11-11T14:00:00.500Z', True),
    ('2026-11-11T14:00:02Z', True),
    ('2026-11-11T14:00:02.000001Z', False),
    ('2026-11-11T14:00:02.500Z', False),
    ('2026-11-11T13:59:59.999999Z', False),
])
def test_first_and_range_quote_windows_have_exact_inclusive_boundaries(indexed_store, stamp, accepted):
    store, connection, part = indexed_store
    connection.execute('INSERT INTO quotes VALUES(?,?,?,?)', (stamp, 'OPTION', 99, 100))
    result = store.first_quote_many([part], 'OPTION', '2026-11-11T14:00:00Z', 2)
    assert (result is not None) is accepted
    frame = store.quotes_between_many([part], 'OPTION', '2026-11-11T14:00:00Z', '2026-11-11T14:00:02Z')
    assert len(frame) == int(accepted)


def test_first_quote_uses_chronological_order_across_segments_and_precisions(indexed_store):
    store, connection, part = indexed_store
    for stamp in ('2026-11-11T14:00:01.500Z', '2026-11-11T14:00:01Z', '2026-11-11T14:00:00.900Z'):
        connection.execute('INSERT INTO quotes VALUES(?,?,?,?)', (stamp, 'OPTION', 99, 100))
    result = store.first_quote_many([part, part], 'OPTION', '2026-11-11T14:00:00.950Z', 2)
    assert parse_time(result['timestamp']) == parse_time('2026-11-11T14:00:01Z')
    frame = store.quotes_between_many([part, part], 'OPTION', '2026-11-11T14:00:00.950Z', '2026-11-11T14:00:02Z')
    assert list(frame.timestamp) == [parse_time('2026-11-11T14:00:01Z'), parse_time('2026-11-11T14:00:01.500Z')]
