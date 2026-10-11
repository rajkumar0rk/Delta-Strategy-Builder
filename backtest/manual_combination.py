from __future__ import annotations

import argparse
import itertools
import json
import re
import tomllib
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .ema_vwap_research import (
    EarlyFailureConfig,
    ExecutionConfig,
    MomentumBreakoutConfig,
    PullbackReversalConfig,
)
from .plain_bt123_2026 import (
    SEGMENTS,
    Segment,
    _manifest_range,
    plain_scenarios,
    print_summary,
    run,
)


DEFAULT_CONFIG = Path("backtest/config.manual-combination.toml")
DEFAULT_OUTPUT_ROOT = Path("backtest/reports/manual-combinations")
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
WINDOW_PATTERN = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")
WEEKDAYS = {
    "MONDAY": 0,
    "TUESDAY": 1,
    "WEDNESDAY": 2,
    "THURSDAY": 3,
    "FRIDAY": 4,
    "SATURDAY": 5,
    "SUNDAY": 6,
}
UTC = timezone.utc
MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@dataclass(frozen=True)
class BacktestSelection:
    source: str = "PUBLIC_HISTORY"
    start_date: str | None = None
    end_date: str | None = None
    months: tuple[str, ...] = ()
    directory: str | None = None


@dataclass(frozen=True)
class CombinationConfig:
    name: str
    backtest: BacktestSelection
    bt_families: tuple[int, ...]
    exit_policy: str
    ema_exit_rule: str
    max_hold_hours: float | None
    exit_days_to_expiry: float | None
    entry_mode: str
    profit_protection_enabled: bool
    profit_protection_mode: str
    profit_protection_activation_percent: float
    profit_protection_protect_percent: float
    macd: bool
    h6: bool
    h6_true_ranges: int
    fee_aware_multiplier: float
    m30: bool
    m30_minutes: int
    stoch_momentum: bool
    min_ema_strength_atr: float
    max_ema_strength_atr: float | None
    min_vwap_displacement_atr: float
    min_signal_volume_ratio: float
    zigzag: PullbackReversalConfig
    momentum_breakout: MomentumBreakoutConfig
    early_failure: EarlyFailureConfig
    execution: ExecutionConfig
    hard_stop_percent: float
    hard_stop_fill_mode: str
    max_spread_percent: float
    min_volume: float
    volume_quantity_multiplier: float
    min_days_to_expiry: float
    min_days_to_expiry_inclusive: bool
    max_days_to_expiry: float
    entry_windows_ist_minutes: tuple[tuple[int, int], ...]
    no_trade_days_ist: tuple[int, ...]

    @property
    def entry_windows_ist(self) -> list[str]:
        return [f"{_clock(start)}-{_clock(end)}" for start, end in self.entry_windows_ist_minutes]

    @property
    def no_trade_day_names(self) -> list[str]:
        by_number = {value: key.title() for key, value in WEEKDAYS.items()}
        return [by_number[value] for value in self.no_trade_days_ist]

    @property
    def enabled_filters(self) -> list[str]:
        filters: list[str] = []
        if self.macd:
            filters.append("MACD")
        if self.h6:
            filters.append(f"H{self.h6_true_ranges}")
        if self.fee_aware_multiplier > 0:
            filters.append(f"FA{int(round(self.fee_aware_multiplier * 100))}")
        if self.m30:
            filters.append(f"M{self.m30_minutes}")
        if self.stoch_momentum:
            filters.append("STOCH_MOMENTUM")
        if self.min_signal_volume_ratio > 0.0:
            ratio = f"{self.min_signal_volume_ratio:g}".replace(".", "P")
            filters.append(f"VOLUME_RATIO_{ratio}")
        if self.min_vwap_displacement_atr > 0.0:
            value = f"{self.min_vwap_displacement_atr:g}".replace(".", "P")
            filters.append(f"VWAP_ATR_{value}")
        if self.min_ema_strength_atr > 0.0:
            value = f"{self.min_ema_strength_atr:g}".replace(".", "P")
            filters.append(f"EMA_MIN_ATR_{value}")
        if self.max_ema_strength_atr is not None:
            value = f"{self.max_ema_strength_atr:g}".replace(".", "P")
            filters.append(f"EMA_MAX_ATR_{value}")
        if self.zigzag.enabled:
            filters.append(f"ZIGZAG_L{self.zigzag.lookback_candles}")
            filters.append("ZZ_RSI" if self.zigzag.rsi_enabled else "ZZ_NO_RSI")
            filters.append(
                f"ZZ_ATR{int(round(self.zigzag.atr_reversal_multiplier * 100))}"
                if self.zigzag.atr_enabled
                else "ZZ_NO_ATR"
            )
            if self.zigzag.require_ema_slope:
                filters.append("ZZ_EMA_SLOPE")
                if self.zigzag.allow_flat_ema50:
                    filters.append("ZZ_FLAT_EMA50")
            if (
                self.zigzag.atr_enabled
                and self.zigzag.max_touch_close_distance_atr is not None
            ):
                filters.append(
                    "ZZ_TOUCH_ATR"
                    + str(
                        int(round(self.zigzag.max_touch_close_distance_atr * 100))
                    )
                )
            if self.zigzag.use_actual_pullback_sequence:
                filters.append("ZZ_SEQUENCE")
        if self.entry_mode in {"MOMENTUM", "BOTH"}:
            filters.append(f"MOMENTUM_L{self.momentum_breakout.lookback_candles}")
        if self.early_failure.enabled:
            filters.append(
                f"EARLY_{self.early_failure.monitor_candles}_{self.early_failure.condition_mode}"
            )
        if (
            self.min_days_to_expiry != 1.0
            or not self.min_days_to_expiry_inclusive
            or self.max_days_to_expiry != 3.0
        ):
            lower = "GTE" if self.min_days_to_expiry_inclusive else "GT"
            filters.append(
                f"DTE_{lower}_{self.min_days_to_expiry:g}_TO_{self.max_days_to_expiry:g}"
            )
        if self.entry_windows_ist_minutes:
            filters.append(f"IST_WINDOWS_{len(self.entry_windows_ist_minutes)}")
        if self.no_trade_days_ist:
            filters.append("NO_" + "_".join(self.no_trade_day_names).upper())
        return filters

    @property
    def max_hold_label(self) -> str:
        if self.max_hold_hours is None:
            return "NO_MAX_HOLD"
        value = f"{self.max_hold_hours:g}".replace(".", "P")
        return f"HOLD_{value}H"

    @property
    def expiry_exit_label(self) -> str | None:
        if self.exit_days_to_expiry is None:
            return None
        value = f"{self.exit_days_to_expiry:g}".replace(".", "P")
        return f"DTE_EXIT_{value}D"

    @property
    def profit_protection_label(self) -> str | None:
        if not self.profit_protection_enabled:
            return None
        activation = f"{self.profit_protection_activation_percent:g}".replace(
            ".", "P"
        )
        protected = f"{self.profit_protection_protect_percent:g}".replace(
            ".", "P"
        )
        if self.profit_protection_mode == "FIXED":
            return f"PP_FIXED_A{activation}_P{protected}"
        return f"PP_A{activation}_P{protected}"


def _clock(minutes: int) -> str:
    if minutes == 24 * 60:
        return "24:00"
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _clock_minutes(hour: int, minute: int, *, end: bool) -> int:
    if hour == 24 and minute == 0 and end:
        return 24 * 60
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("IST window times must use HH:MM from 00:00 through 24:00")
    return hour * 60 + minute


def _entry_windows(value: Any) -> tuple[tuple[int, int], ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("entry_windows_ist must be a TOML array of HH:MM-HH:MM strings")
    windows: list[tuple[int, int]] = []
    for raw in value:
        match = WINDOW_PATTERN.fullmatch(str(raw).strip())
        if not match:
            raise ValueError(f"invalid IST entry window: {raw!r}")
        start_hour, start_minute, end_hour, end_minute = map(int, match.groups())
        start = _clock_minutes(start_hour, start_minute, end=False)
        end = _clock_minutes(end_hour, end_minute, end=True)
        if start >= end:
            raise ValueError(f"IST entry window must end after it starts: {raw!r}")
        windows.append((start, end))
    windows.sort()
    for previous, current in zip(windows, windows[1:]):
        if current[0] < previous[1]:
            raise ValueError("IST entry windows cannot overlap")
    return tuple(windows)


def _no_trade_days(value: Any) -> tuple[int, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("no_trade_days must be a TOML array of weekday names")
    days: list[int] = []
    for raw in value:
        name = str(raw).strip().upper()
        if name not in WEEKDAYS:
            raise ValueError(f"invalid no-trade weekday: {raw!r}")
        days.append(WEEKDAYS[name])
    return tuple(sorted(set(days)))


def _table(payload: dict[str, Any], name: str) -> dict[str, Any]:
    value = payload.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"[{name}] must be a TOML table")
    return value


def _max_hold_hours(value: Any) -> float | None:
    if isinstance(value, str):
        normalized = value.strip().upper().replace("-", "_")
        if normalized in {"NONE", "OFF", "DISABLED", "NO_MAX_HOLD"}:
            return None
        try:
            value = float(value)
        except ValueError as exc:
            raise ValueError(
                'exit.max_hold_hours must be a positive number or "NONE"'
            ) from exc
    if isinstance(value, bool):
        raise ValueError('exit.max_hold_hours must be a positive number or "NONE"')
    try:
        hours = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            'exit.max_hold_hours must be a positive number or "NONE"'
        ) from exc
    if hours <= 0:
        raise ValueError('exit.max_hold_hours must be positive or "NONE"')
    return hours


def _exit_days_to_expiry(value: Any) -> float | None:
    if isinstance(value, str):
        normalized = value.strip().upper().replace("-", "_")
        if normalized in {"NONE", "OFF", "DISABLED", "NO_DTE_EXIT"}:
            return None
        try:
            value = float(value)
        except ValueError as exc:
            raise ValueError(
                'exit.exit_days_to_expiry must be a non-negative number or "NONE"'
            ) from exc
    if isinstance(value, bool):
        raise ValueError(
            'exit.exit_days_to_expiry must be a non-negative number or "NONE"'
        )
    try:
        days = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            'exit.exit_days_to_expiry must be a non-negative number or "NONE"'
        ) from exc
    if days < 0:
        raise ValueError(
            'exit.exit_days_to_expiry must be non-negative or "NONE"'
        )
    return days


def _touch_close_distance_atr(value: Any) -> float | None:
    if isinstance(value, str):
        normalized = value.strip().upper().replace("-", "_")
        if normalized in {"NONE", "OFF", "DISABLED"}:
            return None
        try:
            value = float(value)
        except ValueError as exc:
            raise ValueError(
                'zigzag.max_touch_close_distance_atr must be non-negative or "NONE"'
            ) from exc
    if isinstance(value, bool):
        raise ValueError(
            'zigzag.max_touch_close_distance_atr must be non-negative or "NONE"'
        )
    try:
        distance = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            'zigzag.max_touch_close_distance_atr must be non-negative or "NONE"'
        ) from exc
    if distance < 0.0:
        raise ValueError(
            'zigzag.max_touch_close_distance_atr must be non-negative or "NONE"'
        )
    return distance


def _optional_nonnegative(value: Any, field_name: str) -> float | None:
    if isinstance(value, str):
        normalized = value.strip().upper().replace("-", "_")
        if normalized in {"NONE", "OFF", "DISABLED"}:
            return None
        try:
            value = float(value)
        except ValueError as exc:
            raise ValueError(f'{field_name} must be non-negative or "NONE"') from exc
    if isinstance(value, bool):
        raise ValueError(f'{field_name} must be non-negative or "NONE"')
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{field_name} must be non-negative or "NONE"') from exc
    if number < 0.0:
        raise ValueError(f'{field_name} must be non-negative or "NONE"')
    return number


def _optional_date(value: Any, field_name: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD") from exc


def _backtest_months(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("backtest.months must be a TOML array of YYYY-MM values")
    months: list[str] = []
    for raw in value:
        month = str(raw).strip()
        if not MONTH_PATTERN.fullmatch(month):
            raise ValueError(f"invalid backtest month {raw!r}; use YYYY-MM")
        months.append(month)
    return tuple(sorted(set(months)))


def load_config(path: Path) -> CombinationConfig:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)

    return parse_config(payload)


def parse_config(payload: dict[str, Any]) -> CombinationConfig:

    backtest = _table(payload, "backtest")
    filters = _table(payload, "filters")
    exit_settings = _table(payload, "exit")
    profit_protection = _table(payload, "profit_protection")
    option = _table(payload, "option")
    session = _table(payload, "session")
    zigzag = _table(payload, "zigzag")
    entry = _table(payload, "entry")
    momentum = _table(payload, "momentum_breakout")
    early_failure = _table(payload, "early_failure")
    execution = _table(payload, "execution")
    risk = _table(payload, "risk")
    liquidity = _table(payload, "liquidity")
    name = str(payload.get("name", "manual-combination")).strip()
    if not SAFE_NAME.fullmatch(name):
        raise ValueError(
            "name must start with a letter or number and contain only letters, "
            "numbers, dots, hyphens, or underscores"
        )

    raw_families = payload.get("bt_families", [1, 2, 3])
    if not isinstance(raw_families, list) or not raw_families:
        raise ValueError("bt_families must be a non-empty TOML array")
    families = tuple(dict.fromkeys(int(item) for item in raw_families))
    if any(item not in (1, 2, 3) for item in families):
        raise ValueError("bt_families may contain only 1, 2, and 3")

    exit_policy = str(payload.get("exit_policy", "PLAIN")).strip().upper().replace("-", "_")
    if exit_policy not in {"PLAIN", "ALL_FAIL"}:
        raise ValueError("exit_policy must be PLAIN or ALL_FAIL")

    explicit_entry_mode = "mode" in entry
    entry_mode = str(entry.get("mode", "BASELINE")).strip().upper().replace("-", "_")
    if not explicit_entry_mode:
        zigzag_enabled = bool(zigzag.get("enabled", False))
        momentum_enabled = bool(momentum.get("enabled", False))
        entry_mode = (
            "BOTH"
            if zigzag_enabled and momentum_enabled
            else "ZIGZAG"
            if zigzag_enabled
            else "MOMENTUM"
            if momentum_enabled
            else "BASELINE"
        )
    zigzag_enabled = entry_mode in {"ZIGZAG", "BOTH"}
    momentum_enabled = entry_mode in {"MOMENTUM", "BOTH"}

    config = CombinationConfig(
        name=name,
        backtest=BacktestSelection(
            source=str(backtest.get("source", "PUBLIC_HISTORY"))
            .strip()
            .upper()
            .replace("-", "_"),
            start_date=_optional_date(
                backtest.get("start_date"), "backtest.start_date"
            ),
            end_date=_optional_date(
                backtest.get("end_date"), "backtest.end_date"
            ),
            months=_backtest_months(backtest.get("months", [])),
            directory=(
                str(backtest.get("directory", "")).strip() or None
            ),
        ),
        bt_families=families,
        exit_policy=exit_policy,
        ema_exit_rule=str(
            exit_settings.get("ema_rule", "STRICT_ORDER")
        ).strip().upper().replace("-", "_"),
        max_hold_hours=_max_hold_hours(exit_settings.get("max_hold_hours", 1.0)),
        exit_days_to_expiry=_exit_days_to_expiry(
            exit_settings.get("exit_days_to_expiry", "NONE")
        ),
        entry_mode=entry_mode,
        profit_protection_enabled=bool(
            profit_protection.get("enabled", False)
        ),
        profit_protection_mode=str(
            profit_protection.get("mode", "TRAILING")
        ).strip().upper().replace("-", "_"),
        profit_protection_activation_percent=float(
            profit_protection.get("activation_percent", 20.0)
        ),
        profit_protection_protect_percent=float(
            profit_protection.get("protect_percent", 50.0)
        ),
        macd=bool(filters.get("macd", False)),
        h6=bool(filters.get("h6", False)),
        h6_true_ranges=int(filters.get("h6_true_ranges", 6)),
        fee_aware_multiplier=float(filters.get("fee_aware_multiplier", 0.0)),
        m30=bool(filters.get("m30", False)),
        m30_minutes=int(filters.get("m30_minutes", 30)),
        stoch_momentum=bool(filters.get("stoch_momentum", False)),
        min_ema_strength_atr=float(filters.get("min_ema_strength_atr", 0.0)),
        max_ema_strength_atr=_optional_nonnegative(
            filters.get("max_ema_strength_atr", "NONE"),
            "filters.max_ema_strength_atr",
        ),
        min_vwap_displacement_atr=float(
            filters.get("min_vwap_displacement_atr", 0.0)
        ),
        min_signal_volume_ratio=float(
            filters.get("min_signal_volume_ratio", 0.0)
        ),
        zigzag=PullbackReversalConfig(
            enabled=zigzag_enabled,
            lookback_candles=int(zigzag.get("pullback_lookback_candles", 4)),
            touch_ema20=bool(zigzag.get("touch_ema20", True)),
            touch_vwap=bool(zigzag.get("touch_vwap", True)),
            require_ema_slope=bool(zigzag.get("require_ema_slope", False)),
            allow_flat_ema50=bool(zigzag.get("allow_flat_ema50", True)),
            max_touch_close_distance_atr=_touch_close_distance_atr(
                zigzag.get("max_touch_close_distance_atr", 0.2)
            ),
            use_actual_pullback_sequence=bool(
                zigzag.get("use_actual_pullback_sequence", True)
            ),
            rsi_enabled=bool(zigzag.get("rsi_enabled", True)),
            bull_rsi_min=float(zigzag.get("bull_rsi_min", 40.0)),
            bull_rsi_max=float(zigzag.get("bull_rsi_max", 55.0)),
            bear_rsi_min=float(zigzag.get("bear_rsi_min", 45.0)),
            bear_rsi_max=float(zigzag.get("bear_rsi_max", 60.0)),
            atr_enabled=bool(zigzag.get("atr_enabled", True)),
            atr_reversal_multiplier=float(
                zigzag.get("atr_reversal_multiplier", 0.4)
            ),
        ),
        momentum_breakout=MomentumBreakoutConfig(
            enabled=momentum_enabled,
            lookback_candles=int(momentum.get("lookback_candles", 6)),
            breakout_buffer_atr=float(momentum.get("breakout_buffer_atr", 0.0)),
            min_volume_ratio=float(momentum.get("min_volume_ratio", 1.25)),
            min_vwap_displacement_atr=float(
                momentum.get("min_vwap_displacement_atr", 1.0)
            ),
            min_ema_strength_atr=float(
                momentum.get("min_ema_strength_atr", 0.0)
            ),
            max_ema_strength_atr=_optional_nonnegative(
                momentum.get("max_ema_strength_atr", 0.75),
                "momentum_breakout.max_ema_strength_atr",
            ),
        ),
        early_failure=EarlyFailureConfig(
            enabled=bool(early_failure.get("enabled", False)),
            monitor_candles=int(early_failure.get("monitor_candles", 3)),
            condition_mode=str(
                early_failure.get("condition_mode", "ANY")
            ).strip().upper(),
            exit_on_vwap_failure=bool(
                early_failure.get("exit_on_vwap_failure", True)
            ),
            vwap_reclaim_candles=int(
                early_failure.get("vwap_reclaim_candles", 0)
            ),
            exit_on_structure_break=bool(
                early_failure.get("exit_on_structure_break", True)
            ),
            structure_lookback_candles=int(
                early_failure.get("structure_lookback_candles", 4)
            ),
            exit_on_ema9_ema20_cross=bool(
                early_failure.get("exit_on_ema9_ema20_cross", True)
            ),
        ),
        execution=ExecutionConfig(
            mode=str(execution.get("mode", "FULL_BBO")).strip().upper(),
            size_participation_rate=float(
                execution.get("size_participation_rate", 1.0)
            ),
            size_capacity_multiplier=float(
                execution.get("size_capacity_multiplier", 1.0)
            ),
            entry_fill_timeout_seconds=float(
                execution.get("entry_fill_timeout_seconds", 0.0)
            ),
            minimum_entry_fill_percent=float(
                execution.get("minimum_entry_fill_percent", 0.0)
            ),
            max_entry_quote_delay_seconds=_optional_nonnegative(
                execution.get("max_entry_quote_delay_seconds", "NONE"),
                "execution.max_entry_quote_delay_seconds",
            ),
            max_exit_quote_delay_seconds=_optional_nonnegative(
                execution.get("max_exit_quote_delay_seconds", "NONE"),
                "execution.max_exit_quote_delay_seconds",
            ),
            exit_fill_timeout_seconds=_optional_nonnegative(
                execution.get("exit_fill_timeout_seconds", 300.0),
                "execution.exit_fill_timeout_seconds",
            ),
            unfilled_exit_policy=str(
                execution.get("unfilled_exit_policy", "ZERO")
            ).strip().upper(),
        ),
        hard_stop_percent=float(risk.get("hard_stop_percent", -15.0)),
        hard_stop_fill_mode=str(
            risk.get("hard_stop_fill_mode", "NEXT_QUOTE")
        ).strip().upper(),
        max_spread_percent=float(liquidity.get("max_spread_percent", 3.0)),
        min_volume=float(liquidity.get("min_volume", 30.0)),
        volume_quantity_multiplier=float(
            liquidity.get("volume_quantity_multiplier", 5.0)
        ),
        min_days_to_expiry=float(option.get("min_days_to_expiry", 1.0)),
        min_days_to_expiry_inclusive=bool(
            option.get("min_days_to_expiry_inclusive", True)
        ),
        max_days_to_expiry=float(option.get("max_days_to_expiry", 3.0)),
        entry_windows_ist_minutes=_entry_windows(session.get("entry_windows_ist")),
        no_trade_days_ist=_no_trade_days(session.get("no_trade_days")),
    )
    validate_config(config)
    return config


def validate_config(config: CombinationConfig) -> None:
    selection = config.backtest
    if selection.source not in {"PUBLIC_HISTORY", "R2_L1"}:
        raise ValueError("backtest.source must be PUBLIC_HISTORY or R2_L1")
    if (selection.start_date is None) != (selection.end_date is None):
        raise ValueError(
            "backtest.start_date and backtest.end_date must be set together"
        )
    if selection.months and selection.start_date is not None:
        raise ValueError(
            "backtest.months cannot be combined with start_date/end_date"
        )
    if selection.start_date is not None and selection.end_date is not None:
        if date.fromisoformat(selection.end_date) < date.fromisoformat(
            selection.start_date
        ):
            raise ValueError("backtest.end_date must be on or after start_date")
    if selection.source == "R2_L1" and selection.directory is None:
        raise ValueError("backtest.directory is required when source=R2_L1")
    if config.entry_mode not in {"BASELINE", "ZIGZAG", "MOMENTUM", "BOTH"}:
        raise ValueError("entry.mode must be BASELINE, ZIGZAG, MOMENTUM, or BOTH")
    if config.h6_true_ranges < 1:
        raise ValueError("h6_true_ranges must be at least 1")
    if config.fee_aware_multiplier < 0:
        raise ValueError("fee_aware_multiplier cannot be negative")
    if config.fee_aware_multiplier > 0 and not config.h6:
        raise ValueError("FA requires h6=true because it uses recent option True Range")
    if config.m30_minutes < 5 or config.m30_minutes % 5:
        raise ValueError("m30_minutes must be a positive multiple of 5")
    if config.min_signal_volume_ratio < 0.0:
        raise ValueError("filters.min_signal_volume_ratio cannot be negative")
    if config.min_vwap_displacement_atr < 0.0:
        raise ValueError("filters.min_vwap_displacement_atr cannot be negative")
    if config.min_ema_strength_atr < 0.0:
        raise ValueError("filters.min_ema_strength_atr cannot be negative")
    if (
        config.max_ema_strength_atr is not None
        and config.max_ema_strength_atr < config.min_ema_strength_atr
    ):
        raise ValueError(
            "filters.max_ema_strength_atr must be at least min_ema_strength_atr"
        )
    if not 1 <= config.zigzag.lookback_candles <= 20:
        raise ValueError("zigzag.pullback_lookback_candles must be between 1 and 20")
    if not config.zigzag.touch_ema20 and not config.zigzag.touch_vwap:
        raise ValueError("zigzag must enable touch_ema20, touch_vwap, or both")
    for label, lower, upper in (
        (
            "bull",
            config.zigzag.bull_rsi_min,
            config.zigzag.bull_rsi_max,
        ),
        (
            "bear",
            config.zigzag.bear_rsi_min,
            config.zigzag.bear_rsi_max,
        ),
    ):
        if not 0.0 <= lower <= upper <= 100.0:
            raise ValueError(
                f"zigzag {label} RSI range must satisfy 0 <= min <= max <= 100"
            )
    if config.zigzag.atr_reversal_multiplier < 0.0:
        raise ValueError("zigzag.atr_reversal_multiplier cannot be negative")
    if (
        config.zigzag.max_touch_close_distance_atr is not None
        and config.zigzag.max_touch_close_distance_atr < 0.0
    ):
        raise ValueError("zigzag.max_touch_close_distance_atr cannot be negative")
    if not 1 <= config.momentum_breakout.lookback_candles <= 100:
        raise ValueError("momentum_breakout.lookback_candles must be between 1 and 100")
    if config.momentum_breakout.breakout_buffer_atr < 0.0:
        raise ValueError("momentum_breakout.breakout_buffer_atr cannot be negative")
    if config.momentum_breakout.min_volume_ratio < 0.0:
        raise ValueError("momentum_breakout.min_volume_ratio cannot be negative")
    if config.momentum_breakout.min_vwap_displacement_atr < 0.0:
        raise ValueError(
            "momentum_breakout.min_vwap_displacement_atr cannot be negative"
        )
    if config.momentum_breakout.min_ema_strength_atr < 0.0:
        raise ValueError("momentum_breakout.min_ema_strength_atr cannot be negative")
    if (
        config.momentum_breakout.max_ema_strength_atr is not None
        and config.momentum_breakout.max_ema_strength_atr
        < config.momentum_breakout.min_ema_strength_atr
    ):
        raise ValueError(
            "momentum_breakout.max_ema_strength_atr must be at least its minimum"
        )
    if config.early_failure.condition_mode not in {"ANY", "ALL"}:
        raise ValueError("early_failure.condition_mode must be ANY or ALL")
    if not 1 <= config.early_failure.monitor_candles <= 100:
        raise ValueError("early_failure.monitor_candles must be between 1 and 100")
    if not 0 <= config.early_failure.vwap_reclaim_candles <= 100:
        raise ValueError(
            "early_failure.vwap_reclaim_candles must be between 0 and 100"
        )
    if not 1 <= config.early_failure.structure_lookback_candles <= 100:
        raise ValueError(
            "early_failure.structure_lookback_candles must be between 1 and 100"
        )
    if config.early_failure.enabled and not any(
        (
            config.early_failure.exit_on_vwap_failure,
            config.early_failure.exit_on_structure_break,
            config.early_failure.exit_on_ema9_ema20_cross,
        )
    ):
        raise ValueError("early_failure must enable at least one exit condition")
    if config.execution.mode not in {"FULL_BBO", "SIZE_AWARE"}:
        raise ValueError("execution.mode must be FULL_BBO or SIZE_AWARE")
    if not 0.0 < config.execution.size_participation_rate <= 1.0:
        raise ValueError("execution.size_participation_rate must be in (0, 1]")
    if config.execution.size_capacity_multiplier <= 0.0:
        raise ValueError("execution.size_capacity_multiplier must be positive")
    if config.execution.entry_fill_timeout_seconds < 0.0:
        raise ValueError("execution.entry_fill_timeout_seconds cannot be negative")
    if not 0.0 <= config.execution.minimum_entry_fill_percent <= 100.0:
        raise ValueError("execution.minimum_entry_fill_percent must be 0 to 100")
    if (
        config.execution.max_entry_quote_delay_seconds is not None
        and config.execution.max_entry_quote_delay_seconds < 0.0
    ):
        raise ValueError("execution.max_entry_quote_delay_seconds cannot be negative")
    if (
        config.execution.max_exit_quote_delay_seconds is not None
        and config.execution.max_exit_quote_delay_seconds < 0.0
    ):
        raise ValueError("execution.max_exit_quote_delay_seconds cannot be negative")
    if config.execution.unfilled_exit_policy not in {"ZERO", "LAST_BID"}:
        raise ValueError(
            "execution.unfilled_exit_policy must be ZERO or LAST_BID"
        )
    if config.ema_exit_rule not in {
        "STRICT_ORDER",
        "FAST_AND_MID_VS_SLOW",
        "FAST_OR_MID_VS_SLOW",
    }:
        raise ValueError(
            "exit.ema_rule must be STRICT_ORDER, FAST_AND_MID_VS_SLOW, "
            "or FAST_OR_MID_VS_SLOW"
        )
    if config.min_days_to_expiry < 0:
        raise ValueError("min_days_to_expiry cannot be negative")
    if config.max_days_to_expiry <= config.min_days_to_expiry:
        raise ValueError("max_days_to_expiry must be greater than min_days_to_expiry")
    if (
        config.exit_days_to_expiry is not None
        and config.exit_days_to_expiry >= config.max_days_to_expiry
    ):
        raise ValueError(
            "exit.exit_days_to_expiry must be less than option.max_days_to_expiry"
        )
    if config.profit_protection_activation_percent <= 0.0:
        raise ValueError(
            "profit_protection.activation_percent must be greater than zero"
        )
    if config.profit_protection_mode not in {"TRAILING", "FIXED"}:
        raise ValueError("profit_protection.mode must be TRAILING or FIXED")
    minimum_protection = (
        0.0 if config.profit_protection_mode == "FIXED" else 1e-12
    )
    if not minimum_protection <= config.profit_protection_protect_percent <= 100.0:
        raise ValueError(
            "profit_protection.protect_percent must be between zero and 100; "
            "TRAILING requires a value greater than zero"
        )
    if (
        config.profit_protection_mode == "FIXED"
        and config.profit_protection_protect_percent
        > config.profit_protection_activation_percent
    ):
        raise ValueError(
            "FIXED protect_percent cannot exceed activation_percent"
        )
    if config.hard_stop_percent >= 0.0:
        raise ValueError("risk.hard_stop_percent must be negative")
    if config.hard_stop_fill_mode not in {"SAME_QUOTE", "NEXT_QUOTE"}:
        raise ValueError(
            "risk.hard_stop_fill_mode must be SAME_QUOTE or NEXT_QUOTE"
        )
    if config.max_spread_percent < 0.0:
        raise ValueError("liquidity.max_spread_percent cannot be negative")
    if config.min_volume < 0.0:
        raise ValueError("liquidity.min_volume cannot be negative")
    if config.volume_quantity_multiplier < 0.0:
        raise ValueError("liquidity.volume_quantity_multiplier cannot be negative")


def build_scenarios(config: CombinationConfig):
    suffix = "_" + "_".join(config.enabled_filters) if config.enabled_filters else "_BASE"
    exit_suffix = "_ALLFAIL" if config.exit_policy == "ALL_FAIL" else ""
    ema_exit_suffix = (
        "_EXIT_FAST_MID_VS_SLOW"
        if config.ema_exit_rule == "FAST_AND_MID_VS_SLOW"
        else "_EXIT_FAST_OR_MID_VS_SLOW"
        if config.ema_exit_rule == "FAST_OR_MID_VS_SLOW"
        else ""
    )
    hold_suffix = (
        ""
        if config.max_hold_hours == 1.0
        else f"_{config.max_hold_label}"
    )
    expiry_exit_suffix = (
        f"_{config.expiry_exit_label}"
        if config.expiry_exit_label is not None
        else ""
    )
    protection_suffix = (
        f"_{config.profit_protection_label}"
        if config.profit_protection_label is not None
        else ""
    )
    return [
        replace(
            scenario,
            name=(
                f"{scenario.name}{exit_suffix}{ema_exit_suffix}"
                f"{hold_suffix}{expiry_exit_suffix}{protection_suffix}{suffix}"
            ),
            protection=(
                "FIXED"
                if config.profit_protection_enabled
                and config.profit_protection_mode == "FIXED"
                else "Z"
                if config.profit_protection_enabled
                else "NONE"
            ),
            retention=(
                config.profit_protection_protect_percent / 100.0
                if config.profit_protection_enabled
                else 0.0
            ),
            activation_percent=(
                config.profit_protection_activation_percent
                if config.profit_protection_enabled
                else 0.0
            ),
            fixed_protected_profit_percent=(
                config.profit_protection_protect_percent
                if config.profit_protection_enabled
                and config.profit_protection_mode == "FIXED"
                else 0.0
            ),
            require_macd=config.macd,
            min_option_true_ranges=config.h6_true_ranges if config.h6 else 0,
            fee_aware_multiplier=config.fee_aware_multiplier,
            directional_confirmation_minutes=config.m30_minutes if config.m30 else 0,
            require_stoch_rsi_momentum_entry=config.stoch_momentum,
            min_ema_strength_atr=config.min_ema_strength_atr,
            max_ema_strength_atr=config.max_ema_strength_atr,
            min_vwap_displacement_atr=config.min_vwap_displacement_atr,
            min_signal_volume_ratio=config.min_signal_volume_ratio,
            min_days_to_expiry=config.min_days_to_expiry,
            min_days_to_expiry_inclusive=config.min_days_to_expiry_inclusive,
            max_days_to_expiry=config.max_days_to_expiry,
            ema_exit_rule=config.ema_exit_rule,
            exit_when_all_fail=config.exit_policy == "ALL_FAIL",
            entry_windows_ist_minutes=config.entry_windows_ist_minutes,
            blocked_weekdays_ist=config.no_trade_days_ist,
            pullback_reversal=config.zigzag,
            entry_mode=config.entry_mode,
            momentum_breakout=config.momentum_breakout,
            early_failure=config.early_failure,
            hard_stop_percent_override=config.hard_stop_percent,
            hard_stop_fill_mode=config.hard_stop_fill_mode,
        )
        for scenario in plain_scenarios()
        if scenario.group in config.bt_families
    ]


def configuration_metadata(config: CombinationConfig) -> dict[str, Any]:
    result = asdict(config)
    result["enabled_filters"] = config.enabled_filters
    result["entry_windows_ist"] = config.entry_windows_ist
    result["no_trade_days"] = config.no_trade_day_names
    return result


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _month_interval(value: str) -> tuple[datetime, datetime]:
    start = datetime.strptime(value, "%Y-%m").replace(tzinfo=UTC)
    end = (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )
    return start, end


def _requested_intervals(
    selection: BacktestSelection,
) -> list[tuple[datetime, datetime]] | None:
    if selection.months:
        raw = [_month_interval(value) for value in selection.months]
    elif selection.start_date is not None and selection.end_date is not None:
        start = datetime.combine(
            date.fromisoformat(selection.start_date), datetime.min.time(), UTC
        )
        end = datetime.combine(
            date.fromisoformat(selection.end_date) + timedelta(days=1),
            datetime.min.time(),
            UTC,
        )
        raw = [(start, end)]
    else:
        return None

    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(raw):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _candidate_segments(selection: BacktestSelection) -> tuple[Segment, ...]:
    if selection.directory is None:
        if selection.source == "R2_L1":
            raise ValueError("backtest.directory is required when source=R2_L1")
        return SEGMENTS

    directory = Path(selection.directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"backtest data directory does not exist: {directory}")
    catalog_path = directory / "catalog.json"
    if catalog_path.exists():
        if selection.source != "PUBLIC_HISTORY":
            raise ValueError("catalog directories support source=PUBLIC_HISTORY only")
        from .history_archive import load_catalog

        catalog = load_catalog(directory)
        if not catalog:
            raise RuntimeError(f"history archive catalog has no segments: {catalog_path}")
        return tuple(
            Segment(item.name, item.directory, item.start, item.end)
            for item in catalog
        )
    available_start, available_end = _manifest_range(directory)
    label = "r2_l1" if selection.source == "R2_L1" else "configured_history"
    return (
        Segment(
            label,
            directory,
            _iso_utc(available_start),
            _iso_utc(available_end),
        ),
    )


def configured_segments(config: CombinationConfig) -> tuple[Segment, ...]:
    candidates = _candidate_segments(config.backtest)
    requested = _requested_intervals(config.backtest)
    if requested is None:
        return candidates

    selected: list[Segment] = []
    for candidate in candidates:
        candidate_start = datetime.fromisoformat(
            candidate.start.replace("Z", "+00:00")
        ).astimezone(UTC)
        candidate_end = datetime.fromisoformat(
            candidate.end.replace("Z", "+00:00")
        ).astimezone(UTC)
        for requested_start, requested_end in requested:
            start = max(candidate_start, requested_start)
            end = min(candidate_end, requested_end)
            if start >= end:
                continue
            name = candidate.name
            if start != candidate_start or end != candidate_end:
                name += f"_{start:%Y%m%dT%H%M%S}_{end:%Y%m%dT%H%M%S}"
            selected.append(
                Segment(name, candidate.directory, _iso_utc(start), _iso_utc(end))
            )
    if not selected:
        requested_label = ", ".join(config.backtest.months) or (
            f"{config.backtest.start_date} through {config.backtest.end_date}"
        )
        raise ValueError(
            f"No {config.backtest.source} data overlaps {requested_label}"
        )

    if config.backtest.source == "PUBLIC_HISTORY":
        for requested_start, requested_end in requested:
            cursor = requested_start
            for segment in sorted(selected, key=lambda item: item.start):
                start = datetime.fromisoformat(
                    segment.start.replace("Z", "+00:00")
                ).astimezone(UTC)
                end = datetime.fromisoformat(
                    segment.end.replace("Z", "+00:00")
                ).astimezone(UTC)
                if end <= cursor or start >= requested_end:
                    continue
                if start > cursor:
                    break
                cursor = max(cursor, end)
                if cursor >= requested_end:
                    break
            if cursor < requested_end:
                raise ValueError(
                    "PUBLIC_HISTORY does not fully cover requested interval "
                    f"{_iso_utc(requested_start)} to {_iso_utc(requested_end)}"
                )
    return tuple(selected)


def selected_data_fidelity(config: CombinationConfig) -> str:
    if config.backtest.source == "PUBLIC_HISTORY":
        return "LOW_FIDELITY_SYNTHETIC_BBO"
    assert config.backtest.directory is not None
    manifest_path = Path(config.backtest.directory) / "recording_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    inferred = int(manifest.get("inferred_bid_sizes", 0)) + int(
        manifest.get("inferred_ask_sizes", 0)
    )
    return (
        "RECORDED_BBO_WITH_INFERRED_SIZE"
        if inferred > 0
        else "RECORDED_BBO"
    )


def scenario_output_name(scenarios: list[Any]) -> str:
    if not scenarios:
        raise ValueError("at least one scenario is required for output naming")
    if len(scenarios) == 1:
        return str(scenarios[0].name)

    plain_names = {scenario.group: scenario.name for scenario in plain_scenarios()}
    suffixes: list[str] = []
    family_labels: list[str] = []
    for scenario in scenarios:
        base_name = plain_names.get(scenario.group, "")
        name = str(scenario.name)
        if not base_name or not name.startswith(base_name):
            return "__".join(str(item.name) for item in scenarios)
        family_labels.append(f"BT{scenario.group}")
        suffixes.append(name[len(base_name):])
    if len(set(suffixes)) != 1:
        return "__".join(str(item.name) for item in scenarios)
    return "-".join(family_labels) + suffixes[0]


def versioned_output_path(base: Path) -> Path:
    if not base.exists():
        return base
    for version in itertools.count(2):
        candidate = base.with_name(f"{base.name}_v{version}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("could not allocate a versioned report directory")


def resolve_output_path(
    requested: Path | None,
    scenarios: list[Any],
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> Path:
    if requested is None:
        base = output_root / scenario_output_name(scenarios)
    elif requested.is_absolute():
        base = requested
    else:
        base = output_root / requested
    return versioned_output_path(base)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one manually configured BT1-BT3 filter combination",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "optional folder name under backtest/reports/manual-combinations; "
            "absolute paths are used directly"
        ),
    )
    args = parser.parse_args()

    config = load_config(args.config)
    selected = build_scenarios(config)
    segments = configured_segments(config)
    data_fidelity = selected_data_fidelity(config)
    output = resolve_output_path(args.output, selected)
    output.mkdir(parents=True, exist_ok=False)

    print(f"Combination: {config.name}")
    print(f"Scenario folder: {output.name}")
    print(f"Exit policy: {config.exit_policy}")
    print(f"Entry mode: {config.entry_mode}")
    print(f"Execution mode: {config.execution.mode}")
    print(f"Data source: {config.backtest.source}")
    print(f"Data fidelity: {data_fidelity}")
    print(
        "Backtest range(s): "
        + ", ".join(f"{item.start} to {item.end}" for item in segments)
    )
    print(
        "Maximum hold: "
        + (
            "disabled"
            if config.max_hold_hours is None
            else f"{config.max_hold_hours:g} hours"
        )
    )
    print(
        "Expiry exit: "
        + (
            "disabled"
            if config.exit_days_to_expiry is None
            else f"{config.exit_days_to_expiry:g} days remaining"
        )
    )
    print(
        "Profit protection: "
        + (
            f"{config.profit_protection_mode.lower()} at "
            f"+{config.profit_protection_activation_percent:g}%, "
            f"protect {config.profit_protection_protect_percent:g}%"
            if config.profit_protection_enabled
            else "disabled"
        )
    )
    print(f"Filters: {', '.join(config.enabled_filters) or 'none'}")
    print(f"IST windows: {', '.join(config.entry_windows_ist) or 'all day'}")
    print(f"No-trade days: {', '.join(config.no_trade_day_names) or 'none'}")
    print(f"BT families: {', '.join(f'BT{item}' for item in config.bt_families)}")
    result = run(
        output,
        selected_scenarios=selected,
        study="manual_combination",
        configuration=configuration_metadata(config),
        max_hold_minutes=(
            config.max_hold_hours * 60.0
            if config.max_hold_hours is not None
            else None
        ),
        exit_days_to_expiry=config.exit_days_to_expiry,
        hard_stop_percent=config.hard_stop_percent,
        max_spread_percent=config.max_spread_percent,
        min_volume=config.min_volume,
        volume_quantity_multiplier=config.volume_quantity_multiplier,
        execution=config.execution,
        segments=segments,
        data_source=config.backtest.source,
        data_fidelity=data_fidelity,
    )
    print_summary(result)
    print(f"\nReports ready: {output.resolve()}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise SystemExit(f"Error: {exc}") from None
