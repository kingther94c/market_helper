"""Currency lookthrough — per-currency exposure by looking equities *through* to their
underlying countries (the existing country lookthrough), then mapping country → currency.

This is the **deeper** FX exposure: a USD-listed ex-US fund (VEA, IEMG) no longer counts
as USD — it's split into JPY / EUR / AUD / CNY / … by the countries it actually holds.
Shared by the Portfolio Monitor risk report (a currency breakdown) and the Trade Advisor
FX Hedge panel (current FX exposure), so both speak the same currency definitions.

Reuses ``country_lookthrough_manual.csv`` (symbol → country buckets, maintained by the
lookthrough-researcher) + ``eq_country_lookthrough.csv`` (the aggregate→leaf taxonomy).
The country-bucket → currency map is **bucket-level** and therefore coarse by design:
``DM-EUME`` folds GBP/CHF/SEK into EUR, and mixed regional buckets (ASEAN/LATAM/EMEA/
Other-DM) map to ``Other``. Documented, not fabricated.
"""

from __future__ import annotations

import csv
from pathlib import Path

from market_helper.app.paths import CONFIGS_DIR

_PM_CONFIGS = CONFIGS_DIR / "portfolio_monitor"
DEFAULT_COUNTRY_MANUAL = _PM_CONFIGS / "country_lookthrough_manual.csv"
DEFAULT_COUNTRY_TAXONOMY = _PM_CONFIGS / "eq_country_lookthrough.csv"

# Leaf country bucket → representative currency. Single-country leaves are exact; mixed
# regional buckets fold to their dominant currency or "Other" (see module docstring).
COUNTRY_BUCKET_TO_CURRENCY: dict[str, str] = {
    "DM-US": "USD",
    "DM-EUME": "EUR",       # Eurozone-dominant; folds GBP/CHF/SEK/ILS
    "DM-JP": "JPY",
    "DM-CA": "CAD",
    "DM-AUNZ": "AUD",       # folds NZD
    "DM-Other DM": "Other",
    "EM-CN": "CNY",         # offshore CNH for hedging
    "EM-TW": "TWD",
    "EM-IN": "INR",
    "EM-KR": "KRW",
    "EM-ASEAN": "Other",
    "EM-LATAM": "Other",
    "EM-EMEA EM": "Other",
}
_LEAF_BUCKETS = frozenset(COUNTRY_BUCKET_TO_CURRENCY)


def bucket_currency(bucket: str) -> str:
    """Map a country bucket to its representative currency ("Other" if unmapped)."""
    return COUNTRY_BUCKET_TO_CURRENCY.get((bucket or "").strip(), "Other")


def _load_weight_table(path: Path, key_col: str, bucket_col: str) -> dict[str, list[tuple[str, float]]]:
    """symbol/eq_country → list[(bucket, weight)] from a lookthrough CSV. Empty on any error."""
    out: dict[str, list[tuple[str, float]]] = {}
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                key = (row.get(key_col) or "").strip().upper()
                bucket = (row.get(bucket_col) or "").strip()
                try:
                    weight = float(row.get("weight") or 0.0)
                except (TypeError, ValueError):
                    continue
                if key and bucket and weight > 0:
                    out.setdefault(key, []).append((bucket, weight))
    except (OSError, csv.Error):
        return {}
    return out


def load_country_manual(path=None) -> dict[str, list[tuple[str, float]]]:
    return _load_weight_table(Path(path) if path else DEFAULT_COUNTRY_MANUAL, "symbol", "country_bucket")


def load_country_taxonomy(path=None) -> dict[str, list[tuple[str, float]]]:
    return _load_weight_table(Path(path) if path else DEFAULT_COUNTRY_TAXONOMY, "eq_country", "country_bucket")


def expand_to_leaves(
    bucket_weights: list[tuple[str, float]],
    taxonomy: dict[str, list[tuple[str, float]]],
    *,
    _depth: int = 0,
) -> list[tuple[str, float]]:
    """Recursively expand aggregate buckets (ACWI/DM/EM) to leaf buckets via the taxonomy."""
    if _depth > 6:
        return list(bucket_weights)
    out: list[tuple[str, float]] = []
    for bucket, weight in bucket_weights:
        if bucket in _LEAF_BUCKETS or bucket not in taxonomy:
            out.append((bucket, weight))
        else:
            for child, child_w in taxonomy[bucket]:
                out.extend(expand_to_leaves([(child, weight * child_w)], taxonomy, _depth=_depth + 1))
    return out


def symbol_currency_weights(
    symbol: str,
    *,
    manual: dict | None = None,
    taxonomy: dict | None = None,
) -> list[tuple[str, float]]:
    """Per-currency weights for one equity symbol via the country lookthrough.

    Returns ``[(currency, weight), …]`` sorted desc, or ``[]`` when the symbol isn't in
    the country lookthrough (the caller then falls back to the listing currency).
    """
    manual = manual if manual is not None else load_country_manual()
    taxonomy = taxonomy if taxonomy is not None else load_country_taxonomy()
    rows = manual.get((symbol or "").strip().upper())
    if not rows:
        return []
    by_ccy: dict[str, float] = {}
    for bucket, weight in expand_to_leaves(rows, taxonomy):
        ccy = bucket_currency(bucket)
        by_ccy[ccy] = by_ccy.get(ccy, 0.0) + weight
    return sorted(by_ccy.items(), key=lambda kv: kv[1], reverse=True)


def country_exposure_to_currency(country_exposure: dict[str, float]) -> list[tuple[str, float]]:
    """Aggregate a leaf country-bucket → USD exposure map into currency → USD (sorted desc).

    For the monitor: it already computes a leaf-level country breakdown, so this just
    re-buckets that by currency.
    """
    by_ccy: dict[str, float] = {}
    for bucket, usd in country_exposure.items():
        by_ccy[bucket_currency(bucket)] = by_ccy.get(bucket_currency(bucket), 0.0) + usd
    return sorted(by_ccy.items(), key=lambda kv: kv[1], reverse=True)
