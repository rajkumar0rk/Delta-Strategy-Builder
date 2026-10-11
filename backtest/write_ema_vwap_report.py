from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parent
REPORT_ROOT = ROOT / "reports"
MATRIX_ROOT = REPORT_ROOT / "ema-vwap-matrix-with-fees-v2"
ACTIVATION_ROOT = REPORT_ROOT / "ema-vwap-activation-z55-with-fees-v2"
STOP_LOSS_ROOT = REPORT_ROOT / "ema-vwap-bt2-point-stops-with-fees-v1"
CONFIRMATION_ROOT = REPORT_ROOT / "ema-vwap-bt2-confirmation-with-fees-v1"
MACD_ROOT = REPORT_ROOT / "ema-vwap-macd-with-fees-v1"
STOCH_ROOT = REPORT_ROOT / "ema-vwap-stoch-with-fees-v1"
UTC_SESSION_ROOT = REPORT_ROOT / "ema-vwap-utc00-16-with-fees-v1"
ALL_FAIL_EXIT_ROOT = REPORT_ROOT / "ema-vwap-all-fail-exits-utc00-16-with-fees-v1"
ALL_FAIL_MACD_EXIT_ROOT = (
    REPORT_ROOT / "ema-vwap-all-fail-macd-exit-utc00-16-with-fees-v1"
)
MACD_EXIT_POLICIES_ROOT = (
    REPORT_ROOT / "ema-vwap-macd-exit-policies-utc00-16-with-fees-v1"
)
LOCKED_H6_ROOT = REPORT_ROOT / "ema-vwap-locked-h6-utc00-16-with-fees-v1"
LOCKED_H6_FA125_ROOT = REPORT_ROOT / "ema-vwap-locked-h6-fa125-utc00-16-with-fees-v1"
LOCKED_H6_FA150_ROOT = REPORT_ROOT / "ema-vwap-locked-h6-fa150-utc00-16-with-fees-v1"
LOCKED_H6_FA200_ROOT = REPORT_ROOT / "ema-vwap-locked-h6-fa200-utc00-16-with-fees-v1"
LOCKED_H6_FA150_M30_ROOT = (
    REPORT_ROOT / "ema-vwap-locked-h6-fa150-m30-utc00-16-with-fees-v1"
)
LOCKED_H6_FA150_M30_STOCH_ROOT = (
    REPORT_ROOT / "ema-vwap-locked-h6-fa150-m30-stoch-utc00-16-with-fees-v1"
)
LOCKED_M30_ROOT = REPORT_ROOT / "ema-vwap-locked-m30-utc00-16-with-fees-v1"
LOCKED_H6_FA150_UTC08_ROOT = (
    REPORT_ROOT / "ema-vwap-locked-h6-fa150-utc08-16-with-fees-v1"
)
ALL_FAIL_Z50_ROOT = REPORT_ROOT / "ema-vwap-all-fail-z50a50-utc00-16-with-fees-v1"
ALL_FAIL_ATR_ROOT = REPORT_ROOT / "ema-vwap-all-fail-atr14x2-utc00-16-with-fees-v1"
ATR_SENSITIVITY_ROOT = REPORT_ROOT / "ema-vwap-all-fail-atr14x25-x3-utc00-16-with-fees-v1"
OUTPUT = REPORT_ROOT / "ema-vwap-full-backtest-results.md"
ARCHIVE_OUTPUT = REPORT_ROOT / "ema-vwap-ignored-backtest-results.md"
OUTLIER_SIGNAL = "2026-08-19T14:35:00+00:00"
TRANSACTION_LOG = Path(r"C:\Users\rajku\Downloads\Delta-TransactionLog-AssetHistory.csv")


def money(value: float) -> str:
    return f"${value:+.2f}"


def number(value: float | None, decimals: int = 3) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value:.{decimals}f}"


def load_study(directory: Path) -> tuple[dict[str, Any], pd.DataFrame, dict[str, pd.DataFrame]]:
    report = json.loads((directory / "matrix_summary.json").read_text(encoding="utf-8"))
    summary = pd.read_csv(directory / "matrix_summary.csv")
    trades = {
        Path(dataset["data_directory"]).name: pd.read_csv(
            directory / Path(dataset["data_directory"]).name / "trades.csv"
        )
        for dataset in report["datasets"]
    }
    return report, summary, trades


def trade_stats(frame: pd.DataFrame) -> dict[str, float | int]:
    pnl = frame["pnl_usd"].astype(float)
    wins = pnl[pnl > 0.0]
    losses = pnl[pnl < 0.0]
    return {
        "trades": len(pnl),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": int((pnl == 0.0).sum()),
        "gross_profit": float(wins.sum()),
        "gross_loss": float(abs(losses.sum())),
        "average_win": float(wins.mean()) if len(wins) else 0.0,
        "average_loss": float(losses.mean()) if len(losses) else 0.0,
        "gross_trading_pnl": float(frame["gross_pnl_usd"].sum()),
        "fee_base": float(
            frame["entry_fee_base_usd"].sum() + frame["exit_fee_base_usd"].sum()
        ),
        "fee_gst": float(
            frame["entry_fee_gst_usd"].sum() + frame["exit_fee_gst_usd"].sum()
        ),
        "fees": float(frame["fees_usd"].sum()),
        "net_pnl": float(pnl.sum()),
    }


def transaction_log_stats(path: Path) -> dict[str, float | int]:
    frame = pd.read_csv(path)
    fees = frame.loc[frame["Transaction type"].eq("trading fees")].copy()
    fees["Amount with GST"] = pd.to_numeric(fees["Amount with GST"], errors="coerce")
    fees["GST"] = pd.to_numeric(fees["GST"], errors="coerce")
    fees["base_fee"] = fees["Amount with GST"] - fees["GST"]
    ratios = fees["GST"].abs().div(fees["base_fee"].abs())
    return {
        "rows": len(frame),
        "fee_rows": len(fees),
        "base_fee": float(abs(fees["base_fee"].sum())),
        "gst": float(abs(fees["GST"].sum())),
        "total_fee": float(abs(fees["Amount with GST"].sum())),
        "gst_min": float(ratios.min()),
        "gst_max": float(ratios.max()),
    }


def rejection_text(rejects: dict[str, int]) -> str:
    if not rejects:
        return "None"
    return ", ".join(f"{key}: {value}" for key, value in sorted(rejects.items()))


def exit_counts(frame: pd.DataFrame) -> str:
    counts = Counter(frame["exit_reason"])
    labels = (
        ("CONDITION_EXIT", "Condition"),
        ("MACD_REVERSAL_EXIT", "MACD reversal"),
        ("MACD_CONFIRMED_REVERSAL_EXIT", "Confirmed MACD reversal"),
        ("ATR_TRAILING_STOP", "ATR trail"),
        ("HARD_STOP", "Hard stop"),
        ("MAX_HOLD", "Max hold"),
        ("PROTECTED_STOP", "Protected"),
    )
    populated = [
        f"{label}: {counts[reason]}"
        for reason, label in labels
        if counts.get(reason, 0) > 0
    ]
    return ", ".join(populated) if populated else "None"


def detailed_table(
    report: dict[str, Any],
    summary: pd.DataFrame,
    trades: dict[str, pd.DataFrame],
    dataset: str,
    scenario_filter: set[str] | None = None,
) -> list[str]:
    result_by_name = {
        item["scenario"]["name"]: item
        for item in next(
            item for item in report["datasets"]
            if Path(item["data_directory"]).name == dataset
        )["results"]
    }
    lines = [
        "| Scenario | Trades | W | L | BE | Win rate | P&L before fees | Base fee | GST | Total fees | Net winning P&L | Net losing P&L | Net P&L | Return | PF | Expectancy | Avg net win | Avg net loss | Max DD | Exits | Entry/data rejects |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    selected_summary = summary.loc[summary["dataset"] == dataset]
    if scenario_filter is not None:
        selected_summary = selected_summary.loc[
            selected_summary["scenario"].isin(scenario_filter)
        ]
    for _, row in selected_summary.iterrows():
        scenario = str(row["scenario"])
        selected = trades[dataset].loc[trades[dataset]["scenario"] == scenario]
        stats = trade_stats(selected)
        rejects = result_by_name[scenario]["rejects"]
        lines.append(
            "| "
            + " | ".join([
                scenario,
                str(stats["trades"]),
                str(stats["wins"]),
                str(stats["losses"]),
                str(stats["breakeven"]),
                f"{row['win_rate_percent']:.2f}%",
                money(float(stats["gross_trading_pnl"])),
                money(-float(stats["fee_base"])),
                money(-float(stats["fee_gst"])),
                money(-float(stats["fees"])),
                money(float(stats["gross_profit"])),
                money(-float(stats["gross_loss"])),
                money(float(row["net_pnl_usd"])),
                f"{row['return_percent']:+.2f}%",
                number(float(row["profit_factor"])),
                money(float(row["expectancy_usd"])),
                money(float(stats["average_win"])),
                money(float(stats["average_loss"])),
                f"${row['max_drawdown_usd']:.2f}",
                exit_counts(selected),
                rejection_text(rejects),
            ])
            + " |"
        )
    return lines


def sequential_drawdown(frame: pd.DataFrame, starting_balance: float = 100.0) -> float:
    ordered = frame.sort_values("entry_time")
    equity = starting_balance
    peak = starting_balance
    drawdown = 0.0
    for pnl in ordered["pnl_usd"].astype(float):
        equity += pnl
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def first_depletion(frame: pd.DataFrame, starting_balance: float = 100.0) -> tuple[int, str] | None:
    ordered = frame.sort_values("entry_time").reset_index(drop=True)
    equity = starting_balance + ordered["pnl_usd"].astype(float).cumsum()
    depleted = equity.loc[equity <= 0.0]
    if depleted.empty:
        return None
    index = int(depleted.index[0])
    return index + 1, str(ordered.loc[index, "entry_time"])


def combined_table(
    summary: pd.DataFrame,
    trades: dict[str, pd.DataFrame],
    scenario_filter: set[str] | None = None,
) -> list[str]:
    combined = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in trades.items()],
        ignore_index=True,
    )
    lines = [
        "| Scenario | Trades | W | L | BE | Win rate | P&L before fees | Base fee | GST | Total fees | Net winning P&L | Net losing P&L | Net P&L | Fixed-size return | PF | Expectancy | Sequential max DD | Development net | Holdout net |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    scenario_names = summary["scenario"].drop_duplicates()
    if scenario_filter is not None:
        scenario_names = scenario_names.loc[scenario_names.isin(scenario_filter)]
    for scenario in scenario_names:
        selected = combined.loc[combined["scenario"] == scenario]
        stats = trade_stats(selected)
        net = float(selected["pnl_usd"].sum())
        profit_factor = (
            float(stats["gross_profit"]) / float(stats["gross_loss"])
            if float(stats["gross_loss"]) > 0.0 else None
        )
        period = summary.loc[summary["scenario"] == scenario].set_index("dataset")
        development = float(period.loc["delta-2026-09-15_22", "net_pnl_usd"])
        holdout = float(period.loc["delta-holdout-2026-07-25_08-24", "net_pnl_usd"])
        lines.append(
            "| "
            + " | ".join([
                str(scenario),
                str(stats["trades"]),
                str(stats["wins"]),
                str(stats["losses"]),
                str(stats["breakeven"]),
                f"{100.0 * int(stats['wins']) / int(stats['trades']):.2f}%",
                money(float(stats["gross_trading_pnl"])),
                money(-float(stats["fee_base"])),
                money(-float(stats["fee_gst"])),
                money(-float(stats["fees"])),
                money(float(stats["gross_profit"])),
                money(-float(stats["gross_loss"])),
                money(net),
                f"{net:+.2f}%",
                number(profit_factor),
                money(net / int(stats["trades"])),
                f"${sequential_drawdown(selected):.2f}",
                money(development),
                money(holdout),
            ])
            + " |"
        )
    return lines


def macd_comparison(
    matrix_summary: pd.DataFrame,
    matrix_trades: dict[str, pd.DataFrame],
    macd_summary: pd.DataFrame,
    macd_trades: dict[str, pd.DataFrame],
) -> list[str]:
    baseline_names = ("BT1_EMA", "BT2_EMA_VWAP", "BT3_EMA_VWAP_RSI")
    macd_names = (
        "BT1_EMA_MACD",
        "BT2_EMA_VWAP_MACD",
        "BT3_EMA_VWAP_RSI_MACD",
    )
    sources = (
        ("BT1", baseline_names[0], macd_names[0]),
        ("BT2", baseline_names[1], macd_names[1]),
        ("BT3", baseline_names[2], macd_names[2]),
    )
    baseline = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in matrix_trades.items()],
        ignore_index=True,
    )
    confirmed = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in macd_trades.items()],
        ignore_index=True,
    )
    lines = [
        "| Family | Variant | Trades | Win rate | Development net | Holdout net | Combined net | Without exceptional event | PF | Max DD | Change vs baseline |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for family, baseline_name, macd_name in sources:
        baseline_net = float(
            baseline.loc[baseline["scenario"].eq(baseline_name), "pnl_usd"].sum()
        )
        for label, name, frame, summary in (
            ("Original", baseline_name, baseline, matrix_summary),
            ("MACD 12/26/9", macd_name, confirmed, macd_summary),
        ):
            selected = frame.loc[frame["scenario"].eq(name)]
            stats = trade_stats(selected)
            period = summary.loc[summary["scenario"].eq(name)].set_index("dataset")
            development = float(period.loc["delta-2026-09-15_22", "net_pnl_usd"])
            holdout = float(
                period.loc["delta-holdout-2026-07-25_08-24", "net_pnl_usd"]
            )
            net = float(stats["net_pnl"])
            without_event = selected.loc[
                ~(
                    selected["dataset"].eq("delta-holdout-2026-07-25_08-24")
                    & selected["signal_time"].eq(OUTLIER_SIGNAL)
                ),
                "pnl_usd",
            ].sum()
            profit_factor = (
                float(stats["gross_profit"]) / float(stats["gross_loss"])
                if float(stats["gross_loss"]) > 0.0 else None
            )
            change = net - baseline_net
            lines.append(
                "| "
                + " | ".join([
                    family,
                    label,
                    str(stats["trades"]),
                    f"{100.0 * int(stats['wins']) / int(stats['trades']):.2f}%",
                    money(development),
                    money(holdout),
                    money(net),
                    money(float(without_event)),
                    number(profit_factor),
                    f"${sequential_drawdown(selected):.2f}",
                    money(change),
                ])
                + " |"
            )
    return lines


def stoch_comparison(
    matrix_trades: dict[str, pd.DataFrame],
    stoch_trades: dict[str, pd.DataFrame],
) -> list[str]:
    baseline = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in matrix_trades.items()],
        ignore_index=True,
    )
    filtered = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in stoch_trades.items()],
        ignore_index=True,
    )
    mappings = (
        ("BT1", "BT1_EMA", "BT1_EMA_STOCH"),
        ("BT2", "BT2_EMA_VWAP", "BT2_EMA_VWAP_STOCH"),
        ("BT3", "BT3_EMA_VWAP_RSI", "BT3_EMA_VWAP_RSI_STOCH"),
    )
    lines = [
        "| Family | Variant | Trades | Win rate | Development | Holdout | Combined | Without exceptional event | PF | Robust change vs plain |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for family, baseline_name, stoch_name in mappings:
        base = baseline.loc[baseline["scenario"].eq(baseline_name)]
        base_robust = base.loc[
            ~(
                base["dataset"].eq("delta-holdout-2026-07-25_08-24")
                & base["signal_time"].eq(OUTLIER_SIGNAL)
            )
        ]
        base_robust_net = float(base_robust["pnl_usd"].sum())
        for label, scenario, source in (
            ("Plain", baseline_name, baseline),
            ("Stoch RSI", stoch_name, filtered),
        ):
            selected = source.loc[source["scenario"].eq(scenario)]
            stats = trade_stats(selected)
            development = float(
                selected.loc[
                    selected["dataset"].eq("delta-2026-09-15_22"),
                    "pnl_usd",
                ].sum()
            )
            holdout = float(
                selected.loc[
                    selected["dataset"].eq("delta-holdout-2026-07-25_08-24"),
                    "pnl_usd",
                ].sum()
            )
            robust = selected.loc[
                ~(
                    selected["dataset"].eq("delta-holdout-2026-07-25_08-24")
                    & selected["signal_time"].eq(OUTLIER_SIGNAL)
                )
            ]
            robust_net = float(robust["pnl_usd"].sum())
            profit_factor = (
                float(stats["gross_profit"]) / float(stats["gross_loss"])
                if float(stats["gross_loss"]) > 0.0 else None
            )
            lines.append(
                "| "
                + " | ".join([
                    family,
                    label,
                    str(stats["trades"]),
                    f"{100.0 * int(stats['wins']) / int(stats['trades']):.2f}%",
                    money(development),
                    money(holdout),
                    money(float(stats["net_pnl"])),
                    money(robust_net),
                    number(profit_factor),
                    money(robust_net - base_robust_net),
                ])
                + " |"
            )
    return lines


def utc_session_comparison(
    matrix_trades: dict[str, pd.DataFrame],
    macd_trades: dict[str, pd.DataFrame],
    session_summary: pd.DataFrame,
    session_trades: dict[str, pd.DataFrame],
) -> list[str]:
    original = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in matrix_trades.items()],
        ignore_index=True,
    )
    macd = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in macd_trades.items()],
        ignore_index=True,
    )
    filtered = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in session_trades.items()],
        ignore_index=True,
    )
    mappings = (
        ("BT1", "BT1_EMA", "BT1_EMA_UTC00_16", original),
        ("BT2", "BT2_EMA_VWAP", "BT2_EMA_VWAP_UTC00_16", original),
        ("BT3", "BT3_EMA_VWAP_RSI", "BT3_EMA_VWAP_RSI_UTC00_16", original),
        ("BT1 + MACD", "BT1_EMA_MACD", "BT1_EMA_MACD_UTC00_16", macd),
        ("BT2 + MACD", "BT2_EMA_VWAP_MACD", "BT2_EMA_VWAP_MACD_UTC00_16", macd),
        ("BT3 + MACD", "BT3_EMA_VWAP_RSI_MACD", "BT3_EMA_VWAP_RSI_MACD_UTC00_16", macd),
    )
    lines = [
        "| Variant | Trades | Win rate | Development net | Holdout net | Combined net | Without exceptional event | PF | Max DD | Change vs unrestricted |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, base_name, filtered_name, base_frame in mappings:
        base_net = float(
            base_frame.loc[base_frame["scenario"].eq(base_name), "pnl_usd"].sum()
        )
        selected = filtered.loc[filtered["scenario"].eq(filtered_name)]
        stats = trade_stats(selected)
        period = session_summary.loc[
            session_summary["scenario"].eq(filtered_name)
        ].set_index("dataset")
        development = float(period.loc["delta-2026-09-15_22", "net_pnl_usd"])
        holdout = float(
            period.loc["delta-holdout-2026-07-25_08-24", "net_pnl_usd"]
        )
        net = float(stats["net_pnl"])
        without_event = selected.loc[
            ~(
                selected["dataset"].eq("delta-holdout-2026-07-25_08-24")
                & selected["signal_time"].eq(OUTLIER_SIGNAL)
            ),
            "pnl_usd",
        ].sum()
        profit_factor = (
            float(stats["gross_profit"]) / float(stats["gross_loss"])
            if float(stats["gross_loss"]) > 0.0 else None
        )
        lines.append(
            "| "
            + " | ".join([
                label,
                str(stats["trades"]),
                f"{100.0 * int(stats['wins']) / int(stats['trades']):.2f}%",
                money(development),
                money(holdout),
                money(net),
                money(float(without_event)),
                number(profit_factor),
                f"${sequential_drawdown(selected):.2f}",
                money(net - base_net),
            ])
            + " |"
        )
    return lines


def all_fail_exit_comparison(
    session_trades: dict[str, pd.DataFrame],
    all_fail_summary: pd.DataFrame,
    all_fail_trades: dict[str, pd.DataFrame],
) -> list[str]:
    current = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in session_trades.items()],
        ignore_index=True,
    )
    revised = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in all_fail_trades.items()],
        ignore_index=True,
    )
    mappings = (
        ("BT1", "BT1_EMA_UTC00_16", "BT1_EMA_ALLFAIL_UTC00_16"),
        ("BT2", "BT2_EMA_VWAP_UTC00_16", "BT2_EMA_VWAP_ALLFAIL_UTC00_16"),
        ("BT3", "BT3_EMA_VWAP_RSI_UTC00_16", "BT3_EMA_VWAP_RSI_ALLFAIL_UTC00_16"),
        (
            "BT1 + MACD",
            "BT1_EMA_MACD_UTC00_16",
            "BT1_EMA_MACD_ALLFAIL_UTC00_16",
        ),
        (
            "BT2 + MACD",
            "BT2_EMA_VWAP_MACD_UTC00_16",
            "BT2_EMA_VWAP_MACD_ALLFAIL_UTC00_16",
        ),
        (
            "BT3 + MACD",
            "BT3_EMA_VWAP_RSI_MACD_UTC00_16",
            "BT3_EMA_VWAP_RSI_MACD_ALLFAIL_UTC00_16",
        ),
    )
    lines = [
        "| Variant | Previous trades | Revised trades | Trade change | Previous net | Revised net | Net change | Development net | Holdout net | Without exceptional event | Win rate | PF | Max DD |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, current_name, revised_name in mappings:
        current_selected = current.loc[current["scenario"].eq(current_name)]
        current_net = float(current_selected["pnl_usd"].sum())
        selected = revised.loc[revised["scenario"].eq(revised_name)]
        stats = trade_stats(selected)
        period = all_fail_summary.loc[
            all_fail_summary["scenario"].eq(revised_name)
        ].set_index("dataset")
        development = float(period.loc["delta-2026-09-15_22", "net_pnl_usd"])
        holdout = float(
            period.loc["delta-holdout-2026-07-25_08-24", "net_pnl_usd"]
        )
        net = float(stats["net_pnl"])
        without_event = selected.loc[
            ~(
                selected["dataset"].eq("delta-holdout-2026-07-25_08-24")
                & selected["signal_time"].eq(OUTLIER_SIGNAL)
            ),
            "pnl_usd",
        ].sum()
        profit_factor = (
            float(stats["gross_profit"]) / float(stats["gross_loss"])
            if float(stats["gross_loss"]) > 0.0 else None
        )
        lines.append(
                "| "
                + " | ".join([
                    label,
                    str(len(current_selected)),
                    str(stats["trades"]),
                    f"{int(stats['trades']) - len(current_selected):+d}",
                    money(current_net),
                    money(net),
                    money(net - current_net),
                    money(development),
                    money(holdout),
                    money(float(without_event)),
                    f"{100.0 * int(stats['wins']) / int(stats['trades']):.2f}%",
                    number(profit_factor),
                    f"${sequential_drawdown(selected):.2f}",
                ])
                + " |"
            )
    return lines


def all_fail_z50_comparison(
    all_fail_trades: dict[str, pd.DataFrame],
    z50_summary: pd.DataFrame,
    z50_trades: dict[str, pd.DataFrame],
) -> list[str]:
    baseline = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in all_fail_trades.items()],
        ignore_index=True,
    )
    protected = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in z50_trades.items()],
        ignore_index=True,
    )
    mappings = (
        (
            "BT1",
            "BT1_EMA_ALLFAIL_UTC00_16",
            "BT1_EMA_ALLFAIL_Z50A50_UTC00_16",
        ),
        (
            "BT2",
            "BT2_EMA_VWAP_ALLFAIL_UTC00_16",
            "BT2_EMA_VWAP_ALLFAIL_Z50A50_UTC00_16",
        ),
        (
            "BT3",
            "BT3_EMA_VWAP_RSI_ALLFAIL_UTC00_16",
            "BT3_EMA_VWAP_RSI_ALLFAIL_Z50A50_UTC00_16",
        ),
        (
            "BT1 + MACD",
            "BT1_EMA_MACD_ALLFAIL_UTC00_16",
            "BT1_EMA_MACD_ALLFAIL_Z50A50_UTC00_16",
        ),
        (
            "BT2 + MACD",
            "BT2_EMA_VWAP_MACD_ALLFAIL_UTC00_16",
            "BT2_EMA_VWAP_MACD_ALLFAIL_Z50A50_UTC00_16",
        ),
        (
            "BT3 + MACD",
            "BT3_EMA_VWAP_RSI_MACD_ALLFAIL_UTC00_16",
            "BT3_EMA_VWAP_RSI_MACD_ALLFAIL_Z50A50_UTC00_16",
        ),
    )
    lines = [
        "| Variant | All-Fail trades | Z50 trades | Protected exits | All-Fail net | Z50 net | Net change | Z50 development | Z50 holdout | Z50 without exceptional event | PF | Max DD |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, baseline_name, protected_name in mappings:
        baseline_selected = baseline.loc[baseline["scenario"].eq(baseline_name)]
        baseline_net = float(baseline_selected["pnl_usd"].sum())
        selected = protected.loc[protected["scenario"].eq(protected_name)]
        stats = trade_stats(selected)
        period = z50_summary.loc[z50_summary["scenario"].eq(protected_name)].set_index(
            "dataset"
        )
        development = float(period.loc["delta-2026-09-15_22", "net_pnl_usd"])
        holdout = float(
            period.loc["delta-holdout-2026-07-25_08-24", "net_pnl_usd"]
        )
        net = float(stats["net_pnl"])
        without_event = selected.loc[
            ~(
                selected["dataset"].eq("delta-holdout-2026-07-25_08-24")
                & selected["signal_time"].eq(OUTLIER_SIGNAL)
            ),
            "pnl_usd",
        ].sum()
        profit_factor = (
            float(stats["gross_profit"]) / float(stats["gross_loss"])
            if float(stats["gross_loss"]) > 0.0 else None
        )
        lines.append(
            "| "
            + " | ".join([
                label,
                str(len(baseline_selected)),
                str(stats["trades"]),
                str(int(selected["exit_reason"].eq("PROTECTED_STOP").sum())),
                money(baseline_net),
                money(net),
                money(net - baseline_net),
                money(development),
                money(holdout),
                money(float(without_event)),
                number(profit_factor),
                f"${sequential_drawdown(selected):.2f}",
            ])
            + " |"
        )
    return lines


def all_fail_macd_exit_comparison(
    all_fail_trades: dict[str, pd.DataFrame],
    macd_exit_summary: pd.DataFrame,
    macd_exit_trades: dict[str, pd.DataFrame],
) -> list[str]:
    baseline = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in all_fail_trades.items()],
        ignore_index=True,
    )
    revised = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in macd_exit_trades.items()],
        ignore_index=True,
    )
    mappings = (
        (
            "BT1",
            "BT1_EMA_ALLFAIL_UTC00_16",
            "BT1_EMA_ALLFAIL_MACDEXIT_UTC00_16",
        ),
        (
            "BT2",
            "BT2_EMA_VWAP_ALLFAIL_UTC00_16",
            "BT2_EMA_VWAP_ALLFAIL_MACDEXIT_UTC00_16",
        ),
        (
            "BT3",
            "BT3_EMA_VWAP_RSI_ALLFAIL_UTC00_16",
            "BT3_EMA_VWAP_RSI_ALLFAIL_MACDEXIT_UTC00_16",
        ),
        (
            "BT1 + MACD entry",
            "BT1_EMA_MACD_ALLFAIL_UTC00_16",
            "BT1_EMA_MACD_ALLFAIL_MACDEXIT_UTC00_16",
        ),
        (
            "BT2 + MACD entry",
            "BT2_EMA_VWAP_MACD_ALLFAIL_UTC00_16",
            "BT2_EMA_VWAP_MACD_ALLFAIL_MACDEXIT_UTC00_16",
        ),
        (
            "BT3 + MACD entry",
            "BT3_EMA_VWAP_RSI_MACD_ALLFAIL_UTC00_16",
            "BT3_EMA_VWAP_RSI_MACD_ALLFAIL_MACDEXIT_UTC00_16",
        ),
    )
    lines = [
        "| Variant | All-Fail trades | MACD-exit trades | MACD exits | All-Fail net | MACD-exit net | Net change | Development | Holdout | Without exceptional event | PF | Max DD |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, baseline_name, revised_name in mappings:
        baseline_selected = baseline.loc[baseline["scenario"].eq(baseline_name)]
        baseline_net = float(baseline_selected["pnl_usd"].sum())
        selected = revised.loc[revised["scenario"].eq(revised_name)]
        stats = trade_stats(selected)
        period = macd_exit_summary.loc[
            macd_exit_summary["scenario"].eq(revised_name)
        ].set_index("dataset")
        development = float(period.loc["delta-2026-09-15_22", "net_pnl_usd"])
        holdout = float(
            period.loc["delta-holdout-2026-07-25_08-24", "net_pnl_usd"]
        )
        net = float(stats["net_pnl"])
        without_event = selected.loc[
            ~(
                selected["dataset"].eq("delta-holdout-2026-07-25_08-24")
                & selected["signal_time"].eq(OUTLIER_SIGNAL)
            ),
            "pnl_usd",
        ].sum()
        profit_factor = (
            float(stats["gross_profit"]) / float(stats["gross_loss"])
            if float(stats["gross_loss"]) > 0.0
            else None
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    label,
                    str(len(baseline_selected)),
                    str(stats["trades"]),
                    str(int(selected["exit_reason"].eq("MACD_REVERSAL_EXIT").sum())),
                    money(baseline_net),
                    money(net),
                    money(net - baseline_net),
                    money(development),
                    money(holdout),
                    money(float(without_event)),
                    number(profit_factor),
                    f"${sequential_drawdown(selected):.2f}",
                ]
            )
            + " |"
        )
    return lines


def macd_exit_policy_table(
    policy_trades: dict[str, pd.DataFrame],
    policy_filter: set[str] | None = None,
) -> list[str]:
    combined = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in policy_trades.items()],
        ignore_index=True,
    )
    mappings = (
        ("Original", "MACD reversal only", "BT1-BT3", "BT1_EMA_MACDREV_ONLY_UTC00_16"),
        ("Original", "MACD included in All-Fail", "BT1", "BT1_EMA_ALLFAIL_WITH_MACD_UTC00_16"),
        ("Original", "MACD included in All-Fail", "BT2/BT3", "BT2_EMA_VWAP_ALLFAIL_WITH_MACD_UTC00_16"),
        ("Original", "Confirmed MACD reversal", "BT1-BT3", "BT1_EMA_MACDREV_CONFIRM1_ONLY_UTC00_16"),
        ("MACD-filtered", "MACD reversal only", "BT1-BT3", "BT1_EMA_MACD_MACDREV_ONLY_UTC00_16"),
        ("MACD-filtered", "MACD included in All-Fail", "BT1", "BT1_EMA_MACD_ALLFAIL_WITH_MACD_UTC00_16"),
        ("MACD-filtered", "MACD included in All-Fail", "BT2/BT3", "BT2_EMA_VWAP_MACD_ALLFAIL_WITH_MACD_UTC00_16"),
        ("MACD-filtered", "Confirmed MACD reversal", "BT1-BT3", "BT1_EMA_MACD_MACDREV_CONFIRM1_ONLY_UTC00_16"),
    )
    lines = [
        "| Entry | Exit policy | Family | Trades | Win rate | Development | Holdout | Combined | Without exceptional event | PF | Max DD | Exits |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for entry, policy, family, scenario in mappings:
        if policy_filter is not None and policy not in policy_filter:
            continue
        selected = combined.loc[combined["scenario"].eq(scenario)]
        stats = trade_stats(selected)
        pnl = selected["pnl_usd"].astype(float)
        development = float(
            selected.loc[
                selected["dataset"].eq("delta-2026-09-15_22"), "pnl_usd"
            ].sum()
        )
        holdout = float(
            selected.loc[
                selected["dataset"].eq("delta-holdout-2026-07-25_08-24"),
                "pnl_usd",
            ].sum()
        )
        without_event = float(
            selected.loc[
                ~(
                    selected["dataset"].eq("delta-holdout-2026-07-25_08-24")
                    & selected["signal_time"].eq(OUTLIER_SIGNAL)
                ),
                "pnl_usd",
            ].sum()
        )
        profit_factor = (
            float(stats["gross_profit"]) / float(stats["gross_loss"])
            if float(stats["gross_loss"]) > 0.0
            else None
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    entry,
                    policy,
                    family,
                    str(stats["trades"]),
                    f"{100.0 * int(stats['wins']) / int(stats['trades']):.2f}%",
                    money(development),
                    money(holdout),
                    money(float(pnl.sum())),
                    money(without_event),
                    number(profit_factor),
                    f"${sequential_drawdown(selected):.2f}",
                    exit_counts(selected),
                ]
            )
            + " |"
        )
    return lines


def locked_filter_sequence_table(
    macd_or_trades: dict[str, pd.DataFrame],
    reversal_only_trades: dict[str, pd.DataFrame],
    m30_only_trades: dict[str, pd.DataFrame],
    h6_trades: dict[str, pd.DataFrame],
    fa125_trades: dict[str, pd.DataFrame],
    fa150_trades: dict[str, pd.DataFrame],
    fa200_trades: dict[str, pd.DataFrame],
    m30_trades: dict[str, pd.DataFrame],
    m30_stoch_trades: dict[str, pd.DataFrame],
) -> list[str]:
    def combined(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
        return pd.concat(
            [frame.assign(dataset=dataset) for dataset, frame in frames.items()],
            ignore_index=True,
        )

    sources = {
        "or": combined(macd_or_trades),
        "only": combined(reversal_only_trades),
        "m30_only": combined(m30_only_trades),
        "h6": combined(h6_trades),
        "fa125": combined(fa125_trades),
        "fa150": combined(fa150_trades),
        "fa200": combined(fa200_trades),
        "m30": combined(m30_trades),
        "m30_stoch": combined(m30_stoch_trades),
    }
    rows = (
        ("Baseline", "OR All-Fail", "BT1", "or", "BT1_EMA_MACD_ALLFAIL_MACDEXIT_UTC00_16"),
        ("Baseline", "OR All-Fail", "BT2/BT3", "or", "BT2_EMA_VWAP_MACD_ALLFAIL_MACDEXIT_UTC00_16"),
        ("Baseline", "Reversal only", "BT1-BT3", "only", "BT1_EMA_MACD_MACDREV_ONLY_UTC00_16"),
        ("M30 only", "OR All-Fail", "BT1", "m30_only", "BT1_EMA_MACD_ALLFAIL_MACDEXIT_M30_UTC00_16"),
        ("M30 only", "OR All-Fail", "BT2/BT3", "m30_only", "BT2_EMA_VWAP_MACD_ALLFAIL_MACDEXIT_M30_UTC00_16"),
        ("M30 only", "Reversal only", "BT1-BT3", "m30_only", "BT1_EMA_MACD_MACDREV_ONLY_M30_UTC00_16"),
        ("H6", "OR All-Fail", "BT1", "h6", "BT1_EMA_MACD_ALLFAIL_MACDEXIT_H6_UTC00_16"),
        ("H6", "OR All-Fail", "BT2/BT3", "h6", "BT2_EMA_VWAP_MACD_ALLFAIL_MACDEXIT_H6_UTC00_16"),
        ("H6", "Reversal only", "BT1-BT3", "h6", "BT1_EMA_MACD_MACDREV_ONLY_H6_UTC00_16"),
        ("H6 + FA125", "OR All-Fail", "BT1", "fa125", "BT1_EMA_MACD_ALLFAIL_MACDEXIT_H6_FA125_UTC00_16"),
        ("H6 + FA125", "OR All-Fail", "BT2/BT3", "fa125", "BT2_EMA_VWAP_MACD_ALLFAIL_MACDEXIT_H6_FA125_UTC00_16"),
        ("H6 + FA125", "Reversal only", "BT1-BT3", "fa125", "BT1_EMA_MACD_MACDREV_ONLY_H6_FA125_UTC00_16"),
        ("H6 + FA150", "OR All-Fail", "BT1", "fa150", "BT1_EMA_MACD_ALLFAIL_MACDEXIT_H6_FA150_UTC00_16"),
        ("H6 + FA150", "OR All-Fail", "BT2/BT3", "fa150", "BT2_EMA_VWAP_MACD_ALLFAIL_MACDEXIT_H6_FA150_UTC00_16"),
        ("H6 + FA150", "Reversal only", "BT1-BT3", "fa150", "BT1_EMA_MACD_MACDREV_ONLY_H6_FA150_UTC00_16"),
        ("H6 + FA200", "OR All-Fail", "BT1", "fa200", "BT1_EMA_MACD_ALLFAIL_MACDEXIT_H6_FA200_UTC00_16"),
        ("H6 + FA200", "OR All-Fail", "BT2/BT3", "fa200", "BT2_EMA_VWAP_MACD_ALLFAIL_MACDEXIT_H6_FA200_UTC00_16"),
        ("H6 + FA200", "Reversal only", "BT1-BT3", "fa200", "BT1_EMA_MACD_MACDREV_ONLY_H6_FA200_UTC00_16"),
        ("H6 + FA150 + M30", "OR All-Fail", "BT1", "m30", "BT1_EMA_MACD_ALLFAIL_MACDEXIT_H6_FA150_M30_UTC00_16"),
        ("H6 + FA150 + M30", "OR All-Fail", "BT2/BT3", "m30", "BT2_EMA_VWAP_MACD_ALLFAIL_MACDEXIT_H6_FA150_M30_UTC00_16"),
        ("H6 + FA150 + M30", "Reversal only", "BT1-BT3", "m30", "BT1_EMA_MACD_MACDREV_ONLY_H6_FA150_M30_UTC00_16"),
        ("H6 + FA150 + M30 + Stoch RSI", "Reversal only", "BT1", "m30_stoch", "BT1_EMA_MACD_MACDREV_ONLY_H6_FA150_M30_STOCH_UTC00_16"),
    )
    lines = [
        "| Filter stage | Exit | Family | Trades | Win rate | Development | Holdout | Combined | Without exceptional event | PF | Max DD |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for stage, exit_policy, family, source, scenario in rows:
        selected = sources[source].loc[sources[source]["scenario"].eq(scenario)]
        stats = trade_stats(selected)
        pnl = selected["pnl_usd"].astype(float)
        development = float(
            selected.loc[selected["dataset"].eq("delta-2026-09-15_22"), "pnl_usd"].sum()
        )
        holdout = float(
            selected.loc[
                selected["dataset"].eq("delta-holdout-2026-07-25_08-24"),
                "pnl_usd",
            ].sum()
        )
        without_event = float(
            selected.loc[
                ~(
                    selected["dataset"].eq("delta-holdout-2026-07-25_08-24")
                    & selected["signal_time"].eq(OUTLIER_SIGNAL)
                ),
                "pnl_usd",
            ].sum()
        )
        profit_factor = (
            float(stats["gross_profit"]) / float(stats["gross_loss"])
            if float(stats["gross_loss"]) > 0.0 else None
        )
        lines.append(
            "| "
            + " | ".join([
                stage,
                exit_policy,
                family,
                str(stats["trades"]),
                f"{100.0 * int(stats['wins']) / int(stats['trades']):.2f}%",
                money(development),
                money(holdout),
                money(float(pnl.sum())),
                money(without_event),
                number(profit_factor),
                f"${sequential_drawdown(selected):.2f}",
            ])
            + " |"
        )
    return lines


def loss_window_comparison(
    fa150_trades: dict[str, pd.DataFrame],
    utc08_trades: dict[str, pd.DataFrame],
) -> list[str]:
    baseline = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in fa150_trades.items()],
        ignore_index=True,
    )
    filtered = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in utc08_trades.items()],
        ignore_index=True,
    )
    rows = (
        (
            "H6 + FA150, 00:00-15:59",
            baseline,
            "BT1_EMA_MACD_MACDREV_ONLY_H6_FA150_UTC00_16",
        ),
        (
            "H6 + FA150, 08:00-15:59",
            filtered,
            "BT1_EMA_MACD_MACDREV_ONLY_H6_FA150_UTC08_16",
        ),
    )
    lines = [
        "| Candidate | Trades | W | L | Development | Holdout | Combined | Without exceptional event | Robust PF | Robust expectancy | Max DD |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, source, scenario in rows:
        selected = source.loc[source["scenario"].eq(scenario)]
        pnl = selected["pnl_usd"].astype(float)
        development = float(
            selected.loc[selected["dataset"].eq("delta-2026-09-15_22"), "pnl_usd"].sum()
        )
        holdout = float(
            selected.loc[
                selected["dataset"].eq("delta-holdout-2026-07-25_08-24"),
                "pnl_usd",
            ].sum()
        )
        robust = selected.loc[
            ~(
                selected["dataset"].eq("delta-holdout-2026-07-25_08-24")
                & selected["signal_time"].eq(OUTLIER_SIGNAL)
            )
        ]
        robust_pnl = robust["pnl_usd"].astype(float)
        gross_profit = float(robust_pnl[robust_pnl > 0.0].sum())
        gross_loss = float(-robust_pnl[robust_pnl < 0.0].sum())
        lines.append(
            "| "
            + " | ".join([
                label,
                str(len(selected)),
                str(int((pnl > 0.0).sum())),
                str(int((pnl < 0.0).sum())),
                money(development),
                money(holdout),
                money(float(pnl.sum())),
                money(float(robust_pnl.sum())),
                number(gross_profit / gross_loss if gross_loss > 0.0 else None),
                money(float(robust_pnl.mean())),
                f"${sequential_drawdown(selected):.2f}",
            ])
            + " |"
        )
    return lines


def robust_loss_breakdown(
    trades: dict[str, pd.DataFrame],
    scenario: str,
) -> list[str]:
    combined = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in trades.items()],
        ignore_index=True,
    )
    selected = combined.loc[combined["scenario"].eq(scenario)].copy()
    selected = selected.loc[
        ~(
            selected["dataset"].eq("delta-holdout-2026-07-25_08-24")
            & selected["signal_time"].eq(OUTLIER_SIGNAL)
        )
    ]
    lines = [
        "| Breakdown | Trades | W | L | Win rate | Net P&L | Average P&L |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for column in ("direction", "exit_reason"):
        for value, group in selected.groupby(column, sort=True):
            pnl = group["pnl_usd"].astype(float)
            lines.append(
                "| "
                + " | ".join([
                    f"{column}: {value}",
                    str(len(group)),
                    str(int((pnl > 0.0).sum())),
                    str(int((pnl < 0.0).sum())),
                    f"{100.0 * float((pnl > 0.0).mean()):.2f}%",
                    money(float(pnl.sum())),
                    money(float(pnl.mean())),
                ])
                + " |"
            )
    return lines


def all_fail_atr_comparison(
    all_fail_trades: dict[str, pd.DataFrame],
    atr_summary: pd.DataFrame,
    atr_trades: dict[str, pd.DataFrame],
) -> list[str]:
    baseline = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in all_fail_trades.items()],
        ignore_index=True,
    )
    trailed = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in atr_trades.items()],
        ignore_index=True,
    )
    mappings = (
        (
            "BT1",
            "BT1_EMA_ALLFAIL_UTC00_16",
            "BT1_EMA_ALLFAIL_ATR14X2_UTC00_16",
        ),
        (
            "BT2",
            "BT2_EMA_VWAP_ALLFAIL_UTC00_16",
            "BT2_EMA_VWAP_ALLFAIL_ATR14X2_UTC00_16",
        ),
        (
            "BT3",
            "BT3_EMA_VWAP_RSI_ALLFAIL_UTC00_16",
            "BT3_EMA_VWAP_RSI_ALLFAIL_ATR14X2_UTC00_16",
        ),
        (
            "BT1 + MACD",
            "BT1_EMA_MACD_ALLFAIL_UTC00_16",
            "BT1_EMA_MACD_ALLFAIL_ATR14X2_UTC00_16",
        ),
        (
            "BT2 + MACD",
            "BT2_EMA_VWAP_MACD_ALLFAIL_UTC00_16",
            "BT2_EMA_VWAP_MACD_ALLFAIL_ATR14X2_UTC00_16",
        ),
        (
            "BT3 + MACD",
            "BT3_EMA_VWAP_RSI_MACD_ALLFAIL_UTC00_16",
            "BT3_EMA_VWAP_RSI_MACD_ALLFAIL_ATR14X2_UTC00_16",
        ),
    )
    lines = [
        "| Variant | All-Fail trades | ATR trades | ATR exits | All-Fail net | ATR net | Net change | ATR development | ATR holdout | ATR without exceptional event | PF | Max DD |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, baseline_name, atr_name in mappings:
        baseline_selected = baseline.loc[baseline["scenario"].eq(baseline_name)]
        baseline_net = float(baseline_selected["pnl_usd"].sum())
        selected = trailed.loc[trailed["scenario"].eq(atr_name)]
        stats = trade_stats(selected)
        period = atr_summary.loc[atr_summary["scenario"].eq(atr_name)].set_index(
            "dataset"
        )
        development = float(period.loc["delta-2026-09-15_22", "net_pnl_usd"])
        holdout = float(
            period.loc["delta-holdout-2026-07-25_08-24", "net_pnl_usd"]
        )
        net = float(stats["net_pnl"])
        without_event = selected.loc[
            ~(
                selected["dataset"].eq("delta-holdout-2026-07-25_08-24")
                & selected["signal_time"].eq(OUTLIER_SIGNAL)
            ),
            "pnl_usd",
        ].sum()
        profit_factor = (
            float(stats["gross_profit"]) / float(stats["gross_loss"])
            if float(stats["gross_loss"]) > 0.0 else None
        )
        lines.append(
            "| "
            + " | ".join([
                label,
                str(len(baseline_selected)),
                str(stats["trades"]),
                str(int(selected["exit_reason"].eq("ATR_TRAILING_STOP").sum())),
                money(baseline_net),
                money(net),
                money(net - baseline_net),
                money(development),
                money(holdout),
                money(float(without_event)),
                number(profit_factor),
                f"${sequential_drawdown(selected):.2f}",
            ])
            + " |"
        )
    return lines


def atr_multiplier_comparison(
    atr2_summary: pd.DataFrame,
    atr2_trades: dict[str, pd.DataFrame],
    sensitivity_summary: pd.DataFrame,
    sensitivity_trades: dict[str, pd.DataFrame],
) -> list[str]:
    sources = {
        2.0: (
            "2",
            atr2_summary,
            pd.concat(
                [frame.assign(dataset=dataset) for dataset, frame in atr2_trades.items()],
                ignore_index=True,
            ),
        ),
        2.5: (
            "25",
            sensitivity_summary,
            pd.concat(
                [
                    frame.assign(dataset=dataset)
                    for dataset, frame in sensitivity_trades.items()
                ],
                ignore_index=True,
            ),
        ),
        3.0: (
            "3",
            sensitivity_summary,
            pd.concat(
                [
                    frame.assign(dataset=dataset)
                    for dataset, frame in sensitivity_trades.items()
                ],
                ignore_index=True,
            ),
        ),
    }
    families = (
        ("BT1", "BT1_EMA_ALLFAIL_ATR14X{tag}_UTC00_16"),
        ("BT2", "BT2_EMA_VWAP_ALLFAIL_ATR14X{tag}_UTC00_16"),
        ("BT3", "BT3_EMA_VWAP_RSI_ALLFAIL_ATR14X{tag}_UTC00_16"),
        ("BT1 + MACD", "BT1_EMA_MACD_ALLFAIL_ATR14X{tag}_UTC00_16"),
        ("BT2 + MACD", "BT2_EMA_VWAP_MACD_ALLFAIL_ATR14X{tag}_UTC00_16"),
        ("BT3 + MACD", "BT3_EMA_VWAP_RSI_MACD_ALLFAIL_ATR14X{tag}_UTC00_16"),
    )
    lines = [
        "| Variant | ATR multiplier | Trades | ATR exits | Development net | Holdout net | Combined net | Without exceptional event | PF | Max DD |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for family, pattern in families:
        for multiplier, (tag, summary, trades) in sources.items():
            name = pattern.format(tag=tag)
            selected = trades.loc[trades["scenario"].eq(name)]
            stats = trade_stats(selected)
            period = summary.loc[summary["scenario"].eq(name)].set_index("dataset")
            development = float(period.loc["delta-2026-09-15_22", "net_pnl_usd"])
            holdout = float(
                period.loc["delta-holdout-2026-07-25_08-24", "net_pnl_usd"]
            )
            without_event = selected.loc[
                ~(
                    selected["dataset"].eq("delta-holdout-2026-07-25_08-24")
                    & selected["signal_time"].eq(OUTLIER_SIGNAL)
                ),
                "pnl_usd",
            ].sum()
            profit_factor = (
                float(stats["gross_profit"]) / float(stats["gross_loss"])
                if float(stats["gross_loss"]) > 0.0 else None
            )
            lines.append(
                "| "
                + " | ".join([
                    family,
                    f"{multiplier:.1f}x",
                    str(stats["trades"]),
                    str(int(selected["exit_reason"].eq("ATR_TRAILING_STOP").sum())),
                    money(development),
                    money(holdout),
                    money(float(stats["net_pnl"])),
                    money(float(without_event)),
                    number(profit_factor),
                    f"${sequential_drawdown(selected):.2f}",
                ])
                + " |"
            )
    return lines


def activation_sensitivity(trades: dict[str, pd.DataFrame]) -> list[str]:
    combined = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in trades.items()],
        ignore_index=True,
    )
    outlier = (
        combined["dataset"].eq("delta-holdout-2026-07-25_08-24")
        & combined["signal_time"].eq(OUTLIER_SIGNAL)
    )
    lines = [
        "| Activation | Protection | P&L before fees | Total fees | Net P&L | Net excluding exceptional event | Largest net trade |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for scenario in combined["scenario"].drop_duplicates():
        selected = combined.loc[combined["scenario"] == scenario]
        selected_without = combined.loc[(combined["scenario"] == scenario) & ~outlier]
        activation = scenario.removeprefix("ACT").split("_", 1)[0]
        lines.append(
            f"| +{activation}% | 55% | {money(float(selected['gross_pnl_usd'].sum()))} | "
            f"{money(-float(selected['fees_usd'].sum()))} | "
            f"{money(float(selected['pnl_usd'].sum()))} | "
            f"{money(float(selected_without['pnl_usd'].sum()))} | "
            f"{money(float(selected['pnl_usd'].max()))} |"
        )
    return lines


def point_stop_comparison(
    matrix_trades: dict[str, pd.DataFrame],
    stop_trades: dict[str, pd.DataFrame],
) -> list[str]:
    baseline = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in matrix_trades.items()],
        ignore_index=True,
    )
    baseline = baseline.loc[baseline["scenario"].eq("BT2_EMA_VWAP")]
    stops = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in stop_trades.items()],
        ignore_index=True,
    )
    combined = pd.concat([baseline, stops], ignore_index=True)
    outlier = (
        combined["dataset"].eq("delta-holdout-2026-07-25_08-24")
        & combined["signal_time"].eq(OUTLIER_SIGNAL)
    )
    labels = {
        "BT2_EMA_VWAP": "Original -15% premium stop",
        "BT2_EMA_VWAP_SL100": "Entry premium - 100 points",
        "BT2_EMA_VWAP_SL150": "Entry premium - 150 points",
        "BT2_EMA_VWAP_SL200": "Entry premium - 200 points",
    }
    lines = [
        "| Variant | Trades | W | L | Win rate | P&L before fees | Total fees | Net P&L | PF | Expectancy | Sequential max DD | Hard-stop exits | Net excluding exceptional event |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for scenario in labels:
        selected = combined.loc[combined["scenario"].eq(scenario)]
        stats = trade_stats(selected)
        selected_without = combined.loc[combined["scenario"].eq(scenario) & ~outlier]
        hard_stops = int(selected["exit_reason"].eq("HARD_STOP").sum())
        lines.append(
            "| "
            + " | ".join([
                labels[scenario],
                str(stats["trades"]),
                str(stats["wins"]),
                str(stats["losses"]),
                f"{100.0 * int(stats['wins']) / int(stats['trades']):.2f}%",
                money(float(stats["gross_trading_pnl"])),
                money(-float(stats["fees"])),
                money(float(stats["net_pnl"])),
                number(float(stats["gross_profit"]) / float(stats["gross_loss"])),
                money(float(stats["net_pnl"]) / int(stats["trades"])),
                f"${sequential_drawdown(selected):.2f}",
                str(hard_stops),
                money(float(selected_without["pnl_usd"].sum())),
            ])
            + " |"
        )
    return lines


def confirmation_comparison(
    matrix_trades: dict[str, pd.DataFrame],
    confirmation_trades: dict[str, pd.DataFrame],
) -> list[str]:
    baseline = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in matrix_trades.items()],
        ignore_index=True,
    )
    baseline = baseline.loc[baseline["scenario"].eq("BT2_EMA_VWAP")]
    confirmations = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in confirmation_trades.items()],
        ignore_index=True,
    )
    combined = pd.concat([baseline, confirmations], ignore_index=True)
    outlier = (
        combined["dataset"].eq("delta-holdout-2026-07-25_08-24")
        & combined["signal_time"].eq(OUTLIER_SIGNAL)
    )
    labels = {
        "BT2_EMA_VWAP": "Immediate entry",
        "BT2_EMA_VWAP_CONFIRM_1": "Wait 1 candle",
        "BT2_EMA_VWAP_CONFIRM_2": "Wait 2 candles",
        "BT2_EMA_VWAP_CONFIRM_3": "Wait 3 candles",
        "BT2_EMA_VWAP_CONFIRM_4": "Wait 4 candles",
    }
    lines = [
        "| Entry timing | Trades | W | L | Win rate | P&L before fees | Total fees | Net P&L | PF | Expectancy | Sequential max DD | Net excluding exceptional event |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for scenario, label in labels.items():
        selected = combined.loc[combined["scenario"].eq(scenario)]
        stats = trade_stats(selected)
        selected_without = combined.loc[combined["scenario"].eq(scenario) & ~outlier]
        lines.append(
            "| "
            + " | ".join([
                label,
                str(stats["trades"]),
                str(stats["wins"]),
                str(stats["losses"]),
                f"{100.0 * int(stats['wins']) / int(stats['trades']):.2f}%",
                money(float(stats["gross_trading_pnl"])),
                money(-float(stats["fees"])),
                money(float(stats["net_pnl"])),
                number(float(stats["gross_profit"]) / float(stats["gross_loss"])),
                money(float(stats["net_pnl"]) / int(stats["trades"])),
                f"${sequential_drawdown(selected):.2f}",
                money(float(selected_without["pnl_usd"].sum())),
            ])
            + " |"
        )
    return lines


def _write_legacy_report() -> None:
    matrix_report, matrix_summary, matrix_trades = load_study(MATRIX_ROOT)
    activation_report, activation_summary, activation_trades = load_study(ACTIVATION_ROOT)
    confirmation_report, confirmation_summary, confirmation_trades = load_study(
        CONFIRMATION_ROOT
    )
    development = "delta-2026-09-15_22"
    holdout = "delta-holdout-2026-07-25_08-24"
    all_matrix_trades = pd.concat(
        [frame.assign(dataset=dataset) for dataset, frame in matrix_trades.items()],
        ignore_index=True,
    )
    candidate = all_matrix_trades.loc[
        all_matrix_trades["scenario"] == "BT7_EMA_VWAP_Z55"
    ]
    candidate_stats = trade_stats(candidate)
    apparent_best = all_matrix_trades.loc[
        all_matrix_trades["scenario"] == "BT2_EMA_VWAP"
    ]
    apparent_stats = trade_stats(apparent_best)
    outlier = (
        apparent_best["dataset"].eq(holdout)
        & apparent_best["signal_time"].eq(OUTLIER_SIGNAL)
    )
    apparent_without_outlier = float(apparent_best.loc[~outlier, "pnl_usd"].sum())
    ledger = transaction_log_stats(TRANSACTION_LOG)
    candidate_depletion = first_depletion(candidate)

    lines = [
        "# EMA/VWAP/RSI BTC Option Strategy Backtest Results With Delta Fees",
        "",
        "> Generated from the saved calculation-backtest reports. This document describes research results, not a claim of live profitability.",
        "",
        "## Executive Summary",
        "",
        "After applying Delta Exchange India's current options fees to every entry and exit, **the previously selected strategy is not profitable**. The earlier EMA+VWAP, +20% activation, Z55 candidate (`BT7_EMA_VWAP_Z55`) produced:",
        "",
        f"- Trades: **{candidate_stats['trades']}**",
        f"- Wins / losses / breakeven after fees: **{candidate_stats['wins']} / {candidate_stats['losses']} / {candidate_stats['breakeven']}**",
        f"- Net win rate: **{100.0 * int(candidate_stats['wins']) / int(candidate_stats['trades']):.2f}%**",
        f"- Trading P&L before fees: **{money(float(candidate_stats['gross_trading_pnl']))}**",
        f"- Base trading fees: **{money(-float(candidate_stats['fee_base']))}**",
        f"- GST on fees: **{money(-float(candidate_stats['fee_gst']))}**",
        f"- Total fees: **{money(-float(candidate_stats['fees']))}**",
        f"- Net P&L: **{money(float(candidate_stats['net_pnl']))}** on fixed $6.67 premium sizing",
        f"- Net profit factor: **{number(float(candidate_stats['gross_profit']) / float(candidate_stats['gross_loss']))}**",
        f"- Average net P&L per trade: **{money(float(candidate['pnl_usd'].mean()))}**",
        f"- Sequential maximum drawdown: **${sequential_drawdown(candidate):.2f}**",
        "- Development net P&L: **-$84.91**; holdout net P&L: **-$105.56**",
        "",
        "`BT2_EMA_VWAP` has the highest raw fee-adjusted total at +$74.82, but one exceptional estimated option move contributes roughly $276.31 net. Without that event it loses $201.49. Therefore no tested scenario has a robust positive result after fees.",
        "",
        f"With a strict $100 balance and fixed $6.67 sizing, the former Z55 candidate reaches zero cumulative equity on trade **{candidate_depletion[0]}** at **{candidate_depletion[1]}**. The tables continue fixed-size trades after that point so scenarios remain comparable, but those later trades would not be executable by an unfunded $100 account.",
        "",
        "## Active Research Scope",
        "",
        "Only the three unprotected condition-exit families remain active:",
        "",
        "| Active family | Exit rule | Development net | Holdout net | Combined net | Combined without exceptional event |",
        "|---|---|---:|---:|---:|---:|",
        "| BT1 | EMA ordering fails | -$105.93 | +$167.27 | +$61.34 | -$214.97 |",
        "| BT2 | EMA ordering or VWAP direction fails | -$101.02 | +$175.84 | +$74.82 | -$201.49 |",
        "| BT3 | EMA ordering, VWAP direction, or RSI band fails | -$147.05 | -$162.42 | -$309.48 | -$310.19 |",
        "",
        "BT4-BT10, fixed-point stops, and delayed one-to-four-candle confirmation are closed experiments. Their saved results remain available for audit, but they are not candidates and will not be optimized further.",
        "",
        "## Verified Delta Fee Model",
        "",
        "Delta Exchange India's current official schedule states that options maker and taker fees are 0.010% of notional value, capped at 3.5% of option premium. An additional 18% GST applies. Fees are charged on both opening and closing executions.",
        "Fee schedule verification date: **2026-10-01**.",
        "",
        "Per fill:",
        "",
        "```text",
        "notional_fee = BTC_spot * quantity * 0.001 * 0.010%",
        "premium_cap = option_premium * quantity * 0.001 * 3.5%",
        "base_fee = min(notional_fee, premium_cap)",
        "GST = base_fee * 18%",
        "total_fee = base_fee + GST",
        "```",
        "",
        "The backtest applies this formula independently to entry and exit. BTC spot is approximated using the latest completed five-minute BTC close at each simulated fill.",
        "",
        "Official sources:",
        "",
        "- [Delta Exchange India fee page](https://www.delta.exchange/fees)",
        "- [Delta Exchange India options fee calculation](https://www.delta.exchange/support/solutions?articleId=80001177864&categoryId=undefined&folderId=undefined)",
        "",
        "## Transaction Log Audit",
        "",
        "Your `Delta-TransactionLog-AssetHistory.csv` independently confirms the GST treatment:",
        "",
        f"- Total rows: **{ledger['rows']}**",
        f"- Trading-fee rows: **{ledger['fee_rows']}**",
        f"- Base trading fees: **${ledger['base_fee']:.8f}**",
        f"- GST: **${ledger['gst']:.8f}**",
        f"- Total fees including GST: **${ledger['total_fee']:.8f}**",
        f"- Observed GST/base-fee ratio: **{100.0 * float(ledger['gst_min']):.5f}% to {100.0 * float(ledger['gst_max']):.5f}%**",
        "",
        "The tiny range around 18% is only decimal rounding in individual ledger rows.",
        "",
        "## Test Configuration",
        "",
        "| Setting | Value |",
        "|---|---|",
        "| Development period | 2026-08-24 00:00 UTC to 2026-09-23 00:00 UTC |",
        "| Holdout period | 2026-07-25 00:00 UTC to 2026-08-24 00:00 UTC |",
        "| Starting capital | $100.00 |",
        "| Premium budget per trade | $6.67, fixed and not compounded |",
        "| Underlying bars | BTC, 5 minute |",
        "| Option quotes | Estimated one-minute bid/ask (`LOW_FIDELITY_SYNTHETIC_BBO`) |",
        "| Fill method | Buy at next available ask; sell at next available bid after an exit trigger |",
        "| Options fee | 0.010% of notional, capped at 3.5% of premium, on entry and exit |",
        "| GST | 18% of base trading fee |",
        "| Fee spot proxy | Latest completed five-minute BTC close |",
        "| Hard stop | -15% option premium |",
        "| Maximum hold | 60 minutes |",
        "| Contract selection | Nearest ATM CALL/PUT with 1-3 days to expiry |",
        "| Spread filter | Maximum 3% |",
        "| Volume filter | At least max(30, quantity x 5) |",
        "| Open interest | Must be positive |",
        "| VWAP | HLC3 volume-weighted, reset at 00:00 Asia/Kolkata |",
        "| Entry evaluation | Completed five-minute candle; enter only on transition into a valid condition |",
        "| Exit priority | Technical condition failure first, then hard/protected stop, then maximum hold |",
        "",
        f"Development contained **{matrix_report['datasets'][0]['raw_signals_with_contract']}** raw signals with a matching option contract. Holdout contained **{matrix_report['datasets'][1]['raw_signals_with_contract']}**.",
        "",
        "## Strategy Rules",
        "",
        "### Entry",
        "",
        "- CALL: close above VWAP, EMA9 > EMA20 > EMA50, RSI 50-70.",
        "- PUT: close below VWAP, EMA9 < EMA20 < EMA50, RSI 30-50.",
        "- Stoch RSI is not used.",
        "",
        "### Exit Variants",
        "",
        "- `EMA`: exit immediately when EMA9/20/50 ordering fails.",
        "- `EMA_VWAP`: exit immediately when EMA ordering or VWAP direction fails.",
        "- `EMA_VWAP_RSI`: exit immediately when EMA ordering, VWAP direction, or RSI band fails.",
        "",
        "### Protection Variants",
        "",
        "- `Z40/Z45/Z50/Z55/Z60`: after peak option profit reaches +20%, protect the stated percentage of the highest open profit continuously.",
        "- `E90`: +10% peak moves stop to breakeven; +15% protects 50% of peak profit; +30% protects 90%.",
        "- `E95`: same tiers, but +30% protects 95%.",
        "- A technical exit is never delayed by profit protection.",
        "",
        "## Historical Scenario Legend",
        "",
        "| Group | Protection | Exit variants |",
        "|---|---|---|",
        "| BT1-BT3 | None | EMA; EMA+VWAP; EMA+VWAP+RSI |",
        "| BT4 | Z50 at +20% activation | All three exit variants |",
        "| BT5 | Z40 at +20% activation | All three exit variants |",
        "| BT6 | Z45 at +20% activation | All three exit variants |",
        "| BT7 | Z55 at +20% activation | All three exit variants |",
        "| BT8 | Z60 at +20% activation | All three exit variants |",
        "| BT9 | E90 tiered protection | All three exit variants |",
        "| BT10 | E95 tiered protection | All three exit variants |",
        "",
        "## Combined Matrix Results",
        "",
        "These totals concatenate the adjacent holdout and development periods chronologically. Return is based on the original $100 while trade sizing remains fixed at $6.67; it is not compounded. Win rate, profit factor, expectancy, and drawdown use net P&L after both execution fees and GST.",
        "",
        *combined_table(matrix_summary, matrix_trades),
        "",
        "## Development Results",
        "",
        "Period: 2026-08-24 through 2026-09-22 UTC.",
        "",
        *detailed_table(matrix_report, matrix_summary, matrix_trades, development),
        "",
        "## Holdout Results",
        "",
        "Period: 2026-07-25 through 2026-08-23 UTC.",
        "",
        *detailed_table(matrix_report, matrix_summary, matrix_trades, holdout),
        "",
        "## Activation Threshold Study",
        "",
        "After the fixed +20% comparison selected Z55 with EMA+VWAP exit, protection was held at 55% and activation was varied across +10%, +15%, +20%, +25%, and +30%.",
        "",
        "### Combined Sensitivity",
        "",
        *activation_sensitivity(activation_trades),
        "",
        "Every activation threshold loses money after fees when the exceptional event is removed. The +30% holdout period appears positive only because that configuration held the exceptional CALL long enough to capture a very large estimated move; its combined two-period result is still negative.",
        "",
        "### Activation Development Details",
        "",
        *detailed_table(activation_report, activation_summary, activation_trades, development),
        "",
        "### Activation Holdout Details",
        "",
        *detailed_table(activation_report, activation_summary, activation_trades, holdout),
        "",
        "## BT2 Delayed Confirmation Comparison",
        "",
        "The full CALL or PUT condition first creates a pending signal. Entry is delayed by one to four completed five-minute candles. The same full condition must remain valid on every waiting candle; a neutral or opposite reading cancels the signal. Confirmed trades retain BT2's EMA+VWAP exit, -15% premium stop, 60-minute maximum hold, and fee model.",
        "",
        *confirmation_comparison(matrix_trades, confirmation_trades),
        "",
        "Waiting filters out many short-lived signals: development confirmations fall from 743 immediate raw signals to 578, 475, 391, and 341; holdout confirmations fall from 676 to 527, 445, 370, and 328. None of the delayed variants captured the exceptional August event.",
        "",
        "The two-candle wait has the least negative combined result at -$129.66. It improves on immediate BT2 after removing the exceptional event (-$201.49), but it remains negative in development (-$64.17) and holdout (-$65.49), with profit factors below 1 in both periods.",
        "",
        "### Confirmation Development Details",
        "",
        *detailed_table(
            confirmation_report,
            confirmation_summary,
            confirmation_trades,
            development,
        ),
        "",
        "### Confirmation Holdout Details",
        "",
        *detailed_table(
            confirmation_report,
            confirmation_summary,
            confirmation_trades,
            holdout,
        ),
        "",
        "## Exceptional Trade Audit",
        "",
        "On 2026-08-19 at 14:35 UTC, the selected BTC 68,000 CALL moved from an entry ask near 23.2 to a peak estimated bid near 1,630.8 while BTC rose sharply through the strike. This single event produced very large gains for variants that stayed in the trade. The underlying move appears in the source data, but the option bid/ask is estimated from public candle history rather than recorded executable L1 quotes.",
        "",
        "Consequences:",
        "",
        "- Raw holdout profits for several loose/no-protection scenarios are highly concentrated in this event.",
        "- Activation +30% appears best only when this trade is included.",
        "- No activation threshold remains profitable after both fees and removal of this event.",
        "",
        "## Interpretation",
        "",
        "1. The pre-fee edge was too small for Delta's option fee structure. For the former Z55 candidate, $60.35 of trading profit was overwhelmed by $250.82 of total fees.",
        "2. EMA+VWAP exits still outperform the other exit families relatively, but relative improvement is not enough: their robust fee-adjusted results remain negative.",
        "3. The RSI-continuous exit family trades most frequently and is especially fee-sensitive.",
        "4. The positive raw totals for BT1, BT2, and some Z40-Z50 variants depend on one exceptional event. Excluding it makes every tested scenario negative.",
        "5. Changing activation between 10% and 30% does not repair the negative expectancy after costs.",
        "6. This strategy should not be promoted to live trading in its current form.",
        "",
        "## Limitations",
        "",
        "- Option bid/ask values are reconstructed estimates, not the recorded order book available at every decision instant.",
        "- Current published Delta fees and GST are modeled, but future fee changes, account-specific discounts, offers, or rebates are not.",
        "- No explicit exchange latency, API latency, rejected-order probability, or partial fills are modeled.",
        "- Trade size is fixed rather than recalculated from changing account equity.",
        "- The engine continues fixed-size research trades after simulated equity reaches zero. Results beyond depletion measure signal economics, not an executable $100 account path.",
        "- The development and holdout datasets are adjacent and cover a limited market history.",
        "- Parameter selection after looking at holdout results introduces selection bias; a fresh untouched period is required.",
        "",
        "## Recommended Next Validation",
        "",
        "Do not move BT1, BT2, or BT3 to live trading in their current form. Further research will stay within these three core families and focus on improving entry quality and gross expectancy rather than adding protection tiers, fixed-point stops, or delayed confirmation. A revised candidate must be profitable after fees in both development and a fresh untouched holdout before L1 replay and analyzer validation.",
        "",
        "## Source Files",
        "",
        "- Fee-adjusted matrix JSON: `backtest/reports/ema-vwap-matrix-with-fees-v2/matrix_summary.json`",
        "- Fee-adjusted matrix CSV: `backtest/reports/ema-vwap-matrix-with-fees-v2/matrix_summary.csv`",
        "- Fee-adjusted activation JSON: `backtest/reports/ema-vwap-activation-z55-with-fees-v2/matrix_summary.json`",
        "- Fee-adjusted activation CSV: `backtest/reports/ema-vwap-activation-z55-with-fees-v2/matrix_summary.csv`",
        "- Fee-adjusted BT2 confirmation results: `backtest/reports/ema-vwap-bt2-confirmation-with-fees-v1/`",
        "- Earlier no-fee reports remain in their original `v1` directories for comparison.",
        "- Research implementation: `backtest/ema_vwap_research.py`",
        "",
    ]
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUTPUT.resolve())


def main() -> None:
    matrix_report, matrix_summary, matrix_trades = load_study(MATRIX_ROOT)
    activation_report, activation_summary, activation_trades = load_study(ACTIVATION_ROOT)
    stop_report, stop_summary, stop_trades = load_study(STOP_LOSS_ROOT)
    confirmation_report, confirmation_summary, confirmation_trades = load_study(
        CONFIRMATION_ROOT
    )
    macd_report, macd_summary, macd_trades = load_study(MACD_ROOT)
    stoch_report, stoch_summary, stoch_trades = load_study(STOCH_ROOT)
    session_report, session_summary, session_trades = load_study(UTC_SESSION_ROOT)
    all_fail_report, all_fail_summary, all_fail_trades = load_study(
        ALL_FAIL_EXIT_ROOT
    )
    macd_exit_report, macd_exit_summary, macd_exit_trades = load_study(
        ALL_FAIL_MACD_EXIT_ROOT
    )
    policy_report, policy_summary, policy_trades = load_study(
        MACD_EXIT_POLICIES_ROOT
    )
    h6_report, h6_summary, h6_trades = load_study(LOCKED_H6_ROOT)
    fa125_report, fa125_summary, fa125_trades = load_study(LOCKED_H6_FA125_ROOT)
    fa150_report, fa150_summary, fa150_trades = load_study(LOCKED_H6_FA150_ROOT)
    fa200_report, fa200_summary, fa200_trades = load_study(LOCKED_H6_FA200_ROOT)
    m30_report, m30_summary, m30_trades = load_study(LOCKED_H6_FA150_M30_ROOT)
    m30_stoch_report, m30_stoch_summary, m30_stoch_trades = load_study(
        LOCKED_H6_FA150_M30_STOCH_ROOT
    )
    m30_only_report, m30_only_summary, m30_only_trades = load_study(LOCKED_M30_ROOT)
    utc08_report, utc08_summary, utc08_trades = load_study(
        LOCKED_H6_FA150_UTC08_ROOT
    )
    z50_report, z50_summary, z50_trades = load_study(ALL_FAIL_Z50_ROOT)
    atr_report, atr_summary, atr_trades = load_study(ALL_FAIL_ATR_ROOT)
    atr_sensitivity_report, atr_sensitivity_summary, atr_sensitivity_trades = load_study(
        ATR_SENSITIVITY_ROOT
    )
    development = "delta-2026-09-15_22"
    holdout = "delta-holdout-2026-07-25_08-24"
    active = {"BT1_EMA", "BT2_EMA_VWAP", "BT3_EMA_VWAP_RSI"}
    ignored = set(matrix_summary["scenario"].unique()) - active
    active_policy_scenarios = {
        str(name)
        for name in policy_summary["scenario"].unique()
        if "MACDREV_ONLY" in str(name)
    }
    ignored_policy_scenarios = (
        set(policy_summary["scenario"].astype(str).unique())
        - active_policy_scenarios
    )
    ledger = transaction_log_stats(TRANSACTION_LOG)

    active_lines = [
        "# Active BT1-BT3 BTC Option Backtest Results",
        "",
        "> Active research only. Rejected protection, point-stop, and delayed-entry experiments were moved to `ema-vwap-ignored-backtest-results.md`.",
        "",
        "## Current Decision",
        "",
        "Only the BT1, BT2, and BT3 families remain under consideration. Each now has an additional MACD-confirmed entry variant. The locked MACD exit shortlist is `MACD reversal only` and `MACD reversal OR All-Fail`; all other MACD exit policies are archived. None is currently live-ready after Delta Exchange fees and exceptional-event testing.",
        "",
        "| Family | Exit rule | Development net | Holdout net | Combined net | Combined without exceptional event |",
        "|---|---|---:|---:|---:|---:|",
        "| BT1 | EMA ordering fails | -$105.93 | +$167.27 | +$61.34 | -$214.97 |",
        "| BT2 | EMA ordering or VWAP direction fails | -$101.02 | +$175.84 | +$74.82 | -$201.49 |",
        "| BT3 | EMA ordering, VWAP direction, or RSI band fails | -$147.05 | -$162.42 | -$309.48 | -$310.19 |",
        "",
        "BT1 and BT2 show positive raw combined totals only because of one exceptional estimated option move on 2026-08-19. Removing the same event makes all three families substantially negative.",
        "MACD improves the combined result of BT1 by $26.57, BT2 by $14.60, and BT3 by $40.14, but every MACD variant remains negative after removing the exceptional event.",
        "",
        "## Entry Rules",
        "",
        "- CALL: close above session VWAP, EMA9 > EMA20 > EMA50, and RSI 50-70.",
        "- PUT: close below session VWAP, EMA9 < EMA20 < EMA50, and RSI 30-50.",
        "- MACD variants add standard MACD(12,26,9): CALL requires MACD > signal; PUT requires MACD < signal.",
        "- The original MACD variants use MACD only as an entry confirmation. A separate study below tests fresh adverse MACD crossovers as an additional exit.",
        "- UTC session variants allow new entries from 00:00 through 15:59 UTC and block them from 16:00 through 23:59 UTC.",
        "- Open positions continue to use their normal exits after 16:00 UTC.",
        "- Entries use completed five-minute candles and the next available option ask.",
        "- BT1-BT3 use the original -15% option-premium hard stop and a 60-minute maximum hold.",
        "",
        "## Exit Rules",
        "",
        "- BT1 exits when the directional EMA9/20/50 ordering fails.",
        "- BT2 exits when EMA ordering or the directional VWAP condition fails.",
        "- BT3 exits when EMA ordering, VWAP direction, or the entry RSI band fails.",
        "",
        "## Delta Fee Model",
        "",
        "Fee schedule verified on 2026-10-01:",
        "",
        "```text",
        "notional_fee = BTC_spot * quantity * 0.001 * 0.010%",
        "premium_cap = option_premium * quantity * 0.001 * 3.5%",
        "base_fee = min(notional_fee, premium_cap)",
        "GST = base_fee * 18%",
        "total_fee = base_fee + GST",
        "```",
        "",
        "The fee is applied independently on entry and exit. The latest completed five-minute BTC close is used as the spot proxy.",
        "",
        "- [Delta Exchange India fee page](https://www.delta.exchange/fees)",
        "- [Delta Exchange India options fee calculation](https://www.delta.exchange/support/solutions?articleId=80001177864&categoryId=undefined&folderId=undefined)",
        "",
        "## Transaction Log Audit",
        "",
        f"The supplied transaction log contains {ledger['fee_rows']} trading-fee rows: ${ledger['base_fee']:.8f} base fees, ${ledger['gst']:.8f} GST, and ${ledger['total_fee']:.8f} total fees. The observed GST ratio is {100.0 * float(ledger['gst_min']):.5f}% to {100.0 * float(ledger['gst_max']):.5f}%, confirming 18% apart from decimal rounding.",
        "",
        "## Test Configuration",
        "",
        "| Setting | Value |",
        "|---|---|",
        "| Development | 2026-08-24 00:00 UTC to 2026-09-23 00:00 UTC |",
        "| Holdout | 2026-07-25 00:00 UTC to 2026-08-24 00:00 UTC |",
        "| Starting capital | $100 |",
        "| Premium budget | $6.67 per trade, fixed and not compounded |",
        "| Data fidelity | Estimated one-minute option BBO and five-minute BTC candles |",
        "| Fill model | Next ask for entry; next bid after exit trigger |",
        "| Contract | Nearest ATM CALL/PUT with 1-3 days to expiry |",
        "| Liquidity | Spread <= 3%; volume >= max(30, quantity x 5); OI > 0 |",
        "| VWAP | HLC3 volume-weighted; resets 00:00 Asia/Kolkata |",
        "| Costs | Delta option fees on entry and exit, including 18% GST |",
        "",
        "## Combined Results",
        "",
        "Metrics below use net P&L after fees and GST. Fixed sizing continues after theoretical account depletion so the table compares signal economics; later trades would not be executable by an unfunded $100 account.",
        "",
        *combined_table(matrix_summary, matrix_trades, active),
        "",
        "## MACD Comparison",
        "",
        "The MACD variants change only entry confirmation. Their BT1-BT3 exit rules, -15% hard stop, 60-minute maximum hold, sizing, liquidity checks, fill model, and fees are unchanged.",
        "",
        *macd_comparison(matrix_summary, matrix_trades, macd_summary, macd_trades),
        "",
        "### MACD Development Details",
        "",
        *detailed_table(macd_report, macd_summary, macd_trades, development),
        "",
        "### MACD Holdout Details",
        "",
        *detailed_table(macd_report, macd_summary, macd_trades, holdout),
        "",
        "## Plain BT1-BT3 With Stoch RSI",
        "",
        "This isolated test adds only the standard Stoch RSI(14,14,3,3) entry relationship to the plain BT1-BT3 families. CALL requires D > K and PUT requires K > D on the completed five-minute signal candle. MACD, H6, FA, M30, and UTC entry restrictions are disabled. Each family retains its original exit rule.",
        "",
        *stoch_comparison(matrix_trades, stoch_trades),
        "",
        "### Plain Stoch Findings",
        "",
        "- Stoch RSI does not improve any plain family. Exceptional-event-free P&L worsens by $30.04 for BT1, $33.02 for BT2, and $30.58 for BT3.",
        "- Development worsens from -$105.93 to -$128.43 for BT1, -$101.02 to -$128.08 for BT2, and -$147.05 to -$170.89 for BT3.",
        "- BT1 and BT2 Stoch exclude the exceptional 2026-08-19 runner, but the robust comparison remains negative even after removing that event from their plain controls.",
        "- Lower trade counts and lower fees do not help because the gate removes more gross payoff than costs. These three Stoch variants are not selected.",
        "",
        "### Plain Stoch Development Details",
        "",
        *detailed_table(stoch_report, stoch_summary, stoch_trades, development),
        "",
        "### Plain Stoch Holdout Details",
        "",
        *detailed_table(stoch_report, stoch_summary, stoch_trades, holdout),
        "",
        "## UTC Entry-Session Filter",
        "",
        "This filter is applied to all three original families and all three MACD variants. Both the completed signal candle and the actual next-quote entry must occur before 16:00 UTC.",
        "",
        *utc_session_comparison(
            matrix_trades,
            macd_trades,
            session_summary,
            session_trades,
        ),
        "",
        "### UTC-Filtered Development Details",
        "",
        *detailed_table(session_report, session_summary, session_trades, development),
        "",
        "### UTC-Filtered Holdout Details",
        "",
        *detailed_table(session_report, session_summary, session_trades, holdout),
        "",
        "## All-Conditions-Fail Exit Study",
        "",
        "The current exit policy closes BT2 or BT3 when any required condition fails. This study changes BT2 to exit only when EMA and VWAP both fail on the same completed candle, and BT3 to exit only when EMA, VWAP, and RSI all fail together. BT1 is an unchanged control. The UTC entry window and all other assumptions remain fixed.",
        "",
        "### Exact Revised Rules",
        "",
        "- BT1: exit when the directional EMA9/20/50 ordering fails.",
        "- BT2: exit only when both the EMA ordering and directional VWAP conditions fail on the same completed five-minute candle.",
        "- BT3: exit only when EMA ordering, directional VWAP, and the directional RSI entry band all fail on the same completed five-minute candle.",
        "- Hard stop remains -15% of option premium and maximum holding time remains 60 minutes.",
        "- The 00:00-15:59 UTC restriction affects new entries only; exits remain active at all times.",
        "- Original and MACD-confirmed entries are tested separately. MACD remains an entry filter and is not part of the exit decision.",
        "",
        *all_fail_exit_comparison(
            session_trades,
            all_fail_summary,
            all_fail_trades,
        ),
        "",
        "BT2 and BT3 produce identical revised trades in both periods. In this sample, every completed candle where EMA ordering and VWAP direction both failed also had RSI outside the entry band, so BT3's third simultaneous-failure requirement never delayed an exit beyond BT2.",
        "",
        "### Difference Analysis",
        "",
        "- BT1 and BT1 + MACD are exact controls: their rules, trade counts, P&L, and drawdowns do not change.",
        "- BT2 holds positions longer and takes 88 fewer trades. Its non-MACD combined result decreases by $5.40, from +$143.74 to +$138.35.",
        "- BT2 + MACD takes 53 fewer trades and improves by $8.52, from +$151.99 to +$160.51.",
        "- BT3 no longer exits merely because RSI leaves the entry band. Its trade count drops from 948 to 607 and its combined result improves by $357.78, from -$219.43 to +$138.35.",
        "- BT3 + MACD drops from 805 to 550 trades and improves by $362.30, from -$201.79 to +$160.51.",
        "- The apparent combined profits remain concentrated in the exceptional 2026-08-19 option event. Excluding that event leaves BT2/BT3 at -$137.97 and their MACD versions at -$115.80.",
        "- All six development-period results remain negative, so the improvement is not stable across periods and does not justify live deployment.",
        "",
        "### All-Fail Development Details",
        "",
        *detailed_table(
            all_fail_report,
            all_fail_summary,
            all_fail_trades,
            development,
        ),
        "",
        "### All-Fail Holdout Details",
        "",
        *detailed_table(
            all_fail_report,
            all_fail_summary,
            all_fail_trades,
            holdout,
        ),
        "",
        "## Locked MACD Reversal OR All-Fail Exit",
        "",
        "This locked policy adds one exit to every All-Fail variant: after entry, a fresh adverse MACD(12,26,9) crossover on a completed five-minute BTC candle requests an exit at the next available option bid. A CALL requires MACD to cross from above the signal line to at or below it; a PUT requires the opposite cross. The normal All-Fail condition remains active as an independent exit, and the -15% hard stop, 60-minute maximum hold, UTC entry window, sizing, liquidity checks, fills, and fees are unchanged.",
        "",
        *all_fail_macd_exit_comparison(
            all_fail_trades,
            macd_exit_summary,
            macd_exit_trades,
        ),
        "",
        "### MACD Exit Findings",
        "",
        "- The MACD exit improves every combined result, but only by $0.94 to $4.35 across the six variants.",
        "- Development improves by $7.52 to $15.48, while holdout worsens by $6.23 to $11.90. That disagreement indicates the improvement is not stable across periods.",
        "- The strongest combined result is BT1 + MACD entry at +$165.55. Removing the exceptional event leaves it at -$110.76, still negative.",
        "- MACD reversal is responsible for 278 to 342 exits, so this is a material behavior change despite the small net improvement.",
        "- BT2 and BT3 remain identical because their additional RSI all-fail requirement does not delay an exit in this sample.",
        "- This test does not establish a profitable or live-ready edge.",
        "",
        "### MACD-Exit Development Details",
        "",
        *detailed_table(
            macd_exit_report,
            macd_exit_summary,
            macd_exit_trades,
            development,
        ),
        "",
        "### MACD-Exit Holdout Details",
        "",
        *detailed_table(
            macd_exit_report,
            macd_exit_summary,
            macd_exit_trades,
            holdout,
        ),
        "",
        "## Locked MACD Reversal-Only Exit",
        "",
        "`MACD reversal only` disables the family condition exit and exits on the first fresh adverse MACD crossover. All exits use the next option bid; the -15% hard stop and 60-minute maximum hold remain active. This policy and the preceding `MACD reversal OR All-Fail` policy are the two locked research candidates.",
        "",
        *macd_exit_policy_table(policy_trades, {"MACD reversal only"}),
        "",
        "### Locked-Policy Findings",
        "",
        "- MACD reversal only with MACD-filtered entry is the numerical winner: +$166.01 combined and -$110.31 without the exceptional event.",
        "- It improves the previous `MACD reversal OR All-Fail` winner by only $0.45 combined and $0.45 without the exceptional event. This is too small to establish a meaningful advantage.",
        "- All development and exceptional-event-free results remain negative. Neither locked policy establishes a stable, live-ready edge.",
        "- BT1-BT3 are identical under reversal-only because that policy intentionally disables the EMA/VWAP/RSI family exit.",
        "",
        "### Reversal-Only Development Details",
        "",
        *detailed_table(
            policy_report,
            policy_summary,
            policy_trades,
            development,
            active_policy_scenarios,
        ),
        "",
        "### Reversal-Only Holdout Details",
        "",
        *detailed_table(
            policy_report,
            policy_summary,
            policy_trades,
            holdout,
            active_policy_scenarios,
        ),
        "",
        "## Sequential H6, Fee-Aware, and M30 Study",
        "",
        "H6 and M30 were first tested independently on the two locked exits. FA125, FA150, and FA200 were then tested after the six observations required to calculate their movement-capacity estimate, followed by the FA150 + M30 combination. The comparison below uses MACD-filtered entries because they were already the stronger entry family.",
        "",
        "- H6 aggregates raw cached Delta one-minute option OHLC into completed five-minute candles and requires at least six valid True Range observations before the signal. This requires at least seven completed option candles.",
        "- FA uses the mean of the latest six option True Ranges as movement capacity. Movement capacity in USD is compared with estimated round-trip Delta option fees, including GST, for the calculated position size.",
        "- FA125, FA150, and FA200 require movement capacity of at least 1.25x, 1.50x, and 2.00x estimated round-trip fees respectively.",
        "- M30 requires the completed BTC signal-candle close to be directionally favorable versus the completed close six five-minute bars earlier. CALL requires a positive move and PUT a negative move.",
        "",
        *locked_filter_sequence_table(
            macd_exit_trades,
            policy_trades,
            m30_only_trades,
            h6_trades,
            fa125_trades,
            fa150_trades,
            fa200_trades,
            m30_trades,
            m30_stoch_trades,
        ),
        "",
        "### Sequential Findings",
        "",
        "- H6 alone removed only one losing trade per configuration and improved net P&L by approximately $0.76. It is useful as a data-quality guard, not as an edge.",
        "- M30 alone improves the best exceptional-event-free result by $6.63, from -$110.31 to -$103.68, and lowers maximum drawdown from $89.98 to $83.00. It remains a weak standalone filter.",
        "- FA cannot be calculated without recent option history. Therefore each FA test inherently requires the six True Range observations used by H6; there is no mathematically valid FA-only row without that history requirement.",
        "- FA125 materially improves the exceptional-event-free result from approximately -$110 to -$56 to -$58 and reduces drawdown to about $54-$55.",
        "- FA150 is the strongest fee threshold: reversal only reaches +$242.14 combined, -$34.18 without the exceptional event, and $47.23 maximum drawdown.",
        "- FA200 is too restrictive for this sample. It improves profit factor and drawdown but worsens development and exceptional-event-free P&L versus FA150.",
        "- Adding M30 to FA150 improves the best combined and exceptional-event-free totals by only $1.38, while development worsens by $0.17. That change is too small and inconsistent to justify locking M30.",
        "- Adding the requested Stoch RSI(14,14,3,3) gate to H6 + FA150 + M30 requires D > K for CALL and K > D for PUT. It removes 15 trades, improves development by $3.94, but reduces holdout by $25.65 and worsens exceptional-event-free P&L by $21.71, from -$32.80 to -$54.51. It is not selected from the existing periods.",
        "- The preferred filter candidate is therefore H6 + FA150 without M30. It still loses -$24.76 in development and -$34.18 without the exceptional event, so it is not live-ready.",
        "",
        "### H6 + FA150 Development Details",
        "",
        *detailed_table(fa150_report, fa150_summary, fa150_trades, development),
        "",
        "### H6 + FA150 Holdout Details",
        "",
        *detailed_table(fa150_report, fa150_summary, fa150_trades, holdout),
        "",
        "### H6 + FA150 + M30 Development Details",
        "",
        *detailed_table(m30_report, m30_summary, m30_trades, development),
        "",
        "### H6 + FA150 + M30 Holdout Details",
        "",
        *detailed_table(m30_report, m30_summary, m30_trades, holdout),
        "",
        "### H6 + FA150 + M30 + Stoch RSI Development Details",
        "",
        *detailed_table(
            m30_stoch_report,
            m30_stoch_summary,
            m30_stoch_trades,
            development,
        ),
        "",
        "### H6 + FA150 + M30 + Stoch RSI Holdout Details",
        "",
        *detailed_table(
            m30_stoch_report,
            m30_stoch_summary,
            m30_stoch_trades,
            holdout,
        ),
        "",
        "## Loss Analysis and Prevention Pattern",
        "",
        "The preferred H6 + FA150 reversal-only candidate was decomposed by direction, exit reason, session, fees, and unrealized favorable movement. This analysis identifies where losses are realized and which pattern survives an actual backtest rerun; it does not prove causation from exit labels alone.",
        "",
        "### Main Loss Causes",
        "",
        "- The entry edge is weak outside the later UTC window. With entries allowed from 00:00 UTC, the candidate loses -$24.76 in development and -$34.18 after removing the exceptional event. The 00:00-07:59 UTC trades account for most of that deterioration.",
        "- Fees amplify the problem rather than create it. In development, gross P&L before fees is only +$7.09 and $31.85 of fees converts it to -$24.76. Seven otherwise profitable trades become net losses after fees.",
        "- Most losing trades are false or choppy entries that never develop enough favorable movement. Median maximum favorable excursion among losers is only about 2.3%-2.5%; only 28 development losses and 24 holdout losses ever reached +10% before reversing.",
        "- Hard-stop exits are the largest losses per trade. After the later-session filter and removal of the exceptional event, 35 hard stops lose $47.57, averaging -$1.36 each. Historical next-bid execution can cross below the configured -15% threshold, so the realized loss can be worse than -15%.",
        "- MACD reversal exits create many small losses: 102 robust trades lose $48.39 in aggregate, averaging -$0.47. The exit limits damage compared with the hard stop, but cannot repair poor entries.",
        "- The profitable payoff comes from trades allowed to mature. Robust maximum-hold exits produce +$112.38 across 48 trades with 40 winners. Shortening the hold or adding aggressive trailing protection would likely remove the payoff that currently offsets frequent small losses.",
        "",
        "### Tested Prevention Pattern",
        "",
        "The strongest observed prevention pattern is to keep H6 + FA150 and allow new entries only from 08:00 through 15:59 UTC. This was rerun through the backtester, including contract selection, fills, exits, and fees; it is not merely a post-processing deletion of trades.",
        "",
        *loss_window_comparison(fa150_trades, utc08_trades),
        "",
        "After removing the exceptional 2026-08-19 trade, the 08:00-15:59 candidate has 185 trades, +$16.43 net P&L, 1.156 profit factor, +$0.09 expectancy per trade, and $17.17 maximum drawdown. Development is also positive at +$5.63. This is the first tested rule in this research sequence to be positive in both existing periods.",
        "",
        "### Robust Breakdown for 08:00-15:59 UTC",
        "",
        *robust_loss_breakdown(
            utc08_trades,
            "BT1_EMA_MACD_MACDREV_ONLY_H6_FA150_UTC08_16",
        ),
        "",
        "### What Not to Change Yet",
        "",
        "- Do not remove the -15% hard stop. It contains rare severe failures even though next-quote gaps can overshoot it.",
        "- Do not shorten the 60-minute maximum hold or add a tight profit trail. The robust positive payoff is concentrated in positions that survive to maximum hold, while most losers never had material profit to protect.",
        "- Do not tighten RSI, EMA-gap, VWAP-distance, ATR, or M30 thresholds from this sample. Winner/loss differences for those indicators are inconsistent between development and holdout and would invite overfitting.",
        "- PUT trades are weak at -$1.28 robust net versus +$17.71 for CALL, but the development/holdout direction split is inconsistent. Disabling PUT requires a fresh-period test rather than another in-sample choice.",
        "",
        "### Validation Requirement",
        "",
        "The 08:00 UTC boundary was discovered using the existing development and holdout samples. Its +$16.43 robust result therefore has selection bias and a thin 1.156 profit factor. Keep it as the leading hypothesis, but require a new untouched date range and preferably recorded Delta L1 quotes before changing the live strategy.",
        "",
        "### UTC08 Development Details",
        "",
        *detailed_table(utc08_report, utc08_summary, utc08_trades, development),
        "",
        "### UTC08 Holdout Details",
        "",
        *detailed_table(utc08_report, utc08_summary, utc08_trades, holdout),
        "",
        "## Development Details",
        "",
        *detailed_table(matrix_report, matrix_summary, matrix_trades, development, active),
        "",
        "## Holdout Details",
        "",
        *detailed_table(matrix_report, matrix_summary, matrix_trades, holdout, active),
        "",
        "## Exceptional Event",
        "",
        "On 2026-08-19 at 14:35 UTC, the selected BTC 68,000 CALL entered near 23.2 and later showed an estimated bid above 1,600 while BTC moved sharply through the strike. The source move exists, but the option BBO is reconstructed rather than recorded executable L1 data. BT1 and BT2 depend on this event for their positive raw totals.",
        "",
        "## Conclusion",
        "",
        "The loss analysis isolates 00:00-07:59 UTC as the strongest preventable pattern in the current sample. H6 + FA150 with reversal-only exit and entries restricted to 08:00-15:59 UTC is positive in development and after removing the exceptional event, while materially reducing drawdown. Because that window was selected from the same historical data and its robust profit factor is only 1.156, it remains a research candidate rather than a live-ready strategy until it passes a fresh untouched period with higher-fidelity quotes.",
        "",
        "## Files",
        "",
        "- Active fee-adjusted matrix: `backtest/reports/ema-vwap-matrix-with-fees-v2/`",
        "- MACD-confirmed BT1-BT3 study: `backtest/reports/ema-vwap-macd-with-fees-v1/`",
        "- Plain BT1-BT3 Stoch RSI study: `backtest/reports/ema-vwap-stoch-with-fees-v1/`",
        "- UTC 00:00-15:59 entry-session study: `backtest/reports/ema-vwap-utc00-16-with-fees-v1/`",
        "- All-conditions-fail exit study: `backtest/reports/ema-vwap-all-fail-exits-utc00-16-with-fees-v1/`",
        "- All-Fail + MACD reversal exit study: `backtest/reports/ema-vwap-all-fail-macd-exit-utc00-16-with-fees-v1/`",
        "- MACD exit-policy comparison: `backtest/reports/ema-vwap-macd-exit-policies-utc00-16-with-fees-v1/`",
        "- Locked H6 study: `backtest/reports/ema-vwap-locked-h6-utc00-16-with-fees-v1/`",
        "- Locked M30-only study: `backtest/reports/ema-vwap-locked-m30-utc00-16-with-fees-v1/`",
        "- Locked H6 + FA125 study: `backtest/reports/ema-vwap-locked-h6-fa125-utc00-16-with-fees-v1/`",
        "- Locked H6 + FA150 study: `backtest/reports/ema-vwap-locked-h6-fa150-utc00-16-with-fees-v1/`",
        "- Locked H6 + FA200 study: `backtest/reports/ema-vwap-locked-h6-fa200-utc00-16-with-fees-v1/`",
        "- Locked H6 + FA150 + M30 study: `backtest/reports/ema-vwap-locked-h6-fa150-m30-utc00-16-with-fees-v1/`",
        "- Locked H6 + FA150 + M30 + Stoch RSI study: `backtest/reports/ema-vwap-locked-h6-fa150-m30-stoch-utc00-16-with-fees-v1/`",
        "- Locked H6 + FA150 UTC 08:00-15:59 loss-prevention study: `backtest/reports/ema-vwap-locked-h6-fa150-utc08-16-with-fees-v1/`",
        "- Ignored experiment archive: `backtest/reports/ema-vwap-ignored-backtest-results.md`",
        "- Research implementation: `backtest/ema_vwap_research.py`",
        "",
    ]

    archive_lines = [
        "# Ignored BTC Option Backtest Results",
        "",
        "> Historical archive only. None of these variants is an active candidate or should be optimized further.",
        "",
        "## Archived Scope",
        "",
        "- BT4-BT10 profit-protection families.",
        "- Z55 activation thresholds from 10% through 30%.",
        "- BT2 fixed 100/150/200 option-premium point stops.",
        "- BT2 delayed confirmation from one through four candles.",
        "- All-Fail + Z50 with +50% activation and 50% peak-profit retention.",
        "- All-Fail + ATR(14) trailing exits at 2.0x, 2.5x, and 3.0x.",
        "- MACD included inside the All-Fail conjunction.",
        "- MACD reversal requiring one additional five-minute confirmation candle.",
        "",
        "All monetary metrics include Delta options fees on entry and exit plus 18% GST. The same low-fidelity quote and fill limitations described in the active report apply.",
        "",
        "## BT4-BT10 Combined Results",
        "",
        *combined_table(matrix_summary, matrix_trades, ignored),
        "",
        "## BT4-BT10 Development Details",
        "",
        *detailed_table(matrix_report, matrix_summary, matrix_trades, development, ignored),
        "",
        "## BT4-BT10 Holdout Details",
        "",
        *detailed_table(matrix_report, matrix_summary, matrix_trades, holdout, ignored),
        "",
        "## Z55 Activation Threshold Study",
        "",
        *activation_sensitivity(activation_trades),
        "",
        "### Activation Development Details",
        "",
        *detailed_table(activation_report, activation_summary, activation_trades, development),
        "",
        "### Activation Holdout Details",
        "",
        *detailed_table(activation_report, activation_summary, activation_trades, holdout),
        "",
        "## Fixed Point Stop-Loss Study",
        "",
        "The point stop replaces the original -15% premium stop with entry premium minus 100, 150, or 200 points.",
        "",
        *point_stop_comparison(matrix_trades, stop_trades),
        "",
        "### Point-Stop Development Details",
        "",
        *detailed_table(stop_report, stop_summary, stop_trades, development),
        "",
        "### Point-Stop Holdout Details",
        "",
        *detailed_table(stop_report, stop_summary, stop_trades, holdout),
        "",
        "## Delayed Confirmation Study",
        "",
        "The same full entry condition had to remain valid for every waiting candle before entry.",
        "",
        *confirmation_comparison(matrix_trades, confirmation_trades),
        "",
        "### Confirmation Development Details",
        "",
        *detailed_table(
            confirmation_report,
            confirmation_summary,
            confirmation_trades,
            development,
        ),
        "",
        "### Confirmation Holdout Details",
        "",
        *detailed_table(
            confirmation_report,
            confirmation_summary,
            confirmation_trades,
            holdout,
        ),
        "",
        "## Rejected All-Fail + Z50 Study",
        "",
        "Z50 activated at +50% option profit and protected 50% of the highest open profit. It was rejected because it clipped the exceptional runner and reduced every combined result by approximately $63-$65 without producing positive development or exceptional-event-free expectancy.",
        "",
        *all_fail_z50_comparison(
            all_fail_trades,
            z50_summary,
            z50_trades,
        ),
        "",
        "### Z50 Development Details",
        "",
        *detailed_table(z50_report, z50_summary, z50_trades, development),
        "",
        "### Z50 Holdout Details",
        "",
        *detailed_table(z50_report, z50_summary, z50_trades, holdout),
        "",
        "## Rejected All-Fail + ATR Study",
        "",
        "ATR trailing exits were rejected because all multipliers remained negative in development and after removing the exceptional event. ATR 2.0x was strongest, while 2.5x and 3.0x allowed more giveback and performed worse.",
        "",
        *all_fail_atr_comparison(
            all_fail_trades,
            atr_summary,
            atr_trades,
        ),
        "",
        "### ATR Multiplier Comparison",
        "",
        *atr_multiplier_comparison(
            atr_summary,
            atr_trades,
            atr_sensitivity_summary,
            atr_sensitivity_trades,
        ),
        "",
        "### ATR 2.0x Development Details",
        "",
        *detailed_table(atr_report, atr_summary, atr_trades, development),
        "",
        "### ATR 2.0x Holdout Details",
        "",
        *detailed_table(atr_report, atr_summary, atr_trades, holdout),
        "",
        "### ATR 2.5x and 3.0x Development Details",
        "",
        *detailed_table(
            atr_sensitivity_report,
            atr_sensitivity_summary,
            atr_sensitivity_trades,
            development,
        ),
        "",
        "### ATR 2.5x and 3.0x Holdout Details",
        "",
        *detailed_table(
            atr_sensitivity_report,
            atr_sensitivity_summary,
            atr_sensitivity_trades,
            holdout,
        ),
        "",
        "## Rejected MACD Exit Policies",
        "",
        "`MACD included in All-Fail` and `Confirmed MACD reversal` were removed from the active shortlist. The former did not beat the two locked policies, while the extra confirmation candle gave back too much of the option move. Their raw outputs remain available for audit.",
        "",
        *macd_exit_policy_table(
            policy_trades,
            {"MACD included in All-Fail", "Confirmed MACD reversal"},
        ),
        "",
        "### Rejected MACD-Policy Development Details",
        "",
        *detailed_table(
            policy_report,
            policy_summary,
            policy_trades,
            development,
            ignored_policy_scenarios,
        ),
        "",
        "### Rejected MACD-Policy Holdout Details",
        "",
        *detailed_table(
            policy_report,
            policy_summary,
            policy_trades,
            holdout,
            ignored_policy_scenarios,
        ),
        "",
        "## Archive Conclusion",
        "",
        "None of these experiments produced robust positive fee-adjusted expectancy across both periods. Raw positive totals in several variants depend on the exceptional 2026-08-19 option move.",
        "",
        "## Source Directories",
        "",
        "- `backtest/reports/ema-vwap-matrix-with-fees-v2/`",
        "- `backtest/reports/ema-vwap-activation-z55-with-fees-v2/`",
        "- `backtest/reports/ema-vwap-bt2-point-stops-with-fees-v1/`",
        "- `backtest/reports/ema-vwap-bt2-confirmation-with-fees-v1/`",
        "- `backtest/reports/ema-vwap-all-fail-z50a50-utc00-16-with-fees-v1/`",
        "- `backtest/reports/ema-vwap-all-fail-atr14x2-utc00-16-with-fees-v1/`",
        "- `backtest/reports/ema-vwap-all-fail-atr14x25-x3-utc00-16-with-fees-v1/`",
        "- `backtest/reports/ema-vwap-macd-exit-policies-utc00-16-with-fees-v1/`",
        "",
    ]

    OUTPUT.write_text("\n".join(active_lines), encoding="utf-8")
    ARCHIVE_OUTPUT.write_text("\n".join(archive_lines), encoding="utf-8")
    print(OUTPUT.resolve())
    print(ARCHIVE_OUTPUT.resolve())


if __name__ == "__main__":
    main()
