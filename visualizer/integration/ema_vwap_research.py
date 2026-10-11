from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from backtest.calculations import calculate_quantity, ema, required_entry_volume, rsi_wilder

from .data import OptionSpec, timestamp_ns


UTC = timezone.utc
IST = ZoneInfo("Asia/Kolkata")
NS_MINUTE = 60 * 1_000_000_000


@dataclass(frozen=True)
class PullbackReversalConfig:
    enabled: bool = False
    lookback_candles: int = 4
    touch_ema20: bool = True
    touch_vwap: bool = True
    require_ema_slope: bool = False
    allow_flat_ema50: bool = True
    max_touch_close_distance_atr: float | None = 0.2
    use_actual_pullback_sequence: bool = True
    rsi_enabled: bool = True
    bull_rsi_min: float = 40.0
    bull_rsi_max: float = 55.0
    bear_rsi_min: float = 45.0
    bear_rsi_max: float = 60.0
    atr_enabled: bool = True
    atr_reversal_multiplier: float = 0.4


@dataclass(frozen=True)
class MomentumBreakoutConfig:
    enabled: bool = False
    lookback_candles: int = 6
    breakout_buffer_atr: float = 0.0
    min_volume_ratio: float = 1.25
    min_vwap_displacement_atr: float = 1.0
    min_ema_strength_atr: float = 0.0
    max_ema_strength_atr: float | None = 0.75


@dataclass(frozen=True)
class EarlyFailureConfig:
    enabled: bool = False
    monitor_candles: int = 3
    condition_mode: str = "ANY"
    exit_on_vwap_failure: bool = True
    vwap_reclaim_candles: int = 0
    exit_on_structure_break: bool = True
    structure_lookback_candles: int = 4
    exit_on_ema9_ema20_cross: bool = True


@dataclass(frozen=True)
class ExecutionConfig:
    mode: str = "FULL_BBO"
    size_participation_rate: float = 1.0
    size_capacity_multiplier: float = 1.0
    entry_fill_timeout_seconds: float = 0.0
    minimum_entry_fill_percent: float = 0.0
    max_entry_quote_delay_seconds: float | None = None
    max_exit_quote_delay_seconds: float | None = None
    exit_fill_timeout_seconds: float | None = 300.0
    unfilled_exit_policy: str = "ZERO"


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
    require_stoch_rsi_entry: bool = False
    require_stoch_rsi_momentum_entry: bool = False
    entry_start_hour_utc: int = 0
    entry_end_hour_utc: int = 24
    entry_windows_ist_minutes: tuple[tuple[int, int], ...] = ()
    blocked_weekdays_ist: tuple[int, ...] = ()
    exit_when_all_fail: bool = False
    atr_trailing_multiplier: float = 0.0
    macd_reversal_exit: bool = False
    macd_exit_policy: str = "NONE"
    min_option_true_ranges: int = 0
    fee_aware_multiplier: float = 0.0
    directional_confirmation_minutes: int = 0
    entry_min_conditions: int = 3
    one_trade_per_ema_regime: bool = False
    min_ema_strength_atr: float = 0.0
    min_vwap_displacement_atr: float = 0.0
    min_signal_volume_ratio: float = 0.0
    min_days_to_expiry: float = 1.0
    min_days_to_expiry_inclusive: bool = True
    max_days_to_expiry: float = 3.0
    hard_stop_percent_override: float | None = None
    hard_stop_fill_mode: str = "NEXT_QUOTE"
    ema_exit_rule: str = "STRICT_ORDER"
    pullback_reversal: PullbackReversalConfig = field(
        default_factory=PullbackReversalConfig
    )
    entry_mode: str = "BASELINE"
    momentum_breakout: MomentumBreakoutConfig = field(
        default_factory=MomentumBreakoutConfig
    )
    early_failure: EarlyFailureConfig = field(default_factory=EarlyFailureConfig)
    fixed_protected_profit_percent: float = 0.0
    max_ema_strength_atr: float | None = None


@dataclass
class SignalEvent:
    timestamp_ns: int
    direction: str
    underlying: float
    option: OptionSpec
    quotes: list[dict[str, float]]
    option_true_ranges: list[float] = field(default_factory=list)
    ema_regime_start_ns: int = 0
    entry_type: str = "BASELINE"
    execution_attempt: dict[str, Any] | None = None


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


def stoch_scenarios() -> list[Scenario]:
    return [
        Scenario("BT1_EMA_STOCH", 1, "EMA", require_stoch_rsi_entry=True),
        Scenario(
            "BT2_EMA_VWAP_STOCH",
            2,
            "EMA_VWAP",
            require_stoch_rsi_entry=True,
        ),
        Scenario(
            "BT3_EMA_VWAP_RSI_STOCH",
            3,
            "EMA_VWAP_RSI",
            require_stoch_rsi_entry=True,
        ),
    ]


def stoch_momentum_scenarios() -> list[Scenario]:
    return [
        Scenario(
            "BT1_EMA_STOCH_KGT_D",
            1,
            "EMA",
            require_stoch_rsi_momentum_entry=True,
        ),
        Scenario(
            "BT2_EMA_VWAP_STOCH_KGT_D",
            2,
            "EMA_VWAP",
            require_stoch_rsi_momentum_entry=True,
        ),
        Scenario(
            "BT3_EMA_VWAP_RSI_STOCH_KGT_D",
            3,
            "EMA_VWAP_RSI",
            require_stoch_rsi_momentum_entry=True,
        ),
    ]


def entry_condition_count_scenarios() -> list[Scenario]:
    """Compare 1-of-3, 2-of-3, and 3-of-3 entries across BT1-BT3 exits."""
    exits = (("EMA", 1), ("EMA_VWAP", 2), ("EMA_VWAP_RSI", 3))
    return [
        Scenario(
            f"BT{group}_{mode}_ENTRY{minimum}OF3",
            group,
            mode,
            entry_min_conditions=minimum,
        )
        for minimum in (1, 2, 3)
        for mode, group in exits
    ]


def one_trade_per_ema_regime_scenarios() -> list[Scenario]:
    return [
        Scenario("BT2_EMA_VWAP_CONTROL", 2, "EMA_VWAP"),
        Scenario(
            "BT2_EMA_VWAP_ONE_PER_EMA_REGIME",
            2,
            "EMA_VWAP",
            one_trade_per_ema_regime=True,
        ),
    ]


def ema_strength_scenarios() -> list[Scenario]:
    return [
        Scenario(
            "BT2_EMA_VWAP_ONE_PER_REGIME_STRENGTH_CONTROL",
            2,
            "EMA_VWAP",
            one_trade_per_ema_regime=True,
        ),
        *[
            Scenario(
                f"BT2_EMA_VWAP_ONE_PER_REGIME_STRENGTH_{int(value * 100):03d}",
                2,
                "EMA_VWAP",
                one_trade_per_ema_regime=True,
                min_ema_strength_atr=value,
            )
            for value in (0.25, 0.50, 0.75, 1.00)
        ],
    ]


def vwap_volume_scenarios() -> list[Scenario]:
    common = {
        "group": 2,
        "exit_mode": "EMA_VWAP",
        "one_trade_per_ema_regime": True,
    }
    return [
        Scenario("BT2_ONE_PER_REGIME_CONTROL", **common),
        Scenario(
            "BT2_ONE_PER_REGIME_VWAP_DISPLACEMENT_150",
            **common,
            min_vwap_displacement_atr=1.50,
        ),
        Scenario(
            "BT2_ONE_PER_REGIME_VOLUME_EXPANSION_125",
            **common,
            min_signal_volume_ratio=1.25,
        ),
        Scenario(
            "BT2_ONE_PER_REGIME_VWAP_150_VOLUME_125",
            **common,
            min_vwap_displacement_atr=1.50,
            min_signal_volume_ratio=1.25,
        ),
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


def locked_h6_fa_scenarios(multiplier: float) -> list[Scenario]:
    label = str(int(round(multiplier * 100)))
    return [
        replace(
            scenario,
            name=scenario.name.replace("_H6_", f"_H6_FA{label}_"),
            fee_aware_multiplier=multiplier,
        )
        for scenario in locked_h6_scenarios()
    ]


def locked_h6_fa150_m30_scenarios() -> list[Scenario]:
    return [
        replace(
            scenario,
            name=scenario.name.replace("_FA150_", "_FA150_M30_"),
            directional_confirmation_minutes=30,
        )
        for scenario in locked_h6_fa_scenarios(1.50)
    ]


def locked_h6_fa150_m30_stoch_scenarios() -> list[Scenario]:
    baseline_name = "BT1_EMA_MACD_MACDREV_ONLY_H6_FA150_M30_UTC00_16"
    baseline = next(
        scenario
        for scenario in locked_h6_fa150_m30_scenarios()
        if scenario.name == baseline_name
    )
    return [replace(
        baseline,
        name=baseline.name.replace("_M30_", "_M30_STOCH_"),
        require_stoch_rsi_entry=True,
    )]


def locked_m30_scenarios() -> list[Scenario]:
    return [
        replace(
            scenario,
            name=scenario.name.replace("_H6_", "_M30_"),
            min_option_true_ranges=0,
            directional_confirmation_minutes=30,
        )
        for scenario in locked_h6_scenarios()
    ]


def locked_h6_fa150_utc08_scenarios() -> list[Scenario]:
    return [
        replace(
            scenario,
            name=scenario.name.replace("_UTC00_16", "_UTC08_16"),
            entry_start_hour_utc=8,
        )
        for scenario in locked_h6_fa_scenarios(1.50)
    ]


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


def _stoch_rsi_entry_direction(direction: str, k_value: float, d_value: float) -> str:
    if not (math.isfinite(k_value) and math.isfinite(d_value)):
        return ""
    if direction == "CALL" and d_value > k_value:
        return direction
    if direction == "PUT" and k_value > d_value:
        return direction
    return ""


def _stoch_rsi_momentum_entry_direction(
    direction: str,
    k_value: float,
    d_value: float,
) -> str:
    if not (math.isfinite(k_value) and math.isfinite(d_value)):
        return ""
    if direction == "CALL" and k_value > d_value:
        return direction
    if direction == "PUT" and d_value > k_value:
        return direction
    return ""


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
    rsi_values = frame["rsi14"]
    stoch_low = rsi_values.rolling(14, min_periods=14).min()
    stoch_high = rsi_values.rolling(14, min_periods=14).max()
    stoch_range = (stoch_high - stoch_low).replace(0.0, math.nan)
    stoch_raw = 100.0 * (rsi_values - stoch_low) / stoch_range
    frame["stoch_rsi_k"] = stoch_raw.rolling(3, min_periods=3).mean()
    frame["stoch_rsi_d"] = frame["stoch_rsi_k"].rolling(3, min_periods=3).mean()
    frame["atr14"] = atr_wilder(
        frame["high"].astype(float).tolist(),
        frame["low"].astype(float).tolist(),
        closes,
        14,
    )
    frame["volume_median20_prior"] = frame["volume"].shift(1).rolling(
        20,
        min_periods=20,
    ).median()
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
    for source in ("direction", "direction_macd"):
        target = f"{source}_stoch"
        frame[target] = pd.Series(
            [
                _stoch_rsi_entry_direction(direction, k_value, d_value)
                for direction, k_value, d_value in zip(
                    frame[source], frame["stoch_rsi_k"], frame["stoch_rsi_d"]
                )
            ],
            index=frame.index,
        )
        signal_target = (
            "entry_signal_macd_stoch"
            if source == "direction_macd"
            else "entry_signal_stoch"
        )
        frame[signal_target] = frame[target].ne("") & frame[target].ne(
            frame[target].shift(1).fillna("")
        )
        momentum_target = f"{source}_stoch_momentum"
        frame[momentum_target] = pd.Series(
            [
                _stoch_rsi_momentum_entry_direction(direction, k_value, d_value)
                for direction, k_value, d_value in zip(
                    frame[source], frame["stoch_rsi_k"], frame["stoch_rsi_d"]
                )
            ],
            index=frame.index,
        )
        momentum_signal_target = (
            "entry_signal_macd_stoch_momentum"
            if source == "direction_macd"
            else "entry_signal_stoch_momentum"
        )
        frame[momentum_signal_target] = frame[momentum_target].ne("") & frame[
            momentum_target
        ].ne(frame[momentum_target].shift(1).fillna(""))
    return frame


def _select_option(
    specs: list[OptionSpec],
    signal_ns: int,
    direction: str,
    underlying: float,
    *,
    min_days_to_expiry: float = 1.0,
    min_days_to_expiry_inclusive: bool = True,
    max_days_to_expiry: float = 3.0,
) -> OptionSpec | None:
    if min_days_to_expiry < 0.0 or max_days_to_expiry < min_days_to_expiry:
        raise ValueError("invalid option expiry range")
    option_type = "CE" if direction == "CALL" else "PE"
    day_ns = 24 * 60 * NS_MINUTE
    minimum_expiry = signal_ns + int(min_days_to_expiry * day_ns)
    maximum_expiry = signal_ns + int(max_days_to_expiry * day_ns)
    eligible = [
        item for item in specs
        if item.option_type == option_type
        and item.activation_ns <= signal_ns < item.expiration_ns
        and (
            item.expiration_ns >= minimum_expiry
            if min_days_to_expiry_inclusive
            else item.expiration_ns > minimum_expiry
        )
        and item.expiration_ns <= maximum_expiry
    ]
    if not eligible:
        return None
    expiry = min(item.expiration_ns for item in eligible)
    return min(
        (item for item in eligible if item.expiration_ns == expiry),
        key=lambda item: (abs(item.strike - underlying), item.strike),
    )



def _decision_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _append_decision_event(
    target: list[dict[str, Any]] | None,
    *,
    timestamp: Any,
    stage: str,
    status: str,
    reason: str,
    direction: str,
    row: Any | None = None,
    entry_type: str = "",
    symbol: str = "",
) -> None:
    if target is None:
        return
    values: dict[str, Any] = {}
    if row is not None:
        for key in (
            "open", "high", "low", "close", "volume", "ema9", "ema20", "ema50",
            "vwap", "rsi14", "atr14", "volume_median20_prior",
        ):
            value = _decision_float(row.get(key))
            if value is not None:
                values[key] = value
        atr = _decision_float(row.get("atr14"))
        close = _decision_float(row.get("close"))
        vwap = _decision_float(row.get("vwap"))
        ema9 = _decision_float(row.get("ema9"))
        ema50 = _decision_float(row.get("ema50"))
        volume = _decision_float(row.get("volume"))
        volume_median = _decision_float(row.get("volume_median20_prior"))
        if volume is not None and volume_median not in {None, 0.0}:
            values["volume_ratio"] = volume / volume_median
        if atr not in {None, 0.0}:
            if ema9 is not None and ema50 is not None:
                values["ema_strength_atr"] = abs(ema9 - ema50) / atr
            if close is not None and vwap is not None:
                values["vwap_displacement_atr"] = abs(close - vwap) / atr
    time_text = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
    target.append({
        "timestamp": time_text,
        "stage": stage,
        "status": status,
        "reason": reason,
        "direction": direction,
        "entry_type": entry_type,
        "symbol": symbol,
        **values,
    })


def pullback_reversal_directions(
    frame: pd.DataFrame,
    config: PullbackReversalConfig,
    diagnostics: dict[str, int] | None = None,
    diagnostic_eligible: pd.Series | None = None,
    decision_events: list[dict[str, Any]] | None = None,
) -> pd.Series:
    """Return confirmed CALL/PUT pullback reversals using completed candles."""
    if not config.enabled:
        return pd.Series("", index=frame.index, dtype="object")
    if not 1 <= config.lookback_candles <= 20:
        raise ValueError("pullback lookback_candles must be between 1 and 20")
    if not config.touch_ema20 and not config.touch_vwap:
        raise ValueError("pullback must enable touch_ema20, touch_vwap, or both")
    if not config.bull_rsi_min <= config.bull_rsi_max:
        raise ValueError("bull pullback RSI minimum cannot exceed maximum")
    if not config.bear_rsi_min <= config.bear_rsi_max:
        raise ValueError("bear pullback RSI minimum cannot exceed maximum")
    if config.atr_reversal_multiplier < 0.0:
        raise ValueError("ATR reversal multiplier cannot be negative")
    if (
        config.max_touch_close_distance_atr is not None
        and config.max_touch_close_distance_atr < 0.0
    ):
        raise ValueError("pullback touch ATR distance cannot be negative")

    required = {
        "high",
        "low",
        "close",
        "ema9",
        "ema20",
        "ema50",
        "vwap",
        "rsi14",
        "atr14",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(
            "pullback reversal frame is missing columns: " + ", ".join(missing)
        )

    directions = [""] * len(frame)
    for position in range(1, len(frame)):
        row = frame.iloc[position]
        previous = frame.iloc[position - 1]
        window = frame.iloc[
            max(0, position - config.lookback_candles):position
        ]
        if window.empty:
            continue

        bull_base_trend = bool(
            row["ema9"] > row["ema20"] > row["ema50"]
            and row["close"] > row["vwap"]
        )
        bear_base_trend = bool(
            row["ema9"] < row["ema20"] < row["ema50"]
            and row["close"] < row["vwap"]
        )
        bull_slope = True
        bear_slope = True
        if config.require_ema_slope:
            ema50_bullish = (
                row["ema50"] >= previous["ema50"]
                if config.allow_flat_ema50
                else row["ema50"] > previous["ema50"]
            )
            ema50_bearish = (
                row["ema50"] <= previous["ema50"]
                if config.allow_flat_ema50
                else row["ema50"] < previous["ema50"]
            )
            bull_slope = bool(
                row["ema9"] > previous["ema9"]
                and row["ema20"] > previous["ema20"]
                and ema50_bullish
            )
            bear_slope = bool(
                row["ema9"] < previous["ema9"]
                and row["ema20"] < previous["ema20"]
                and ema50_bearish
            )

        bull_raw_touches = pd.Series(False, index=window.index)
        bear_raw_touches = pd.Series(False, index=window.index)
        bull_touches = pd.Series(False, index=window.index)
        bear_touches = pd.Series(False, index=window.index)
        if config.touch_ema20:
            bull_ema20_raw = window["low"].le(window["ema20"])
            bear_ema20_raw = window["high"].ge(window["ema20"])
            bull_ema20 = bull_ema20_raw.copy()
            bear_ema20 = bear_ema20_raw.copy()
            if config.atr_enabled and config.max_touch_close_distance_atr is not None:
                tolerance = config.max_touch_close_distance_atr * window["atr14"]
                bull_ema20 &= window["close"].ge(window["ema20"] - tolerance)
                bear_ema20 &= window["close"].le(window["ema20"] + tolerance)
            bull_raw_touches |= bull_ema20_raw
            bear_raw_touches |= bear_ema20_raw
            bull_touches |= bull_ema20
            bear_touches |= bear_ema20
        if config.touch_vwap:
            bull_vwap_raw = window["low"].le(window["vwap"])
            bear_vwap_raw = window["high"].ge(window["vwap"])
            bull_vwap = bull_vwap_raw.copy()
            bear_vwap = bear_vwap_raw.copy()
            if config.atr_enabled and config.max_touch_close_distance_atr is not None:
                tolerance = config.max_touch_close_distance_atr * window["atr14"]
                bull_vwap &= window["close"].ge(window["vwap"] - tolerance)
                bear_vwap &= window["close"].le(window["vwap"] + tolerance)
            bull_raw_touches |= bull_vwap_raw
            bear_raw_touches |= bear_vwap_raw
            bull_touches |= bull_vwap
            bear_touches |= bear_vwap

        def pullback_sequence(touches: pd.Series) -> pd.DataFrame:
            positions = [
                index for index, touched in enumerate(touches.tolist()) if touched
            ]
            if not positions:
                return window.iloc[0:0]
            if not config.use_actual_pullback_sequence:
                return window
            start = positions[-1]
            while start > 0 and bool(touches.iloc[start - 1]):
                start -= 1
            return window.iloc[start:]

        bull_pullback = pullback_sequence(bull_touches)
        bear_pullback = pullback_sequence(bear_touches)

        bull_confirmation = bool(
            row["close"] > row["ema9"]
            and row["close"] > previous["high"]
        )
        bear_confirmation = bool(
            row["close"] < row["ema9"]
            and row["close"] < previous["low"]
        )

        bull_rsi = True
        bear_rsi = True
        if config.rsi_enabled:
            bull_rsi = bool(
                bull_pullback["rsi14"].between(
                    config.bull_rsi_min,
                    config.bull_rsi_max,
                    inclusive="both",
                ).any()
                and row["rsi14"] > previous["rsi14"]
            )
            bear_rsi = bool(
                bear_pullback["rsi14"].between(
                    config.bear_rsi_min,
                    config.bear_rsi_max,
                    inclusive="both",
                ).any()
                and row["rsi14"] < previous["rsi14"]
            )

        bull_atr = True
        bear_atr = True
        if config.atr_enabled:
            atr = float(row["atr14"])
            bull_atr = bool(
                math.isfinite(atr)
                and atr > 0.0
                and not bull_pullback.empty
                and row["close"] - bull_pullback["low"].min()
                >= config.atr_reversal_multiplier * atr
            )
            bear_atr = bool(
                math.isfinite(atr)
                and atr > 0.0
                and not bear_pullback.empty
                and bear_pullback["high"].max() - row["close"]
                >= config.atr_reversal_multiplier * atr
            )

        call = (
            bull_base_trend
            and bull_slope
            and bool(bull_touches.any())
            and bull_confirmation
            and bull_rsi
            and bull_atr
        )
        put = (
            bear_base_trend
            and bear_slope
            and bool(bear_touches.any())
            and bear_confirmation
            and bear_rsi
            and bear_atr
        )
        collect_diagnostics = diagnostics is not None and (
            diagnostic_eligible is None or bool(diagnostic_eligible.iloc[position])
        )
        if collect_diagnostics:
            assert diagnostics is not None
            diagnostics["CANDLES_EVALUATED"] = (
                diagnostics.get("CANDLES_EVALUATED", 0) + 1
            )
            for direction, stages in (
                (
                    "CALL",
                    (
                        bull_base_trend,
                        bull_slope,
                        bool(bull_raw_touches.any()),
                        bool(bull_touches.any()),
                        bull_rsi,
                        bull_confirmation,
                        bull_atr,
                    ),
                ),
                (
                    "PUT",
                    (
                        bear_base_trend,
                        bear_slope,
                        bool(bear_raw_touches.any()),
                        bool(bear_touches.any()),
                        bear_rsi,
                        bear_confirmation,
                        bear_atr,
                    ),
                ),
            ):
                (
                    base_trend,
                    slope_ok,
                    raw_touch,
                    qualified_touch,
                    rsi_ok,
                    confirmation_ok,
                    atr_ok,
                ) = stages
                if not base_trend:
                    continue
                diagnostics["TREND_CANDIDATES"] = (
                    diagnostics.get("TREND_CANDIDATES", 0) + 1
                )
                if not slope_ok:
                    diagnostics["SLOPE_REJECTED"] = (
                        diagnostics.get("SLOPE_REJECTED", 0) + 1
                    )
                    continue
                if not raw_touch:
                    diagnostics["TOUCH_REJECTED"] = (
                        diagnostics.get("TOUCH_REJECTED", 0) + 1
                    )
                    continue
                if not qualified_touch:
                    diagnostics["TOUCH_TOLERANCE_REJECTED"] = (
                        diagnostics.get("TOUCH_TOLERANCE_REJECTED", 0) + 1
                    )
                    continue
                if not rsi_ok:
                    diagnostics["RSI_REJECTED"] = (
                        diagnostics.get("RSI_REJECTED", 0) + 1
                    )
                    continue
                if not confirmation_ok:
                    diagnostics["CONFIRMATION_REJECTED"] = (
                        diagnostics.get("CONFIRMATION_REJECTED", 0) + 1
                    )
                    continue
                if not atr_ok:
                    diagnostics["ATR_REJECTED"] = (
                        diagnostics.get("ATR_REJECTED", 0) + 1
                    )
                    continue
                diagnostics["QUALIFYING_CANDLES"] = (
                    diagnostics.get("QUALIFYING_CANDLES", 0) + 1
                )
                key = f"{direction}_QUALIFYING_CANDLES"
                diagnostics[key] = diagnostics.get(key, 0) + 1
        collect_decisions = decision_events is not None and (
            diagnostic_eligible is None or bool(diagnostic_eligible.iloc[position])
        )
        if collect_decisions:
            for direction, stages in (
                (
                    "CALL",
                    (
                        bull_base_trend,
                        bull_slope,
                        bool(bull_raw_touches.any()),
                        bool(bull_touches.any()),
                        bull_rsi,
                        bull_confirmation,
                        bull_atr,
                    ),
                ),
                (
                    "PUT",
                    (
                        bear_base_trend,
                        bear_slope,
                        bool(bear_raw_touches.any()),
                        bool(bear_touches.any()),
                        bear_rsi,
                        bear_confirmation,
                        bear_atr,
                    ),
                ),
            ):
                base_trend, slope_ok, raw_touch, qualified_touch, rsi_ok, confirmation_ok, atr_ok = stages
                if not base_trend:
                    continue
                reason = (
                    "SLOPE_REJECTED" if not slope_ok
                    else "TOUCH_REJECTED" if not raw_touch
                    else "TOUCH_TOLERANCE_REJECTED" if not qualified_touch
                    else "RSI_REJECTED" if not rsi_ok
                    else "CONFIRMATION_REJECTED" if not confirmation_ok
                    else "ATR_REJECTED" if not atr_ok
                    else "QUALIFIED"
                )
                _append_decision_event(
                    decision_events,
                    timestamp=frame.index[position],
                    stage="ZIGZAG",
                    status="QUALIFIED" if reason == "QUALIFIED" else "REJECTED",
                    reason=reason,
                    direction=direction,
                    row=row,
                    entry_type="ZIGZAG",
                )
        directions[position] = (
            "CALL" if call and not put else "PUT" if put and not call else ""
        )
    return pd.Series(directions, index=frame.index, dtype="object")


def momentum_breakout_directions(
    frame: pd.DataFrame,
    config: MomentumBreakoutConfig,
    diagnostics: dict[str, int] | None = None,
    diagnostic_eligible: pd.Series | None = None,
    decision_events: list[dict[str, Any]] | None = None,
) -> pd.Series:
    """Return trend-aligned range breakouts using completed 5-minute candles."""
    if not config.enabled:
        return pd.Series("", index=frame.index, dtype="object")
    if not 1 <= config.lookback_candles <= 100:
        raise ValueError("momentum lookback_candles must be between 1 and 100")
    if config.breakout_buffer_atr < 0.0:
        raise ValueError("momentum breakout_buffer_atr cannot be negative")
    if config.min_volume_ratio < 0.0:
        raise ValueError("momentum min_volume_ratio cannot be negative")
    if config.min_vwap_displacement_atr < 0.0:
        raise ValueError("momentum min_vwap_displacement_atr cannot be negative")
    if config.min_ema_strength_atr < 0.0:
        raise ValueError("momentum min_ema_strength_atr cannot be negative")
    if (
        config.max_ema_strength_atr is not None
        and config.max_ema_strength_atr < config.min_ema_strength_atr
    ):
        raise ValueError(
            "momentum max_ema_strength_atr must be at least min_ema_strength_atr"
        )

    directions = [""] * len(frame)
    for position in range(config.lookback_candles, len(frame)):
        row = frame.iloc[position]
        direction = str(row["direction"])
        if not direction:
            continue
        collect = diagnostics is not None and (
            diagnostic_eligible is None or bool(diagnostic_eligible.iloc[position])
        )
        if collect:
            diagnostics["TREND_CANDIDATES"] = diagnostics.get("TREND_CANDIDATES", 0) + 1
        window = frame.iloc[position - config.lookback_candles:position]
        atr = float(row.get("atr14", math.nan))
        close = float(row["close"])
        buffer = config.breakout_buffer_atr * atr if math.isfinite(atr) else math.nan
        breakout = bool(
            math.isfinite(buffer)
            and (
                close > float(window["high"].max()) + buffer
                if direction == "CALL"
                else close < float(window["low"].min()) - buffer
            )
        )
        volume_median = float(row.get("volume_median20_prior", math.nan))
        volume_ratio = (
            float(row["volume"]) / volume_median
            if math.isfinite(volume_median) and volume_median > 0.0
            else math.nan
        )
        vwap_displacement = (
            abs(close - float(row["vwap"])) / atr
            if math.isfinite(atr) and atr > 0.0
            else math.nan
        )
        ema_strength = (
            abs(float(row["ema9"]) - float(row["ema50"])) / atr
            if math.isfinite(atr) and atr > 0.0
            else math.nan
        )
        checks = (
            (breakout, "BREAKOUT_REJECTED"),
            (
                math.isfinite(volume_ratio)
                and volume_ratio >= config.min_volume_ratio,
                "VOLUME_REJECTED",
            ),
            (
                math.isfinite(vwap_displacement)
                and vwap_displacement >= config.min_vwap_displacement_atr,
                "VWAP_DISPLACEMENT_REJECTED",
            ),
            (
                math.isfinite(ema_strength)
                and ema_strength >= config.min_ema_strength_atr,
                "EMA_STRENGTH_TOO_LOW",
            ),
            (
                config.max_ema_strength_atr is None
                or (
                    math.isfinite(ema_strength)
                    and ema_strength <= config.max_ema_strength_atr
                ),
                "EMA_STRENGTH_TOO_HIGH",
            ),
        )
        rejection = next((reason for passed, reason in checks if not passed), None)
        if decision_events is not None and (
            diagnostic_eligible is None or bool(diagnostic_eligible.iloc[position])
        ):
            _append_decision_event(
                decision_events,
                timestamp=frame.index[position],
                stage="MOMENTUM",
                status="REJECTED" if rejection is not None else "QUALIFIED",
                reason=rejection or "QUALIFIED",
                direction=direction,
                row=row,
                entry_type="MOMENTUM",
            )
        if rejection is not None:
            if collect:
                diagnostics[rejection] = diagnostics.get(rejection, 0) + 1
            continue
        directions[position] = direction
        if collect:
            diagnostics["QUALIFYING_CANDLES"] = (
                diagnostics.get("QUALIFYING_CANDLES", 0) + 1
            )
            key = f"{direction}_QUALIFYING_CANDLES"
            diagnostics[key] = diagnostics.get(key, 0) + 1
    return pd.Series(directions, index=frame.index, dtype="object")


def signal_events(
    frame: pd.DataFrame,
    specs: list[OptionSpec],
    start_ns: int,
    end_ns: int,
    confirmation_candles: int = 0,
    require_macd: bool = False,
    require_stoch_rsi_entry: bool = False,
    require_stoch_rsi_momentum_entry: bool = False,
    entry_start_hour_utc: int = 0,
    entry_end_hour_utc: int = 24,
    entry_windows_ist_minutes: tuple[tuple[int, int], ...] = (),
    blocked_weekdays_ist: tuple[int, ...] = (),
    entry_min_conditions: int = 3,
    min_days_to_expiry: float = 1.0,
    min_days_to_expiry_inclusive: bool = True,
    max_days_to_expiry: float = 3.0,
    pullback_reversal: PullbackReversalConfig = PullbackReversalConfig(),
    entry_mode: str = "BASELINE",
    momentum_breakout: MomentumBreakoutConfig = MomentumBreakoutConfig(),
    signal_diagnostics: dict[str, int] | None = None,
    decision_events: list[dict[str, Any]] | None = None,
) -> list[SignalEvent]:
    if require_stoch_rsi_entry and require_stoch_rsi_momentum_entry:
        raise ValueError("only one Stoch RSI entry relationship can be enabled")
    if entry_min_conditions not in {1, 2, 3}:
        raise ValueError("entry_min_conditions must be 1, 2, or 3")
    entry_mode = entry_mode.strip().upper().replace("-", "_")
    # Preserve configurations created before entry_mode existed.
    if entry_mode == "BASELINE":
        if pullback_reversal.enabled and momentum_breakout.enabled:
            entry_mode = "BOTH"
        elif pullback_reversal.enabled:
            entry_mode = "ZIGZAG"
        elif momentum_breakout.enabled:
            entry_mode = "MOMENTUM"
    if entry_mode not in {"BASELINE", "ZIGZAG", "MOMENTUM", "BOTH"}:
        raise ValueError("entry_mode must be BASELINE, ZIGZAG, MOMENTUM, or BOTH")
    events: list[SignalEvent] = []
    direction_column = "direction_macd" if require_macd else "direction"
    signal_column = "entry_signal_macd" if require_macd else "entry_signal"
    entry_types = pd.Series("BASELINE", index=frame.index, dtype="object")
    if entry_mode in {"ZIGZAG", "BOTH"}:
        frame = frame.copy()
        diagnostic_eligible = pd.Series(
            [
                start_ns <= int(timestamp.timestamp() * 1_000_000_000) < end_ns
                and _entry_time_allowed(
                    timestamp,
                    entry_start_hour_utc=entry_start_hour_utc,
                    entry_end_hour_utc=entry_end_hour_utc,
                    entry_windows_ist_minutes=entry_windows_ist_minutes,
                    blocked_weekdays_ist=blocked_weekdays_ist,
                )
                for timestamp in frame.index
            ],
            index=frame.index,
        )
        pullback_direction = pullback_reversal_directions(
            frame,
            replace(pullback_reversal, enabled=True),
            diagnostics=signal_diagnostics,
            diagnostic_eligible=diagnostic_eligible,
            decision_events=decision_events,
        )
        if require_macd:
            pullback_direction = pd.Series(
                [
                    direction
                    if (
                        direction == "CALL" and macd > signal
                    ) or (
                        direction == "PUT" and macd < signal
                    )
                    else ""
                    for direction, macd, signal in zip(
                        pullback_direction,
                        frame["macd"],
                        frame["macd_signal"],
                    )
                ],
                index=frame.index,
            )
        frame["_pullback_reversal_direction"] = pullback_direction
        frame["_pullback_reversal_signal"] = pullback_direction.ne("") & pullback_direction.ne(
            pullback_direction.shift(1).fillna("")
        )
    if entry_mode in {"MOMENTUM", "BOTH"}:
        if not momentum_breakout.enabled:
            momentum_breakout = replace(momentum_breakout, enabled=True)
        if "diagnostic_eligible" not in locals():
            diagnostic_eligible = pd.Series(
                [
                    start_ns <= int(timestamp.timestamp() * 1_000_000_000) < end_ns
                    and _entry_time_allowed(
                        timestamp,
                        entry_start_hour_utc=entry_start_hour_utc,
                        entry_end_hour_utc=entry_end_hour_utc,
                        entry_windows_ist_minutes=entry_windows_ist_minutes,
                        blocked_weekdays_ist=blocked_weekdays_ist,
                    )
                    for timestamp in frame.index
                ],
                index=frame.index,
            )
        momentum_direction = momentum_breakout_directions(
            frame,
            momentum_breakout,
            diagnostics=signal_diagnostics if entry_mode == "MOMENTUM" else None,
            diagnostic_eligible=diagnostic_eligible,
            decision_events=decision_events,
        )
        if require_macd:
            momentum_direction = pd.Series(
                [
                    direction
                    if (direction == "CALL" and macd > signal)
                    or (direction == "PUT" and macd < signal)
                    else ""
                    for direction, macd, signal in zip(
                        momentum_direction, frame["macd"], frame["macd_signal"]
                    )
                ],
                index=frame.index,
            )
        frame["_momentum_direction"] = momentum_direction
        frame["_momentum_signal"] = momentum_direction.ne("") & momentum_direction.ne(
            momentum_direction.shift(1).fillna("")
        )
    if entry_mode == "ZIGZAG":
        direction_column = "_pullback_reversal_direction"
        signal_column = "_pullback_reversal_signal"
        entry_types = pd.Series("ZIGZAG", index=frame.index, dtype="object")
    elif entry_mode == "MOMENTUM":
        direction_column = "_momentum_direction"
        signal_column = "_momentum_signal"
        entry_types = pd.Series("MOMENTUM", index=frame.index, dtype="object")
    elif entry_mode == "BOTH":
        pullback_signal = frame["_pullback_reversal_signal"]
        momentum_signal = frame["_momentum_signal"]
        combined_direction: list[str] = []
        combined_signal: list[bool] = []
        combined_type: list[str] = []
        for pullback, pullback_is_signal, momentum, momentum_is_signal in zip(
            frame["_pullback_reversal_direction"],
            pullback_signal,
            frame["_momentum_direction"],
            momentum_signal,
        ):
            directions = {
                value
                for value, active in (
                    (str(pullback), bool(pullback_is_signal)),
                    (str(momentum), bool(momentum_is_signal)),
                )
                if active and value
            }
            direction = next(iter(directions)) if len(directions) == 1 else ""
            combined_direction.append(direction)
            combined_signal.append(bool(direction))
            combined_type.append(
                "ZIGZAG+MOMENTUM"
                if pullback_is_signal and momentum_is_signal and direction
                else "ZIGZAG"
                if pullback_is_signal and direction
                else "MOMENTUM"
                if momentum_is_signal and direction
                else ""
            )
        direction_column = "_combined_entry_direction"
        signal_column = "_combined_entry_signal"
        frame[direction_column] = combined_direction
        frame[signal_column] = combined_signal
        entry_types = pd.Series(combined_type, index=frame.index, dtype="object")
    elif entry_min_conditions < 3:
        call_score = (
            frame["close"].gt(frame["vwap"]).astype(int)
            + (frame["ema9"].gt(frame["ema20"]) & frame["ema20"].gt(frame["ema50"])).astype(int)
            + frame["rsi14"].between(50.0, 70.0, inclusive="both").astype(int)
        )
        put_score = (
            frame["close"].lt(frame["vwap"]).astype(int)
            + (frame["ema9"].lt(frame["ema20"]) & frame["ema20"].lt(frame["ema50"])).astype(int)
            + frame["rsi14"].between(30.0, 50.0, inclusive="both").astype(int)
        )
        scored_direction = pd.Series(
            [
                "CALL"
                if call >= entry_min_conditions and call > put
                else "PUT"
                if put >= entry_min_conditions and put > call
                else ""
                for call, put in zip(call_score, put_score)
            ],
            index=frame.index,
        )
        if require_macd:
            scored_direction = pd.Series(
                [
                    direction
                    if (
                        direction == "CALL" and macd > signal
                    ) or (
                        direction == "PUT" and macd < signal
                    )
                    else ""
                    for direction, macd, signal in zip(
                        scored_direction, frame["macd"], frame["macd_signal"]
                    )
                ],
                index=frame.index,
            )
        direction_column = "_entry_score_direction"
        signal_column = "_entry_score_signal"
        frame = frame.copy()
        frame[direction_column] = scored_direction
        frame[signal_column] = scored_direction.ne("") & scored_direction.ne(
            scored_direction.shift(1).fillna("")
        )
    signal_positions = [
        position for position, value in enumerate(frame[signal_column].tolist()) if value
    ]
    ema_regime_starts: list[int] = []
    if {"ema9", "ema20", "ema50"}.issubset(frame.columns):
        previous_regime = ""
        regime_start_ns = 0
        for timestamp, regime_row in frame.iterrows():
            regime = (
                "CALL"
                if regime_row["ema9"] > regime_row["ema20"] > regime_row["ema50"]
                else "PUT"
                if regime_row["ema9"] < regime_row["ema20"] < regime_row["ema50"]
                else ""
            )
            if regime != previous_regime:
                regime_start_ns = (
                    int(timestamp.timestamp() * 1_000_000_000) if regime else 0
                )
            ema_regime_starts.append(regime_start_ns if regime else 0)
            previous_regime = regime
    else:
        ema_regime_starts = [0] * len(frame)
    for position in signal_positions:
        direction = str(frame.iloc[position][direction_column])
        confirmed_position = position + confirmation_candles
        if confirmed_position >= len(frame):
            _append_decision_event(
                decision_events, timestamp=frame.index[position], stage="SIGNAL",
                status="REJECTED", reason="CONFIRMATION_OUT_OF_RANGE",
                direction=direction, row=frame.iloc[position], entry_type=str(entry_types.iloc[position]),
            )
            continue
        confirmation = frame.iloc[position:confirmed_position + 1]
        if not confirmation[direction_column].eq(direction).all():
            _append_decision_event(
                decision_events, timestamp=frame.index[confirmed_position], stage="SIGNAL",
                status="REJECTED", reason="SIGNAL_CONFIRMATION_REJECTED",
                direction=direction, row=frame.iloc[confirmed_position], entry_type=str(entry_types.iloc[position]),
            )
            continue
        timestamp = frame.index[confirmed_position]
        row = frame.iloc[confirmed_position]
        if require_stoch_rsi_entry and not _stoch_rsi_entry_direction(
            direction,
            float(row["stoch_rsi_k"]),
            float(row["stoch_rsi_d"]),
        ):
            _append_decision_event(
                decision_events, timestamp=timestamp, stage="SIGNAL", status="REJECTED",
                reason="STOCH_RSI_REJECTED", direction=direction, row=row,
                entry_type=str(entry_types.iloc[position]),
            )
            continue
        if (
            require_stoch_rsi_momentum_entry
            and not _stoch_rsi_momentum_entry_direction(
                direction,
                float(row["stoch_rsi_k"]),
                float(row["stoch_rsi_d"]),
            )
        ):
            _append_decision_event(
                decision_events, timestamp=timestamp, stage="SIGNAL", status="REJECTED",
                reason="STOCH_RSI_MOMENTUM_REJECTED", direction=direction, row=row,
                entry_type=str(entry_types.iloc[position]),
            )
            continue
        if not _entry_time_allowed(
            timestamp,
            entry_start_hour_utc=entry_start_hour_utc,
            entry_end_hour_utc=entry_end_hour_utc,
            entry_windows_ist_minutes=entry_windows_ist_minutes,
            blocked_weekdays_ist=blocked_weekdays_ist,
        ):
            _append_decision_event(
                decision_events, timestamp=timestamp, stage="SIGNAL", status="REJECTED",
                reason="OUTSIDE_ENTRY_SESSION", direction=direction, row=row,
                entry_type=str(entry_types.iloc[position]),
            )
            continue
        signal_ns = int(timestamp.timestamp() * 1_000_000_000)
        if not start_ns <= signal_ns < end_ns:
            continue
        if signal_diagnostics is not None and pullback_reversal.enabled:
            signal_diagnostics["SIGNALS"] = (
                signal_diagnostics.get("SIGNALS", 0) + 1
            )
            key = f"{direction}_SIGNALS"
            signal_diagnostics[key] = signal_diagnostics.get(key, 0) + 1
        option = _select_option(
            specs,
            signal_ns,
            direction,
            float(row["close"]),
            min_days_to_expiry=min_days_to_expiry,
            min_days_to_expiry_inclusive=min_days_to_expiry_inclusive,
            max_days_to_expiry=max_days_to_expiry,
        )
        if option is not None:
            _append_decision_event(
                decision_events, timestamp=timestamp, stage="SIGNAL", status="QUALIFIED",
                reason="SIGNAL_WITH_CONTRACT", direction=direction, row=row,
                entry_type=str(entry_types.iloc[position]), symbol=option.symbol,
            )
            if signal_diagnostics is not None and pullback_reversal.enabled:
                signal_diagnostics["SIGNALS_WITH_CONTRACT"] = (
                    signal_diagnostics.get("SIGNALS_WITH_CONTRACT", 0) + 1
                )
            events.append(SignalEvent(
                signal_ns,
                direction,
                float(row["close"]),
                option,
                [],
                ema_regime_start_ns=ema_regime_starts[confirmed_position],
                entry_type=str(entry_types.iloc[position]),
            ))
        else:
            _append_decision_event(
                decision_events, timestamp=timestamp, stage="SIGNAL", status="REJECTED",
                reason="NO_ELIGIBLE_OPTION_REJECTED", direction=direction, row=row,
                entry_type=str(entry_types.iloc[position]),
            )
            if signal_diagnostics is not None and pullback_reversal.enabled:
                signal_diagnostics["NO_ELIGIBLE_OPTION_REJECTED"] = (
                    signal_diagnostics.get("NO_ELIGIBLE_OPTION_REJECTED", 0) + 1
                )
    return events


def _entry_time_allowed(
    timestamp: datetime | pd.Timestamp,
    *,
    entry_start_hour_utc: int = 0,
    entry_end_hour_utc: int = 24,
    entry_windows_ist_minutes: tuple[tuple[int, int], ...] = (),
    blocked_weekdays_ist: tuple[int, ...] = (),
) -> bool:
    value = timestamp.to_pydatetime() if isinstance(timestamp, pd.Timestamp) else timestamp
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    utc_value = value.astimezone(UTC)
    ist_value = utc_value.astimezone(IST)
    if ist_value.weekday() in blocked_weekdays_ist:
        return False
    if entry_windows_ist_minutes:
        minute = ist_value.hour * 60 + ist_value.minute
        return any(start <= minute < end for start, end in entry_windows_ist_minutes)
    return entry_start_hour_utc <= utc_value.hour < entry_end_hour_utc


def capture_quotes(
    path: Path,
    events: list[SignalEvent],
    horizon_minutes: float | None = 65,
) -> None:
    by_symbol: dict[str, list[SignalEvent]] = {}
    for event in events:
        by_symbol.setdefault(event.option.symbol, []).append(event)
    for selected in by_symbol.values():
        selected.sort(key=lambda item: item.timestamp_ns)
    horizon_ns = (
        int(horizon_minutes * NS_MINUTE)
        if horizon_minutes is not None
        else None
    )
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
                "bid_size": float(row.get("bid_size") or 0.0),
                "ask_size": float(row.get("ask_size") or 0.0),
                "volume": float(row.get("volume") or 0.0),
                "open_interest": float(row.get("open_interest") or 0.0),
            }
            for event in selected:
                capture_end_ns = (
                    event.timestamp_ns + horizon_ns
                    if horizon_ns is not None
                    else event.option.expiration_ns
                )
                capture_end_ns = min(capture_end_ns, event.option.expiration_ns)
                if event.timestamp_ns < current_ns <= capture_end_ns:
                    event.quotes.append(quote)


def option_true_range_observations(
    rows: Iterable[dict[str, Any]],
    candle_seconds: int = 300,
) -> list[tuple[int, float]]:
    buckets: dict[int, dict[str, float]] = {}
    for row in rows:
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
    return observations


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
        rows: list[dict[str, Any]] = []
        for path in sorted((root / source_symbol).glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows.extend(payload.get("rows", []))
        observations = option_true_range_observations(rows, candle_seconds)
        for event in selected:
            event.option_true_ranges = [
                value for close_ns, value in observations
                if close_ns <= event.timestamp_ns
            ]


def _ema_exit_valid(row: pd.Series, direction: str, ema_exit_rule: str) -> bool:
    call = direction == "CALL"
    if ema_exit_rule == "STRICT_ORDER":
        return bool(
            row["ema9"] > row["ema20"] > row["ema50"]
            if call else row["ema9"] < row["ema20"] < row["ema50"]
        )
    if ema_exit_rule == "FAST_AND_MID_VS_SLOW":
        return bool(
            row["ema9"] > row["ema50"] and row["ema20"] > row["ema50"]
            if call
            else row["ema9"] < row["ema50"] and row["ema20"] < row["ema50"]
        )
    if ema_exit_rule == "FAST_OR_MID_VS_SLOW":
        return bool(
            row["ema9"] > row["ema50"] or row["ema20"] > row["ema50"]
            if call
            else row["ema9"] < row["ema50"] or row["ema20"] < row["ema50"]
        )
    raise ValueError(
        "ema_exit_rule must be STRICT_ORDER, FAST_AND_MID_VS_SLOW, "
        "or FAST_OR_MID_VS_SLOW"
    )


def _condition_valid(
    row: pd.Series,
    direction: str,
    exit_mode: str,
    ema_exit_rule: str = "STRICT_ORDER",
) -> bool:
    call = direction == "CALL"
    ema_valid = _ema_exit_valid(row, direction, ema_exit_rule)
    vwap_valid = row["close"] > row["vwap"] if call else row["close"] < row["vwap"]
    rsi_valid = 50.0 <= row["rsi14"] <= 70.0 if call else 30.0 <= row["rsi14"] <= 50.0
    if exit_mode == "EMA":
        return bool(ema_valid)
    if exit_mode == "EMA_VWAP":
        return bool(ema_valid and vwap_valid)
    return bool(ema_valid and vwap_valid and rsi_valid)


def _exit_triggered(row: pd.Series, direction: str, scenario: Scenario) -> bool:
    if not scenario.exit_when_all_fail:
        return not _condition_valid(
            row,
            direction,
            scenario.exit_mode,
            scenario.ema_exit_rule,
        )
    call = direction == "CALL"
    failures = [
        not _ema_exit_valid(row, direction, scenario.ema_exit_rule)
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
    if scenario.protection == "FIXED":
        if peak_percent < scenario.activation_percent:
            return None
        return entry * (1.0 + scenario.fixed_protected_profit_percent / 100.0)
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


def _directional_confirmation_valid(
    frame: pd.DataFrame,
    event: SignalEvent,
    minutes: int,
) -> bool:
    if minutes <= 0:
        return True
    if minutes % 5:
        raise ValueError("directional confirmation must use whole 5-minute candles")
    timestamp = pd.Timestamp(event.timestamp_ns, unit="ns", tz="UTC")
    completed = frame.loc[:timestamp, "close"].dropna()
    lookback = minutes // 5
    if len(completed) <= lookback:
        return False
    move = float(completed.iloc[-1]) - float(completed.iloc[-lookback - 1])
    return move > 0.0 if event.direction == "CALL" else move < 0.0


def _ema_strength_atr(frame: pd.DataFrame, event: SignalEvent) -> float:
    timestamp = pd.Timestamp(event.timestamp_ns, unit="ns", tz="UTC")
    completed = frame.loc[:timestamp]
    if completed.empty:
        return math.nan
    row = completed.iloc[-1]
    atr = float(row.get("atr14", math.nan))
    ema9 = float(row.get("ema9", math.nan))
    ema50 = float(row.get("ema50", math.nan))
    if not all(math.isfinite(value) for value in (atr, ema9, ema50)) or atr <= 0.0:
        return math.nan
    return abs(ema9 - ema50) / atr


def _signal_entry_features(
    frame: pd.DataFrame,
    event: SignalEvent,
) -> tuple[float, float]:
    timestamp = pd.Timestamp(event.timestamp_ns, unit="ns", tz="UTC")
    completed = frame.loc[:timestamp]
    if completed.empty:
        return math.nan, math.nan
    row = completed.iloc[-1]
    atr = float(row.get("atr14", math.nan))
    close = float(row.get("close", math.nan))
    vwap = float(row.get("vwap", math.nan))
    volume = float(row.get("volume", math.nan))
    volume_median = float(row.get("volume_median20_prior", math.nan))
    vwap_displacement_atr = (
        abs(close - vwap) / atr
        if all(math.isfinite(value) for value in (close, vwap, atr)) and atr > 0.0
        else math.nan
    )
    signal_volume_ratio = (
        volume / volume_median
        if all(math.isfinite(value) for value in (volume, volume_median))
        and volume_median > 0.0
        else math.nan
    )
    return vwap_displacement_atr, signal_volume_ratio


def _early_failure_structure(
    frame: pd.DataFrame,
    event: SignalEvent,
    config: EarlyFailureConfig,
) -> float:
    if frame.empty:
        return math.nan
    timestamp = pd.Timestamp(event.timestamp_ns, unit="ns", tz="UTC")
    prior = frame.loc[frame.index < timestamp].tail(config.structure_lookback_candles)
    if prior.empty:
        return math.nan
    column = "low" if event.direction == "CALL" else "high"
    return float(prior[column].min() if event.direction == "CALL" else prior[column].max())


def _early_failure_reason(
    row: pd.Series,
    direction: str,
    config: EarlyFailureConfig,
    structure_level: float,
    vwap_failure_confirmed: bool,
) -> str | None:
    call = direction == "CALL"
    checks: list[tuple[str, bool]] = []
    if config.exit_on_vwap_failure:
        checks.append(("VWAP", vwap_failure_confirmed))
    if config.exit_on_structure_break:
        checks.append(
            (
                "STRUCTURE",
                math.isfinite(structure_level)
                and (
                    float(row["close"]) < structure_level
                    if call
                    else float(row["close"]) > structure_level
                ),
            )
        )
    if config.exit_on_ema9_ema20_cross:
        checks.append(
            (
                "EMA9_EMA20",
                float(row["ema9"]) <= float(row["ema20"])
                if call
                else float(row["ema9"]) >= float(row["ema20"]),
            )
        )
    if not checks:
        return None
    failed = [name for name, value in checks if value]
    triggered = bool(failed) if config.condition_mode == "ANY" else len(failed) == len(checks)
    if not triggered:
        return None
    suffix = "_".join(failed) if config.condition_mode == "ANY" else "ALL"
    return f"EARLY_FAILURE_{suffix}"


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


def _capacity_fill_quantity(
    displayed_size: float,
    remaining: float,
    quantity_step: float,
    config: ExecutionConfig,
) -> float:
    capacity = max(0.0, displayed_size)
    capacity *= config.size_participation_rate * config.size_capacity_multiplier
    candidate = min(remaining, capacity)
    step = max(quantity_step, 1e-12)
    units = math.floor((candidate + 1e-12) / step)
    return min(remaining, units * step)


def _entry_execution(
    quotes: list[dict[str, float]],
    requested_quantity: float,
    quantity_step: float,
    config: ExecutionConfig,
) -> dict[str, Any]:
    first = quotes[0]
    if config.mode == "FULL_BBO":
        return {
            "quantity": requested_quantity,
            "average_price": float(first["ask"]),
            "timestamp_ns": float(first["timestamp_ns"]),
            "first_quote_timestamp_ns": float(first["timestamp_ns"]),
            "fill_quotes": 1.0,
            "quotes_observed": 1,
            "displayed_ask_size_sum": float(first.get("ask_size", 0.0)),
            "participating_capacity_sum": requested_quantity,
            "executable_capacity_sum": requested_quantity,
        }
    start_ns = int(first["timestamp_ns"])
    deadline_ns = start_ns + int(config.entry_fill_timeout_seconds * 1e9)
    remaining = requested_quantity
    filled = 0.0
    cost = 0.0
    last_fill_ns = start_ns
    fill_quotes = 0
    quotes_observed = 0
    displayed_ask_size_sum = 0.0
    participating_capacity_sum = 0.0
    executable_capacity_sum = 0.0
    for quote in quotes:
        quote_ns = int(quote["timestamp_ns"])
        if quote_ns > deadline_ns:
            break
        displayed_size = max(0.0, float(quote.get("ask_size", 0.0)))
        quotes_observed += 1
        displayed_ask_size_sum += displayed_size
        participating_capacity_sum += (
            displayed_size
            * config.size_participation_rate
            * config.size_capacity_multiplier
        )
        fill = _capacity_fill_quantity(
            displayed_size,
            remaining,
            quantity_step,
            config,
        )
        if fill <= 0.0:
            continue
        filled += fill
        remaining = max(0.0, requested_quantity - filled)
        cost += fill * float(quote["ask"])
        executable_capacity_sum += fill
        last_fill_ns = quote_ns
        fill_quotes += 1
        if remaining <= 1e-12:
            break
    return {
        "quantity": filled,
        "average_price": cost / filled if filled > 0.0 else math.nan,
        "timestamp_ns": float(last_fill_ns),
        "first_quote_timestamp_ns": float(first["timestamp_ns"]),
        "fill_quotes": float(fill_quotes),
        "quotes_observed": quotes_observed,
        "displayed_ask_size_sum": displayed_ask_size_sum,
        "participating_capacity_sum": participating_capacity_sum,
        "executable_capacity_sum": executable_capacity_sum,
    }


def _exit_execution(
    quotes: list[dict[str, float]],
    start_ns: int,
    quantity: float,
    quantity_step: float,
    config: ExecutionConfig,
) -> dict[str, float]:
    eligible = [
        quote for quote in quotes if int(quote["timestamp_ns"]) >= start_ns
    ]
    if not eligible:
        return {
            "effective_price": math.nan,
            "average_fill_price": math.nan,
            "filled_quantity": 0.0,
            "unfilled_quantity": quantity,
            "timestamp_ns": float(start_ns),
            "fill_quotes": 0.0,
            "marked_quantity": 0.0,
            "first_fill_timestamp_ns": None,
        }
    first = eligible[0]
    if config.mode == "FULL_BBO":
        return {
            "effective_price": float(first["bid"]),
            "average_fill_price": float(first["bid"]),
            "filled_quantity": quantity,
            "unfilled_quantity": 0.0,
            "timestamp_ns": float(first["timestamp_ns"]),
            "fill_quotes": 1.0,
            "marked_quantity": 0.0,
            "first_fill_timestamp_ns": float(first["timestamp_ns"]),
        }
    deadline_ns = (
        None
        if config.exit_fill_timeout_seconds is None
        else start_ns + int(config.exit_fill_timeout_seconds * 1e9)
    )
    remaining = quantity
    filled = 0.0
    proceeds = 0.0
    last_ns = int(first["timestamp_ns"])
    last_bid = float(first["bid"])
    fill_quotes = 0
    first_fill_ns: int | None = None
    for quote in eligible:
        quote_ns = int(quote["timestamp_ns"])
        if deadline_ns is not None and quote_ns > deadline_ns:
            break
        last_ns = quote_ns
        last_bid = float(quote["bid"])
        fill = _capacity_fill_quantity(
            float(quote.get("bid_size", 0.0)),
            remaining,
            quantity_step,
            config,
        )
        if fill <= 0.0:
            continue
        if first_fill_ns is None:
            first_fill_ns = quote_ns
        filled += fill
        remaining = max(0.0, quantity - filled)
        proceeds += fill * last_bid
        fill_quotes += 1
        if remaining <= 1e-12:
            break
    executed_proceeds = proceeds
    marked_quantity = 0.0
    if remaining > 1e-12 and config.unfilled_exit_policy == "LAST_BID":
        proceeds += remaining * last_bid
        marked_quantity = remaining
    return {
        "effective_price": proceeds / quantity if quantity > 0.0 else math.nan,
        "average_fill_price": executed_proceeds / filled
        if filled > 0.0
        else math.nan,
        "filled_quantity": filled,
        "unfilled_quantity": remaining,
        "timestamp_ns": float(last_ns),
        "fill_quotes": float(fill_quotes),
        "marked_quantity": marked_quantity,
        "first_fill_timestamp_ns": (
            float(first_fill_ns) if first_fill_ns is not None else None
        ),
    }


def simulate_trade(
    event: SignalEvent,
    frame: pd.DataFrame,
    scenario: Scenario,
    *,
    premium_budget_usd: float,
    hard_stop_percent: float,
    max_hold_minutes: float | None,
    exit_days_to_expiry: float | None = None,
    max_spread_percent: float,
    min_volume: float,
    volume_quantity_multiplier: float,
    execution: ExecutionConfig = ExecutionConfig(),
    option_fee_notional_rate: float = 0.0001,
    option_fee_premium_cap_rate: float = 0.035,
    fee_gst_rate: float = 0.18,
    data_fidelity: str = "LOW_FIDELITY_SYNTHETIC_BBO",
) -> tuple[dict[str, Any] | None, str | None]:
    event.execution_attempt = None
    if scenario.hard_stop_fill_mode not in {"SAME_QUOTE", "NEXT_QUOTE"}:
        raise ValueError("hard_stop_fill_mode must be SAME_QUOTE or NEXT_QUOTE")
    if execution.mode not in {"FULL_BBO", "SIZE_AWARE"}:
        raise ValueError("execution mode must be FULL_BBO or SIZE_AWARE")
    if not 0.0 < execution.size_participation_rate <= 1.0:
        raise ValueError("execution size_participation_rate must be in (0, 1]")
    if execution.size_capacity_multiplier <= 0.0:
        raise ValueError("execution size_capacity_multiplier must be positive")
    if execution.entry_fill_timeout_seconds < 0.0:
        raise ValueError("execution entry_fill_timeout_seconds cannot be negative")
    if not 0.0 <= execution.minimum_entry_fill_percent <= 100.0:
        raise ValueError("execution minimum_entry_fill_percent must be 0 to 100")
    if (
        execution.max_entry_quote_delay_seconds is not None
        and execution.max_entry_quote_delay_seconds < 0.0
    ):
        raise ValueError("execution max_entry_quote_delay_seconds cannot be negative")
    if (
        execution.max_exit_quote_delay_seconds is not None
        and execution.max_exit_quote_delay_seconds < 0.0
    ):
        raise ValueError("execution max_exit_quote_delay_seconds cannot be negative")
    if (
        execution.exit_fill_timeout_seconds is not None
        and execution.exit_fill_timeout_seconds < 0.0
    ):
        raise ValueError("execution exit_fill_timeout_seconds cannot be negative")
    if execution.unfilled_exit_policy not in {"ZERO", "LAST_BID"}:
        raise ValueError("execution unfilled_exit_policy must be ZERO or LAST_BID")
    early_failure = scenario.early_failure
    if early_failure.condition_mode not in {"ANY", "ALL"}:
        raise ValueError("early_failure condition_mode must be ANY or ALL")
    if not 1 <= early_failure.monitor_candles <= 100:
        raise ValueError("early_failure monitor_candles must be between 1 and 100")
    if not 0 <= early_failure.vwap_reclaim_candles <= 100:
        raise ValueError("early_failure vwap_reclaim_candles must be between 0 and 100")
    if not 1 <= early_failure.structure_lookback_candles <= 100:
        raise ValueError(
            "early_failure structure_lookback_candles must be between 1 and 100"
        )
    if early_failure.enabled and not any(
        (
            early_failure.exit_on_vwap_failure,
            early_failure.exit_on_structure_break,
            early_failure.exit_on_ema9_ema20_cross,
        )
    ):
        raise ValueError("early_failure must enable at least one exit condition")
    effective_hard_stop_percent = (
        scenario.hard_stop_percent_override
        if scenario.hard_stop_percent_override is not None
        else hard_stop_percent
    )
    recorded_bbo = data_fidelity.startswith("RECORDED_BBO")
    if not event.quotes:
        return None, "QUOTE_UNAVAILABLE"
    days_to_expiry = (
        event.option.expiration_ns - event.timestamp_ns
    ) / (24 * 60 * NS_MINUTE)
    if (
        days_to_expiry < scenario.min_days_to_expiry - 1e-12
        or (
            not scenario.min_days_to_expiry_inclusive
            and days_to_expiry <= scenario.min_days_to_expiry + 1e-12
        )
    ):
        return None, "OPTION_EXPIRY_TOO_NEAR"
    if days_to_expiry > scenario.max_days_to_expiry + 1e-12:
        return None, "OPTION_EXPIRY_TOO_FAR"
    if len(event.option_true_ranges) < scenario.min_option_true_ranges:
        return None, "OPTION_HISTORY_TOO_SHORT"
    if not _directional_confirmation_valid(
        frame,
        event,
        scenario.directional_confirmation_minutes,
    ):
        return None, "DIRECTIONAL_CONFIRMATION_FAILED"
    ema_strength_atr = _ema_strength_atr(frame, event)
    if scenario.min_ema_strength_atr > 0.0 and (
        not math.isfinite(ema_strength_atr)
        or ema_strength_atr < scenario.min_ema_strength_atr
    ):
        return None, "EMA_STRENGTH_TOO_LOW"
    if scenario.max_ema_strength_atr is not None and (
        not math.isfinite(ema_strength_atr)
        or ema_strength_atr > scenario.max_ema_strength_atr
    ):
        return None, "EMA_STRENGTH_TOO_HIGH"
    vwap_displacement_atr, signal_volume_ratio = _signal_entry_features(frame, event)
    if scenario.min_vwap_displacement_atr > 0.0 and (
        not math.isfinite(vwap_displacement_atr)
        or vwap_displacement_atr < scenario.min_vwap_displacement_atr
    ):
        return None, "VWAP_DISPLACEMENT_TOO_LOW"
    if scenario.min_signal_volume_ratio > 0.0 and (
        not math.isfinite(signal_volume_ratio)
        or signal_volume_ratio < scenario.min_signal_volume_ratio
    ):
        return None, "SIGNAL_VOLUME_RATIO_TOO_LOW"
    entry_quote = event.quotes[0]
    requested_quantity = calculate_quantity(
        budget_usd=premium_budget_usd,
        premium=entry_quote["ask"],
        contract_value=event.option.contract_value,
        min_quantity=event.option.min_quantity,
        quantity_step=event.option.size_increment,
        lot_size=event.option.lot_size,
    )
    entry_execution = _entry_execution(
        event.quotes,
        requested_quantity,
        event.option.size_increment,
        execution,
    )
    quantity = float(entry_execution["quantity"])
    signal_to_first_quote_delay_seconds = max(
        0.0,
        (
            int(entry_execution["first_quote_timestamp_ns"])
            - event.timestamp_ns
        ) / 1e9,
    )
    signal_to_entry_delay_seconds = max(
        0.0,
        (int(entry_execution["timestamp_ns"]) - event.timestamp_ns) / 1e9,
    )
    entry_fill_percent = (
        100.0 * quantity / requested_quantity if requested_quantity > 0.0 else 0.0
    )
    average_fill_price = float(entry_execution["average_price"])
    event.execution_attempt = {
        "scenario": scenario.name,
        "signal_time": datetime.fromtimestamp(
            event.timestamp_ns / 1e9, UTC
        ).isoformat(),
        "direction": event.direction,
        "entry_type": event.entry_type,
        "symbol": event.option.symbol,
        "execution_mode": execution.mode,
        "requested_quantity": requested_quantity,
        "hypothetical_filled_quantity": quantity,
        "entry_fill_percent": entry_fill_percent,
        "entry_fill_threshold_passed": (
            quantity + 1e-12 >= event.option.min_quantity
            and entry_fill_percent + 1e-12
            >= execution.minimum_entry_fill_percent
        ),
        "entry_average_fill_price": (
            average_fill_price if math.isfinite(average_fill_price) else None
        ),
        "entry_quotes_observed": int(entry_execution["quotes_observed"]),
        "entry_fill_quotes": int(entry_execution["fill_quotes"]),
        "displayed_ask_size_sum": float(
            entry_execution["displayed_ask_size_sum"]
        ),
        "participating_capacity_sum": float(
            entry_execution["participating_capacity_sum"]
        ),
        "executable_capacity_sum": float(
            entry_execution["executable_capacity_sum"]
        ),
        "entry_fill_timeout_seconds": execution.entry_fill_timeout_seconds,
        "signal_to_entry_delay_seconds": signal_to_entry_delay_seconds,
        "signal_to_first_quote_delay_seconds": signal_to_first_quote_delay_seconds,
        "max_entry_quote_delay_seconds": execution.max_entry_quote_delay_seconds,
        "max_exit_quote_delay_seconds": execution.max_exit_quote_delay_seconds,
        "exit_trigger_time": None,
        "exit_first_fill_time": None,
        "exit_trigger_to_fill_delay_seconds": None,
        "coverage_resume_ns": None,
        "minimum_entry_fill_percent": execution.minimum_entry_fill_percent,
        "size_participation_rate": execution.size_participation_rate,
        "size_capacity_multiplier": execution.size_capacity_multiplier,
        "first_ask": float(entry_quote["ask"]),
        "first_ask_size": float(entry_quote.get("ask_size", 0.0)),
    }
    if (
        execution.max_entry_quote_delay_seconds is not None
        and signal_to_first_quote_delay_seconds
        > execution.max_entry_quote_delay_seconds + 1e-12
    ):
        return None, "ENTRY_QUOTE_TOO_LATE"
    if quantity + 1e-12 < event.option.min_quantity:
        return None, "ENTRY_FILL_TOO_SMALL"
    if entry_fill_percent + 1e-12 < execution.minimum_entry_fill_percent:
        return None, "ENTRY_FILL_PERCENT_TOO_LOW"
    entry = average_fill_price
    entry_ns = int(entry_execution["timestamp_ns"])
    entry_days_to_expiry = (
        event.option.expiration_ns - entry_ns
    ) / (24 * 60 * NS_MINUTE)
    if (
        exit_days_to_expiry is not None
        and entry_days_to_expiry <= exit_days_to_expiry + 1e-12
    ):
        return None, "OPTION_DTE_EXIT_REACHED_AT_ENTRY"
    if not _entry_time_allowed(
        datetime.fromtimestamp(entry_ns / 1e9, UTC),
        entry_start_hour_utc=scenario.entry_start_hour_utc,
        entry_end_hour_utc=scenario.entry_end_hour_utc,
        entry_windows_ist_minutes=scenario.entry_windows_ist_minutes,
        blocked_weekdays_ist=scenario.blocked_weekdays_ist,
    ):
        return None, "OUTSIDE_ENTRY_SESSION"
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
    if scenario.fee_aware_multiplier > 0.0:
        recent_ranges = event.option_true_ranges[-6:]
        if len(recent_ranges) < 6:
            return None, "OPTION_HISTORY_TOO_SHORT"
        _, _, estimated_one_way_fee = option_fee_components(
            spot=event.underlying,
            premium=entry,
            quantity=quantity,
            contract_value=event.option.contract_value,
            notional_rate=option_fee_notional_rate,
            premium_cap_rate=option_fee_premium_cap_rate,
            gst_rate=fee_gst_rate,
        )
        movement_capacity_usd = (
            sum(recent_ranges) / len(recent_ranges)
            * event.option.contract_value
            * quantity
        )
        estimated_round_trip_fee = 2.0 * estimated_one_way_fee
        if movement_capacity_usd < (
            scenario.fee_aware_multiplier * estimated_round_trip_fee
        ):
            return None, "FEE_AWARE_MOVE_TOO_LOW"
    deadline_ns = (
        entry_ns + int(max_hold_minutes * NS_MINUTE)
        if max_hold_minutes is not None
        else None
    )
    completed_entry_quote = next(
        (
            quote
            for quote in reversed(event.quotes)
            if int(quote["timestamp_ns"]) <= entry_ns
        ),
        entry_quote,
    )
    highest_bid = completed_entry_quote["bid"]
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
    early_failure_structure = _early_failure_structure(frame, event, early_failure)
    post_entry_candles = 0
    consecutive_vwap_failure_candles = 0
    pending_reason = ""
    pending_ns = 0
    quote_rows = [
        (int(quote["timestamp_ns"]), quote)
        for quote in event.quotes
        if int(quote["timestamp_ns"]) > entry_ns
    ]
    timeline_end_ns = (
        deadline_ns
        if deadline_ns is not None
        else quote_rows[-1][0]
        if quote_rows
        else event.option.expiration_ns
    )
    deadline_timestamp = pd.Timestamp(timeline_end_ns, unit="ns", tz="UTC")
    if frame.empty:
        bars = frame
    else:
        bars = frame.loc[
            (frame.index > entry_timestamp)
            & (frame.index <= deadline_timestamp)
        ]
    bar_rows = [
        (int(timestamp.timestamp() * 1_000_000_000), row)
        for timestamp, row in bars.iterrows()
    ]
    timeline: list[tuple[int, int, Any]] = [
        *( (stamp, 0, row) for stamp, row in bar_rows ),
        *( (stamp, 1, quote) for stamp, quote in quote_rows ),
    ]
    timeline.sort(key=lambda item: (item[0], item[1]))
    exit_quote: dict[str, float] | None = None
    exit_reason = ""
    exit_trigger_ns = 0
    for current_ns, kind, payload in timeline:
        if kind == 0:
            if not pending_reason:
                post_entry_candles += 1
                if (
                    early_failure.enabled
                    and post_entry_candles <= early_failure.monitor_candles
                ):
                    vwap_failed = (
                        float(payload["close"]) < float(payload["vwap"])
                        if event.direction == "CALL"
                        else float(payload["close"]) > float(payload["vwap"])
                    )
                    consecutive_vwap_failure_candles = (
                        consecutive_vwap_failure_candles + 1
                        if vwap_failed
                        else 0
                    )
                    early_reason = _early_failure_reason(
                        payload,
                        event.direction,
                        early_failure,
                        early_failure_structure,
                        consecutive_vwap_failure_candles
                        > early_failure.vwap_reclaim_candles,
                    )
                    if early_reason:
                        pending_reason = early_reason
                        pending_ns = current_ns
                        continue
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
            exit_trigger_ns = pending_ns
            break
        if deadline_ns is not None and current_ns >= deadline_ns:
            exit_quote, exit_reason = quote, "MAX_HOLD"
            exit_trigger_ns = deadline_ns
            break
        if exit_days_to_expiry is not None:
            remaining_days = (
                event.option.expiration_ns - current_ns
            ) / (24 * 60 * NS_MINUTE)
            if remaining_days <= exit_days_to_expiry + 1e-12:
                exit_quote, exit_reason = quote, "DTE_EXIT"
                exit_trigger_ns = int(
                    event.option.expiration_ns
                    - exit_days_to_expiry * 24 * 60 * NS_MINUTE
                )
                break
        highest_bid = max(highest_bid, quote["bid"])
        pnl_percent = (quote["bid"] - entry) / entry * 100.0
        fixed_stop = (
            max(0.0, entry - scenario.stop_loss_points)
            if scenario.stop_loss_points > 0.0 else None
        )
        stop_hit = (
            quote["bid"] <= fixed_stop
            if fixed_stop is not None else pnl_percent <= effective_hard_stop_percent
        )
        if stop_hit:
            if scenario.hard_stop_fill_mode == "SAME_QUOTE":
                exit_quote, exit_reason = quote, "HARD_STOP"
                exit_trigger_ns = current_ns
                break
            pending_reason, pending_ns = "HARD_STOP", current_ns
            continue
        floor = protected_floor(entry, highest_bid, scenario)
        if floor is not None and quote["bid"] <= floor:
            pending_reason, pending_ns = "PROTECTED_STOP", current_ns
    if exit_quote is None and recorded_bbo:
        if event.execution_attempt is not None:
            event.execution_attempt.update({
                "exit_trigger_time": (
                    datetime.fromtimestamp(pending_ns / 1e9, UTC).isoformat()
                    if pending_ns > 0
                    else None
                ),
                "coverage_status": "INCOMPLETE_R2_COVERAGE",
            })
        return None, "INCOMPLETE_R2_COVERAGE"
    if exit_quote is None and max_hold_minutes is None and quote_rows:
        exit_quote = quote_rows[-1][1]
        exit_reason = "OPTION_EXPIRY_OR_DATA_END"
        exit_trigger_ns = int(exit_quote["timestamp_ns"])
    if exit_quote is None:
        return None, "EXIT_QUOTE_UNAVAILABLE"
    exit_execution = _exit_execution(
        event.quotes,
        int(exit_quote["timestamp_ns"]),
        quantity,
        event.option.size_increment,
        execution,
    )
    first_exit_fill_ns_raw = exit_execution["first_fill_timestamp_ns"]
    if first_exit_fill_ns_raw is None:
        if recorded_bbo:
            if event.execution_attempt is not None:
                event.execution_attempt.update({
                    "exit_trigger_time": datetime.fromtimestamp(
                        exit_trigger_ns / 1e9, UTC
                    ).isoformat(),
                    "coverage_status": "INCOMPLETE_R2_COVERAGE",
                })
            return None, "INCOMPLETE_R2_COVERAGE"
        return None, "EXIT_QUOTE_UNAVAILABLE"
    first_exit_fill_ns = int(first_exit_fill_ns_raw)
    exit_trigger_to_fill_delay_seconds = max(
        0.0, (first_exit_fill_ns - exit_trigger_ns) / 1e9
    )
    if event.execution_attempt is not None:
        event.execution_attempt.update({
            "exit_trigger_time": datetime.fromtimestamp(
                exit_trigger_ns / 1e9, UTC
            ).isoformat(),
            "exit_first_fill_time": datetime.fromtimestamp(
                first_exit_fill_ns / 1e9, UTC
            ).isoformat(),
            "exit_trigger_to_fill_delay_seconds": (
                exit_trigger_to_fill_delay_seconds
            ),
            "coverage_resume_ns": first_exit_fill_ns,
            "coverage_status": "COMPLETE",
        })
    if (
        execution.max_exit_quote_delay_seconds is not None
        and exit_trigger_to_fill_delay_seconds
        > execution.max_exit_quote_delay_seconds + 1e-12
    ):
        if event.execution_attempt is not None:
            event.execution_attempt["coverage_status"] = "EXIT_QUOTE_TOO_LATE"
        return None, "EXIT_QUOTE_TOO_LATE"
    exit_bid = float(exit_execution["effective_price"])
    if not math.isfinite(exit_bid):
        return None, "EXIT_QUOTE_UNAVAILABLE"
    exit_ns = int(exit_execution["timestamp_ns"])
    exit_filled_quantity = float(exit_execution["filled_quantity"])
    exit_average_fill_price = float(exit_execution["average_fill_price"])
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
    if exit_filled_quantity > 0.0 and math.isfinite(exit_average_fill_price):
        exit_fee_base, exit_fee_gst, exit_fee = option_fee_components(
            spot=exit_spot,
            premium=exit_average_fill_price,
            quantity=exit_filled_quantity,
            contract_value=event.option.contract_value,
            notional_rate=option_fee_notional_rate,
            premium_cap_rate=option_fee_premium_cap_rate,
            gst_rate=fee_gst_rate,
        )
    else:
        exit_fee_base = exit_fee_gst = exit_fee = 0.0
    gross_pnl_usd = (exit_bid - entry) * event.option.contract_value * quantity
    fees_usd = entry_fee + exit_fee
    pnl_usd = gross_pnl_usd - fees_usd
    return {
        "scenario": scenario.name,
        "group": scenario.group,
        "signal_time": datetime.fromtimestamp(event.timestamp_ns / 1e9, UTC).isoformat(),
        "entry_time": datetime.fromtimestamp(entry_ns / 1e9, UTC).isoformat(),
        "exit_time": datetime.fromtimestamp(exit_ns / 1e9, UTC).isoformat(),
        "direction": event.direction,
        "entry_type": event.entry_type,
        "ema_regime_start_time": (
            datetime.fromtimestamp(event.ema_regime_start_ns / 1e9, UTC).isoformat()
            if event.ema_regime_start_ns > 0 else ""
        ),
        "one_trade_per_ema_regime": scenario.one_trade_per_ema_regime,
        "ema_strength_atr": ema_strength_atr,
        "min_ema_strength_atr": scenario.min_ema_strength_atr,
        "max_ema_strength_atr": scenario.max_ema_strength_atr,
        "vwap_displacement_atr": (
            vwap_displacement_atr
            if math.isfinite(vwap_displacement_atr)
            else None
        ),
        "min_vwap_displacement_atr": scenario.min_vwap_displacement_atr,
        "signal_volume_ratio": (
            signal_volume_ratio
            if math.isfinite(signal_volume_ratio)
            else None
        ),
        "min_signal_volume_ratio": scenario.min_signal_volume_ratio,
        "symbol": event.option.symbol,
        "days_to_expiry": days_to_expiry,
        "requested_quantity": requested_quantity,
        "quantity": quantity,
        "entry_fill_percent": entry_fill_percent,
        "entry_fill_quotes": int(entry_execution["fill_quotes"]),
        "signal_to_entry_delay_seconds": signal_to_entry_delay_seconds,
        "signal_to_first_quote_delay_seconds": signal_to_first_quote_delay_seconds,
        "entry_ask": entry,
        "exit_bid": exit_bid,
        "exit_average_fill_bid": (
            exit_average_fill_price
            if math.isfinite(exit_average_fill_price)
            else None
        ),
        "exit_filled_quantity": exit_filled_quantity,
        "exit_unfilled_quantity": float(exit_execution["unfilled_quantity"]),
        "exit_marked_quantity": float(exit_execution["marked_quantity"]),
        "exit_fill_quotes": int(exit_execution["fill_quotes"]),
        "exit_trigger_time": datetime.fromtimestamp(
            exit_trigger_ns / 1e9, UTC
        ).isoformat(),
        "exit_trigger_to_fill_delay_seconds": exit_trigger_to_fill_delay_seconds,
        "execution_mode": execution.mode,
        "unfilled_exit_policy": execution.unfilled_exit_policy,
        "entry_spot": entry_spot,
        "exit_spot": exit_spot,
        "highest_bid": highest_bid,
        "exit_reason": exit_reason,
        "configured_hard_stop_percent": effective_hard_stop_percent,
        "hard_stop_fill_mode": scenario.hard_stop_fill_mode,
        "early_failure_enabled": early_failure.enabled,
        "early_failure_monitor_candles": early_failure.monitor_candles,
        "early_failure_condition_mode": early_failure.condition_mode,
        "early_failure_vwap_reclaim_candles": early_failure.vwap_reclaim_candles,
        "early_failure_structure_level": (
            early_failure_structure
            if math.isfinite(early_failure_structure)
            else None
        ),
        "holding_minutes": (exit_ns - entry_ns) / NS_MINUTE,
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
    max_hold_minutes: float | None = 60,
    exit_days_to_expiry: float | None = None,
    max_spread_percent: float = 3.0,
    min_volume: float = 30.0,
    volume_quantity_multiplier: float = 5.0,
    execution: ExecutionConfig = ExecutionConfig(),
    option_fee_notional_rate: float = 0.0001,
    option_fee_premium_cap_rate: float = 0.035,
    fee_gst_rate: float = 0.18,
    scenario_set: list[Scenario] | None = None,
    data_fidelity: str = "LOW_FIDELITY_SYNTHETIC_BBO",
) -> dict[str, Any]:
    start_ns, end_ns = timestamp_ns(start), timestamp_ns(end)
    frame = indicators(directory / "underlying_bars.csv")
    specs = _option_specs(directory / "option_instruments.csv")
    selected_scenarios = scenario_set or scenarios()
    event_keys = sorted(
        {
            (
                item.confirmation_candles,
                item.require_macd,
                item.require_stoch_rsi_entry,
                item.require_stoch_rsi_momentum_entry,
                item.entry_start_hour_utc,
                item.entry_end_hour_utc,
                item.entry_windows_ist_minutes,
                item.blocked_weekdays_ist,
                item.entry_min_conditions,
                item.min_days_to_expiry,
                item.min_days_to_expiry_inclusive,
                item.max_days_to_expiry,
                item.pullback_reversal,
                item.entry_mode,
                item.momentum_breakout,
            )
            for item in selected_scenarios
        },
        key=repr,
    )
    events_by_configuration = {}
    diagnostics_by_configuration = {}
    decision_events_by_configuration: dict[Any, list[dict[str, Any]]] = {}
    for (
            candles,
            require_macd,
            require_stoch,
            require_stoch_momentum,
            start_hour,
            end_hour,
            windows_ist,
            blocked_weekdays_ist,
            entry_min_conditions,
            min_days_to_expiry,
            min_days_to_expiry_inclusive,
            max_days_to_expiry,
            pullback_reversal,
            entry_mode,
            momentum_breakout,
        ) in event_keys:
        key = (
            candles,
            require_macd,
            require_stoch,
            require_stoch_momentum,
            start_hour,
            end_hour,
            windows_ist,
            blocked_weekdays_ist,
            entry_min_conditions,
            min_days_to_expiry,
            min_days_to_expiry_inclusive,
            max_days_to_expiry,
            pullback_reversal,
            entry_mode,
            momentum_breakout,
        )
        diagnostics: dict[str, int] = {}
        configuration_decisions: list[dict[str, Any]] = []
        events_by_configuration[key] = signal_events(
            frame,
            specs,
            start_ns,
            end_ns,
            confirmation_candles=candles,
            require_macd=require_macd,
            require_stoch_rsi_entry=require_stoch,
            require_stoch_rsi_momentum_entry=require_stoch_momentum,
            entry_start_hour_utc=start_hour,
            entry_end_hour_utc=end_hour,
            entry_windows_ist_minutes=windows_ist,
            blocked_weekdays_ist=blocked_weekdays_ist,
            entry_min_conditions=entry_min_conditions,
            min_days_to_expiry=min_days_to_expiry,
            min_days_to_expiry_inclusive=min_days_to_expiry_inclusive,
            max_days_to_expiry=max_days_to_expiry,
            pullback_reversal=pullback_reversal,
            entry_mode=entry_mode,
            momentum_breakout=momentum_breakout,
            signal_diagnostics=diagnostics,
            decision_events=configuration_decisions,
        )
        diagnostics_by_configuration[key] = diagnostics
        decision_events_by_configuration[key] = configuration_decisions
    capture_quotes(
        directory / "option_quotes.csv",
        [event for events in events_by_configuration.values() for event in events],
        horizon_minutes=(
            None
            if max_hold_minutes is None
            or (
                execution.mode == "SIZE_AWARE"
                and execution.exit_fill_timeout_seconds is None
            )
            else
            max_hold_minutes
            + 5.0
            + (
                execution.exit_fill_timeout_seconds / 60.0
                if execution.exit_fill_timeout_seconds is not None
                else 0.0
            )
        ),
    )
    if any(item.min_option_true_ranges > 0 for item in selected_scenarios):
        capture_option_true_ranges(
            directory,
            [event for events in events_by_configuration.values() for event in events],
        )
    results: list[dict[str, Any]] = []
    all_trades: list[dict[str, Any]] = []
    execution_attempts: list[dict[str, Any]] = []
    all_decision_events: list[dict[str, Any]] = []
    for scenario in selected_scenarios:
        scenario_key = (
            scenario.confirmation_candles,
            scenario.require_macd,
            scenario.require_stoch_rsi_entry,
            scenario.require_stoch_rsi_momentum_entry,
            scenario.entry_start_hour_utc,
            scenario.entry_end_hour_utc,
            scenario.entry_windows_ist_minutes,
            scenario.blocked_weekdays_ist,
            scenario.entry_min_conditions,
            scenario.min_days_to_expiry,
            scenario.min_days_to_expiry_inclusive,
            scenario.max_days_to_expiry,
            scenario.pullback_reversal,
            scenario.entry_mode,
            scenario.momentum_breakout,
        )
        all_decision_events.extend(
            {**item, "scenario": scenario.name}
            for item in decision_events_by_configuration.get(scenario_key, [])
        )
        events = events_by_configuration[
            (
                scenario.confirmation_candles,
                scenario.require_macd,
                scenario.require_stoch_rsi_entry,
                scenario.require_stoch_rsi_momentum_entry,
                scenario.entry_start_hour_utc,
                scenario.entry_end_hour_utc,
                scenario.entry_windows_ist_minutes,
                scenario.blocked_weekdays_ist,
                scenario.entry_min_conditions,
                scenario.min_days_to_expiry,
                scenario.min_days_to_expiry_inclusive,
                scenario.max_days_to_expiry,
                scenario.pullback_reversal,
                scenario.entry_mode,
                scenario.momentum_breakout,
            )
        ]
        trades: list[dict[str, Any]] = []
        rejects: dict[str, int] = {}
        available_after_ns = start_ns
        traded_ema_regimes: set[tuple[str, int]] = set()
        for event in events:
            if event.timestamp_ns <= available_after_ns:
                all_decision_events.append({
                    "scenario": scenario.name,
                    "timestamp": datetime.fromtimestamp(event.timestamp_ns / 1_000_000_000, UTC).isoformat(),
                    "stage": "EXECUTION", "status": "REJECTED",
                    "reason": "SIGNAL_DURING_OPEN_TRADE", "direction": event.direction,
                    "entry_type": event.entry_type, "symbol": event.option.symbol,
                })
                rejects["SIGNAL_DURING_OPEN_TRADE"] = (
                    rejects.get("SIGNAL_DURING_OPEN_TRADE", 0) + 1
                )
                continue
            regime_key = (event.direction, event.ema_regime_start_ns)
            if (
                scenario.one_trade_per_ema_regime
                and event.ema_regime_start_ns > 0
                and regime_key in traded_ema_regimes
            ):
                all_decision_events.append({
                    "scenario": scenario.name,
                    "timestamp": datetime.fromtimestamp(event.timestamp_ns / 1_000_000_000, UTC).isoformat(),
                    "stage": "EXECUTION", "status": "REJECTED",
                    "reason": "EMA_REGIME_ALREADY_TRADED", "direction": event.direction,
                    "entry_type": event.entry_type, "symbol": event.option.symbol,
                })
                rejects["EMA_REGIME_ALREADY_TRADED"] = (
                    rejects.get("EMA_REGIME_ALREADY_TRADED", 0) + 1
                )
                continue
            trade, rejection = simulate_trade(
                event,
                frame,
                scenario,
                premium_budget_usd=premium_budget_usd,
                hard_stop_percent=hard_stop_percent,
                max_hold_minutes=max_hold_minutes,
                exit_days_to_expiry=exit_days_to_expiry,
                max_spread_percent=max_spread_percent,
                min_volume=min_volume,
                volume_quantity_multiplier=volume_quantity_multiplier,
                execution=execution,
                option_fee_notional_rate=option_fee_notional_rate,
                option_fee_premium_cap_rate=option_fee_premium_cap_rate,
                fee_gst_rate=fee_gst_rate,
                data_fidelity=data_fidelity,
            )
            if rejection:
                all_decision_events.append({
                    "scenario": scenario.name,
                    "timestamp": datetime.fromtimestamp(event.timestamp_ns / 1_000_000_000, UTC).isoformat(),
                    "stage": "EXECUTION", "status": "REJECTED",
                    "reason": rejection, "direction": event.direction,
                    "entry_type": event.entry_type, "symbol": event.option.symbol,
                })
                if event.execution_attempt is not None:
                    execution_attempts.append({
                        **event.execution_attempt,
                        "trade_accepted": False,
                        "rejection_reason": rejection,
                    })
                if rejection in {
                    "EXIT_QUOTE_TOO_LATE",
                    "INCOMPLETE_R2_COVERAGE",
                }:
                    resume_ns = (
                        event.execution_attempt.get("coverage_resume_ns")
                        if event.execution_attempt is not None
                        else None
                    )
                    available_after_ns = (
                        max(available_after_ns, int(resume_ns))
                        if resume_ns is not None
                        else end_ns
                    )
                rejects[rejection] = rejects.get(rejection, 0) + 1
                continue
            assert trade is not None
            all_decision_events.append({
                "scenario": scenario.name,
                "timestamp": datetime.fromtimestamp(event.timestamp_ns / 1_000_000_000, UTC).isoformat(),
                "stage": "EXECUTION", "status": "ACCEPTED",
                "reason": "TRADE_ACCEPTED", "direction": event.direction,
                "entry_type": event.entry_type, "symbol": event.option.symbol,
            })
            if event.execution_attempt is not None:
                execution_attempts.append({
                    **event.execution_attempt,
                    "trade_accepted": True,
                    "rejection_reason": "",
                })
            trades.append(trade)
            all_trades.append(trade)
            if scenario.one_trade_per_ema_regime and event.ema_regime_start_ns > 0:
                traded_ema_regimes.add(regime_key)
            available_after_ns = timestamp_ns(str(trade["exit_time"]))
        results.append({
            "scenario": asdict(scenario),
            "metrics": _metrics(trades, starting_balance),
            "rejects": rejects,
            "signal_diagnostics": diagnostics_by_configuration[
                (
                    scenario.confirmation_candles,
                    scenario.require_macd,
                    scenario.require_stoch_rsi_entry,
                    scenario.require_stoch_rsi_momentum_entry,
                    scenario.entry_start_hour_utc,
                    scenario.entry_end_hour_utc,
                    scenario.entry_windows_ist_minutes,
                    scenario.blocked_weekdays_ist,
                    scenario.entry_min_conditions,
                    scenario.min_days_to_expiry,
                    scenario.min_days_to_expiry_inclusive,
                    scenario.max_days_to_expiry,
                    scenario.pullback_reversal,
                    scenario.entry_mode,
                    scenario.momentum_breakout,
                )
            ],
            "signals_with_contract": len(events),
        })
    return {
        "data_directory": str(directory.resolve()),
        "start": start,
        "end": end,
        "raw_signals_with_contract": (
            len(events_by_configuration[event_keys[0]])
            if len(event_keys) == 1
            else {
                (
                    f"confirmation={key[0]},macd={key[1]},stoch={key[2]},"
                    f"stoch_momentum={key[3]},utc={key[4]:02d}-{key[5]:02d},"
                    f"ist_windows={key[6]},blocked_weekdays_ist={key[7]},"
                    f"entry_min_conditions={key[8]},dte={key[9]}-{key[11]},"
                    f"min_dte_inclusive={key[10]},pullback_reversal={key[12]},"
                    f"entry_mode={key[13]},momentum_breakout={key[14]}"
                ): len(events_by_configuration[key])
                for key in event_keys
            }
        ),
        "settings": {
            "starting_balance": starting_balance,
            "premium_budget_usd": premium_budget_usd,
            "hard_stop_percent": hard_stop_percent,
            "max_hold_minutes": max_hold_minutes,
            "exit_days_to_expiry": exit_days_to_expiry,
            "max_spread_percent": max_spread_percent,
            "min_volume": min_volume,
            "volume_quantity_multiplier": volume_quantity_multiplier,
            "execution": asdict(execution),
            "fill_mode": "NEXT_QUOTE",
            "fees": {
                "option_notional_rate": option_fee_notional_rate,
                "option_premium_cap_rate": option_fee_premium_cap_rate,
                "gst_rate": fee_gst_rate,
                "charged_on": "ENTRY_AND_EXIT",
                "spot_proxy": "latest completed 5-minute BTC close",
            },
            "fidelity": data_fidelity,
            "vwap": "HLC3 volume-weighted, reset 00:00 Asia/Kolkata",
        },
        "results": results,
        "trades": all_trades,
        "execution_attempts": execution_attempts,
        "decision_events": all_decision_events,
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
    attempts = report.get("execution_attempts", [])
    if attempts:
        with (output / "execution_attempts.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            fieldnames = list(dict.fromkeys(key for row in attempts for key in row))
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(attempts)
    decisions = report.get("decision_events", [])
    if decisions:
        with (output / "decision_events.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            fieldnames = list(dict.fromkeys(key for row in decisions for key in row))
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(decisions)


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
    parser = argparse.ArgumentParser(description="EMA/VWAP/RSI option-strategy matrix research")
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
            "stoch",
            "stoch_momentum",
            "utc_session",
            "all_fail_exit",
            "all_fail_z50",
            "all_fail_atr",
            "all_fail_atr_sensitivity",
            "all_fail_macd_exit",
            "macd_exit_policies",
            "locked_h6",
            "locked_h6_fa125",
            "locked_h6_fa150",
            "locked_h6_fa200",
            "locked_h6_fa150_m30",
            "locked_h6_fa150_m30_stoch",
            "locked_m30",
            "locked_h6_fa150_utc08",
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
        "stoch": stoch_scenarios,
        "stoch_momentum": stoch_momentum_scenarios,
        "utc_session": utc_session_scenarios,
        "all_fail_exit": all_fail_exit_scenarios,
        "all_fail_z50": all_fail_z50_scenarios,
        "all_fail_atr": all_fail_atr_scenarios,
        "all_fail_atr_sensitivity": all_fail_atr_sensitivity_scenarios,
        "all_fail_macd_exit": all_fail_macd_exit_scenarios,
        "macd_exit_policies": macd_exit_policy_scenarios,
        "locked_h6": locked_h6_scenarios,
        "locked_h6_fa125": lambda: locked_h6_fa_scenarios(1.25),
        "locked_h6_fa150": lambda: locked_h6_fa_scenarios(1.50),
        "locked_h6_fa200": lambda: locked_h6_fa_scenarios(2.00),
        "locked_h6_fa150_m30": locked_h6_fa150_m30_scenarios,
        "locked_h6_fa150_m30_stoch": locked_h6_fa150_m30_stoch_scenarios,
        "locked_m30": locked_m30_scenarios,
        "locked_h6_fa150_utc08": locked_h6_fa150_utc08_scenarios,
    }
    selected_scenarios = studies[args.study]()
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "method": "Research-only calculation backtest; production strategy.py is unchanged.",
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
