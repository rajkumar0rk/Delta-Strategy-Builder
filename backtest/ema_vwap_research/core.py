from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd


# ============================================================
# SELF-CONTAINED HELPERS
# ============================================================
# Self-contained calculations for the session-study runner.
# dependencies so this folder can run on its own.


@dataclass(frozen=True)
class OptionSpec:
    symbol: str
    source_symbol: str
    expiry: str
    strike: float
    option_type: str
    activation_ns: int
    expiration_ns: int
    price_precision: int
    size_precision: int
    price_increment: float
    size_increment: float
    lot_size: float
    min_quantity: float
    contract_value: float


def timestamp_ns(value: str | int | float | datetime | pd.Timestamp) -> int:
    """Convert common timestamp representations to UTC nanoseconds."""
    if isinstance(value, pd.Timestamp):
        stamp = value
    elif isinstance(value, datetime):
        stamp = pd.Timestamp(value)
    elif isinstance(value, (int, float)):
        number = float(value)
        # Detect seconds / milliseconds / microseconds / nanoseconds.
        if abs(number) >= 1e17:
            return int(number)
        if abs(number) >= 1e14:
            return int(number * 1_000)
        if abs(number) >= 1e11:
            return int(number * 1_000_000)
        return int(number * 1_000_000_000)
    else:
        stamp = pd.Timestamp(str(value))
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize('UTC')
    else:
        stamp = stamp.tz_convert('UTC')
    return int(stamp.value)


def ema(values: list[float], period: int) -> list[float]:
    """EMA with SMA seed; output length always matches input length."""
    if period <= 0:
        raise ValueError('EMA period must be positive')
    output = [math.nan] * len(values)
    if len(values) < period:
        return output
    numeric = [float(v) for v in values]
    seed = sum(numeric[:period]) / period
    output[period - 1] = seed
    alpha = 2.0 / (period + 1.0)
    previous = seed
    for index in range(period, len(numeric)):
        previous = alpha * numeric[index] + (1.0 - alpha) * previous
        output[index] = previous
    return output


def rsi_wilder(values: list[float], period: int = 14) -> list[float]:
    """Standard Wilder RSI; output length always matches input length."""
    if period <= 0:
        raise ValueError('RSI period must be positive')
    output = [math.nan] * len(values)
    if len(values) <= period:
        return output
    closes = [float(v) for v in values]
    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, period + 1):
        change = closes[index] - closes[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    average_gain = sum(gains) / period
    average_loss = sum(losses) / period

    def _rsi(gain: float, loss: float) -> float:
        if loss == 0.0:
            return 100.0 if gain > 0.0 else 50.0
        rs = gain / loss
        return 100.0 - (100.0 / (1.0 + rs))

    output[period] = _rsi(average_gain, average_loss)
    for index in range(period + 1, len(closes)):
        change = closes[index] - closes[index - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        average_gain = ((average_gain * (period - 1)) + gain) / period
        average_loss = ((average_loss * (period - 1)) + loss) / period
        output[index] = _rsi(average_gain, average_loss)
    return output


def calculate_quantity(
    *,
    budget_usd: float,
    premium: float,
    contract_value: float,
    min_quantity: float,
    quantity_step: float,
    lot_size: float,
) -> float:
    """Largest valid quantity whose option premium cost does not exceed budget."""
    if budget_usd <= 0.0 or premium <= 0.0 or contract_value <= 0.0:
        return 0.0
    raw = budget_usd / (premium * contract_value)
    step = max(float(quantity_step), float(lot_size), 1e-12)
    # A small epsilon protects exact-step values from floating-point underflow.
    units = math.floor((raw + 1e-12) / step)
    quantity = units * step
    if quantity + 1e-12 < float(min_quantity):
        return 0.0
    # Normalize floating point noise without imposing an arbitrary exchange precision.
    return float(f'{quantity:.12g}')


UTC = timezone.utc
IST = ZoneInfo("Asia/Kolkata")
NS_MINUTE = 60 * 1_000_000_000


@dataclass(frozen=True)
class Scenario:
    name: str
    group: int
    exit_mode: str
    protection: str = "NONE"
    retention: float = 0.0
    activation_percent: float = 0.0
    stop_loss_points: float = 0.0
    confirmation_candles: int = 0
    require_macd: bool = False
    entry_start_hour_utc: int = 0
    entry_end_hour_utc: int = 24
    exit_when_all_fail: bool = False
    atr_trailing_multiplier: float = 0.0
    macd_reversal_exit: bool = False
    macd_exit_policy: str = "NONE"
    min_option_true_ranges: int = 0


@dataclass
class SignalEvent:
    timestamp_ns: int
    direction: str
    underlying: float
    option: OptionSpec
    quotes: list[dict[str, float]]
    option_true_ranges: list[float] = field(default_factory=list)


def scenarios() -> list[Scenario]:
    exits = (("EMA", 1), ("EMA_VWAP", 2), ("EMA_VWAP_RSI", 3))
    result = [Scenario(f"BT{group}_{mode}", group, mode) for mode, group in exits]
    for group, retention in ((4, 0.50), (5, 0.40), (6, 0.45), (7, 0.55), (8, 0.60)):
        label = f"Z{int(retention * 100)}"
        result.extend(
            Scenario(f"BT{group}_{mode}_{label}", group, mode, "Z", retention, 20.0)
            for mode, _ in exits
        )
    for group, retention in ((9, 0.90), (10, 0.95)):
        label = f"E{int(retention * 100)}"
        result.extend(
            Scenario(f"BT{group}_{mode}_{label}", group, mode, "E", retention)
            for mode, _ in exits
        )
    return result


def activation_scenarios() -> list[Scenario]:
    return [
        Scenario(
            f"ACT{int(activation)}_EMA_VWAP_Z55",
            11,
            "EMA_VWAP",
            "Z",
            0.55,
            activation,
        )
        for activation in (10.0, 15.0, 20.0, 25.0, 30.0)
    ]


def stop_loss_scenarios() -> list[Scenario]:
    return [
        Scenario(
            f"BT2_EMA_VWAP_SL{int(points)}",
            12,
            "EMA_VWAP",
            stop_loss_points=points,
        )
        for points in (100.0, 150.0, 200.0)
    ]


def confirmation_scenarios() -> list[Scenario]:
    return [
        Scenario(
            f"BT2_EMA_VWAP_CONFIRM_{candles}",
            13,
            "EMA_VWAP",
            confirmation_candles=candles,
        )
        for candles in (1, 2, 3, 4)
    ]


def macd_scenarios() -> list[Scenario]:
    return [
        Scenario("BT1_EMA_MACD", 1, "EMA", require_macd=True),
        Scenario("BT2_EMA_VWAP_MACD", 2, "EMA_VWAP", require_macd=True),
        Scenario("BT3_EMA_VWAP_RSI_MACD", 3, "EMA_VWAP_RSI", require_macd=True),
    ]


def utc_session_scenarios() -> list[Scenario]:
    exits = (("EMA", 1), ("EMA_VWAP", 2), ("EMA_VWAP_RSI", 3))
    unconfirmed = [
        Scenario(
            f"BT{group}_{mode}_UTC00_16",
            group,
            mode,
            entry_start_hour_utc=0,
            entry_end_hour_utc=16,
        )
        for mode, group in exits
    ]
    confirmed = [
        Scenario(
            f"BT{group}_{mode}_MACD_UTC00_16",
            group,
            mode,
            require_macd=True,
            entry_start_hour_utc=0,
            entry_end_hour_utc=16,
        )
        for mode, group in exits
    ]
    return unconfirmed + confirmed


def all_fail_exit_scenarios() -> list[Scenario]:
    exits = (("EMA", 1), ("EMA_VWAP", 2), ("EMA_VWAP_RSI", 3))
    unconfirmed = [
        Scenario(
            f"BT{group}_{mode}_ALLFAIL_UTC00_16",
            group,
            mode,
            entry_start_hour_utc=0,
            entry_end_hour_utc=16,
            exit_when_all_fail=True,
        )
        for mode, group in exits
    ]
    confirmed = [
        Scenario(
            f"BT{group}_{mode}_MACD_ALLFAIL_UTC00_16",
            group,
            mode,
            require_macd=True,
            entry_start_hour_utc=0,
            entry_end_hour_utc=16,
            exit_when_all_fail=True,
        )
        for mode, group in exits
    ]
    return unconfirmed + confirmed


def all_fail_z50_scenarios() -> list[Scenario]:
    exits = (("EMA", 1), ("EMA_VWAP", 2), ("EMA_VWAP_RSI", 3))
    unconfirmed = [
        Scenario(
            f"BT{group}_{mode}_ALLFAIL_Z50A50_UTC00_16",
            group,
            mode,
            protection="Z",
            retention=0.50,
            activation_percent=50.0,
            entry_start_hour_utc=0,
            entry_end_hour_utc=16,
            exit_when_all_fail=True,
        )
        for mode, group in exits
    ]
    confirmed = [
        Scenario(
            f"BT{group}_{mode}_MACD_ALLFAIL_Z50A50_UTC00_16",
            group,
            mode,
            protection="Z",
            retention=0.50,
            activation_percent=50.0,
            require_macd=True,
            entry_start_hour_utc=0,
            entry_end_hour_utc=16,
            exit_when_all_fail=True,
        )
        for mode, group in exits
    ]
    return unconfirmed + confirmed


def all_fail_atr_scenarios() -> list[Scenario]:
    exits = (("EMA", 1), ("EMA_VWAP", 2), ("EMA_VWAP_RSI", 3))
    unconfirmed = [
        Scenario(
            f"BT{group}_{mode}_ALLFAIL_ATR14X2_UTC00_16",
            group,
            mode,
            entry_start_hour_utc=0,
            entry_end_hour_utc=16,
            exit_when_all_fail=True,
            atr_trailing_multiplier=2.0,
        )
        for mode, group in exits
    ]
    confirmed = [
        Scenario(
            f"BT{group}_{mode}_MACD_ALLFAIL_ATR14X2_UTC00_16",
            group,
            mode,
            require_macd=True,
            entry_start_hour_utc=0,
            entry_end_hour_utc=16,
            exit_when_all_fail=True,
            atr_trailing_multiplier=2.0,
        )
        for mode, group in exits
    ]
    return unconfirmed + confirmed


def all_fail_atr_sensitivity_scenarios() -> list[Scenario]:
    exits = (("EMA", 1), ("EMA_VWAP", 2), ("EMA_VWAP_RSI", 3))
    result: list[Scenario] = []
    for multiplier, label in ((2.5, "25"), (3.0, "3")):
        result.extend(
            Scenario(
                f"BT{group}_{mode}_ALLFAIL_ATR14X{label}_UTC00_16",
                group,
                mode,
                entry_start_hour_utc=0,
                entry_end_hour_utc=16,
                exit_when_all_fail=True,
                atr_trailing_multiplier=multiplier,
            )
            for mode, group in exits
        )
        result.extend(
            Scenario(
                f"BT{group}_{mode}_MACD_ALLFAIL_ATR14X{label}_UTC00_16",
                group,
                mode,
                require_macd=True,
                entry_start_hour_utc=0,
                entry_end_hour_utc=16,
                exit_when_all_fail=True,
                atr_trailing_multiplier=multiplier,
            )
            for mode, group in exits
        )
    return result


def all_fail_macd_exit_scenarios() -> list[Scenario]:
    exits = (("EMA", 1), ("EMA_VWAP", 2), ("EMA_VWAP_RSI", 3))
    unconfirmed = [
        Scenario(
            f"BT{group}_{mode}_ALLFAIL_MACDEXIT_UTC00_16",
            group,
            mode,
            entry_start_hour_utc=0,
            entry_end_hour_utc=16,
            exit_when_all_fail=True,
            macd_reversal_exit=True,
        )
        for mode, group in exits
    ]
    confirmed = [
        Scenario(
            f"BT{group}_{mode}_MACD_ALLFAIL_MACDEXIT_UTC00_16",
            group,
            mode,
            require_macd=True,
            entry_start_hour_utc=0,
            entry_end_hour_utc=16,
            exit_when_all_fail=True,
            macd_reversal_exit=True,
        )
        for mode, group in exits
    ]
    return unconfirmed + confirmed


def macd_exit_policy_scenarios() -> list[Scenario]:
    exits = (("EMA", 1), ("EMA_VWAP", 2), ("EMA_VWAP_RSI", 3))
    policies = (
        ("MACDREV_ONLY", "REVERSAL_ONLY", False),
        ("ALLFAIL_WITH_MACD", "IN_ALL_FAIL", True),
        ("MACDREV_CONFIRM1_ONLY", "CONFIRMED_REVERSAL_ONLY", False),
    )
    result: list[Scenario] = []
    for suffix, policy, all_fail in policies:
        result.extend(
            Scenario(
                f"BT{group}_{mode}_{suffix}_UTC00_16",
                group,
                mode,
                entry_start_hour_utc=0,
                entry_end_hour_utc=16,
                exit_when_all_fail=all_fail,
                macd_exit_policy=policy,
            )
            for mode, group in exits
        )
        result.extend(
            Scenario(
                f"BT{group}_{mode}_MACD_{suffix}_UTC00_16",
                group,
                mode,
                require_macd=True,
                entry_start_hour_utc=0,
                entry_end_hour_utc=16,
                exit_when_all_fail=all_fail,
                macd_exit_policy=policy,
            )
            for mode, group in exits
        )
    return result


def locked_h6_scenarios() -> list[Scenario]:
    exits = (("EMA", 1), ("EMA_VWAP", 2), ("EMA_VWAP_RSI", 3))
    result: list[Scenario] = []
    for mode, group in exits:
        result.extend((
            Scenario(
                f"BT{group}_{mode}_ALLFAIL_MACDEXIT_H6_UTC00_16",
                group,
                mode,
                entry_start_hour_utc=0,
                entry_end_hour_utc=16,
                exit_when_all_fail=True,
                macd_reversal_exit=True,
                min_option_true_ranges=6,
            ),
            Scenario(
                f"BT{group}_{mode}_MACD_ALLFAIL_MACDEXIT_H6_UTC00_16",
                group,
                mode,
                require_macd=True,
                entry_start_hour_utc=0,
                entry_end_hour_utc=16,
                exit_when_all_fail=True,
                macd_reversal_exit=True,
                min_option_true_ranges=6,
            ),
            Scenario(
                f"BT{group}_{mode}_MACDREV_ONLY_H6_UTC00_16",
                group,
                mode,
                entry_start_hour_utc=0,
                entry_end_hour_utc=16,
                macd_exit_policy="REVERSAL_ONLY",
                min_option_true_ranges=6,
            ),
            Scenario(
                f"BT{group}_{mode}_MACD_MACDREV_ONLY_H6_UTC00_16",
                group,
                mode,
                require_macd=True,
                entry_start_hour_utc=0,
                entry_end_hour_utc=16,
                macd_exit_policy="REVERSAL_ONLY",
                min_option_true_ranges=6,
            ),
        ))
    return result


def _option_specs(path: Path) -> list[OptionSpec]:
    items: list[OptionSpec] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            items.append(OptionSpec(
                symbol=row["symbol"],
                source_symbol=row.get("source_symbol") or row["symbol"],
                expiry=row["expiry"],
                strike=float(row["strike"]),
                option_type=row["option_type"].upper(),
                activation_ns=timestamp_ns(row["activation"]),
                expiration_ns=timestamp_ns(row["expiration"]),
                price_precision=int(row["price_precision"]),
                size_precision=int(row["size_precision"]),
                price_increment=float(row["price_increment"]),
                size_increment=float(row["size_increment"]),
                lot_size=float(row["lot_size"]),
                min_quantity=float(row["min_quantity"]),
                contract_value=float(row["contract_value"]),
            ))
    return items


def atr_wilder(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float]:
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("ATR inputs must have equal lengths")
    output = [math.nan] * len(closes)
    if len(closes) < period:
        return output
    true_ranges = [float(highs[0]) - float(lows[0])]
    for index in range(1, len(closes)):
        true_ranges.append(max(
            float(highs[index]) - float(lows[index]),
            abs(float(highs[index]) - float(closes[index - 1])),
            abs(float(lows[index]) - float(closes[index - 1])),
        ))
    value = sum(true_ranges[:period]) / period
    output[period - 1] = value
    for index in range(period, len(closes)):
        value = (value * (period - 1) + true_ranges[index]) / period
        output[index] = value
    return output


def indicators(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["timestamp"]).set_index("timestamp").sort_index()
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["open", "high", "low", "close", "volume"])
    closes = frame["close"].astype(float).tolist()
    frame["ema9"] = ema(closes, 9)
    frame["ema20"] = ema(closes, 20)
    frame["ema50"] = ema(closes, 50)
    frame["rsi14"] = rsi_wilder(closes, 14)
    frame["atr14"] = atr_wilder(
        frame["high"].astype(float).tolist(),
        frame["low"].astype(float).tolist(),
        closes,
        14,
    )
    frame["macd"] = pd.Series(ema(closes, 12), index=frame.index) - pd.Series(
        ema(closes, 26), index=frame.index
    )
    frame["macd_signal"] = ema(frame["macd"].astype(float).tolist(), 9)
    local_dates = pd.Series(frame.index.tz_convert(IST).date, index=frame.index)
    typical_volume = ((frame["high"] + frame["low"] + frame["close"]) / 3.0) * frame["volume"]
    cumulative_value = typical_volume.groupby(local_dates).cumsum()
    cumulative_volume = frame["volume"].groupby(local_dates).cumsum()
    frame["vwap"] = cumulative_value.div(cumulative_volume.replace(0.0, math.nan))
    bull = (
        frame["close"].gt(frame["vwap"])
        & frame["ema9"].gt(frame["ema20"])
        & frame["ema20"].gt(frame["ema50"])
        & frame["rsi14"].between(50.0, 70.0, inclusive="both")
    )
    bear = (
        frame["close"].lt(frame["vwap"])
        & frame["ema9"].lt(frame["ema20"])
        & frame["ema20"].lt(frame["ema50"])
        & frame["rsi14"].between(30.0, 50.0, inclusive="both")
    )
    frame["direction"] = pd.Series(
        ["CALL" if up else "PUT" if down else "" for up, down in zip(bull, bear)],
        index=frame.index,
    )
    frame["entry_signal"] = frame["direction"].ne("") & frame["direction"].ne(
        frame["direction"].shift(1).fillna("")
    )
    macd_bull = frame["macd"].gt(frame["macd_signal"])
    macd_bear = frame["macd"].lt(frame["macd_signal"])
    frame["direction_macd"] = pd.Series(
        [
            direction
            if (direction == "CALL" and up) or (direction == "PUT" and down)
            else ""
            for direction, up, down in zip(frame["direction"], macd_bull, macd_bear)
        ],
        index=frame.index,
    )
    frame["entry_signal_macd"] = frame["direction_macd"].ne("") & frame[
        "direction_macd"
    ].ne(frame["direction_macd"].shift(1).fillna(""))
    return frame


def _select_option(
    specs: list[OptionSpec], signal_ns: int, direction: str, underlying: float
) -> OptionSpec | None:
    option_type = "CE" if direction == "CALL" else "PE"
    minimum_expiry = signal_ns + 24 * 60 * NS_MINUTE
    maximum_expiry = signal_ns + 3 * 24 * 60 * NS_MINUTE
    eligible = [
        item for item in specs
        if item.option_type == option_type
        and item.activation_ns <= signal_ns < item.expiration_ns
        and minimum_expiry <= item.expiration_ns <= maximum_expiry
    ]
    if not eligible:
        return None
    expiry = min(item.expiration_ns for item in eligible)
    return min(
        (item for item in eligible if item.expiration_ns == expiry),
        key=lambda item: (abs(item.strike - underlying), item.strike),
    )


def signal_events(
    frame: pd.DataFrame,
    specs: list[OptionSpec],
    start_ns: int,
    end_ns: int,
    confirmation_candles: int = 0,
    require_macd: bool = False,
    entry_start_hour_utc: int = 0,
    entry_end_hour_utc: int = 24,
) -> list[SignalEvent]:
    events: list[SignalEvent] = []
    direction_column = "direction_macd" if require_macd else "direction"
    signal_column = "entry_signal_macd" if require_macd else "entry_signal"
    signal_positions = [
        position for position, value in enumerate(frame[signal_column].tolist()) if value
    ]
    for position in signal_positions:
        direction = str(frame.iloc[position][direction_column])
        confirmed_position = position + confirmation_candles
        if confirmed_position >= len(frame):
            continue
        confirmation = frame.iloc[position:confirmed_position + 1]
        if not confirmation[direction_column].eq(direction).all():
            continue
        timestamp = frame.index[confirmed_position]
        row = frame.iloc[confirmed_position]
        if not entry_start_hour_utc <= timestamp.hour < entry_end_hour_utc:
            continue
        signal_ns = int(timestamp.timestamp() * 1_000_000_000)
        if not start_ns <= signal_ns < end_ns:
            continue
        option = _select_option(specs, signal_ns, direction, float(row["close"]))
        if option is not None:
            events.append(SignalEvent(
                signal_ns,
                direction,
                float(row["close"]),
                option,
                [],
            ))
    return events


def capture_quotes(path: Path, events: list[SignalEvent], horizon_minutes: int = 65) -> None:
    by_symbol: dict[str, list[SignalEvent]] = {}
    for event in events:
        by_symbol.setdefault(event.option.symbol, []).append(event)
    for selected in by_symbol.values():
        selected.sort(key=lambda item: item.timestamp_ns)
    horizon_ns = horizon_minutes * NS_MINUTE
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            selected = by_symbol.get(row["symbol"])
            if not selected:
                continue
            current_ns = timestamp_ns(row["timestamp"])
            quote = {
                "timestamp_ns": float(current_ns),
                "bid": float(row["bid"]),
                "ask": float(row["ask"]),
                "volume": float(row.get("volume") or 0.0),
                "open_interest": float(row.get("open_interest") or 0.0),
            }
            for event in selected:
                if event.timestamp_ns < current_ns <= event.timestamp_ns + horizon_ns:
                    event.quotes.append(quote)


def capture_option_true_ranges(
    directory: Path,
    events: list[SignalEvent],
    candle_seconds: int = 300,
) -> None:
    """Attach completed pre-signal option True Ranges from cached 1-minute OHLC."""
    by_source: dict[str, list[SignalEvent]] = {}
    for event in events:
        by_source.setdefault(event.option.source_symbol, []).append(event)
    root = directory / "raw" / "candles" / "1m"
    for source_symbol, selected in by_source.items():
        buckets: dict[int, dict[str, float]] = {}
        symbol_root = root / source_symbol
        for path in sorted(symbol_root.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            for row in payload.get("rows", []):
                try:
                    timestamp = int(row["time"])
                    high = float(row["high"])
                    low = float(row["low"])
                    close = float(row["close"])
                except (KeyError, TypeError, ValueError):
                    continue
                if not all(math.isfinite(value) and value > 0.0 for value in (high, low, close)):
                    continue
                if high < low:
                    continue
                bucket = timestamp // candle_seconds * candle_seconds
                current = buckets.get(bucket)
                if current is None:
                    buckets[bucket] = {
                        "high": high,
                        "low": low,
                        "close": close,
                        "close_time": float(timestamp),
                    }
                    continue
                current["high"] = max(current["high"], high)
                current["low"] = min(current["low"], low)
                if timestamp >= current["close_time"]:
                    current["close"] = close
                    current["close_time"] = float(timestamp)
        observations: list[tuple[int, float]] = []
        previous_close: float | None = None
        for bucket, candle in sorted(buckets.items()):
            if previous_close is not None:
                true_range = max(
                    candle["high"] - candle["low"],
                    abs(candle["high"] - previous_close),
                    abs(candle["low"] - previous_close),
                )
                if math.isfinite(true_range):
                    close_ns = (bucket + candle_seconds) * 1_000_000_000
                    observations.append((close_ns, true_range))
            previous_close = candle["close"]
        for event in selected:
            event.option_true_ranges = [
                value for close_ns, value in observations
                if close_ns <= event.timestamp_ns
            ]


def _condition_valid(row: pd.Series, direction: str, exit_mode: str) -> bool:
    call = direction == "CALL"
    ema_valid = (
        row["ema9"] > row["ema20"] > row["ema50"]
        if call else row["ema9"] < row["ema20"] < row["ema50"]
    )
    vwap_valid = row["close"] > row["vwap"] if call else row["close"] < row["vwap"]
    rsi_valid = 50.0 <= row["rsi14"] <= 70.0 if call else 30.0 <= row["rsi14"] <= 50.0
    if exit_mode == "EMA":
        return bool(ema_valid)
    if exit_mode == "EMA_VWAP":
        return bool(ema_valid and vwap_valid)
    return bool(ema_valid and vwap_valid and rsi_valid)


def _exit_triggered(row: pd.Series, direction: str, scenario: Scenario) -> bool:
    if not scenario.exit_when_all_fail:
        return not _condition_valid(row, direction, scenario.exit_mode)
    call = direction == "CALL"
    failures = [
        not (
            row["ema9"] > row["ema20"] > row["ema50"]
            if call else row["ema9"] < row["ema20"] < row["ema50"]
        )
    ]
    if scenario.exit_mode in {"EMA_VWAP", "EMA_VWAP_RSI"}:
        failures.append(
            not (row["close"] > row["vwap"] if call else row["close"] < row["vwap"])
        )
    if scenario.exit_mode == "EMA_VWAP_RSI":
        failures.append(
            not (
                50.0 <= row["rsi14"] <= 70.0
                if call else 30.0 <= row["rsi14"] <= 50.0
            )
        )
    return all(failures)


def protected_floor(entry: float, highest_bid: float, scenario: Scenario) -> float | None:
    if entry <= 0.0 or highest_bid <= entry:
        return None
    peak_profit = highest_bid - entry
    peak_percent = peak_profit / entry * 100.0
    if scenario.protection == "Z":
        if peak_percent < scenario.activation_percent:
            return None
        return entry + scenario.retention * peak_profit
    if scenario.protection == "E":
        if peak_percent >= 30.0:
            return entry + scenario.retention * peak_profit
        if peak_percent >= 15.0:
            return entry + 0.50 * peak_profit
        if peak_percent >= 10.0:
            return entry
    return None


def option_fee_components(
    *,
    spot: float,
    premium: float,
    quantity: float,
    contract_value: float,
    notional_rate: float = 0.0001,
    premium_cap_rate: float = 0.035,
    gst_rate: float = 0.18,
) -> tuple[float, float, float]:
    notional_fee = spot * quantity * contract_value * notional_rate
    premium_cap = premium * quantity * contract_value * premium_cap_rate
    base_fee = min(notional_fee, premium_cap)
    gst = base_fee * gst_rate
    return base_fee, gst, base_fee + gst


def _latest_underlying_close(frame: pd.DataFrame, timestamp_ns_value: int, fallback: float) -> float:
    timestamp = pd.Timestamp(timestamp_ns_value, unit="ns", tz="UTC")
    values = frame.loc[:timestamp, "close"].dropna()
    return float(values.iloc[-1]) if not values.empty else fallback


def _entry_rejection(
    event: SignalEvent,
    quote: dict[str, float],
    quantity: float,
    *,
    max_spread_percent: float,
    min_volume: float,
    volume_quantity_multiplier: float,
) -> str | None:
    midpoint = (quote["bid"] + quote["ask"]) / 2.0
    spread = math.inf if midpoint <= 0.0 else (quote["ask"] - quote["bid"]) / midpoint * 100.0
    if spread > max_spread_percent:
        return "SPREAD_TOO_WIDE"
    threshold = max(min_volume, quantity * volume_quantity_multiplier)
    if quote["volume"] < threshold:
        return "VOLUME_TOO_LOW"
    if quote["open_interest"] <= 0.0:
        return "OPEN_INTEREST_TOO_LOW"
    if quantity < event.option.min_quantity:
        return "PREMIUM_BUDGET_TOO_LOW"
    return None


def simulate_trade(
    event: SignalEvent,
    frame: pd.DataFrame,
    scenario: Scenario,
    *,
    premium_budget_usd: float,
    hard_stop_percent: float,
    max_hold_minutes: int,
    max_spread_percent: float,
    min_volume: float,
    volume_quantity_multiplier: float,
    option_fee_notional_rate: float = 0.0001,
    option_fee_premium_cap_rate: float = 0.035,
    fee_gst_rate: float = 0.18,
) -> tuple[dict[str, Any] | None, str | None]:
    if not event.quotes:
        return None, "QUOTE_UNAVAILABLE"
    if len(event.option_true_ranges) < scenario.min_option_true_ranges:
        return None, "OPTION_HISTORY_TOO_SHORT"
    entry_quote = event.quotes[0]
    entry_ns = int(entry_quote["timestamp_ns"])
    entry_hour_utc = datetime.fromtimestamp(entry_ns / 1e9, UTC).hour
    if not scenario.entry_start_hour_utc <= entry_hour_utc < scenario.entry_end_hour_utc:
        return None, "OUTSIDE_ENTRY_SESSION"
    quantity = calculate_quantity(
        budget_usd=premium_budget_usd,
        premium=entry_quote["ask"],
        contract_value=event.option.contract_value,
        min_quantity=event.option.min_quantity,
        quantity_step=event.option.size_increment,
        lot_size=event.option.lot_size,
    )
    rejection = _entry_rejection(
        event,
        entry_quote,
        quantity,
        max_spread_percent=max_spread_percent,
        min_volume=min_volume,
        volume_quantity_multiplier=volume_quantity_multiplier,
    )
    if rejection:
        return None, rejection
    deadline_ns = entry_ns + max_hold_minutes * NS_MINUTE
    entry = entry_quote["ask"]
    highest_bid = entry_quote["bid"]
    highest_underlying = event.underlying
    lowest_underlying = event.underlying
    entry_timestamp = pd.Timestamp(entry_ns, unit="ns", tz="UTC")
    completed_at_entry = frame.loc[:entry_timestamp]
    macd_exit_policy = scenario.macd_exit_policy
    if scenario.macd_reversal_exit and macd_exit_policy == "NONE":
        macd_exit_policy = "OR_ALL_FAIL"
    track_macd_exit = macd_exit_policy != "NONE"
    previous_macd_difference = (
        float(completed_at_entry.iloc[-1]["macd"])
        - float(completed_at_entry.iloc[-1]["macd_signal"])
        if track_macd_exit and not completed_at_entry.empty else math.nan
    )
    macd_confirmation_pending = False
    pending_reason = ""
    pending_ns = 0
    deadline_timestamp = pd.Timestamp(deadline_ns, unit="ns", tz="UTC")
    bars = frame.loc[
        (frame.index > entry_timestamp)
        & (frame.index <= deadline_timestamp)
    ]
    bar_rows = [
        (int(timestamp.timestamp() * 1_000_000_000), row)
        for timestamp, row in bars.iterrows()
    ]
    quote_rows = [
        (int(quote["timestamp_ns"]), quote)
        for quote in event.quotes
        if int(quote["timestamp_ns"]) > entry_ns
    ]
    timeline: list[tuple[int, int, Any]] = [
        *( (stamp, 0, row) for stamp, row in bar_rows ),
        *( (stamp, 1, quote) for stamp, quote in quote_rows ),
    ]
    timeline.sort(key=lambda item: (item[0], item[1]))
    exit_quote: dict[str, float] | None = None
    exit_reason = ""
    for current_ns, kind, payload in timeline:
        if kind == 0:
            if not pending_reason:
                current_macd_difference = (
                    float(payload["macd"]) - float(payload["macd_signal"])
                    if track_macd_exit else math.nan
                )
                macd_adverse = (
                    current_macd_difference <= 0.0
                    if event.direction == "CALL"
                    else current_macd_difference >= 0.0
                )
                macd_reversed = (
                    previous_macd_difference > 0.0
                    and current_macd_difference <= 0.0
                    if event.direction == "CALL"
                    else previous_macd_difference < 0.0
                    and current_macd_difference >= 0.0
                )
                condition_triggered = (
                    False
                    if macd_exit_policy in {
                        "REVERSAL_ONLY",
                        "CONFIRMED_REVERSAL_ONLY",
                    }
                    else _exit_triggered(payload, event.direction, scenario)
                )
                if macd_exit_policy == "IN_ALL_FAIL":
                    condition_triggered = condition_triggered and macd_adverse
                if condition_triggered:
                    pending_reason = "CONDITION_EXIT"
                    pending_ns = current_ns
                    continue
                if macd_exit_policy == "CONFIRMED_REVERSAL_ONLY":
                    if macd_confirmation_pending:
                        macd_confirmation_pending = False
                        if macd_adverse:
                            pending_reason = "MACD_CONFIRMED_REVERSAL_EXIT"
                            pending_ns = current_ns
                    elif macd_reversed:
                        macd_confirmation_pending = True
                elif macd_exit_policy in {"OR_ALL_FAIL", "REVERSAL_ONLY"}:
                    if macd_reversed:
                        pending_reason = "MACD_REVERSAL_EXIT"
                        pending_ns = current_ns
                if track_macd_exit:
                    previous_macd_difference = current_macd_difference
                if pending_reason:
                    continue
                highest_underlying = max(highest_underlying, float(payload["high"]))
                lowest_underlying = min(lowest_underlying, float(payload["low"]))
                atr_value = float(payload.get("atr14", math.nan))
                if scenario.atr_trailing_multiplier > 0.0 and math.isfinite(atr_value):
                    if event.direction == "CALL":
                        atr_stop = (
                            highest_underlying
                            - scenario.atr_trailing_multiplier * atr_value
                        )
                        atr_hit = float(payload["close"]) <= atr_stop
                    else:
                        atr_stop = (
                            lowest_underlying
                            + scenario.atr_trailing_multiplier * atr_value
                        )
                        atr_hit = float(payload["close"]) >= atr_stop
                    if atr_hit:
                        pending_reason = "ATR_TRAILING_STOP"
                        pending_ns = current_ns
            continue
        quote = payload
        if pending_reason and current_ns > pending_ns:
            exit_quote, exit_reason = quote, pending_reason
            break
        if current_ns >= deadline_ns:
            exit_quote, exit_reason = quote, "MAX_HOLD"
            break
        highest_bid = max(highest_bid, quote["bid"])
        pnl_percent = (quote["bid"] - entry) / entry * 100.0
        fixed_stop = (
            max(0.0, entry - scenario.stop_loss_points)
            if scenario.stop_loss_points > 0.0 else None
        )
        stop_hit = (
            quote["bid"] <= fixed_stop
            if fixed_stop is not None else pnl_percent <= hard_stop_percent
        )
        if stop_hit:
            pending_reason, pending_ns = "HARD_STOP", current_ns
            continue
        floor = protected_floor(entry, highest_bid, scenario)
        if floor is not None and quote["bid"] <= floor:
            pending_reason, pending_ns = "PROTECTED_STOP", current_ns
    if exit_quote is None:
        return None, "EXIT_QUOTE_UNAVAILABLE"
    exit_bid = exit_quote["bid"]
    exit_ns = int(exit_quote["timestamp_ns"])
    entry_spot = event.underlying
    exit_spot = _latest_underlying_close(frame, exit_ns, entry_spot)
    entry_fee_base, entry_fee_gst, entry_fee = option_fee_components(
        spot=entry_spot,
        premium=entry,
        quantity=quantity,
        contract_value=event.option.contract_value,
        notional_rate=option_fee_notional_rate,
        premium_cap_rate=option_fee_premium_cap_rate,
        gst_rate=fee_gst_rate,
    )
    exit_fee_base, exit_fee_gst, exit_fee = option_fee_components(
        spot=exit_spot,
        premium=exit_bid,
        quantity=quantity,
        contract_value=event.option.contract_value,
        notional_rate=option_fee_notional_rate,
        premium_cap_rate=option_fee_premium_cap_rate,
        gst_rate=fee_gst_rate,
    )
    gross_pnl_usd = (exit_bid - entry) * event.option.contract_value * quantity
    fees_usd = entry_fee + exit_fee
    pnl_usd = gross_pnl_usd - fees_usd
    return {
        "scenario": scenario.name,
        "group": scenario.group,
        "signal_time": datetime.fromtimestamp(event.timestamp_ns / 1e9, UTC).isoformat(),
        "entry_time": datetime.fromtimestamp(entry_ns / 1e9, UTC).isoformat(),
        "exit_time": datetime.fromtimestamp(int(exit_quote["timestamp_ns"]) / 1e9, UTC).isoformat(),
        "direction": event.direction,
        "symbol": event.option.symbol,
        "quantity": quantity,
        "entry_ask": entry,
        "exit_bid": exit_bid,
        "entry_spot": entry_spot,
        "exit_spot": exit_spot,
        "highest_bid": highest_bid,
        "exit_reason": exit_reason,
        "holding_minutes": (int(exit_quote["timestamp_ns"]) - entry_ns) / NS_MINUTE,
        "gross_pnl_usd": gross_pnl_usd,
        "entry_fee_base_usd": entry_fee_base,
        "entry_fee_gst_usd": entry_fee_gst,
        "entry_fee_usd": entry_fee,
        "exit_fee_base_usd": exit_fee_base,
        "exit_fee_gst_usd": exit_fee_gst,
        "exit_fee_usd": exit_fee,
        "fees_usd": fees_usd,
        "pnl_usd": pnl_usd,
        "return_percent": (exit_bid - entry) / entry * 100.0,
    }, None


def _metrics(trades: list[dict[str, Any]], starting_balance: float) -> dict[str, Any]:
    pnl = [float(item["pnl_usd"]) for item in trades]
    gross_profit = sum(value for value in pnl if value > 0.0)
    gross_loss = abs(sum(value for value in pnl if value < 0.0))
    equity = starting_balance
    peak = starting_balance
    drawdown = 0.0
    for value in pnl:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "trades": len(trades),
        "wins": sum(value > 0.0 for value in pnl),
        "losses": sum(value < 0.0 for value in pnl),
        "win_rate_percent": 100.0 * sum(value > 0.0 for value in pnl) / len(pnl) if pnl else None,
        "net_pnl_usd": sum(pnl),
        "return_percent": 100.0 * sum(pnl) / starting_balance,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0.0 else None,
        "expectancy_usd": sum(pnl) / len(pnl) if pnl else None,
        "max_drawdown_usd": drawdown,
        "exit_reasons": {
            reason: sum(item["exit_reason"] == reason for item in trades)
            for reason in sorted({str(item["exit_reason"]) for item in trades})
        },
    }


def run_dataset(
    directory: Path,
    *,
    start: str,
    end: str,
    starting_balance: float = 100.0,
    premium_budget_usd: float = 6.67,
    hard_stop_percent: float = -15.0,
    max_hold_minutes: int = 60,
    max_spread_percent: float = 3.0,
    min_volume: float = 30.0,
    volume_quantity_multiplier: float = 5.0,
    option_fee_notional_rate: float = 0.0001,
    option_fee_premium_cap_rate: float = 0.035,
    fee_gst_rate: float = 0.18,
    scenario_set: list[Scenario] | None = None,
) -> dict[str, Any]:
    start_ns, end_ns = timestamp_ns(start), timestamp_ns(end)
    frame = indicators(directory / "underlying_bars.csv")
    specs = _option_specs(directory / "option_instruments.csv")
    selected_scenarios = scenario_set or scenarios()
    event_keys = sorted({
        (
            item.confirmation_candles,
            item.require_macd,
            item.entry_start_hour_utc,
            item.entry_end_hour_utc,
        )
        for item in selected_scenarios
    })
    events_by_configuration = {
        (candles, require_macd, start_hour, end_hour): signal_events(
            frame,
            specs,
            start_ns,
            end_ns,
            confirmation_candles=candles,
            require_macd=require_macd,
            entry_start_hour_utc=start_hour,
            entry_end_hour_utc=end_hour,
        )
        for candles, require_macd, start_hour, end_hour in event_keys
    }
    capture_quotes(
        directory / "option_quotes.csv",
        [event for events in events_by_configuration.values() for event in events],
    )
    results: list[dict[str, Any]] = []
    all_trades: list[dict[str, Any]] = []
    for scenario in selected_scenarios:
        events = events_by_configuration[
            (
                scenario.confirmation_candles,
                scenario.require_macd,
                scenario.entry_start_hour_utc,
                scenario.entry_end_hour_utc,
            )
        ]
        trades: list[dict[str, Any]] = []
        rejects: dict[str, int] = {}
        available_after_ns = start_ns
        for event in events:
            if event.timestamp_ns <= available_after_ns:
                continue
            trade, rejection = simulate_trade(
                event,
                frame,
                scenario,
                premium_budget_usd=premium_budget_usd,
                hard_stop_percent=hard_stop_percent,
                max_hold_minutes=max_hold_minutes,
                max_spread_percent=max_spread_percent,
                min_volume=min_volume,
                volume_quantity_multiplier=volume_quantity_multiplier,
                option_fee_notional_rate=option_fee_notional_rate,
                option_fee_premium_cap_rate=option_fee_premium_cap_rate,
                fee_gst_rate=fee_gst_rate,
            )
            if rejection:
                rejects[rejection] = rejects.get(rejection, 0) + 1
                continue
            assert trade is not None
            trades.append(trade)
            all_trades.append(trade)
            available_after_ns = timestamp_ns(str(trade["exit_time"]))
        results.append({
            "scenario": asdict(scenario),
            "metrics": _metrics(trades, starting_balance),
            "rejects": rejects,
        })
    return {
        "data_directory": str(directory.resolve()),
        "start": start,
        "end": end,
        "raw_signals_with_contract": (
            len(events_by_configuration[event_keys[0]])
            if len(event_keys) == 1
            else {
                f"confirmation={candles},macd={require_macd},utc={start_hour:02d}-{end_hour:02d}": len(
                    events_by_configuration[(candles, require_macd, start_hour, end_hour)]
                )
                for candles, require_macd, start_hour, end_hour in event_keys
            }
        ),
        "settings": {
            "starting_balance": starting_balance,
            "premium_budget_usd": premium_budget_usd,
            "hard_stop_percent": hard_stop_percent,
            "max_hold_minutes": max_hold_minutes,
            "max_spread_percent": max_spread_percent,
            "min_volume": min_volume,
            "volume_quantity_multiplier": volume_quantity_multiplier,
            "fill_mode": "NEXT_QUOTE",
            "fees": {
                "option_notional_rate": option_fee_notional_rate,
                "option_premium_cap_rate": option_fee_premium_cap_rate,
                "gst_rate": fee_gst_rate,
                "charged_on": "ENTRY_AND_EXIT",
                "spot_proxy": "latest completed 5-minute BTC close",
            },
            "fidelity": "LOW_FIDELITY_SYNTHETIC_BBO",
            "vwap": "HLC3 volume-weighted, reset 00:00 Asia/Kolkata",
        },
        "results": results,
        "trades": all_trades,
    }


def write_report(report: dict[str, Any], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    trades = report.get("trades", [])
    if trades:
        with (output / "trades.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(trades[0]))
            writer.writeheader()
            writer.writerows(trades)


def _summary_rows(report: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for dataset in report["datasets"]:
        label = Path(dataset["data_directory"]).name
        for result in dataset["results"]:
            yield {
                "dataset": label,
                "scenario": result["scenario"]["name"],
                **result["metrics"],
            }


def main() -> None:
    parser = argparse.ArgumentParser(description="Self-contained EMA/VWAP/RSI option-strategy matrix research")
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--study",
        choices=(
            "matrix",
            "activation",
            "stoploss",
            "confirmation",
            "macd",
            "utc_session",
            "all_fail_exit",
            "all_fail_z50",
            "all_fail_atr",
            "all_fail_atr_sensitivity",
            "all_fail_macd_exit",
            "macd_exit_policies",
        ),
        default="matrix",
        help=(
            "Run the original matrix, Z55 activation sensitivity, BT2 point stops, "
            "delayed confirmation, or MACD entry confirmation."
        ),
    )
    args = parser.parse_args()
    studies = {
        "matrix": scenarios,
        "activation": activation_scenarios,
        "stoploss": stop_loss_scenarios,
        "confirmation": confirmation_scenarios,
        "macd": macd_scenarios,
        "utc_session": utc_session_scenarios,
        "all_fail_exit": all_fail_exit_scenarios,
        "all_fail_z50": all_fail_z50_scenarios,
        "all_fail_atr": all_fail_atr_scenarios,
        "all_fail_atr_sensitivity": all_fail_atr_sensitivity_scenarios,
        "all_fail_macd_exit": all_fail_macd_exit_scenarios,
        "macd_exit_policies": macd_exit_policy_scenarios,
    }
    selected_scenarios = studies[args.study]()
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "method": "Research-only calculation backtest.",
        "study": args.study,
        "scenario_count": len(selected_scenarios),
        "datasets": [
            run_dataset(
                args.development,
                start="2026-08-24T00:00:00Z",
                end="2026-09-23T00:00:00Z",
                scenario_set=selected_scenarios,
            ),
            run_dataset(
                args.holdout,
                start="2026-07-25T00:00:00Z",
                end="2026-08-24T00:00:00Z",
                scenario_set=selected_scenarios,
            ),
        ],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "matrix_summary.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    rows = list(_summary_rows(report))
    with (args.output / "matrix_summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for dataset in report["datasets"]:
        label = Path(dataset["data_directory"]).name
        write_report(dataset, args.output / label)
    print(f"EMA/VWAP research complete: {args.output.resolve()}")


if __name__ == "__main__":
    main()
