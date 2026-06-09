"""YAML-driven advisor rules, merged over in-code defaults.

Mirrors ``suggest/quadrant_policy.py``: editing
``configs/option_advisor/advisor_rules.yaml`` retunes strategy enablement,
strike/DTE targets, filter thresholds, ranking weights, and regime gates
**without touching Python**.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:  # pragma: no cover - yaml is a project dependency
    import yaml
except Exception:  # pragma: no cover
    yaml = None

CONFIG_VERSION = "1"

DEFAULT_RULES: dict[str, Any] = {
    "version": CONFIG_VERSION,
    "strategies": {
        "covered_call": {"enabled": True, "target_delta": 0.30, "dte": 35, "min_round_lots": 1},
        "cash_secured_put": {"enabled": True, "target_delta": 0.27, "dte": 35},
        "protective_put": {"enabled": True, "target_delta": 0.15, "dte": 75, "hedge_weight_trigger": 0.08},
        "collar": {"enabled": True, "put_delta": 0.20, "call_delta": 0.25, "dte": 60},
        "zero_cost_collar": {"enabled": True, "protect_put_delta": 0.25, "floor_put_delta": 0.10, "dte": 60},
        "call_spread": {"enabled": True, "long_delta": 0.40, "short_delta": 0.20, "dte": 40},
        "put_spread": {"enabled": True, "long_delta": 0.40, "short_delta": 0.20, "dte": 40},
        "carry_short_call": {"enabled": True, "target_delta": 0.20, "dte": 35},
        "carry_short_put": {"enabled": True, "target_delta": 0.18, "dte": 35},
    },
    "filters": {
        "min_premium_over_costs": 1.5,   # net credit must clear (commission + half-spread) × this
        "commission_per_contract": 0.65,
        "max_notional_pct_aum": 0.05,    # sizing cap on FUNDED AUM (excludes opts/futures)
        "max_spread_pct": 0.15,          # hard reject above this worst-leg spread
        "thin_oi": 50,                   # soft flag below this min open interest
        "earnings_block_days": 7,        # soft flag if an event falls within DTE and status known
    },
    "ranking": {
        "weights": {
            "yield_or_efficiency": 0.40,
            "regime_align": 0.25,
            "liquidity_conf": 0.20,
            "event_penalty": 0.15,
        },
        "max_proceed": 8,                # top-N PROCEED; rest MONITOR/REJECT
    },
    "premium_screen": {
        # Rule-based VALUE screen for SELLING premium (INCOME). Research basis + sources:
        # docs/architecture/devplans/option_advisor.md "Premium value screen". The edge is
        # the variance risk premium (implied > realized vol); enter ~30-45 DTE (theta sweet
        # spot), manage ~21 DTE. Score blends annualized yield × IV/RV richness.
        "target_yield_annualized": 0.40,  # annualized credit/capital-at-risk that scores 1.0
        "vrp_ratio_span": 0.5,            # IV/RV − 1 of 0.5 (implied 50% over realized) → richness 1.0
        "min_vrp_ratio": 1.0,             # ≤1 = implied cheaper than realized = poor seller value
        "manage_dte": 21,                 # close ≈50% max profit / before gamma ramps
    },
    "regime_gates": {
        # Suppress upside-capping income when strongly risk-on (don't sell calls in a rip).
        "suppress_income_when": ["Goldilocks:High"],
        # Bias toward hedges in these regimes / on crisis flag.
        "hedge_bias_when": ["crisis_flag", "Deflationary Slowdown", "Stagflation"],
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def load_rules(path: str | Path | None = None) -> dict[str, Any]:
    """Return DEFAULT_RULES merged with an optional YAML override file."""
    if path is None:
        return {**DEFAULT_RULES}
    p = Path(path)
    if not p.exists():
        return {**DEFAULT_RULES}
    if yaml is None:  # pragma: no cover
        raise RuntimeError("PyYAML is required to read advisor_rules.yaml")
    payload = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("advisor_rules.yaml must be a mapping")
    return _deep_merge(DEFAULT_RULES, payload)
