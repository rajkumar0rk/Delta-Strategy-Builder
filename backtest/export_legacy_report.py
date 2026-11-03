"""Offline file-oriented H6 report export with opt-in memory fallback.

STREAMED with PACKED_MEMORY quotes is the default for this command only; the
existing run_dataset() Python return contract and research CLI are unchanged.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def export_legacy_report(
    directory: Path, *, start: str, end: str, output: Path,
    storage: str = "STREAMED", spool_directory: Path | None = None,
    quote_storage: str | None = None,
) -> dict[str, Any]:
    from .ema_vwap_research import (
        locked_h6_scenarios, run_dataset,
        run_dataset_to_streamed_report, write_report,
    )

    if storage not in {"STREAMED", "MEMORY"}:
        raise ValueError("storage must be STREAMED or MEMORY")
    if quote_storage is None:
        quote_storage = "PACKED_MEMORY" if storage == "STREAMED" else "MEMORY"
    if quote_storage not in {"MEMORY", "PACKED_MEMORY"}:
        raise ValueError("quote_storage must be MEMORY or PACKED_MEMORY")
    if storage == "MEMORY" and spool_directory is not None:
        raise ValueError("spool_directory requires STREAMED storage")
    if storage == "MEMORY" and quote_storage != "MEMORY":
        raise ValueError("PACKED_MEMORY quote storage requires STREAMED report storage")
    directory = Path(directory)
    output = Path(output)
    if storage == "STREAMED":
        result = run_dataset_to_streamed_report(
            directory, start=start, end=end,
            scenario_set=locked_h6_scenarios(),
            output=output / "summary.json",
            spool_directory=spool_directory,
            csv_directory=output,
            quote_capture_storage=quote_storage,
        )
        return {
            "storage": storage, "quote_storage": quote_storage,
            "summary_json": result["report_path"],
            "csv_paths": result["csv_paths"], "counts": result["counts"],
        }
    report = run_dataset(
        directory, start=start, end=end,
        scenario_set=locked_h6_scenarios(),
    )
    write_report(report, output)
    return {
        "storage": storage, "quote_storage": quote_storage,
        "summary_json": str(output / "summary.json"),
        "csv_paths": {
            name: str(output / f"{name}.csv")
            for name in ("trades", "execution_attempts", "decision_events")
            if report.get(name)
        },
        "counts": {
            name: len(report[name])
            for name in ("trades", "execution_attempts", "decision_events")
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write complete locked-H6 legacy report and CSVs without retaining aggregate report rows"
    )
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--storage", choices=["STREAMED", "MEMORY"], default="STREAMED",
        help="Report output storage; applies only to this export command",
    )
    parser.add_argument("--spool-directory", type=Path)
    parser.add_argument(
        "--quote-storage", choices=["MEMORY", "PACKED_MEMORY"],
        help=("Defaults to PACKED_MEMORY for STREAMED reports and MEMORY "
              "for MEMORY reports; --quote-storage MEMORY restores the "
              "original quote dictionaries for STREAMED exports"),
    )
    args = parser.parse_args()
    result = export_legacy_report(
        args.directory, start=args.start, end=args.end,
        output=args.output, storage=args.storage,
        spool_directory=args.spool_directory,
        quote_storage=args.quote_storage,
    )
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
