from __future__ import annotations

import pytest

from backtest.jan_jul_2026 import (
    END,
    M30_SCENARIO,
    MONTHS,
    PREFERRED_SCENARIO,
    START,
    _aggregate_metrics,
    _retryable_download_error,
    _with_download_retries,
    preferred_scenario,
    research_scenarios,
)


def trade(
    entry: str,
    pnl: float,
    gross: float,
    fees: float,
    direction: str = "CALL",
) -> dict[str, object]:
    return {
        "entry_time": entry,
        "exit_time": entry,
        "pnl_usd": pnl,
        "gross_pnl_usd": gross,
        "fees_usd": fees,
        "direction": direction,
    }


def test_months_cover_january_through_july_without_gaps():
    assert START == MONTHS[0].start
    assert END == MONTHS[-1].end
    assert [month.label for month in MONTHS] == [
        "2026-01",
        "2026-02",
        "2026-03",
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
    ]
    assert all(left.end == right.start for left, right in zip(MONTHS, MONTHS[1:]))


def test_preferred_scenario_is_the_locked_loss_prevention_candidate():
    scenario = preferred_scenario()

    assert scenario.name == PREFERRED_SCENARIO
    assert scenario.require_macd is True
    assert scenario.macd_exit_policy == "REVERSAL_ONLY"
    assert scenario.min_option_true_ranges == 6
    assert scenario.fee_aware_multiplier == pytest.approx(1.5)
    assert scenario.entry_start_hour_utc == 8
    assert scenario.entry_end_hour_utc == 16


def test_january_july_runner_compares_stoch_with_its_m30_control():
    scenarios = research_scenarios()

    assert [scenario.name for scenario in scenarios] == [
        PREFERRED_SCENARIO,
        M30_SCENARIO,
        "BT1_EMA_MACD_MACDREV_ONLY_H6_FA150_M30_STOCH_UTC00_16",
        "BT1_EMA_STOCH",
        "BT2_EMA_VWAP_STOCH",
        "BT3_EMA_VWAP_RSI_STOCH",
    ]


def test_aggregate_metrics_orders_trades_and_includes_fees():
    metrics = _aggregate_metrics(
        [
            trade("2026-02-01T00:00:00Z", -2.0, -1.5, 0.5),
            trade("2026-01-01T00:00:00Z", 3.0, 3.5, 0.5),
            trade("2026-03-01T00:00:00Z", -1.0, -0.5, 0.5, "PUT"),
        ],
        starting_balance=100.0,
    )

    assert metrics["trades"] == 3
    assert metrics["wins"] == 1
    assert metrics["losses"] == 2
    assert metrics["gross_pnl_usd"] == pytest.approx(1.5)
    assert metrics["fees_usd"] == pytest.approx(1.5)
    assert metrics["net_pnl_usd"] == pytest.approx(0.0)
    assert metrics["profit_factor"] == pytest.approx(1.0)
    assert metrics["pnl_per_trade_usd"] == pytest.approx(0.0)
    assert metrics["average_win_usd"] == pytest.approx(3.0)
    assert metrics["average_loss_usd"] == pytest.approx(-1.5)
    assert metrics["largest_win_usd"] == pytest.approx(3.0)
    assert metrics["call_pnl_usd"] == pytest.approx(1.0)
    assert metrics["put_pnl_usd"] == pytest.approx(-1.0)
    assert metrics["max_drawdown_usd"] == pytest.approx(3.0)


@pytest.mark.parametrize(
    "message",
    [
        "Delta API request failed: [Errno 11001] getaddrinfo failed",
        "Delta API returned HTTP 429: slow down",
        "Delta API returned HTTP 503: unavailable",
    ],
)
def test_transient_download_errors_are_retryable(message):
    assert _retryable_download_error(RuntimeError(message)) is True


def test_download_retry_resumes_after_transient_failure_without_waiting_in_test():
    calls: list[int] = []
    waits: list[float] = []

    def operation(attempt: int):
        calls.append(attempt)
        if attempt < 3:
            raise RuntimeError("Delta API request failed: temporary DNS failure")
        return {"downloaded_requests": 1}

    result = _with_download_retries(
        operation,
        attempts=4,
        wait_seconds=2.0,
        sleep=waits.append,
    )

    assert result == {"downloaded_requests": 1}
    assert calls == [1, 2, 3]
    assert waits == [2.0, 4.0]


def test_download_retry_does_not_hide_non_transient_errors():
    with pytest.raises(RuntimeError, match="no usable option candles"):
        _with_download_retries(
            lambda attempt: (_ for _ in ()).throw(
                RuntimeError("Delta returned no usable option candles")
            ),
            attempts=20,
            wait_seconds=0.0,
            sleep=lambda seconds: None,
        )
