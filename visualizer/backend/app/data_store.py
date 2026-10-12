from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, Any, Iterable

import pandas as pd

from .config import data_root, cache_root

UTC = timezone.utc


def parse_time(value: str) -> datetime:
    d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.astimezone(UTC)


def iso(d: datetime) -> str:
    return d.astimezone(UTC).isoformat().replace('+00:00', 'Z')


@dataclass(frozen=True)
class DatasetPaths:
    id: str
    root: Path
    bars: Path
    instruments: Path | None
    quotes: Path | None
    # V13 catalog bounds are optional so legacy folder datasets remain supported.
    catalog_name: str | None = None
    catalog_start: str | None = None
    catalog_end_exclusive: str | None = None


class DataStore:
    """Read-only access to downloaded normalized market data.

    V10 adds composite dataset selection, process-local frame caches, persistent
    SQLite quote connections, and preflight coverage validation. Original CSVs
    remain untouched; all derived state lives under strategy-lab/.cache.
    """

    _index_lock = threading.Lock()
    _frame_lock = threading.Lock()
    _bars_cache: dict[tuple[Any, ...], pd.DataFrame] = {}
    _inst_cache: dict[tuple[Any, ...], pd.DataFrame] = {}
    _metadata_cache: dict[str, dict[str, Any]] = {}

    def __init__(self):
        self._connections: dict[str, sqlite3.Connection] = {}

    def archive_catalog(self) -> dict[str, Any] | None:
        """Return the unified delta-history catalog when present.

        V13 deliberately treats catalog.json as the source of truth for segment
        discovery. This prevents compatibility junctions outside delta-history from
        being counted twice and lets AUTO/ARCHIVE selection choose segments without
        opening multi-gigabyte CSVs merely to learn their date bounds.
        """
        path = data_root() / 'catalog.json'
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except Exception as exc:
            raise ValueError(f'Invalid unified history catalog: {path}: {exc}') from exc
        if not isinstance(payload, dict) or not isinstance(payload.get('segments'), list):
            raise ValueError(f'Invalid unified history catalog: {path}: missing segments list')
        return payload

    def archive_payload(self) -> dict[str, Any]:
        base = data_root()
        catalog = self.archive_catalog()
        if catalog is None:
            return {
                'available': False, 'root': str(base), 'catalog_path': str(base / 'catalog.json'),
                'source': None, 'fidelity': None, 'updated_at': None,
                'start': None, 'end_exclusive': None, 'segment_count': 0, 'segments': [], 'gaps': [],
            }
        segments: list[dict[str, Any]] = []
        intervals: list[tuple[datetime, datetime]] = []
        for item in catalog.get('segments', []):
            if not isinstance(item, dict):
                continue
            directory = str(item.get('directory') or '').strip()
            name = str(item.get('name') or directory or 'segment')
            root = (base / directory).resolve()
            bars = root / 'underlying_bars.csv'
            inst = root / 'option_instruments.csv'
            quotes = root / 'option_quotes.csv'
            start = item.get('start')
            end_exclusive = item.get('end_exclusive')
            if start and end_exclusive:
                try:
                    intervals.append((parse_time(str(start)), parse_time(str(end_exclusive))))
                except Exception:
                    pass
            segments.append({
                'name': name, 'id': directory.replace('\\', '/'), 'directory': directory,
                'path': str(root), 'start': start, 'end_exclusive': end_exclusive,
                'bars_present': bars.exists(), 'instruments_present': inst.exists(), 'quotes_present': quotes.exists(),
            })
        intervals.sort(key=lambda x: x[0])
        gaps: list[dict[str, str]] = []
        if intervals:
            cursor = intervals[0][1]
            for next_start, next_end in intervals[1:]:
                if next_start > cursor:
                    gaps.append({'start': iso(cursor), 'end_exclusive': iso(next_start)})
                if next_end > cursor:
                    cursor = next_end
            start = iso(intervals[0][0])
            end_exclusive = iso(cursor)
        else:
            start = None
            end_exclusive = None
        return {
            'available': True, 'root': str(base), 'catalog_path': str(base / 'catalog.json'),
            'format_version': catalog.get('format_version'), 'source': catalog.get('source'),
            'fidelity': catalog.get('fidelity'), 'updated_at': catalog.get('updated_at'),
            'start': start, 'end_exclusive': end_exclusive,
            'segment_count': len(segments), 'segments': segments, 'gaps': gaps,
        }

    def discover(self) -> list[DatasetPaths]:
        base = data_root()
        out: list[DatasetPaths] = []
        if not base.exists():
            return out

        catalog = self.archive_catalog()
        if catalog is not None:
            # Catalog order is chronological and authoritative. Do not recursively
            # discover compatibility junctions/aliases when the archive exists.
            for item in catalog.get('segments', []):
                if not isinstance(item, dict):
                    continue
                directory = str(item.get('directory') or '').strip()
                if not directory:
                    continue
                root = base / directory
                bars = root / 'underlying_bars.csv'
                inst = root / 'option_instruments.csv'
                quotes = root / 'option_quotes.csv'
                out.append(DatasetPaths(
                    directory.replace('\\', '/'), root, bars,
                    inst if inst.exists() else None, quotes if quotes.exists() else None,
                    str(item.get('name') or directory),
                    str(item.get('start')) if item.get('start') else None,
                    str(item.get('end_exclusive')) if item.get('end_exclusive') else None,
                ))
            return out

        # Legacy fallback for pre-V13 repositories without catalog.json.
        for bars in sorted(base.rglob('underlying_bars.csv')):
            root = bars.parent
            rel = root.relative_to(base).as_posix()
            inst = root / 'option_instruments.csv'
            quotes = root / 'option_quotes.csv'
            out.append(DatasetPaths(rel, root, bars, inst if inst.exists() else None, quotes if quotes.exists() else None))
        return out

    def archive_range_coverage(self, start: str, end: str, parts: list[DatasetPaths] | None = None) -> dict[str, Any]:
        """Validate catalog interval coverage for a requested UTC range.

        This checks declared segment boundaries only; physical candle continuity is
        still checked separately by preflight. It is intentionally cheap.
        """
        if self.archive_catalog() is None:
            return {'available': False, 'covered': True, 'gaps': []}
        s = parse_time(start); e = parse_time(end)
        chosen = parts if parts is not None else self.auto_select(start, end, require_options=False)
        intervals: list[tuple[datetime, datetime, str]] = []
        for p in chosen:
            if not p.catalog_start or not p.catalog_end_exclusive:
                continue
            a = max(s, parse_time(p.catalog_start)); b = min(e, parse_time(p.catalog_end_exclusive))
            if b > a:
                intervals.append((a, b, p.id))
        intervals.sort(key=lambda x: x[0])
        gaps: list[dict[str, str]] = []
        cursor = s
        for a, b, _ in intervals:
            if a > cursor:
                gaps.append({'start': iso(cursor), 'end_exclusive': iso(a)})
            if b > cursor:
                cursor = b
        if cursor < e:
            gaps.append({'start': iso(cursor), 'end_exclusive': iso(e)})
        return {'available': True, 'covered': not gaps, 'gaps': gaps, 'segments': [x[2] for x in intervals]}

    def resolve(self, dataset_id: str) -> DatasetPaths:
        found = {x.id: x for x in self.discover()}
        if dataset_id not in found:
            raise KeyError(f'Unknown dataset: {dataset_id}')
        return found[dataset_id]

    def resolve_many(self, dataset_ids: Iterable[str]) -> list[DatasetPaths]:
        ids = list(dict.fromkeys(str(x) for x in dataset_ids if x))
        if not ids:
            raise ValueError('Select at least one dataset')
        found = {x.id: x for x in self.discover()}
        missing = [x for x in ids if x not in found]
        if missing:
            raise KeyError(f"Unknown dataset(s): {', '.join(missing)}")
        return [found[x] for x in ids]

    def _file_sig(self, path: Path | None) -> tuple[Any, ...]:
        if path is None or not path.exists():
            return (None,)
        st = path.stat()
        return (str(path.resolve()), st.st_size, st.st_mtime_ns)

    @staticmethod
    def _fast_csv_meta(path: Path) -> tuple[str | None, str | None, int]:
        first: str | None = None
        last: str | None = None
        count = 0
        with path.open('r', encoding='utf-8', newline='') as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                ts = str(row.get('timestamp') or '').strip()
                if not ts:
                    continue
                if first is None:
                    first = ts
                last = ts
                count += 1
        return first, last, count

    @staticmethod
    def _csv_edge_timestamps(path: Path) -> tuple[str | None, str | None]:
        """Read only the CSV header, first data row and tail row.

        option_quotes.csv can contain millions of rows. Dataset discovery/preflight
        must never scan the entire quote CSV merely to learn its time range.
        """
        if not path.exists() or path.stat().st_size == 0:
            return None, None
        with path.open('rb') as handle:
            header_raw = handle.readline()
            first_raw = handle.readline()
            if not header_raw or not first_raw:
                return None, None
            header = next(csv.reader([header_raw.decode('utf-8-sig').rstrip('\r\n')]))
            try:
                ts_index = header.index('timestamp')
            except ValueError:
                return None, None
            first_fields = next(csv.reader([first_raw.decode('utf-8').rstrip('\r\n')]))
            first = first_fields[ts_index].strip() if ts_index < len(first_fields) else None

            size = path.stat().st_size
            chunk = min(size, 131072)
            handle.seek(max(0, size - chunk))
            tail = handle.read().decode('utf-8', errors='ignore')
            lines = [line for line in tail.splitlines() if line.strip()]
            last = None
            for line in reversed(lines):
                try:
                    fields = next(csv.reader([line]))
                except Exception:
                    continue
                if ts_index < len(fields):
                    candidate = fields[ts_index].strip()
                    if candidate and candidate != 'timestamp':
                        last = candidate
                        break
            return first, last

    def metadata(self, p: DatasetPaths) -> dict[str, Any]:
        sig = json.dumps({
            'bars': self._file_sig(p.bars), 'inst': self._file_sig(p.instruments), 'quotes': self._file_sig(p.quotes),
            'catalog_start': p.catalog_start, 'catalog_end_exclusive': p.catalog_end_exclusive,
        }, sort_keys=True)
        key = hashlib.sha1(sig.encode()).hexdigest()
        cached = self._metadata_cache.get(key)
        if cached:
            return dict(cached)

        if p.bars.exists():
            start, end, count = self._fast_csv_meta(p.bars)
        else:
            start = end = None
            count = 0
        quote_start = quote_end = None
        if p.quotes and p.quotes.exists():
            # O(1)-ish metadata read: never walk the full multi-million-row quote CSV.
            quote_start, quote_end = self._csv_edge_timestamps(p.quotes)

        # Catalog bounds remain available even if one physical file is temporarily
        # missing, so the UI can explain the expected archive coverage instead of
        # silently hiding that segment. Physical CSV edges win when present.
        display_start = start or p.catalog_start
        display_end = end
        if display_end is None and p.catalog_end_exclusive:
            try:
                display_end = iso(parse_time(p.catalog_end_exclusive) - timedelta(minutes=5))
            except Exception:
                display_end = p.catalog_end_exclusive
        payload = {
            'id': p.id, 'catalog_name': p.catalog_name,
            'path': str(p.root),
            'bar_count': count,
            'start': display_start,
            'end': display_end,
            'catalog_start': p.catalog_start,
            'catalog_end_exclusive': p.catalog_end_exclusive,
            'bars_present': p.bars.exists(),
            'quote_start': quote_start,
            'quote_end': quote_end,
            'has_options': bool(p.instruments and p.quotes),
            'quote_indexed': self.index_valid(p),
            'source_files': {
                'bars': str(p.bars),
                'instruments': str(p.instruments) if p.instruments else None,
                'quotes': str(p.quotes) if p.quotes else None,
            },
        }
        self._metadata_cache[key] = dict(payload)
        return payload

    def list_payload(self) -> list[dict[str, Any]]:
        items = [self.metadata(x) for x in self.discover()]
        return sorted(items, key=lambda x: ((x.get('start') or ''), x['id']))

    def auto_select(self, start: str, end: str, require_options: bool = True) -> list[DatasetPaths]:
        s = parse_time(start)
        e = parse_time(end)
        selected: list[DatasetPaths] = []
        for p in self.discover():
            m = self.metadata(p)
            if require_options and not m['has_options']:
                continue
            # Unified archive selection uses catalog intervals directly. This is
            # O(number of segments), not O(number of CSV rows). Legacy datasets
            # fall back to their physical first/last bar timestamps.
            if p.catalog_start and p.catalog_end_exclusive:
                a = parse_time(p.catalog_start)
                b = parse_time(p.catalog_end_exclusive)
            else:
                if not m['start'] or not m['end']:
                    continue
                a = parse_time(str(m['start']))
                b = parse_time(str(m['end'])) + timedelta(minutes=5)
            if b > s and a < e:
                selected.append(p)
        if not selected:
            raise ValueError('No downloaded dataset overlaps the selected backtest range')
        return selected

    def resolve_request(self, req, require_options: bool = True) -> list[DatasetPaths]:
        mode = getattr(req, 'dataset_mode', 'SINGLE') or 'SINGLE'
        if mode == 'ARCHIVE':
            # Never silently skip a catalog segment because one physical options
            # file is missing. Select by catalog range first; preflight then reports
            # the exact missing bars/instruments/quotes for that segment.
            return self.auto_select(req.start, req.end, require_options=False)
        if mode == 'AUTO':
            return self.auto_select(req.start, req.end, require_options=require_options)
        ids = list(getattr(req, 'dataset_ids', []) or [])
        if mode == 'SINGLE':
            did = getattr(req, 'dataset_id', None)
            ids = [did] if did else ids[:1]
        elif not ids and getattr(req, 'dataset_id', None):
            ids = [req.dataset_id]
        return self.resolve_many(ids)

    def _read_bars_raw(self, p: DatasetPaths) -> pd.DataFrame:
        if not p.bars.exists():
            raise ValueError(f'Archive segment {p.id} is missing underlying_bars.csv: {p.bars}')
        key = self._file_sig(p.bars)
        with self._frame_lock:
            cached = self._bars_cache.get(key)
            if cached is not None:
                return cached.copy(deep=False)
        df = pd.read_csv(p.bars, parse_dates=['timestamp'])
        df['timestamp'] = pd.to_datetime(df.timestamp, utc=True)
        for c in ['open', 'high', 'low', 'close', 'volume']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        df = df.dropna(subset=['open', 'high', 'low', 'close']).sort_values('timestamp')
        with self._frame_lock:
            self._bars_cache[key] = df
        return df.copy(deep=False)

    def load_bars(self, p: DatasetPaths, start: str, end: str, timeframe: str = '5m') -> pd.DataFrame:
        return self.load_bars_many([p], start, end, timeframe)

    def load_bars_many(self, parts: list[DatasetPaths], start: str, end: str, timeframe: str = '5m', warmup_candles: int = 0) -> pd.DataFrame:
        timeframe_minutes = {'5m': 5, '10m': 10, '15m': 15, '30m': 30, '1h': 60}
        if timeframe not in timeframe_minutes:
            raise ValueError(f'Unsupported timeframe: {timeframe}')
        s = pd.Timestamp(parse_time(start))
        e = pd.Timestamp(parse_time(end))
        if e <= s:
            raise ValueError('Bar range end must be after start')

        # Higher-timeframe aggregation uses fixed UTC candle-close boundaries.
        # We load enough warm-in 5m history to complete the first target candle,
        # merge/de-duplicate all selected archive segments, and only retain target
        # candles whose complete expected 5m close sequence is present.
        raw_parts: list[pd.DataFrame] = []
        target_minutes = timeframe_minutes[timeframe]
        if warmup_candles < 0:
            raise ValueError('warmup_candles cannot be negative')
        warmup = pd.Timedelta(minutes=max(0, target_minutes - 5) + warmup_candles * target_minutes)
        for p in parts:
            raw = self._read_bars_raw(p)
            if raw.empty:
                continue
            chunk = raw[(raw.timestamp >= s - warmup) & (raw.timestamp < e)]
            if len(chunk):
                raw_parts.append(chunk)
        if not raw_parts:
            raise ValueError(f'No underlying 5m bars overlap the selected range for {timeframe} aggregation')

        df = pd.concat(raw_parts, ignore_index=True)
        df = df.sort_values('timestamp').drop_duplicates(subset=['timestamp'], keep='last').reset_index(drop=True)

        if target_minutes > 5:
            required = target_minutes // 5
            five = pd.Timedelta(minutes=5)
            # V15.1 anchors all higher-timeframe candles to UTC clock boundaries,
            # never to the first row loaded for a requested range.  This guarantees
            # that changing only From/To cannot regroup the same historical 5m
            # candles into different 10m/15m/30m/1h OHLC values.
            #
            # The source timestamps are candle-close times.  ceil(10min) maps
            # 00:05 -> 00:10 and keeps 00:10 -> 00:10, therefore those two rows
            # form the UTC 10m candle ending 00:10.
            df['_bucket_end'] = df['timestamp'].dt.ceil(f'{target_minutes}min')
            aggregated: list[dict[str, Any]] = []
            for bucket_end, group in df.groupby('_bucket_end', sort=True):
                group = group.sort_values('timestamp').reset_index(drop=True)
                if len(group) != required:
                    continue
                expected_times = pd.date_range(
                    end=pd.Timestamp(bucket_end),
                    periods=required,
                    freq='5min',
                    tz='UTC',
                )
                actual = pd.DatetimeIndex(group['timestamp'])
                if not actual.equals(expected_times):
                    continue
                aggregated.append({
                    'timestamp': pd.Timestamp(bucket_end),
                    'open': float(group['open'].iloc[0]),
                    'high': float(group['high'].max()),
                    'low': float(group['low'].min()),
                    'close': float(group['close'].iloc[-1]),
                    'volume': float(group['volume'].sum()),
                })
            df = pd.DataFrame(aggregated, columns=['timestamp','open','high','low','close','volume'])

        # Range semantics are based on the completed target-timeframe candle timestamp.
        earliest = s - pd.Timedelta(minutes=warmup_candles * target_minutes)
        df = df[(df.timestamp >= earliest) & (df.timestamp < e)]
        if df.empty:
            # Give actionable diagnostics from the actual downloaded 5m rows.
            source = pd.concat(raw_parts, ignore_index=True).sort_values('timestamp').drop_duplicates(subset=['timestamp'])
            sample = ', '.join(ts.strftime('%Y-%m-%d %H:%M') for ts in source['timestamp'].head(8))
            tail = ', '.join(ts.strftime('%Y-%m-%d %H:%M') for ts in source['timestamp'].tail(4))
            raise ValueError(
                f'No complete {timeframe} underlying bars in selected range. '
                f'Found {len(source)} source 5m candles near the range. '
                f'First timestamps: [{sample}]. Last timestamps: [{tail}]. '
                f'A complete {timeframe} candle requires {max(1, target_minutes // 5)} contiguous 5m candles ending on a UTC {timeframe} clock boundary.'
            )
        return df.set_index('timestamp').sort_index()

    def _read_instruments_raw(self, p: DatasetPaths) -> pd.DataFrame:
        if not p.instruments:
            return pd.DataFrame()
        key = self._file_sig(p.instruments)
        with self._frame_lock:
            cached = self._inst_cache.get(key)
            if cached is not None:
                return cached.copy(deep=False)
        df = pd.read_csv(p.instruments)
        for c in ['activation', 'expiration']:
            df[c] = pd.to_datetime(df[c], utc=True)
        for c in ['strike', 'price_increment', 'size_increment', 'lot_size', 'min_quantity', 'contract_value']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        df['option_type'] = df.option_type.astype(str).str.upper()
        with self._frame_lock:
            self._inst_cache[key] = df
        return df.copy(deep=False)

    def load_instruments(self, p: DatasetPaths) -> pd.DataFrame:
        if not p.instruments:
            raise ValueError('Dataset has no option_instruments.csv')
        return self._read_instruments_raw(p)

    def load_instruments_many(self, parts: list[DatasetPaths]) -> pd.DataFrame:
        chunks = [self._read_instruments_raw(p) for p in parts if p.instruments]
        chunks = [x for x in chunks if len(x)]
        if not chunks:
            raise ValueError('Selected datasets contain no option_instruments.csv')
        df = pd.concat(chunks, ignore_index=True)
        return df.sort_values(['expiration', 'strike', 'symbol']).drop_duplicates(subset=['symbol'], keep='last').reset_index(drop=True)

    def _db_path(self, p: DatasetPaths) -> Path:
        cache_root().mkdir(parents=True, exist_ok=True)
        key = hashlib.sha1(str(p.root.resolve()).encode()).hexdigest()[:12]
        return cache_root() / f'quotes-{key}.sqlite3'

    def _source_sig(self, p: DatasetPaths) -> dict[str, Any]:
        if not p.quotes:
            return {}
        st = p.quotes.stat()
        return {'path': str(p.quotes.resolve()), 'size': st.st_size, 'mtime_ns': st.st_mtime_ns}

    def index_valid(self, p: DatasetPaths) -> bool:
        if not p.quotes:
            return False
        db = self._db_path(p)
        if not db.exists():
            return False
        try:
            con = sqlite3.connect(db)
            row = con.execute("SELECT value FROM meta WHERE key='source_sig'").fetchone()
            con.close()
            return bool(row and json.loads(row[0]) == self._source_sig(p))
        except Exception:
            return False

    def ensure_index(self, p: DatasetPaths, progress: Callable[[str], None] | None = None) -> Path:
        if not p.quotes:
            raise ValueError(f'Dataset {p.id} has no option_quotes.csv')
        if self.index_valid(p):
            return self._db_path(p)
        with self._index_lock:
            if self.index_valid(p):
                return self._db_path(p)
            db = self._db_path(p)
            tmp = db.with_suffix('.building.sqlite3')
            if tmp.exists():
                tmp.unlink()
            if progress:
                progress(f'Building quote index for {p.id}…')
            con: sqlite3.Connection | None = None
            try:
                con = sqlite3.connect(tmp)
                con.executescript(
                    'PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA temp_store=MEMORY; '
                    'CREATE TABLE quotes(timestamp TEXT NOT NULL,symbol TEXT NOT NULL,bid REAL NOT NULL,ask REAL NOT NULL,bid_size REAL,ask_size REAL,volume REAL,open_interest REAL,source_event TEXT); '
                    'CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);'
                )
                batch: list[tuple[Any, ...]] = []
                count = 0
                with p.quotes.open('r', encoding='utf-8', newline='') as h:
                    reader = csv.DictReader(h)
                    for row in reader:
                        ts_text = row['timestamp'].strip()
                        if ts_text.endswith('+00:00'):
                            ts_text = ts_text[:-6] + 'Z'
                        batch.append((
                            ts_text, row['symbol'], float(row['bid']), float(row['ask']),
                            float(row.get('bid_size') or 0), float(row.get('ask_size') or 0),
                            float(row['volume']) if row.get('volume') not in (None, '') else None,
                            float(row['open_interest']) if row.get('open_interest') not in (None, '') else None,
                            row.get('source_event', ''),
                        ))
                        if len(batch) >= 100000:
                            con.executemany('INSERT INTO quotes VALUES(?,?,?,?,?,?,?,?,?)', batch)
                            count += len(batch)
                            batch.clear()
                            if progress and count % 500000 == 0:
                                progress(f'{p.id}: indexed {count:,} option quotes…')
                if batch:
                    con.executemany('INSERT INTO quotes VALUES(?,?,?,?,?,?,?,?,?)', batch)
                    count += len(batch)
                if progress:
                    progress(f'{p.id}: creating quote indexes for {count:,} rows…')
                con.execute('CREATE INDEX idx_quotes_symbol_time ON quotes(symbol,timestamp)')
                con.execute('CREATE INDEX idx_quotes_time_symbol ON quotes(timestamp,symbol)')
                con.execute("INSERT INTO meta VALUES('source_sig',?)", (json.dumps(self._source_sig(p), sort_keys=True),))
                con.commit()
                con.close(); con = None
                if db.exists():
                    db.unlink()
                tmp.replace(db)
                if progress:
                    progress(f'{p.id}: quote index ready ({count:,} rows).')
                return db
            except BaseException:
                # A user-requested V11 cancellation may arrive while a very large
                # CSV is being indexed. Never leave a half-built SQLite file that
                # looks reusable on the next run.
                if con is not None:
                    try:
                        con.close()
                    except Exception:
                        pass
                try:
                    if tmp.exists():
                        tmp.unlink()
                except Exception:
                    pass
                raise

    def ensure_indexes(self, parts: list[DatasetPaths], progress: Callable[[str], None] | None = None) -> None:
        for i, p in enumerate(parts, 1):
            if progress:
                progress(f'Preparing option quotes {i}/{len(parts)}: {p.id}')
            self.ensure_index(p, progress)

    def _connection(self, p: DatasetPaths) -> sqlite3.Connection:
        db = self.ensure_index(p)
        key = str(db.resolve())
        con = self._connections.get(key)
        if con is None:
            # One DataStore instance belongs to one backtest worker. Reusing the
            # connection removes thousands of connect/close cycles from option selection.
            con = sqlite3.connect(db, check_same_thread=False)
            con.row_factory = sqlite3.Row
            con.execute('PRAGMA query_only=ON')
            con.execute('PRAGMA cache_size=-65536')
            self._connections[key] = con
        return con

    def _query(self, p: DatasetPaths, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self._connection(p).execute(sql, args).fetchall()]

    def first_quote(self, p: DatasetPaths, symbol: str, at: str, max_delay_seconds: int) -> dict[str, Any] | None:
        return self.first_quote_many([p], symbol, at, max_delay_seconds)

    def first_quote_many(self, parts: list[DatasetPaths], symbol: str, at: str, max_delay_seconds: int) -> dict[str, Any] | None:
        start = parse_time(at)
        end = start + timedelta(seconds=max_delay_seconds)
        best: dict[str, Any] | None = None
        for p in parts:
            if not p.quotes:
                continue
            # Skip files whose bar coverage cannot overlap this timestamp. This is
            # especially important when a year is composed from many monthly folders.
            m = self.metadata(p)
            if m.get('end') and parse_time(str(m['end'])) + timedelta(minutes=5) < start:
                continue
            if m.get('start') and parse_time(str(m['start'])) > end:
                continue
            rows = self._query(
                p,
                'SELECT * FROM quotes WHERE symbol=? AND timestamp>=? AND timestamp<=? ORDER BY timestamp LIMIT 1',
                (symbol, iso(start), iso(end)),
            )
            if rows and (best is None or str(rows[0]['timestamp']) < str(best['timestamp'])):
                best = rows[0]
        return best

    def quotes_between(self, p: DatasetPaths, symbol: str, start: str, end: str) -> pd.DataFrame:
        return self.quotes_between_many([p], symbol, start, end)

    def quotes_between_many(self, parts: list[DatasetPaths], symbol: str, start: str, end: str) -> pd.DataFrame:
        s = parse_time(start)
        e = parse_time(end)
        all_rows: list[dict[str, Any]] = []
        for p in parts:
            if not p.quotes:
                continue
            m = self.metadata(p)
            if m.get('end') and parse_time(str(m['end'])) + timedelta(minutes=5) < s:
                continue
            if m.get('start') and parse_time(str(m['start'])) > e:
                continue
            all_rows.extend(self._query(
                p,
                'SELECT * FROM quotes WHERE symbol=? AND timestamp>=? AND timestamp<=? ORDER BY timestamp',
                (symbol, iso(s), iso(e)),
            ))
        if not all_rows:
            return pd.DataFrame(columns=['timestamp', 'symbol', 'bid', 'ask', 'bid_size', 'ask_size', 'volume', 'open_interest', 'source_event'])
        df = pd.DataFrame(all_rows)
        df['timestamp'] = pd.to_datetime(df.timestamp, utc=True)
        return df.sort_values('timestamp').drop_duplicates(subset=['timestamp', 'symbol'], keep='last').reset_index(drop=True)

    def close(self) -> None:
        for con in self._connections.values():
            try:
                con.close()
            except Exception:
                pass
        self._connections.clear()

    def preflight(self, parts: list[DatasetPaths], start: str, end: str, strategy, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        checks: list[dict[str, Any]] = []
        s = parse_time(start)
        e = parse_time(end)
        if e <= s:
            errors.append('Backtest end must be after start')
            return {'ok': False, 'errors': errors, 'warnings': warnings, 'checks': checks, 'dataset_ids': [p.id for p in parts]}

        if self.archive_catalog() is not None:
            archive_check = self.archive_range_coverage(start, end, parts)
            checks.append({'name': 'Unified archive catalog coverage', 'ok': bool(archive_check.get('covered')), 'gaps': archive_check.get('gaps', [])})
            if not archive_check.get('covered'):
                gaps = archive_check.get('gaps', [])
                text = ', '.join(f"{g['start']} → {g['end_exclusive']}" for g in gaps[:4])
                errors.append(f'Unified archive catalog has uncovered interval(s) in the requested range: {text}')
            missing_bars = [p.id for p in parts if not p.bars.exists()]
            missing_inst = [p.id for p in parts if not (p.instruments and p.instruments.exists())]
            missing_quotes = [p.id for p in parts if not (p.quotes and p.quotes.exists())]
            checks.append({'name': 'Archive segment files', 'ok': not (missing_bars or missing_inst or missing_quotes), 'missing_bars': missing_bars, 'missing_instruments': missing_inst, 'missing_quotes': missing_quotes})
            if missing_bars:
                errors.append('Archive segment(s) missing underlying_bars.csv: ' + ', '.join(missing_bars))
            if missing_inst:
                errors.append('Archive segment(s) missing option_instruments.csv: ' + ', '.join(missing_inst))
            if missing_quotes:
                errors.append('Archive segment(s) missing option_quotes.csv: ' + ', '.join(missing_quotes))

        if progress:
            progress('Preflight: checking underlying 5m bar coverage…')
        try:
            bars5 = self.load_bars_many(parts, start, end, '5m')
            actual = len(bars5)
            expected = max(1, int((e - s).total_seconds() // 300))
            missing = max(0, expected - actual)
            coverage = actual / expected * 100.0 if expected else 100.0
            checks.append({'name': 'Underlying 5m bars', 'ok': actual > 0, 'actual': actual, 'expected': expected, 'missing': missing, 'coverage_percent': coverage})
            if actual == 0:
                errors.append('No underlying bars are available in the requested range')
            elif coverage < 99.0:
                warnings.append(f'Underlying bar coverage is {coverage:.2f}% ({missing:,} expected 5m timestamps missing).')
            first = bars5.index[0].to_pydatetime()
            last = bars5.index[-1].to_pydatetime()
            if first > s + timedelta(minutes=5):
                errors.append(f'Underlying data begins at {iso(first)}, after requested start {iso(s)}')
            if last < e - timedelta(minutes=10):
                errors.append(f'Underlying data ends at {iso(last)}, before requested end {iso(e)}')
        except Exception as exc:
            errors.append(f'Underlying data check failed: {exc}')
            bars5 = None

        enabled_dirs = [
            direction for direction in (['CALL', 'PUT'] if strategy.direction_mode == 'BOTH' else [strategy.direction_mode])
            if (strategy.call_action if direction == 'CALL' else strategy.put_action) != 'ALERT'
        ]
        if progress:
            progress('Preflight: checking option instruments for enabled direction(s)…')
        try:
            inst = self.load_instruments_many(parts) if enabled_dirs else None
            types = set(inst.option_type.astype(str).str.upper()) if inst is not None else set()
            for direction in enabled_dirs:
                required = 'CE' if direction == 'CALL' else 'PE'
                ok = required in types
                checks.append({'name': f'{direction} instruments', 'ok': ok, 'count': int((inst.option_type == required).sum())})
                if not ok:
                    message = f'No {required} option instruments are present for enabled {direction} direction'
                    if strategy.direction_mode == 'BOTH':
                        warnings.append(message + '; signals on that side will be rejected unless you switch direction mode or add the missing data.')
                    else:
                        errors.append(message)
        except Exception as exc:
            errors.append(f'Option instrument check failed: {exc}')

        if progress:
            progress('Preflight: checking option quote files and reusable indexes…')
        quote_parts = [p for p in parts if p.quotes and p.quotes.exists() and p.quotes.stat().st_size > 0]
        checks.append({'name': 'Option quote files', 'ok': bool(quote_parts) or not enabled_dirs, 'count': len(quote_parts)})
        if enabled_dirs and not quote_parts:
            errors.append('No option quote files are available for the selected datasets')

        indexed = sum(self.index_valid(p) for p in quote_parts) if enabled_dirs else 0
        checks.append({'name': 'Quote indexes ready', 'ok': indexed == len(quote_parts) or not enabled_dirs, 'ready': indexed, 'total': len(quote_parts) if enabled_dirs else 0})
        if enabled_dirs and indexed < len(quote_parts):
            warnings.append(f'{len(quote_parts) - indexed} quote file(s) need a one-time SQLite index build before the backtest loop starts.')

        if ('CALL' in enabled_dirs and strategy.call_action == 'SELL') or ('PUT' in enabled_dirs and strategy.put_action == 'SELL'):
            warnings.append('SELL option backtests model executable bid/ask, fees and P&L, but exchange/broker margin requirements are not modeled; fixed/budget sizing is not a margin calculator.')

        return {
            'ok': not errors,
            'errors': errors,
            'warnings': warnings,
            'checks': checks,
            'dataset_ids': [p.id for p in parts],
            'requested_start': start,
            'requested_end': end,
            'direction_mode': strategy.direction_mode,
            'timeframe': strategy.timeframe,
        }
