"""Opt-in incremental H6 BASELINE signal evaluation from complete candle chunks.

Only the legacy BASELINE H6 signal family is supported. Pullback/ZIGZAG
and MOMENTUM signal modes fail closed; they require independent history
and pattern-state work. This module consumes complete, already calculated
indicator chunks and emits individual SignalEvent objects immediately. It
never materializes a complete historical indicator frame or signal list.

The original signal_events()/run_dataset() contracts and defaults remain
unchanged. This is NOT yet an integrated streaming quote/trade executor.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Iterator, Iterable

import pandas as pd

from .data import OptionSpec
from .ema_vwap_research import (
    Scenario, SignalEvent, _append_decision_event,
    _entry_time_allowed, _select_option,
    _stoch_rsi_entry_direction, _stoch_rsi_momentum_entry_direction,
)
from .option_expiry_index import OptionExpiryIndex


@dataclass
class _Pending:
    due_row: int
    timestamp: pd.Timestamp
    signal_row: pd.Series
    direction: str
    entry_type: str
    matched: bool = True


class IncrementalBaselineSignals:
    """Bounded confirmation state for one original H6 baseline configuration."""

    def __init__(
        self,
        specs: list[OptionSpec],
        *,
        start_ns: int,
        end_ns: int,
        scenario: Scenario,
        decision_events: Any | None = None,
        signal_diagnostics: dict[str, int] | None = None,
        option_index: OptionExpiryIndex | None = None,
    ):
        if scenario.entry_mode.strip().upper().replace("-", "_") != "BASELINE":
            raise ValueError("INCREMENTAL_SIGNALS_ENTRY_MODE_UNSUPPORTED")
        if scenario.pullback_reversal.enabled or scenario.momentum_breakout.enabled:
            raise ValueError("INCREMENTAL_SIGNALS_ENTRY_MODE_UNSUPPORTED")
        if scenario.entry_min_conditions not in (1, 2, 3):
            raise ValueError("entry_min_conditions must be 1, 2, or 3")
        if (
            scenario.require_stoch_rsi_entry
            and scenario.require_stoch_rsi_momentum_entry
        ):
            raise ValueError("only one Stoch RSI entry relationship can be enabled")
        if type(scenario.confirmation_candles) is not int or scenario.confirmation_candles < 0:
            raise ValueError("confirmation_candles must be a nonnegative integer")
        if end_ns <= start_ns:
            raise ValueError("end_ns must follow start_ns")
        self.scenario = scenario
        self.specs = specs
        self.start_ns = start_ns
        self.end_ns = end_ns
        self.decision_events = decision_events
        self.signal_diagnostics = signal_diagnostics
        self.option_index = option_index
        self._previous_direction = ""
        self._previous_regime = ""
        self._regime_start_ns = 0
        self._row_index = 0
        self._last_timestamp: pd.Timestamp | None = None
        self._pending: deque[_Pending] = deque()
        self._finished = False
        self.signal_count = 0
        self.max_pending = 0

    def _direction(self, row: pd.Series) -> str:
        scenario = self.scenario
        if scenario.entry_min_conditions == 3:
            return str(row["direction_macd" if scenario.require_macd else "direction"])
        # Use precisely the same three strict tests as original
        # signal_events(entry_min_conditions < 3).
        close = row["close"]
        vwap = row["vwap"]
        ema9, ema20, ema50 = row["ema9"], row["ema20"], row["ema50"]
        rsi = row["rsi14"]
        call = int(close > vwap) + int(ema9 > ema20 and ema20 > ema50) + int(
            50.0 <= rsi <= 70.0
        )
        put = int(close < vwap) + int(ema9 < ema20 and ema20 < ema50) + int(
            30.0 <= rsi <= 50.0
        )
        direction = (
            "CALL" if call >= scenario.entry_min_conditions and call > put
            else "PUT" if put >= scenario.entry_min_conditions and put > call
            else ""
        )
        if scenario.require_macd and (
            (direction == "CALL" and not row["macd"] > row["macd_signal"])
            or (direction == "PUT" and not row["macd"] < row["macd_signal"])
        ):
            return ""
        return direction

    def _session_allowed(self, timestamp: pd.Timestamp) -> bool:
        scenario = self.scenario
        return _entry_time_allowed(
            timestamp,
            entry_start_hour_utc=scenario.entry_start_hour_utc,
            entry_end_hour_utc=scenario.entry_end_hour_utc,
            entry_windows_ist_minutes=scenario.entry_windows_ist_minutes,
            blocked_weekdays_ist=scenario.blocked_weekdays_ist,
        )

    def _decision(
        self, timestamp: pd.Timestamp, row: pd.Series, *,
        status: str, reason: str, direction: str,
        symbol: str = "", entry_type: str = "BASELINE",
    ) -> None:
        _append_decision_event(
            self.decision_events,
            timestamp=timestamp,
            stage="SIGNAL",
            status=status,
            reason=reason,
            direction=direction,
            row=row,
            entry_type=entry_type,
            symbol=symbol,
        )

    def _complete(
        self, pending: _Pending, timestamp: pd.Timestamp, row: pd.Series,
    ) -> SignalEvent | None:
        direction = pending.direction
        if not pending.matched:
            self._decision(
                timestamp, row, status="REJECTED",
                reason="SIGNAL_CONFIRMATION_REJECTED",
                direction=direction, entry_type=pending.entry_type,
            )
            return None
        scenario = self.scenario
        if scenario.require_stoch_rsi_entry and not _stoch_rsi_entry_direction(
            direction, float(row["stoch_rsi_k"]), float(row["stoch_rsi_d"]),
        ):
            self._decision(
                timestamp, row, status="REJECTED", reason="STOCH_RSI_REJECTED",
                direction=direction, entry_type=pending.entry_type,
            )
            return None
        if (
            scenario.require_stoch_rsi_momentum_entry
            and not _stoch_rsi_momentum_entry_direction(
                direction, float(row["stoch_rsi_k"]), float(row["stoch_rsi_d"]),
            )
        ):
            self._decision(
                timestamp, row, status="REJECTED",
                reason="STOCH_RSI_MOMENTUM_REJECTED",
                direction=direction, entry_type=pending.entry_type,
            )
            return None
        if not self._session_allowed(timestamp):
            self._decision(
                timestamp, row, status="REJECTED",
                reason="OUTSIDE_ENTRY_SESSION",
                direction=direction, entry_type=pending.entry_type,
            )
            return None
        signal_ns = int(timestamp.timestamp() * 1_000_000_000)
        if not self.start_ns <= signal_ns < self.end_ns:
            return None
        option = (
            self.option_index.select(
                signal_ns, direction, float(row["close"]),
                min_days_to_expiry=scenario.min_days_to_expiry,
                min_days_to_expiry_inclusive=scenario.min_days_to_expiry_inclusive,
                max_days_to_expiry=scenario.max_days_to_expiry,
            )
            if self.option_index is not None
            else _select_option(
                self.specs, signal_ns, direction, float(row["close"]),
                min_days_to_expiry=scenario.min_days_to_expiry,
                min_days_to_expiry_inclusive=scenario.min_days_to_expiry_inclusive,
                max_days_to_expiry=scenario.max_days_to_expiry,
            )
        )
        if option is None:
            self._decision(
                timestamp, row, status="REJECTED",
                reason="NO_ELIGIBLE_OPTION_REJECTED",
                direction=direction, entry_type=pending.entry_type,
            )
            return None
        self._decision(
            timestamp, row, status="QUALIFIED",
            reason="SIGNAL_WITH_CONTRACT", direction=direction,
            symbol=option.symbol, entry_type=pending.entry_type,
        )
        self.signal_count += 1
        return SignalEvent(
            signal_ns, direction, float(row["close"]), option, [],
            ema_regime_start_ns=self._regime_start_ns,
            entry_type=pending.entry_type,
        )

    def process_chunk(self, frame: pd.DataFrame) -> Iterator[SignalEvent]:
        if self._finished:
            raise RuntimeError("INCREMENTAL_SIGNALS_ALREADY_FINISHED")
        required = {
            "open", "high", "low", "close", "volume", "vwap",
            "ema9", "ema20", "ema50", "rsi14", "atr14",
            "volume_median20_prior", "macd", "macd_signal",
            "stoch_rsi_k", "stoch_rsi_d", "direction", "direction_macd",
        }
        missing = required - set(frame.columns)
        if missing:
            raise ValueError("INCREMENTAL_SIGNALS_MISSING_COLUMNS: " + ",".join(sorted(missing)))
        if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
            raise ValueError("INCREMENTAL_SIGNALS_TIMESTAMPS_REQUIRE_TIMEZONE")
        for timestamp, row in frame.iterrows():
            if self._last_timestamp is not None and timestamp < self._last_timestamp:
                raise ValueError("INCREMENTAL_SIGNALS_TIMESTAMP_OUT_OF_ORDER")
            self._last_timestamp = timestamp
            current_direction = self._direction(row)
            regime = (
                "CALL"
                if row["ema9"] > row["ema20"] > row["ema50"]
                else "PUT"
                if row["ema9"] < row["ema20"] < row["ema50"]
                else ""
            )
            if regime != self._previous_regime:
                self._regime_start_ns = (
                    int(timestamp.timestamp() * 1_000_000_000) if regime else 0
                )
            self._previous_regime = regime
            if self._pending:
                # Pending confirmations are always processed in original
                # signal-position order, never by completion timestamp.
                for pending in self._pending:
                    if current_direction != pending.direction:
                        pending.matched = False
                while self._pending and self._pending[0].due_row == self._row_index:
                    pending = self._pending.popleft()
                    event = self._complete(pending, timestamp, row)
                    if event is not None:
                        yield event
            if current_direction and current_direction != self._previous_direction:
                pending = _Pending(
                    due_row=self._row_index + self.scenario.confirmation_candles,
                    timestamp=timestamp, signal_row=row, direction=current_direction,
                    entry_type="BASELINE",
                )
                if self.scenario.confirmation_candles == 0:
                    event = self._complete(pending, timestamp, row)
                    if event is not None:
                        yield event
                else:
                    self._pending.append(pending)
                    self.max_pending = max(self.max_pending, len(self._pending))
            self._previous_direction = current_direction
            self._row_index += 1

    def finish(self) -> None:
        if self._finished:
            raise RuntimeError("INCREMENTAL_SIGNALS_ALREADY_FINISHED")
        for pending in self._pending:
            self._decision(
                pending.timestamp, pending.signal_row,
                status="REJECTED", reason="CONFIRMATION_OUT_OF_RANGE",
                direction=pending.direction, entry_type=pending.entry_type,
            )
        self._pending.clear()
        self._finished = True


def iter_incremental_baseline_signals(
    chunks: Iterable[pd.DataFrame],
    specs: list[OptionSpec],
    *,
    start_ns: int,
    end_ns: int,
    scenario: Scenario,
    decision_events: Any | None = None,
    signal_diagnostics: dict[str, int] | None = None,
    option_index: OptionExpiryIndex | None = None,
) -> Iterator[SignalEvent]:
    """Produce qualified H6 baseline events without retaining event history."""
    state = IncrementalBaselineSignals(
        specs, start_ns=start_ns, end_ns=end_ns, scenario=scenario,
        decision_events=decision_events,
        signal_diagnostics=signal_diagnostics, option_index=option_index,
    )
    for chunk in chunks:
        yield from state.process_chunk(chunk)
    state.finish()
