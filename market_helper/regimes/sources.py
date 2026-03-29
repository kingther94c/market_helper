from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from market_helper.utils.io import read_json


@dataclass(frozen=True)
class RegimeInputBundle:
    """Normalized aligned inputs for regime detection."""

    dates: list[str]
    vix: list[float]
    move: list[float]
    hy_oas: list[float]
    y2: list[float]
    y10: list[float]
    eq_returns: list[float]
    fi_returns: list[float]
    source_info: dict[str, str]


_REQUIRED_PROXY_KEYS = ("VIX", "MOVE", "HY_OAS", "UST2Y", "UST10Y")
_REQUIRED_RETURN_KEYS = ("EQ", "FI")


def load_regime_inputs(
    *,
    proxy_path: str | Path,
    returns_path: str | Path,
) -> RegimeInputBundle:
    """Load aligned regime inputs from local JSON proxy and returns files."""
    proxy = _load_json(proxy_path)
    returns = _load_json(returns_path)

    proxy_series = {key: _coerce_dated_series(proxy, key) for key in _REQUIRED_PROXY_KEYS}
    return_series = {key: _coerce_dated_series(returns, key) for key in _REQUIRED_RETURN_KEYS}

    dates = sorted(
        set(proxy_series["VIX"]).intersection(
            proxy_series["MOVE"],
            proxy_series["HY_OAS"],
            proxy_series["UST2Y"],
            proxy_series["UST10Y"],
            return_series["EQ"],
            return_series["FI"],
        )
    )
    if not dates:
        raise ValueError("No overlapping dates found across required proxy/return inputs")

    return RegimeInputBundle(
        dates=dates,
        vix=[proxy_series["VIX"][date] for date in dates],
        move=[proxy_series["MOVE"][date] for date in dates],
        hy_oas=[proxy_series["HY_OAS"][date] for date in dates],
        y2=[proxy_series["UST2Y"][date] for date in dates],
        y10=[proxy_series["UST10Y"][date] for date in dates],
        eq_returns=[return_series["EQ"][date] for date in dates],
        fi_returns=[return_series["FI"][date] for date in dates],
        source_info={
            "proxy_path": str(proxy_path),
            "returns_path": str(returns_path),
        },
    )


def _load_json(path: str | Path) -> Any:
    return read_json(path)


def _coerce_dated_series(payload: Any, key: str) -> dict[str, float]:
    if not isinstance(payload, dict):
        raise ValueError("Input JSON must be a dictionary payload")
    raw = payload.get(key)
    if raw is None:
        lowered = {str(k).lower(): v for k, v in payload.items()}
        raw = lowered.get(key.lower())
    if raw is None:
        raise ValueError(f"Missing required series key: {key}")

    if isinstance(raw, dict):
        return {str(k): float(v) for k, v in raw.items()}

    if isinstance(raw, list):
        if not raw:
            return {}
        if isinstance(raw[0], dict):
            out: dict[str, float] = {}
            for idx, row in enumerate(raw):
                if not isinstance(row, dict):
                    continue
                as_of = row.get("as_of") or row.get("date") or row.get("timestamp") or f"idx-{idx:05d}"
                value = row.get("value")
                if value is None:
                    continue
                out[str(as_of)] = float(value)
            return out
        return {f"idx-{idx:05d}": float(value) for idx, value in enumerate(raw)}

    raise ValueError(f"Unsupported series format for key: {key}")
