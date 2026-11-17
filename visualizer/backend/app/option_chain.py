"""Historical strike-reference metadata from Delta's full cached product listings.

Normalized option_instruments.csv only contains downloaded contracts that also
yielded usable candle quotes. It must never be treated as the complete exchange
strike list when choosing ATM/ITM/OTM contracts.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd


COLUMNS = ("strike", "option_type", "activation", "expiration")


def load_strike_reference(parts: list, normalized: pd.DataFrame) -> pd.DataFrame:
    """Combine normalized history with Delta cached *full* product listings.

    Raw product listings are metadata-only. This function does not fabricate
    executable instrument records, quotes or fills. The caller must continue
    to select from normalized contracts with actual historical quote rows.
    """
    rows: list[dict] = []
    for part in parts:
        directory = Path(part.root) / "raw" / "products"
        if not directory.is_dir():
            continue
        for file in sorted(directory.glob("BTC-*.json")):
            try:
                payload = json.loads(file.read_text(encoding="utf-8"))
                products = payload.get("products")
            except (OSError, ValueError, TypeError, AttributeError):
                continue
            if not isinstance(products, list):
                continue
            for product in products:
                if not isinstance(product, dict):
                    continue
                kind = {"call_options": "CE", "put_options": "PE"}.get(product.get("contract_type"))
                if kind is None:
                    continue
                underlying = product.get("underlying_asset") or {}
                if isinstance(underlying, dict) and underlying.get("symbol") not in (None, "BTC"):
                    continue
                try:
                    strike = float(product["strike_price"])
                    activation = pd.to_datetime(product.get("launch_time") or product.get("created_at"), utc=True, errors="coerce")
                    expiration = pd.to_datetime(product["settlement_time"], utc=True, errors="coerce")
                except (KeyError, ValueError, TypeError):
                    continue
                if not math.isfinite(strike) or strike <= 0 or pd.isna(activation) or pd.isna(expiration):
                    continue
                if activation >= expiration:
                    continue
                rows.append(dict(strike=strike, option_type=kind, activation=activation, expiration=expiration))

    if not rows:
        return normalized

    reference = pd.concat(
        [normalized.loc[:, list(COLUMNS)], pd.DataFrame(rows, columns=COLUMNS)],
        ignore_index=True,
    )
    return reference.drop_duplicates(subset=list(COLUMNS), keep="first")
