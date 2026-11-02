"""Offline file-oriented H6 report export with opt-in memory fallback.

STREAMED is the default for this new file-export command only; the
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
) -> dict[str, Any]:
    from .ema_vwap_research import (
        locked_h6_scenarios, run_dataset,
        run_dataset_to_streamed_report, write_report,
    )

    if storage not in {"STREAMED", "MEMORY"}:
        raise ValueError("storage must be STREAMED or MEMORY")
    if storage == "MEMORY" and spool_directory is not None:
        raise ValueError("spool_directory requires STREAMED storage")
    directory = Path(directory)
    output = Path(output)
    if storage == "STREAMED":
        result = run_dataset_to_streamed_report(
            directory, start=start, end=end,
            scenario_set=locked_h6_scenarios(),
            output=output / "summary.json",
            spool_directory=spool_directory,
            csv_directory=output,
        )
        return {
            "storage": storage, "summary_json": result["report_path"],
            "csv_paths": result["csv_paths"], "counts": result["counts"],
        }
    report = run_dataset(
        directory, start=start, end=end,
        scenario_set=locked_h6_scenarios(),
    )
    write_report(report, output)
    return {
        "storage": storage,
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
    args = parser.parse_args()
    result = export_legacy_report(
        args.directory, start=args.start, end=args.end,
        output=args.output, storage=args.storage,
        spool_directory=args.spool_directory,
    )
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
