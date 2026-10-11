"""BTC EMA/VWAP/RSI research tools.

The repository contains a self-contained session-study package in this
directory and the main matrix engine in the sibling ``ema_vwap_research.py``
file.  Python resolves the package before the sibling module, so re-export the
matrix engine here to keep existing ``backtest.ema_vwap_research`` imports
unambiguous.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_ENGINE_NAME = "backtest._ema_vwap_matrix_engine"
_ENGINE_PATH = Path(__file__).resolve().parent.parent / "ema_vwap_research.py"

_engine = sys.modules.get(_ENGINE_NAME)
if _engine is None:
    _spec = importlib.util.spec_from_file_location(_ENGINE_NAME, _ENGINE_PATH)
    if _spec is None or _spec.loader is None:
        raise ImportError(f"Could not load EMA/VWAP matrix engine from {_ENGINE_PATH}")
    _engine = importlib.util.module_from_spec(_spec)
    sys.modules[_ENGINE_NAME] = _engine
    _spec.loader.exec_module(_engine)

for _name, _value in vars(_engine).items():
    if not _name.startswith("__"):
        globals()[_name] = _value

__all__ = sorted(name for name in vars(_engine) if not name.startswith("_"))
