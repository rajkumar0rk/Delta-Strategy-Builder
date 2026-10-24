"""Optional broker-derived settlement and margin observations; never synthesize missing data.

Put CSVs in the chosen dataset folder, or at the unified archive root.
The "source" column is provenance claimed by the importer, not cryptographic authentication.
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd


def _csv_locations(parts, filename: str):
    seen = set()
    for part in parts:
        candidates = [Path(part.root) / filename]
        if Path(part.root).parent.name == 'segments':
            candidates.append(Path(part.root).parent.parent / filename)
        for candidate in candidates:
            if candidate.is_file() and str(candidate.resolve()) not in seen:
                seen.add(str(candidate.resolve()))
                yield candidate


def _positive(value, name, *, zero=True):
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f'Invalid {name}: {value!r}') from exc
    if not math.isfinite(result) or result < 0 or (not zero and result == 0):
        raise ValueError(f'Invalid {name}: {value!r}')
    return result


def load_option_settlements(parts) -> dict[tuple[str, pd.Timestamp], dict]:
    """Records from Delta's expired products API; no futures/TWAP fallback."""
    observations = {}
    required = {'symbol', 'expiration', 'settlement_price', 'source'}
    for source_file in _csv_locations(parts, 'option_settlements.csv'):
        data = pd.read_csv(source_file, dtype={'symbol':str, 'source':str}, keep_default_na=False)
        if not required.issubset(data.columns):
            raise ValueError(f'{source_file} must contain {sorted(required)}')
        for row in data.to_dict('records'):
            if row['source'] != 'DELTA_EXPIRED_PRODUCTS':
                raise ValueError(f'{source_file}: unrecognized settlement provenance {row["source"]!r}')
            symbol = str(row['symbol']).strip()
            if not symbol:
                raise ValueError(f'{source_file}: empty settlement symbol')
            expiration = pd.to_datetime(row['expiration'], utc=True, errors='raise')
            price = _positive(row['settlement_price'], 'option settlement price')
            twap = None
            if 'index_twap' in row and str(row['index_twap']).strip():
                twap = _positive(row['index_twap'], 'settlement index TWAP', zero=False)
            key = symbol, expiration
            observation = {'price':price, 'index_twap':twap}
            if key in observations and observations[key] != observation:
                raise ValueError(f'Conflicting Delta option settlement observations: {key}')
            observations[key] = observation
    return observations


def settlement_for(observations, instrument):
    key = str(instrument['symbol']), pd.to_datetime(instrument['expiration'], utc=True)
    return observations.get(key)


def load_margin_audit(parts) -> dict[str, list[dict]]:
    """Observed broker account states are diagnostic, never what-if order margins."""
    observations: dict[str, list[dict]] = {}
    required = {'timestamp', 'symbol', 'initial_margin_usd', 'maintenance_margin_usd',
                'account_equity_usd', 'source'}
    for source_file in _csv_locations(parts, 'account_margin_snapshots.csv'):
        data = pd.read_csv(source_file, dtype={'symbol':str, 'source':str}, keep_default_na=False)
        if not required.issubset(data.columns):
            raise ValueError(f'{source_file}: expected columns {sorted(required)}')
        for row in data.to_dict('records'):
            if row['source'] != 'DELTA_ACCOUNT_EXPORT':
                raise ValueError(f'{source_file}: unrecognized account margin provenance')
            stamp = pd.to_datetime(row['timestamp'], utc=True)
            record = {'timestamp':stamp, 'symbol':str(row['symbol']).strip(),
                      'initial_margin_usd':_positive(row['initial_margin_usd'], 'initial margin'),
                      'maintenance_margin_usd':_positive(row['maintenance_margin_usd'], 'maintenance margin'),
                      'account_equity_usd':_positive(row['account_equity_usd'], 'account equity')}
            if record['initial_margin_usd'] < record['maintenance_margin_usd']:
                raise ValueError('Broker initial margin cannot be less than maintenance margin')
            observations.setdefault(record['symbol'], []).append(record)
    for records in observations.values():
        records.sort(key=lambda x:x['timestamp'])
    return observations


def audit_margin_observation(observations, symbol, at, estimates):
    """Compare a nearby *observed* account snapshot without affecting executions."""
    if not estimates or estimates.get('initial_margin_usd') is None:
        return None
    stamp = pd.to_datetime(at, utc=True)
    eligible = [row for row in observations.get(symbol, [])
                if pd.Timedelta(0) <= stamp-row['timestamp'] <= pd.Timedelta(minutes=5)]
    if not eligible:
        return None
    row = eligible[-1]
    return {
        'timestamp':stamp.isoformat(), 'broker_snapshot_time':row['timestamp'].isoformat(),
        'symbol':symbol, 'observed_account_initial_usd':row['initial_margin_usd'],
        'observed_account_maintenance_usd':row['maintenance_margin_usd'],
        'observed_account_equity_usd':row['account_equity_usd'],
        'assumed_trade_initial_usd':estimates['initial_margin_usd'],
        'comparable':False,
        'reason':'Entire observed account margin is not hypothetical marginal margin for strategy order',
    }
