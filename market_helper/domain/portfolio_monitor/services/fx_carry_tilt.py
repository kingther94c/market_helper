"""FX Carry tilt overlay on top of the SGD-hedge FX-futures allocation.

The :mod:`fx_hedge_advisor` engine produces the *variance-minimising* hedge: a
target notional per CME FX future (betas vs USD/SGD). This module layers a
**bounded carry tilt** on that baseline — overweight the higher-carry legs,
underweight the lower/negative-carry ones — and reports the **before/after**
exposure and carry so the operator can see exactly what the tilt buys (extra
carry) and costs (deviation from the hedge-optimal allocation = basis risk).

Pure + offline: it operates on an already-computed
:class:`~.fx_hedge_advisor.FxHedgeAllocation`; no network, no Yahoo, no rate
feed. Carry is **rate-approximated** from the configured overnight-rate
differential ``on_rate_i - on_rate_usd`` (the same number the hedge engine
already attributes). A genuine *futures-implied* carry would need a CME forward
curve, which is not in-repo — :attr:`FxCarryTiltResult.method` records which was
used so the UI never dresses the approximation up as the real thing.

Read-only / advisory: this emits a *suggested* tilt and its economics; it never
places, sizes-to-execute, or persists anything.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

CARRY_METHOD_RATE_DIFF = "rate_differential"  # on_rate_i - on_rate_usd (no forward curve in-repo)

# Engine guardrails (the UI slider maps into [0, 1] of MAX_DEVIATION).
DEFAULT_TILT_STRENGTH = 0.5
MAX_PER_LEG_DEVIATION = 0.25  # a tilt never moves a leg more than ±25% off its hedge target


def _round_half_away(x: float) -> int:
    """Round to the nearest integer, halves away from zero (matches the hedge engine)."""
    if not math.isfinite(x):
        return 0
    return int(x + math.copysign(0.5, x))


def _derive_on_rate_usd(legs: list[Any]) -> float:
    """Recover the USD overnight rate from any leg: on_rate - carry/realized_notional."""
    for leg in legs:
        realized = float(getattr(leg, "realized_notional_usd", 0.0) or 0.0)
        if realized:
            carry = float(getattr(leg, "expected_annual_carry_usd", 0.0) or 0.0)
            return float(getattr(leg, "on_rate", 0.0) or 0.0) - carry / realized
    return 0.0


@dataclass(frozen=True)
class FxCarryTiltResult:
    """A bounded carry tilt + its before/after economics (all USD, annualized)."""

    method: str
    tilt_strength: float
    max_deviation: float
    on_rate_usd: float
    rows: list[dict[str, Any]] = field(default_factory=list)
    before: dict[str, float] = field(default_factory=dict)
    after: dict[str, float] = field(default_factory=dict)
    carry_impact_usd: float = 0.0
    carry_impact_bps: float = 0.0
    hedge_deviation_pct: float = 0.0
    note: str = ""

    def as_detail(self) -> dict[str, Any]:
        """JSON-serializable payload for a ``Suggestion.detail`` (body_kind=fx_carry)."""
        return {
            "method": self.method,
            "tilt_strength": round(self.tilt_strength, 3),
            "max_deviation": round(self.max_deviation, 3),
            "on_rate_usd": round(self.on_rate_usd, 5),
            "rows": self.rows,
            "before": self.before,
            "after": self.after,
            "carry_impact_usd": round(self.carry_impact_usd, 0),
            "carry_impact_bps": round(self.carry_impact_bps, 1),
            "hedge_deviation_pct": round(self.hedge_deviation_pct, 4),
            "note": self.note,
        }


def compute_fx_carry_tilt(
    allocation: Any,
    *,
    tilt_strength: float = DEFAULT_TILT_STRENGTH,
    max_deviation: float = MAX_PER_LEG_DEVIATION,
) -> FxCarryTiltResult | None:
    """Bounded carry tilt over a hedge allocation's legs. ``None`` if there are no legs.

    ``tilt_strength`` ∈ [0, 1] is the UI knob; the effective per-leg cap is
    ``λ = tilt_strength · max_deviation``. Each leg's hedge-target notional is
    scaled by ``1 + λ·w`` where ``w ∈ [-1, 1]`` ranks the leg's carry rate against
    the cross-leg mean — so a high-carry leg is overweighted, a low-carry leg
    underweighted, and the deviation is bounded by construction. Contracts are
    re-rounded (halves away from zero); carry is recomputed on the *rounded*
    realized notional so the after-figures match a tradeable book.
    """
    legs = list(getattr(allocation, "legs", []) or [])
    if not legs:
        return None

    tilt_strength = max(0.0, min(1.0, float(tilt_strength)))
    max_deviation = max(0.0, float(max_deviation))
    lam = tilt_strength * max_deviation

    hedge_notional = float(getattr(allocation, "hedge_notional_usd", 0.0) or 0.0)
    on_rate_usd = _derive_on_rate_usd(legs)

    # Per-leg carry rate (per unit long notional) and the centered tilt weight.
    carry_rates = [float(getattr(leg, "on_rate", 0.0) or 0.0) - on_rate_usd for leg in legs]
    mean_cr = sum(carry_rates) / len(carry_rates)
    devs = [cr - mean_cr for cr in carry_rates]
    denom = max((abs(d) for d in devs), default=0.0)

    rows: list[dict[str, Any]] = []
    base_gross = base_net = base_carry = 0.0
    tilt_gross = tilt_net = tilt_carry = 0.0
    abs_notional_shift = 0.0

    for leg, cr, dev in zip(legs, carry_rates, devs):
        base_realized = float(getattr(leg, "realized_notional_usd", 0.0) or 0.0)
        usd_per_contract = float(getattr(leg, "usd_notional_per_contract", 0.0) or 0.0)
        base_contracts = int(getattr(leg, "target_contracts", 0) or 0)
        base_carry_leg = float(getattr(leg, "expected_annual_carry_usd", 0.0) or 0.0)
        target_notional = float(getattr(leg, "target_notional_usd", 0.0) or 0.0)

        weight = (dev / denom) if denom else 0.0          # w ∈ [-1, 1]
        factor = 1.0 + lam * weight                        # bounded multiplicative tilt
        tilted_notional = target_notional * factor
        tilted_contracts = (
            _round_half_away(tilted_notional / usd_per_contract) if usd_per_contract else base_contracts
        )
        tilted_realized = tilted_contracts * usd_per_contract
        # Keep the engine's authoritative base carry; the tilt adds only the *marginal*
        # carry from the change in realized notional (so a zero tilt is an exact no-op).
        tilted_carry_leg = base_carry_leg + (tilted_realized - base_realized) * cr

        base_gross += abs(base_realized)
        base_net += base_realized
        base_carry += base_carry_leg
        tilt_gross += abs(tilted_realized)
        tilt_net += tilted_realized
        tilt_carry += tilted_carry_leg
        abs_notional_shift += abs(tilted_realized - base_realized)

        rows.append(
            {
                "currency": getattr(leg, "currency", ""),
                "instrument": getattr(leg, "instrument", ""),
                "carry_rate_pct": round(cr * 100.0, 3),
                "carry_bps": round((10_000.0 * base_carry_leg / base_realized) if base_realized else 0.0, 1),
                "base_contracts": base_contracts,
                "tilted_contracts": tilted_contracts,
                "delta_contracts": tilted_contracts - base_contracts,
                "base_notional_usd": round(base_realized, 0),
                "tilted_notional_usd": round(tilted_realized, 0),
                "delta_notional_usd": round(tilted_realized - base_realized, 0),
                "base_carry_usd": round(base_carry_leg, 0),
                "tilted_carry_usd": round(tilted_carry_leg, 0),
            }
        )

    before = {
        "gross_notional_usd": round(base_gross, 0),
        "net_notional_usd": round(base_net, 0),
        "annual_carry_usd": round(base_carry, 0),
        "carry_bps": round(10_000.0 * base_carry / hedge_notional, 1) if hedge_notional else 0.0,
    }
    after = {
        "gross_notional_usd": round(tilt_gross, 0),
        "net_notional_usd": round(tilt_net, 0),
        "annual_carry_usd": round(tilt_carry, 0),
        "carry_bps": round(10_000.0 * tilt_carry / hedge_notional, 1) if hedge_notional else 0.0,
    }
    hedge_dev = (abs_notional_shift / base_gross) if base_gross else 0.0
    note = (
        "Carry is rate-approximated from configured overnight-rate differentials "
        "(no CME forward curve in-repo). The tilt deviates "
        f"{hedge_dev:.0%} (gross) from the hedge-optimal allocation — that deviation is "
        "added basis/tracking risk, the price of the extra carry. Advisory only."
    )
    return FxCarryTiltResult(
        method=CARRY_METHOD_RATE_DIFF,
        tilt_strength=tilt_strength,
        max_deviation=max_deviation,
        on_rate_usd=on_rate_usd,
        rows=rows,
        before=before,
        after=after,
        carry_impact_usd=tilt_carry - base_carry,
        carry_impact_bps=after["carry_bps"] - before["carry_bps"],
        hedge_deviation_pct=hedge_dev,
        note=note,
    )
