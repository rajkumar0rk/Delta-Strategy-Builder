from __future__ import annotations
from typing import Any, Literal
import re
from pydantic import BaseModel, Field, model_validator

Operator = Literal[
    "GT", "GTE", "LT", "LTE", "EQ", "BETWEEN",
    "CROSSES_ABOVE", "CROSSES_BELOW", "RISING", "FALLING",
    "GT_BY_POINTS", "LT_BY_POINTS", "GT_BY_PERCENT", "LT_BY_PERCENT",
    "WAS_GT", "WAS_GTE", "WAS_LT", "WAS_LTE", "WAS_BETWEEN",
    "CROSSED_ABOVE_WITHIN", "CROSSED_BELOW_WITHIN",
    # V10 generic count/slope operators. COUNT_* uses lookback_bars and `value`
    # as the required count. SLOPE_* uses lookback_bars and `value` as the
    # required points-per-bar slope.
    "COUNT_TRUE_GTE", "COUNT_CROSS_ABOVE_GTE", "COUNT_CROSS_BELOW_GTE", "COUNT_CROSS_EITHER_GTE",
    "SLOPE_GT", "SLOPE_GTE", "SLOPE_LT", "SLOPE_LTE",
]


class IndicatorInstance(BaseModel):
    id: str = Field(min_length=1, pattern=r"^[A-Za-z][A-Za-z0-9_\-]*$")
    kind: str
    params: dict[str, float | int | str] = Field(default_factory=dict)
    visible: bool = True
    chart_only: bool = False
    # `strategy` means calculate on the strategy timeframe. Higher-timeframe
    # indicators are calculated only from fully completed aggregated candles and
    # forward-filled onto later lower-timeframe candles (no look-ahead).
    timeframe: Literal["strategy", "5m", "10m", "15m", "30m", "1h"] = "strategy"


class Condition(BaseModel):
    id: str = ""
    left: str
    operator: Operator
    right: str | None = None
    value: float | None = None
    value2: float | None = None
    left_offset: int = Field(default=0, ge=0, le=100)
    right_offset: int = Field(default=0, ge=0, le=100)
    lookback_bars: int = Field(default=5, ge=1, le=1000)

    @model_validator(mode="after")
    def validate_rhs(self):
        if self.operator in {"RISING", "FALLING"}:
            return self
        if self.operator in {"COUNT_TRUE_GTE", "COUNT_CROSS_ABOVE_GTE", "COUNT_CROSS_BELOW_GTE", "COUNT_CROSS_EITHER_GTE"}:
            if self.value is None or self.value < 0:
                raise ValueError(f"{self.operator} requires value >= 0 as the required count")
            if self.operator != "COUNT_TRUE_GTE" and self.right is None:
                raise ValueError(f"{self.operator} requires a right operand")
            return self
        if self.operator in {"SLOPE_GT", "SLOPE_GTE", "SLOPE_LT", "SLOPE_LTE"}:
            if self.value is None:
                raise ValueError(f"{self.operator} requires a numeric slope threshold in value")
            return self
        if self.operator in {"BETWEEN", "WAS_BETWEEN"}:
            if self.value is None or self.value2 is None:
                raise ValueError(f"{self.operator} requires value and value2")
            return self
        if self.operator in {"GT_BY_POINTS", "LT_BY_POINTS", "GT_BY_PERCENT", "LT_BY_PERCENT"}:
            if self.right is None or self.value is None:
                raise ValueError(f"{self.operator} requires a right operand and a margin value")
            if self.value < 0:
                raise ValueError(f"{self.operator} margin must be >= 0")
            return self
        if self.right is None and self.value is None:
            raise ValueError(f"{self.operator} requires right operand or value")
        return self


class RuleGroup(BaseModel):
    mode: Literal["ALL", "ANY", "AT_LEAST"] = "ALL"
    min_pass: int = Field(default=1, ge=1)
    conditions: list[Condition] = Field(default_factory=list)
    groups: list["RuleGroup"] = Field(default_factory=list)

    def configured(self) -> bool:
        return bool(self.conditions or self.groups)


AlertSource = Literal[
    "CALL_ENTRY", "PUT_ENTRY", "CALL_EXIT", "PUT_EXIT",
    "NO_TRADE", "CALL_NO_TRADE", "PUT_NO_TRADE", "LEGACY_CUSTOM",
]
SignalMode = Literal["ORDER_ONLY", "ALERT_ONLY", "BOTH"]

ALERT_SOURCE_FIELDS = {
    "CALL_ENTRY": "call_entry", "PUT_ENTRY": "put_entry",
    "CALL_EXIT": "call_exit", "PUT_EXIT": "put_exit",
    "NO_TRADE": "no_trade", "CALL_NO_TRADE": "call_no_trade",
    "PUT_NO_TRADE": "put_no_trade",
}


class AlertRule(BaseModel):
    """Independent completed-candle alert that never places an option order."""
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=100)
    message: str = Field(default="", max_length=500)
    enabled: bool = True
    direction: Literal["CALL", "PUT", "NEUTRAL"] = "NEUTRAL"
    trigger_mode: Literal["ON_ENTER", "EVERY_BAR"] = "ON_ENTER"
    cooldown_bars: int = Field(default=0, ge=0, le=10000)
    source: AlertSource = "CALL_ENTRY"
    # Optional reference to one EXISTING condition within the chosen rule tree.
    # Empty means the entire existing AND/OR tree. No second rule builder.
    condition_id: str | None = None
    # Only for backward-compatible V16.1 JSON saved before source selection.
    conditions: RuleGroup = Field(default_factory=RuleGroup)

    @model_validator(mode="before")
    @classmethod
    def migrate_independent_conditions(cls, value):
        if isinstance(value, dict) and "source" not in value and value.get("conditions"):
            return {**value, "source": "LEGACY_CUSTOM"}
        return value

    @model_validator(mode="after")
    def validate_name(self):
        if not self.name.strip():
            raise ValueError("Alert name must not be blank")
        return self


class EntryBehavior(BaseModel):
    """One independent entry lifecycle.

    A lifecycle arms when its trigger becomes true. `delay_bars` is the minimum
    number of completed candles to wait after arming. `max_wait_bars` optionally
    limits how long the lifecycle may wait for the *full* directional entry tree
    to become true. If that window expires, the lifecycle stays expired until its
    trigger becomes false and later rearms. This gives strategies a clean
    "condition A happened; wait up to N candles for condition B" primitive.
    """
    id: str = Field(default="lifecycle-1", min_length=1, pattern=r"^[A-Za-z][A-Za-z0-9_\-]*$")
    name: str = "Lifecycle 1"
    enabled: bool = True
    trigger_condition_id: str | None = None
    delay_bars: int = Field(default=0, ge=0, le=500)
    max_wait_bars: int | None = Field(default=None, ge=0, le=5000)
    max_entries_per_activation: int = Field(default=1, ge=1, le=100)
    cooldown_bars: int = Field(default=0, ge=0, le=5000)

    @model_validator(mode="after")
    def validate_wait_window(self):
        if self.max_wait_bars is not None and self.max_wait_bars < self.delay_bars:
            raise ValueError("max_wait_bars must be >= delay_bars")
        return self


class OptionSelection(BaseModel):
    strike_mode: Literal["ATM", "ITM", "OTM"] = "ATM"
    strike_steps: int = Field(default=0, ge=0, le=20)
    min_dte_days: float = Field(default=0.25, ge=0)
    max_dte_days: float = Field(default=3.0, gt=0)
    min_premium: float | None = Field(default=None, ge=0)
    max_premium: float | None = Field(default=None, ge=0)
    max_spread_percent: float | None = Field(default=5.0, ge=0)
    min_volume: float | None = Field(default=None, ge=0)
    min_open_interest: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.max_dte_days < self.min_dte_days:
            raise ValueError("max_dte_days must be >= min_dte_days")
        if self.min_premium is not None and self.max_premium is not None and self.max_premium < self.min_premium:
            raise ValueError("max_premium must be >= min_premium")
        return self


class FeeEdgeFilterConfig(BaseModel):
    """Fee/spread-aware entry filter without pretending historical Greeks exist.

    The user supplies an assumed favorable option-premium move. The engine compares
    that gross move with current bid/ask spread + estimated Delta entry/exit fees.
    """
    enabled: bool = False
    expected_option_move_percent: float = Field(default=10.0, gt=0, le=1000)
    min_edge_multiple: float = Field(default=1.5, ge=0)
    min_net_edge_usd: float = Field(default=0.0, ge=0)


class ExecutionConfig(BaseModel):
    max_entry_quote_delay_seconds: int = Field(default=90, ge=0, le=3600)
    max_exit_quote_delay_seconds: int = Field(default=90, ge=0, le=3600)
    slippage_ticks: int = Field(default=0, ge=0, le=100)
    fee_model: Literal["DELTA_OPTIONS"] = "DELTA_OPTIONS"
    option_notional_fee_rate_percent: Literal[0.01] = 0.01
    premium_fee_cap_percent: Literal[3.5] = 3.5
    gst_percent: Literal[18.0] = 18.0
    decision_log_mode: Literal["FULL", "EVENTS_ONLY"] = "FULL"
    end_of_data_quote_max_age_seconds: int = Field(default=300, ge=0, le=3600)
    fee_edge_filter: FeeEdgeFilterConfig = Field(default_factory=FeeEdgeFilterConfig)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_fee_rate(cls, value: Any):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        # V1-V4 exposed a simple premium percentage fee. V5 intentionally
        # migrates to the requested Delta options fee/cap/GST model instead.
        data.pop("fee_rate_percent", None)
        data.setdefault("fee_model", "DELTA_OPTIONS")
        data.setdefault("option_notional_fee_rate_percent", 0.01)
        data.setdefault("premium_fee_cap_percent", 3.5)
        data.setdefault("gst_percent", 18.0)
        return data


class StopLoss(BaseModel):
    mode: Literal["NONE", "OPTION_PERCENT", "OPTION_POINTS", "UNDERLYING_ATR"] = "OPTION_PERCENT"
    value: float = 15.0


class TakeProfit(BaseModel):
    mode: Literal["NONE", "OPTION_PERCENT", "OPTION_POINTS"] = "NONE"
    value: float = 30.0


class ProfitProtection(BaseModel):
    mode: Literal["NONE", "PEAK_RETENTION", "TRAILING_PERCENT"] = "NONE"
    activation_percent: float = Field(default=20.0, ge=0)
    retain_peak_percent: float = Field(default=50.0, ge=0, le=100)
    trail_percent_points: float = Field(default=10.0, ge=0)


class BigTrendScoreComponent(BaseModel):
    condition_id: str = Field(min_length=1)
    weight: float = Field(default=1.0, gt=0, le=1000)
    # BINARY preserves V10/V11 behavior. CONTINUOUS maps the condition's left
    # numeric operand linearly from zero_at -> full_at, clamped to 0..100% of
    # this component's weight. full_at may be lower than zero_at for lower-is-better.
    scoring_mode: Literal["BINARY", "CONTINUOUS"] = "BINARY"
    zero_at: float | None = None
    full_at: float | None = None

    @model_validator(mode="after")
    def validate_continuous(self):
        if self.scoring_mode == "CONTINUOUS":
            if self.zero_at is None or self.full_at is None:
                raise ValueError("CONTINUOUS score component requires zero_at and full_at")
            if float(self.zero_at) == float(self.full_at):
                raise ValueError("CONTINUOUS score component zero_at and full_at must differ")
        return self


class BigTrendScoreConfig(BaseModel):
    enabled: bool = False
    threshold: float = Field(default=70.0, ge=0, le=100)
    # GATE = entry tree must pass AND persisted score gate passes. SCORE_ONLY lets
    # the persisted Big Trend score gate be the directional decision by itself.
    mode: Literal["GATE", "SCORE_ONLY"] = "GATE"
    components: list[BigTrendScoreComponent] = Field(default_factory=list)
    # Example: threshold=80, persistence_hits=2, persistence_window=3 means
    # score >= 80 in at least 2 of the last 3 completed strategy candles.
    persistence_hits: int = Field(default=1, ge=1, le=1000)
    persistence_window: int = Field(default=1, ge=1, le=1000)
    require_current_threshold: bool = True

    @model_validator(mode="after")
    def validate_persistence(self):
        if self.persistence_hits > self.persistence_window:
            raise ValueError("persistence_hits must be <= persistence_window")
        return self


class TrendPhaseConfig(BaseModel):
    enabled: bool = False
    compression_max_score: float = Field(default=45.0, ge=0, le=100)
    ignition_min_score: float = Field(default=55.0, ge=0, le=100)
    confirmation_min_score: float = Field(default=70.0, ge=0, le=100)
    big_trend_min_score: float = Field(default=80.0, ge=0, le=100)
    exhaustion_below_score: float = Field(default=55.0, ge=0, le=100)

    @model_validator(mode="after")
    def validate_thresholds(self):
        if not (self.compression_max_score <= self.ignition_min_score <= self.confirmation_min_score <= self.big_trend_min_score):
            raise ValueError("Trend phase scores must satisfy COMPRESSION <= IGNITION <= CONFIRMATION <= BIG_TREND")
        return self


class BreakoutRetestConfig(BaseModel):
    enabled: bool = False
    breakout_condition_id: str | None = None
    breakout_level_operand: str | None = None
    tolerance_mode: Literal["POINTS", "PERCENT", "ATR"] = "PERCENT"
    tolerance_value: float = Field(default=0.25, ge=0)
    atr_operand: str | None = None
    max_retest_wait_bars: int = Field(default=12, ge=1, le=5000)
    hold_bars: int = Field(default=1, ge=1, le=100)
    require_retest_for_entry: bool = False
    false_breakout_window_bars: int = Field(default=3, ge=1, le=500)
    false_breakout_buffer_points: float = Field(default=0.0, ge=0)
    block_false_breakout_until_rearm: bool = True
    max_trend_age_bars: int | None = Field(default=30, ge=1, le=10000)

    @model_validator(mode="after")
    def validate_breakout(self):
        if self.enabled and (not self.breakout_condition_id or not self.breakout_level_operand):
            raise ValueError("Enabled breakout/retest requires breakout_condition_id and breakout_level_operand")
        if self.tolerance_mode == "ATR" and self.enabled and not self.atr_operand:
            raise ValueError("ATR breakout/retest tolerance requires atr_operand")
        return self


class RiskConfig(BaseModel):
    stop_loss: StopLoss = Field(default_factory=StopLoss)
    take_profit: TakeProfit = Field(default_factory=TakeProfit)
    profit_protection: ProfitProtection = Field(default_factory=ProfitProtection)
    max_hold_minutes: int | None = Field(default=240, ge=1)
    starting_balance_usd: float = Field(default=100.0, gt=0)
    quantity_mode: Literal["FIXED", "BUDGET"] = "FIXED"
    quantity: float = Field(default=10.0, gt=0)
    budget_usd: float = Field(default=50.0, gt=0)
    # If true, a valid minimum/fixed quantity is rejected when its premium-notional
    # plus entry fee exceeds budget_usd. If false, the engine may use the minimum
    # valid contract quantity even when it exceeds budget_usd. Exchange quantity
    # validity (min_quantity + size_increment) is always enforced either way.
    enforce_trade_budget_strict: bool = True
    enforce_cash: bool = True
    # V10 daily circuit breakers. Percent is measured from the day's opening
    # closed-trade equity. Limits reset at midnight in session.timezone.
    max_daily_loss_percent: float | None = Field(default=None, gt=0, le=100)
    max_trades_per_day: int | None = Field(default=None, ge=1, le=10000)
    max_consecutive_losses: int | None = Field(default=None, ge=1, le=1000)
    stop_trading_after_daily_loss_limit: bool = True


class SessionWindow(BaseModel):
    start: str = "00:00"
    end: str = "23:59"

    @model_validator(mode="after")
    def validate_clock(self):
        pattern = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
        if not pattern.match(self.start) or not pattern.match(self.end):
            raise ValueError("Session window times must use 24-hour HH:MM format")
        return self


class SessionConfig(BaseModel):
    timezone: str = "Asia/Kolkata"
    # V14 supports several trading windows in one local day. start/end remain in
    # the model for backward compatibility with V1-V13 strategy JSON.
    start: str = "00:00"
    end: str = "23:59"
    windows: list[SessionWindow] = Field(default_factory=lambda: [SessionWindow()])
    blocked_weekdays: list[int] = Field(default_factory=list)  # Monday=0

    @model_validator(mode="before")
    @classmethod
    def migrate_single_window(cls, value: Any):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if not data.get("windows"):
            data["windows"] = [{
                "start": str(data.get("start") or "00:00"),
                "end": str(data.get("end") or "23:59"),
            }]
        return data

    @model_validator(mode="after")
    def validate_windows(self):
        if not self.windows:
            raise ValueError("Entry session requires at least one enabled time window")
        if len(self.windows) > 16:
            raise ValueError("Entry session supports at most 16 time windows")
        # Keep legacy fields synchronized with the first window so older exports
        # and helper code still see a sensible start/end pair.
        self.start = self.windows[0].start
        self.end = self.windows[0].end
        self.blocked_weekdays = sorted(set(self.blocked_weekdays))
        if any(day < 0 or day > 6 for day in self.blocked_weekdays):
            raise ValueError("blocked_weekdays values must be between 0 and 6")
        return self


def _condition_ids(group: RuleGroup) -> set[str]:
    out = {c.id for c in group.conditions if c.id}
    for child in group.groups:
        out.update(_condition_ids(child))
    return out


def find_condition_for_validation(group: RuleGroup, condition_id: str) -> Condition | None:
    for condition in group.conditions:
        if condition.id == condition_id:
            return condition
    for child in group.groups:
        found = find_condition_for_validation(child, condition_id)
        if found is not None:
            return found
    return None


class StrategyConfig(BaseModel):
    name: str = "New BTC options strategy"
    timeframe: Literal["5m", "10m", "15m", "30m", "1h"] = "5m"
    direction_mode: Literal["CALL", "PUT", "BOTH"] = "BOTH"
    call_action: Literal["BUY", "SELL"] = "BUY"
    put_action: Literal["BUY", "SELL"] = "BUY"
    call_signal_mode: SignalMode = "ORDER_ONLY"
    put_signal_mode: SignalMode = "ORDER_ONLY"
    call_exit_signal_mode: SignalMode = "ORDER_ONLY"
    put_exit_signal_mode: SignalMode = "ORDER_ONLY"
    call_exit_alert_message: str = Field(default="CALL exit conditions triggered", max_length=500)
    put_exit_alert_message: str = Field(default="PUT exit conditions triggered", max_length=500)
    call_alert_message: str = Field(default="CALL entry conditions triggered", max_length=500)
    put_alert_message: str = Field(default="PUT entry conditions triggered", max_length=500)
    alerts: list[AlertRule] = Field(default_factory=list, max_length=30)
    indicators: list[IndicatorInstance] = Field(default_factory=list)
    call_entry: RuleGroup = Field(default_factory=RuleGroup)
    put_entry: RuleGroup = Field(default_factory=RuleGroup)
    # Legacy single-lifecycle fields are kept for backward import/research-path
    # compatibility. V8 uses the *_entry_lifecycles lists as the canonical source.
    call_entry_behavior: EntryBehavior = Field(default_factory=lambda: EntryBehavior(id="call-1", name="CALL lifecycle 1"))
    put_entry_behavior: EntryBehavior = Field(default_factory=lambda: EntryBehavior(id="put-1", name="PUT lifecycle 1"))
    call_entry_lifecycles: list[EntryBehavior] = Field(default_factory=list)
    put_entry_lifecycles: list[EntryBehavior] = Field(default_factory=list)
    call_exit: RuleGroup = Field(default_factory=lambda: RuleGroup(mode="ANY"))
    put_exit: RuleGroup = Field(default_factory=lambda: RuleGroup(mode="ANY"))
    # Shared no-trade stays for backward compatibility; V12 adds directional
    # filters which are ORed with the shared filter for their own side only.
    no_trade: RuleGroup = Field(default_factory=RuleGroup)
    call_no_trade: RuleGroup = Field(default_factory=RuleGroup)
    put_no_trade: RuleGroup = Field(default_factory=RuleGroup)
    call_big_trend_score: BigTrendScoreConfig = Field(default_factory=BigTrendScoreConfig)
    put_big_trend_score: BigTrendScoreConfig = Field(default_factory=BigTrendScoreConfig)
    call_trend_phase: TrendPhaseConfig = Field(default_factory=TrendPhaseConfig)
    put_trend_phase: TrendPhaseConfig = Field(default_factory=TrendPhaseConfig)
    call_breakout_retest: BreakoutRetestConfig = Field(default_factory=BreakoutRetestConfig)
    put_breakout_retest: BreakoutRetestConfig = Field(default_factory=BreakoutRetestConfig)
    option: OptionSelection = Field(default_factory=OptionSelection)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    conflict_policy: Literal["SKIP", "PREFER_CALL", "PREFER_PUT"] = "SKIP"
    # V7 remains intentionally exclusive: while a CALL is open PUT entry rules are
    # not evaluated, and vice versa. This makes the behavior explicit in JSON/UI.
    position_policy: Literal["EXCLUSIVE"] = "EXCLUSIVE"

    @model_validator(mode="before")
    @classmethod
    def migrate_older_shared_exit(cls, value: Any):
        """Import older strategy JSON while adding V8 lifecycle-list defaults."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        legacy = data.pop("exit", None)
        if legacy is not None:
            data.setdefault("call_exit", legacy)
            data.setdefault("put_exit", legacy)
        data.setdefault("call_entry_behavior", {"id": "call-1", "name": "CALL lifecycle 1"})
        data.setdefault("put_entry_behavior", {"id": "put-1", "name": "PUT lifecycle 1"})
        if not data.get("call_entry_lifecycles"):
            raw = data.get("call_entry_behavior") or {}
            legacy = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
            legacy.setdefault("id", "call-1")
            legacy.setdefault("name", "CALL lifecycle 1")
            data["call_entry_lifecycles"] = [legacy]
        if not data.get("put_entry_lifecycles"):
            raw = data.get("put_entry_behavior") or {}
            legacy = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
            legacy.setdefault("id", "put-1")
            legacy.setdefault("name", "PUT lifecycle 1")
            data["put_entry_lifecycles"] = [legacy]
        data.setdefault("position_policy", "EXCLUSIVE")
        data.setdefault("direction_mode", "BOTH")
        # V16.1 represented an alert-only direction as call_action=ALERT.
        # Migrate to orthogonal BUY/SELL trade direction + delivery mode.
        for side in ("call", "put"):
            key = f"{side}_action"
            if data.get(key) == "ALERT":
                data.setdefault(f"{side}_signal_mode", "ALERT_ONLY")
                data[key] = "BUY"
            data.setdefault(key, "BUY")
        data.setdefault("call_big_trend_score", {})
        data.setdefault("put_big_trend_score", {})
        data.setdefault("call_no_trade", {})
        data.setdefault("put_no_trade", {})
        data.setdefault("call_trend_phase", {})
        data.setdefault("put_trend_phase", {})
        data.setdefault("call_breakout_retest", {})
        data.setdefault("put_breakout_retest", {})
        return data

    @model_validator(mode="after")
    def validate_strategy_references(self):
        tf_minutes = {"5m":5,"10m":10,"15m":15,"30m":30,"1h":60}
        base = tf_minutes[self.timeframe]
        for indicator in self.indicators:
            if indicator.timeframe == "strategy":
                continue
            target = tf_minutes[indicator.timeframe]
            if target < base or target % base != 0:
                raise ValueError(
                    f"Indicator '{indicator.id}' timeframe {indicator.timeframe} must be an exact multiple "
                    f"of strategy timeframe {self.timeframe}"
                )
        blocked = {x.id for x in self.indicators if x.chart_only}

        def walk(g: RuleGroup):
            for c in g.conditions:
                for ref in (c.left, c.right):
                    if not ref:
                        continue
                    base = ref.split(".", 1)[0]
                    if base in blocked:
                        raise ValueError(
                            f"Chart-only indicator '{base}' is referenced by a strategy rule. "
                            "Turn off Chart only or remove it from the rule."
                        )
            for child in g.groups:
                walk(child)

        for group in (self.call_entry, self.put_entry, self.call_exit, self.put_exit, self.no_trade, self.call_no_trade, self.put_no_trade):
            walk(group)
        seen_alerts: set[str] = set()
        for alert in self.alerts:
            if alert.id in seen_alerts:
                raise ValueError(f"Alert ids must be unique: {alert.id}")
            seen_alerts.add(alert.id)
            if alert.source == "LEGACY_CUSTOM":
                walk(alert.conditions)
                if alert.condition_id:
                    raise ValueError("Legacy alert cannot reference a source condition")
            else:
                source_tree = getattr(self, ALERT_SOURCE_FIELDS[alert.source])
                if alert.condition_id and not find_condition_for_validation(source_tree, alert.condition_id):
                    raise ValueError(
                        f"Alert {alert.id} references missing condition id "
                        f"{alert.condition_id} in {alert.source}"
                    )

        for side, group, behaviors in (
            ("CALL", self.call_entry, self.call_entry_lifecycles),
            ("PUT", self.put_entry, self.put_entry_lifecycles),
        ):
            enabled_side = self.direction_mode in {side, "BOTH"}
            seen: set[str] = set()
            ids = _condition_ids(group)
            for behavior in behaviors:
                if behavior.id in seen:
                    raise ValueError(f"{side} entry lifecycle ids must be unique: {behavior.id}")
                seen.add(behavior.id)
                if behavior.trigger_condition_id and behavior.trigger_condition_id not in ids:
                    raise ValueError(
                        f"{side} trigger_condition_id '{behavior.trigger_condition_id}' does not exist in the {side} entry rule tree"
                    )
            action = self.call_action if side == "CALL" else self.put_action
            if enabled_side and action != "ALERT" and not any(x.enabled for x in behaviors):
                raise ValueError(f"{side} requires at least one enabled entry lifecycle when direction_mode includes {side}")
        for side, group, score in (("CALL", self.call_entry, self.call_big_trend_score), ("PUT", self.put_entry, self.put_big_trend_score)):
            if not score.enabled:
                continue
            ids = _condition_ids(group)
            if not score.components:
                raise ValueError(f"{side} Big Trend Score is enabled but has no weighted components")
            unknown = [x.condition_id for x in score.components if x.condition_id not in ids]
            if unknown:
                raise ValueError(f"{side} Big Trend Score references unknown entry condition ids: {', '.join(unknown)}")
            # Prevent direct circular scoring. The score can be used by OTHER entry
            # rules, history/slope/count rules, phases, and lifecycle triggers, but a
            # component that constructs the score itself may not reference V12
            # strategy-state operands derived from that same score/breakout machine.
            prefix = side.lower() + "_"
            special_prefixes = (prefix + "big_trend_score", prefix + "phase_", prefix + "breakout_", prefix + "retest_", prefix + "false_breakout", prefix + "bars_since_breakout", prefix + "trend_too_old")
            for component in score.components:
                condition = find_condition_for_validation(group, component.condition_id)
                if condition and any((ref or "").startswith(special_prefixes) for ref in (condition.left, condition.right)):
                    raise ValueError(f"{side} Big Trend Score component '{component.condition_id}' creates a circular strategy-state reference")

        for side, group, cfg in (("CALL", self.call_entry, self.call_breakout_retest), ("PUT", self.put_entry, self.put_breakout_retest)):
            if not cfg.enabled:
                continue
            ids = _condition_ids(group)
            if cfg.breakout_condition_id not in ids:
                raise ValueError(f"{side} breakout_condition_id '{cfg.breakout_condition_id}' does not exist in the {side} entry rule tree")
            breakout_condition = find_condition_for_validation(group, cfg.breakout_condition_id or "")
            prefix=side.lower()+"_"
            if breakout_condition and any((ref or "").startswith((prefix+"breakout_",prefix+"retest_",prefix+"false_breakout",prefix+"bars_since_breakout",prefix+"phase_",prefix+"trend_phase")) for ref in (breakout_condition.left,breakout_condition.right)):
                raise ValueError(f"{side} breakout trigger may not depend on its own breakout/phase state")
            # breakout_level_operand may be a multi-output key like donchian.upper,
            # so runtime gives the precise missing-column error if unavailable.
            if not cfg.breakout_level_operand:
                raise ValueError(f"{side} breakout_level_operand is required")

        for side, phase, score in (("CALL",self.call_trend_phase,self.call_big_trend_score),("PUT",self.put_trend_phase,self.put_big_trend_score)):
            if phase.enabled and not score.enabled:
                raise ValueError(f"{side} Trend Phase requires {side} Big Trend Score to be enabled")

        # Keep the legacy single-lifecycle mirrors synchronized when present.
        if self.call_entry_lifecycles:
            self.call_entry_behavior = self.call_entry_lifecycles[0].model_copy(deep=True)
        if self.put_entry_lifecycles:
            self.put_entry_behavior = self.put_entry_lifecycles[0].model_copy(deep=True)
        return self


class DatasetSelection(BaseModel):
    dataset_id: str | None = None
    dataset_ids: list[str] = Field(default_factory=list)
    dataset_mode: Literal["SINGLE", "MULTI", "AUTO", "ARCHIVE"] = "SINGLE"
    # V14 opt-in self-healing archive preflight. Only ARCHIVE backtests use it;
    # preview/research requests may carry the field harmlessly.
    auto_download_missing_data: bool = False

    def requested_ids(self) -> list[str]:
        if self.dataset_mode == "SINGLE":
            return [self.dataset_id] if self.dataset_id else []
        if self.dataset_mode in {"AUTO", "ARCHIVE"}:
            return []
        return list(dict.fromkeys(self.dataset_ids))


class BacktestRequest(DatasetSelection):
    start: str
    end: str
    strategy: StrategyConfig
    # V15 result persistence profile. ANALYSIS is the recommended default: it
    # keeps reproducible metrics/trades plus compressed diagnostics without
    # duplicating large arrays in summary.json.
    storage_mode: Literal["COMPACT", "ANALYSIS", "FULL_DEBUG"] = "FULL_DEBUG"
    warmup_candles: int = Field(default=500, ge=0, le=20000)
    warmup_policy: Literal["WARN", "REQUIRE"] = "WARN"
    # Require complete 5m candle-close coverage to avoid silently trading across
    # missing history. WARN is an explicit compatibility/research override.
    bar_gap_policy: Literal["WARN", "REQUIRE"] = "REQUIRE"


class PreviewRequest(DatasetSelection):
    start: str
    end: str
    timeframe: Literal["5m", "10m", "15m", "30m", "1h"] = "5m"
    indicators: list[IndicatorInstance] = Field(default_factory=list)
    strategy: StrategyConfig | None = None


class PreflightRequest(DatasetSelection):
    start: str
    end: str
    strategy: StrategyConfig




class ArchiveSyncRequest(BaseModel):
    start: str
    end: str

class SaveStrategyRequest(BaseModel):
    strategy: StrategyConfig


class AiStrategyPromptRequest(BaseModel):
    dataset_id: str | None = None
    start: str | None = None
    end: str | None = None
    strategy: StrategyConfig




class TrendDiscoveryRequest(DatasetSelection):
    start: str
    end: str
    strategy: StrategyConfig
    # Forward window used to decide whether a setup was followed by a genuine
    # directional move. Values are strategy-timeframe candles.
    lookahead_bars: int = Field(default=24, ge=2, le=1000)
    big_move_percent: float = Field(default=1.5, gt=0, le=100)
    # Candidate fake-trend events are sampled only when the directional Big Trend
    # score reaches this threshold but the forward move fails to hit big_move_percent.
    candidate_score_threshold: float = Field(default=70.0, ge=0, le=100)
    prelude_bars: int = Field(default=12, ge=1, le=500)
    min_separation_bars: int = Field(default=12, ge=1, le=1000)
    max_events: int = Field(default=500, ge=10, le=5000)

class SweepDimension(BaseModel):
    path: str = Field(min_length=1)
    values: list[float] = Field(min_length=1, max_length=20)


class ResearchSweepRequest(BaseModel):
    dataset_id: str
    start: str
    end: str
    strategy: StrategyConfig
    dimensions: list[SweepDimension] = Field(min_length=1, max_length=3)
    max_combinations: int = Field(default=40, ge=1, le=200)
    walk_forward_folds: int = Field(default=0, ge=0, le=4)

    @model_validator(mode="after")
    def validate_walk_forward(self):
        if self.walk_forward_folds == 1:
            raise ValueError("walk_forward_folds must be 0 (off) or 2..4")
        return self


class AblationRequest(BaseModel):
    dataset_id: str
    start: str
    end: str
    strategy: StrategyConfig


RuleGroup.model_rebuild()
