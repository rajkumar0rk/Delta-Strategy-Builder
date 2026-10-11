from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UTC = timezone.utc


def _timestamp(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _number(row: dict[str, str], key: str) -> float:
    value = row.get(key, "")
    return float(value) if value not in {"", None} else 0.0


def _trade_key(row: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        row["signal_time"],
        row["direction"],
        row["symbol"],
        row["entry_type"],
    )


def _dataset_records(summary: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for dataset in summary["datasets"]:
        directory = Path(dataset["data_directory"])
        instruments = {
            row["symbol"]: row
            for row in _load_csv(directory / "option_instruments.csv")
        }
        records.append({
            "directory": directory,
            "start": _timestamp(dataset["start"]),
            "end": _timestamp(dataset["end"]),
            "instruments": instruments,
            "spread_percent": float(dataset.get("estimated_spread_percent", 1.0)),
        })
    return records


def _dataset_for_trade(
    datasets: list[dict[str, Any]],
    entry_time: str,
) -> dict[str, Any]:
    stamp = _timestamp(entry_time)
    for dataset in datasets:
        if dataset["start"] <= stamp < dataset["end"]:
            return dataset
    raise RuntimeError(f"no source dataset covers trade at {entry_time}")


def _quote_snapshot(
    dataset: dict[str, Any],
    symbol: str,
    quote_time: str,
    cache: dict[Path, dict[int, dict[str, Any]]],
) -> dict[str, float | str | None]:
    instrument = dataset["instruments"].get(symbol)
    if instrument is None:
        return {}
    quote_stamp = _timestamp(quote_time)
    candle_stamp = quote_stamp - 60
    source_symbol = instrument["source_symbol"]
    candle_day = datetime.fromtimestamp(candle_stamp, UTC).date().isoformat()
    path = (
        dataset["directory"]
        / "raw"
        / "candles"
        / "1m"
        / source_symbol
        / f"{candle_day}.json"
    )
    if path not in cache:
        if not path.exists():
            cache[path] = {}
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
            cache[path] = {
                int(row["time"]): row for row in payload.get("rows", [])
            }
    candle = cache[path].get(candle_stamp)
    if candle is None:
        return {}
    midpoint = float(candle["close"])
    volume = max(0.0, float(candle.get("volume") or 0.0))
    tick = float(instrument["price_increment"])
    half_spread = dataset["spread_percent"] / 200.0
    bid = math.floor(midpoint * (1.0 - half_spread) / tick) * tick
    ask = math.ceil(midpoint * (1.0 + half_spread) / tick) * tick
    bid = max(tick, bid)
    ask = max(bid + tick, ask)
    return {
        "bid": bid,
        "ask": ask,
        "bid_size": max(1.0, volume),
        "ask_size": max(1.0, volume),
        "candle_volume": volume,
        "size_source": "SYNTHETIC_MAX_1_OR_1M_VOLUME",
        "source_file": str(path.resolve()),
    }


def build_audit(run: Path, output: Path, control: Path | None = None) -> dict[str, Any]:
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    trades = sorted(_load_csv(run / "trades.csv"), key=lambda row: row["entry_time"])
    datasets = _dataset_records(summary)
    config = summary["configuration"]
    execution = config["execution"]
    candle_cache: dict[Path, dict[int, dict[str, Any]]] = {}
    audit_rows: list[dict[str, Any]] = []

    for index, trade in enumerate(trades, 1):
        dataset = _dataset_for_trade(datasets, trade["entry_time"])
        instrument = dataset["instruments"].get(trade["symbol"])
        contract_value = float(instrument["contract_value"]) if instrument else 0.0
        entry_quote = _quote_snapshot(
            dataset, trade["symbol"], trade["entry_time"], candle_cache
        )
        exit_quote = _quote_snapshot(
            dataset, trade["symbol"], trade["exit_time"], candle_cache
        )
        requested = _number(trade, "requested_quantity")
        entry_filled = _number(trade, "quantity")
        exit_filled = _number(trade, "exit_filled_quantity")
        unfilled = _number(trade, "exit_unfilled_quantity")
        final_bid = float(exit_quote.get("bid") or 0.0)
        zero_loss = unfilled * final_bid * contract_value
        net_pnl = _number(trade, "pnl_usd")
        audit_rows.append({
            "trade_id": f"C34-{index:04d}",
            "signal_time": trade["signal_time"],
            "entry_time": trade["entry_time"],
            "exit_time": trade["exit_time"],
            "option_symbol": trade["symbol"],
            "direction": trade["direction"],
            "entry_type": trade["entry_type"],
            "requested_qty": requested,
            "entry_filled_qty": entry_filled,
            "entry_fill_percent": _number(trade, "entry_fill_percent"),
            "entry_avg_price": _number(trade, "entry_ask"),
            "entry_bid": entry_quote.get("bid"),
            "entry_ask": entry_quote.get("ask"),
            "entry_bid_size": entry_quote.get("bid_size"),
            "entry_ask_size": entry_quote.get("ask_size"),
            "entry_fill_quotes": int(_number(trade, "entry_fill_quotes")),
            "entry_timeout_seconds": execution["entry_fill_timeout_seconds"],
            "exit_requested_qty": entry_filled,
            "exit_filled_qty": exit_filled,
            "exit_fill_percent": (
                100.0 * exit_filled / entry_filled if entry_filled > 0.0 else 0.0
            ),
            "exit_avg_price": trade.get("exit_average_fill_bid") or None,
            "exit_effective_bid_after_zero_policy": _number(trade, "exit_bid"),
            "exit_final_bid": exit_quote.get("bid"),
            "exit_final_ask": exit_quote.get("ask"),
            "exit_final_bid_size": exit_quote.get("bid_size"),
            "exit_final_ask_size": exit_quote.get("ask_size"),
            "exit_fill_quotes": int(_number(trade, "exit_fill_quotes")),
            "exit_timeout_seconds": execution["exit_fill_timeout_seconds"],
            "unfilled_exit_qty": unfilled,
            "zero_valued_qty": unfilled if execution["unfilled_exit_policy"] == "ZERO" else 0.0,
            "zero_policy_loss_vs_final_bid_usd": zero_loss,
            "gross_pnl_usd": _number(trade, "gross_pnl_usd"),
            "fees_usd": _number(trade, "fees_usd"),
            "net_pnl_usd": net_pnl,
            "net_pnl_if_residual_marked_at_final_bid_usd": net_pnl + zero_loss,
            "exit_reason": trade["exit_reason"],
            "contract_value": contract_value,
            "size_source": entry_quote.get("size_source"),
            "data_directory": str(dataset["directory"].resolve()),
        })

    scenario = next(iter(summary["combined"]))
    metrics = summary["combined"][scenario]
    diagnostics = summary["signal_diagnostics"][scenario]
    rejections = Counter(summary["entry_rejections"][scenario])
    accepted = len(audit_rows)
    execution_attempts = accepted + sum(
        rejections.get(reason, 0)
        for reason in (
            "ENTRY_FILL_TOO_SMALL",
            "ENTRY_FILL_PERCENT_TOO_LOW",
            "OUTSIDE_ENTRY_SESSION",
            "SPREAD_TOO_WIDE",
            "VOLUME_TOO_LOW",
            "OPEN_INTEREST_TOO_LOW",
            "PREMIUM_BUDGET_TOO_LOW",
            "FEE_AWARE_MOVE_TOO_LOW",
        )
    )
    full_entries = sum(
        row["entry_filled_qty"] + 1e-12 >= row["requested_qty"]
        for row in audit_rows
    )
    full_exits = sum(row["unfilled_exit_qty"] <= 1e-12 for row in audit_rows)
    residual_exits = accepted - full_exits
    total_zero_qty = sum(row["zero_valued_qty"] for row in audit_rows)
    total_zero_loss = sum(
        row["zero_policy_loss_vs_final_bid_usd"] for row in audit_rows
    )
    result: dict[str, Any] = {
        "run": str(run.resolve()),
        "scenario": scenario,
        "configuration": config,
        "signals_generated": diagnostics.get("SIGNALS", 0),
        "signals_with_contract": diagnostics.get("SIGNALS_WITH_CONTRACT", 0),
        "entry_attempts_reaching_execution": execution_attempts,
        "accepted_entries": accepted,
        "fully_filled_entries": full_entries,
        "partially_filled_entries": accepted - full_entries,
        "all_rejections": dict(rejections),
        "entries_rejected_below_minimum_fill": rejections.get(
            "ENTRY_FILL_PERCENT_TOO_LOW", 0
        ),
        "average_requested_quantity_accepted": (
            sum(row["requested_qty"] for row in audit_rows) / accepted
        ),
        "average_filled_quantity_accepted": (
            sum(row["entry_filled_qty"] for row in audit_rows) / accepted
        ),
        "average_entry_fill_percent_accepted": (
            sum(row["entry_fill_percent"] for row in audit_rows) / accepted
        ),
        "full_exits": full_exits,
        "partial_exits": residual_exits,
        "exits_with_residual_quantity": residual_exits,
        "exits_where_zero_policy_applied": residual_exits,
        "total_quantity_valued_at_zero": total_zero_qty,
        "pnl_lost_to_zero_vs_final_observed_bid_usd": total_zero_loss,
        "reported_net_pnl_usd": metrics["net_pnl_usd"],
        "net_pnl_if_residual_marked_at_final_bid_usd": (
            metrics["net_pnl_usd"] + total_zero_loss
        ),
        "accepted_trade_metrics": metrics,
        "limitations": [
            "Rejected-entry requested and filled quantities were not retained by this old run.",
            "A rejected entry has no counterfactual exit path, so rejected winners versus losers cannot be known from this run.",
            "Historical sizes are synthetic max(1, one-minute candle volume), not recorded BBO depth.",
            "The final observed bid counterfactual is a mark, not proof that residual quantity could execute there.",
        ],
    }

    if control is not None:
        control_trades = _load_csv(control / "trades.csv")
        selected_keys = {_trade_key(row) for row in trades}
        control_by_key = {_trade_key(row): row for row in control_trades}
        matched_control = [
            control_by_key[key] for key in selected_keys if key in control_by_key
        ]
        control_only = [
            row for row in control_trades if _trade_key(row) not in selected_keys
        ]
        result["full_bbo_control"] = {
            "run": str(control.resolve()),
            "trades": len(control_trades),
            "net_pnl_usd": sum(_number(row, "pnl_usd") for row in control_trades),
            "matched_trades": len(matched_control),
            "matched_full_bbo_pnl_usd": sum(
                _number(row, "pnl_usd") for row in matched_control
            ),
            "matched_size_aware_pnl_usd": sum(
                _number(row, "pnl_usd")
                for row in trades
                if _trade_key(row) in control_by_key
            ),
            "full_bbo_only_trades": len(control_only),
            "full_bbo_only_wins": sum(
                _number(row, "pnl_usd") > 0.0 for row in control_only
            ),
            "full_bbo_only_losses": sum(
                _number(row, "pnl_usd") <= 0.0 for row in control_only
            ),
            "full_bbo_only_pnl_usd": sum(
                _number(row, "pnl_usd") for row in control_only
            ),
            "warning": (
                "This is path-dependent: different fills and exit times alter "
                "which later signals are available. FULL_BBO-only trades are not "
                "all direct fill rejections."
            ),
        }

    output.mkdir(parents=True, exist_ok=True)
    with (output / "execution_trades.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(audit_rows[0]))
        writer.writeheader()
        writer.writerows(audit_rows)
    (output / "execution_summary.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    _write_markdown(result, output / "execution_audit.md")
    return result


def _write_markdown(result: dict[str, Any], path: Path) -> None:
    control = result.get("full_bbo_control", {})
    lines = [
        "# Config 34 SIZE_AWARE Execution Audit",
        "",
        "## Main Finding",
        "",
        (
            f"Config 34 reported **${result['reported_net_pnl_usd']:+.2f}**. "
            f"It valued {result['total_quantity_valued_at_zero']:g} residual "
            f"contracts at zero across {result['exits_where_zero_policy_applied']} "
            "exits. Relative to marking those residuals at the final observed "
            f"synthetic bid, the ZERO penalty was **${result['pnl_lost_to_zero_vs_final_observed_bid_usd']:.2f}**."
        ),
        "",
        "## Execution Funnel",
        "",
        f"- Signals generated: `{result['signals_generated']}`",
        f"- Signals with an option contract: `{result['signals_with_contract']}`",
        f"- Attempts reaching execution sizing: `{result['entry_attempts_reaching_execution']}`",
        f"- Accepted entries: `{result['accepted_entries']}`",
        f"- Fully filled accepted entries: `{result['fully_filled_entries']}`",
        f"- Partially filled accepted entries: `{result['partially_filled_entries']}`",
        f"- Rejected below 25% fill: `{result['entries_rejected_below_minimum_fill']}`",
        f"- Average requested quantity, accepted trades: `{result['average_requested_quantity_accepted']:.2f}`",
        f"- Average filled quantity, accepted trades: `{result['average_filled_quantity_accepted']:.2f}`",
        f"- Average entry fill, accepted trades: `{result['average_entry_fill_percent_accepted']:.2f}%`",
        f"- Full exits: `{result['full_exits']}`",
        f"- Partial exits with residual: `{result['partial_exits']}`",
        f"- Total residual quantity valued at zero: `{result['total_quantity_valued_at_zero']:g}`",
        f"- ZERO penalty versus final observed bid: `${result['pnl_lost_to_zero_vs_final_observed_bid_usd']:.2f}`",
        f"- Net if residuals were only marked at final bid: `${result['net_pnl_if_residual_marked_at_final_bid_usd']:+.2f}`",
        "",
        "## Rejections",
        "",
    ]
    lines.extend(
        f"- `{reason}`: `{count}`"
        for reason, count in sorted(result["all_rejections"].items())
    )
    if control:
        lines.extend([
            "",
            "## Config 33 FULL_BBO Control",
            "",
            f"- FULL_BBO trades: `{control['trades']}`",
            f"- FULL_BBO net P&L: `${control['net_pnl_usd']:+.2f}`",
            f"- Signals matching an accepted Config 34 trade: `{control['matched_trades']}`",
            f"- Matched FULL_BBO P&L: `${control['matched_full_bbo_pnl_usd']:+.2f}`",
            f"- Matched SIZE_AWARE P&L: `${control['matched_size_aware_pnl_usd']:+.2f}`",
            f"- FULL_BBO-only trades: `{control['full_bbo_only_trades']}`",
            f"- FULL_BBO-only wins/losses: `{control['full_bbo_only_wins']}/{control['full_bbo_only_losses']}`",
            f"- FULL_BBO-only P&L: `${control['full_bbo_only_pnl_usd']:+.2f}`",
            "",
            f"> {control['warning']}",
        ])
    lines.extend([
        "",
        "## Simulator Mechanics",
        "",
        "- Requested quantity: `floor(budget / (premium * contract_value), quantity increment)`.",
        "- Entry capacity per quote: `ask_size * participation_rate * capacity_multiplier`.",
        "- Exit capacity per quote: `bid_size * participation_rate * capacity_multiplier`.",
        "- Config 34 entry timeout: `10 seconds`; exit timeout: `300 seconds`; minimum entry fill: `25%`.",
        "- Public-history size formula: `bid_size = ask_size = max(1, one-minute option candle volume)`.",
        "- Implementation: `backtest/ema_vwap_research.py` functions `_capacity_fill_quantity`, `_entry_execution`, and `_exit_execution`.",
        "- Position sizing: `backtest.calculations.calculate_quantity`.",
        "- Synthetic-size construction: `backtest/providers/delta_india.py` in `sync_historical_dataset`.",
        "",
        "## Limits Of This Existing Run",
        "",
    ])
    lines.extend(f"- {item}" for item in result["limitations"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit SIZE_AWARE backtest execution")
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--control", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.run / "execution-audit"
    build_audit(args.run, output, args.control)
    print(f"Execution audit ready: {output.resolve()}")


if __name__ == "__main__":
    main()
