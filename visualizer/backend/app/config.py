from __future__ import annotations
import os
from pathlib import Path


def project_root() -> Path:
    configured = os.getenv("STRATEGY_LAB_PROJECT_ROOT") or os.getenv("BT_PROJECT_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    # <repo>/strategy-lab/backend/app/config.py
    return Path(__file__).resolve().parents[3]


def data_root() -> Path:
    configured = os.getenv("STRATEGY_LAB_DATA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()

    # V13 unified public-history archive. The archive owns catalog.json and
    # segments/*; legacy folders outside this root may remain as junctions but are
    # deliberately not rediscovered here, avoiding duplicate 29 GB histories.
    archive = project_root() / "backtest" / "data" / "delta-history"
    if archive.exists():
        return archive

    # Compatibility fallback for a repository that has not migrated yet. As soon
    # as delta-history exists it automatically becomes the preferred/default root.
    return project_root() / "backtest" / "data"


def result_root() -> Path:
    configured = os.getenv("STRATEGY_LAB_RESULT_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return project_root() / "strategy-lab" / "results"


def cache_root() -> Path:
    configured = os.getenv("STRATEGY_LAB_CACHE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return project_root() / "strategy-lab" / ".cache"
