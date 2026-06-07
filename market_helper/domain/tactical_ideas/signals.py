"""Rule-based tactical signal layer — grounds idea anchors on offline artifacts.

Reads the latest regime snapshot + the policy-expert predictor/trending (all
best-effort, offline, graceful) into a :class:`TacticalContext`, then derives a
handful of grounded :class:`TacticalIdea` anchors. Each idea cites its evidence
and its invalidation, is tagged with a ``data_mode`` (``regime`` vs
``regime+model``), and is **advisory only** (the adapter caps them at MONITOR).

No network in the standard path: ``predict_latest`` is called with
``allow_retrain=False`` (pure inference if the model artifact exists). All inputs
are injectable so tests stay hermetic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from market_helper.application.trade_advisor.regime_seed import (
    DEFAULT_REGIME_SNAPSHOT_PATH,
    current_regime_seed,
)

# Regime-quadrant → favored equity sectors (the rotation anchor).
_REGIME_SECTORS = {
    "Goldilocks": "tech / growth / consumer discretionary (XLK, XLY)",
    "Reflation": "energy / financials / materials (XLE, XLF, XLB)",
    "Stagflation": "energy / materials / defensives (XLE, XLB, XLP)",
    "Deflationary Slowdown": "defensives / staples / utilities + long duration (XLP, XLU)",
}


@dataclass(frozen=True)
class TacticalContext:
    """The offline signal snapshot the tactical anchors + the AI brief read from."""

    as_of: str = ""
    regime: str = ""
    confidence: str = ""
    crisis: bool = False
    growth_score: float | None = None
    inflation_score: float | None = None
    risk_score: float | None = None
    # Forward policy-expert tilt (predict_latest).
    expert_available: bool = False
    top_expert: str = ""
    expert_confidence: float = 0.0
    sleeve_weights: dict[str, float] = field(default_factory=dict)
    # Backward momentum (compute_trending).
    trend_available: bool = False
    trend_top: str = ""
    trend_probabilities: dict[str, float] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)  # which artifacts were available (honesty)


@dataclass(frozen=True)
class TacticalIdea:
    """One grounded, independent short-term trade idea (advisory)."""

    theme: str            # SHORT_USD | RISK_OFF | SHORT_VIX | TREND | STEEPENER | SECTOR_ROTATION | CM_RV | JPY
    title: str
    direction: str        # plain-English stance, e.g. "Short USD", "Reduce risk"
    thesis: str
    why_now: str
    evidence: list[str] = field(default_factory=list)
    invalidation: str = ""
    expression: str = ""  # suggested NON-binding instruments (futures / ETF options)
    confidence: str = "Medium"
    data_mode: str = "regime"

    def as_detail(self) -> dict[str, Any]:
        return {
            "theme": self.theme, "direction": self.direction, "thesis": self.thesis,
            "why_now": self.why_now, "evidence": list(self.evidence), "invalidation": self.invalidation,
            "expression": self.expression, "confidence": self.confidence,
        }


def _read_snapshot(path: Path) -> dict | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if isinstance(payload, list):
        snap = payload[-1] if payload else None
    else:
        snap = payload
    return snap if isinstance(snap, dict) else None


def _f(x: Any) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def build_tactical_context(
    *,
    regime_path: str | Path | None = None,
    prediction: Any = None,
    trending: Any = None,
) -> TacticalContext:
    """Assemble the offline tactical context. ``prediction`` / ``trending`` are
    injectable; when omitted they are loaded best-effort (offline, no retrain)."""
    sources: list[str] = []
    seed = current_regime_seed(regime_path)
    snap = _read_snapshot(Path(regime_path) if regime_path else DEFAULT_REGIME_SNAPSHOT_PATH) or {}
    if snap:
        sources.append("regime_snapshot")
    growth = _f(snap.get("final_growth_score"))
    inflation = _f(snap.get("final_inflation_score"))
    risk = _f(snap.get("risk_score"))

    if prediction is None:
        try:
            from market_helper.regimes.policy_expert_predictor import predict_latest
            prediction = predict_latest(allow_retrain=False)
        except Exception:  # noqa: BLE001 — predictor is best-effort context
            prediction = None
    expert_available = bool(getattr(prediction, "available", False))
    if expert_available:
        sources.append("policy_expert_predictor")

    if trending is None:
        try:
            from market_helper.regimes.policy_expert_trending import compute_trending
            trending = compute_trending()
        except Exception:  # noqa: BLE001 — trending is best-effort context
            trending = None
    trend_available = bool(getattr(trending, "available", False))
    if trend_available:
        sources.append("policy_expert_trending")
    probs = dict(getattr(trending, "probabilities", {}) or {}) if trend_available else {}
    trend_top = max(probs, key=probs.get) if probs else ""

    return TacticalContext(
        as_of=str(snap.get("as_of") or snap.get("run_date") or ""),
        regime=seed.regime,
        confidence=seed.confidence,
        crisis=seed.crisis,
        growth_score=growth,
        inflation_score=inflation,
        risk_score=risk,
        expert_available=expert_available,
        top_expert=str(getattr(prediction, "top_expert", "") or "") if expert_available else "",
        expert_confidence=float(getattr(prediction, "confidence", 0.0) or 0.0) if expert_available else 0.0,
        sleeve_weights=dict(getattr(prediction, "sleeve_weights", {}) or {}) if expert_available else {},
        trend_available=trend_available,
        trend_top=trend_top,
        trend_probabilities=probs,
        sources=sources,
    )


def _mode(ctx: TacticalContext) -> str:
    return "regime+model" if (ctx.expert_available or ctx.trend_available) else "regime"


def generate_tactical_ideas(ctx: TacticalContext) -> list[TacticalIdea]:
    """Derive grounded tactical idea anchors from the context. Conditional on the
    signals present — an idea only fires when the data supports it, and cites it."""
    ideas: list[TacticalIdea] = []
    mode = _mode(ctx)
    infl_up = (ctx.inflation_score or 0.0) > 0.05
    growth_up = (ctx.growth_score or 0.0) > 0.05
    reflationary = ctx.regime in ("Reflation", "Stagflation") or infl_up

    # 1) Risk-off / vol — when the stress overlay is on or the risk score is elevated.
    if ctx.crisis or (ctx.risk_score or 0.0) >= 0.65:
        ideas.append(TacticalIdea(
            theme="RISK_OFF", title="Risk-off: trim beta / add a vol hedge", direction="Reduce risk",
            thesis="Regime stress is active — cut gross equity beta and/or buy convexity until it clears.",
            why_now=f"Risk overlay {'on' if ctx.crisis else 'elevated'} (risk_score={ctx.risk_score}).",
            evidence=[f"regime={ctx.regime or '?'}", f"crisis={ctx.crisis}", f"risk_score={ctx.risk_score}"],
            invalidation="Risk overlay turns off / risk_score falls back below the enter threshold.",
            expression="Long vol (VIX calls / SPY put-spread) or reduce gross; not a base-position overlay.",
            confidence="High" if ctx.crisis else "Medium", data_mode=mode,
        ))
    else:
        # 3b) Short-VIX carry — only when calm AND stress is clearly receding (not mid-spike).
        if (ctx.risk_score or 1.0) <= 0.35:
            ideas.append(TacticalIdea(
                theme="SHORT_VIX", title="Short-VIX carry (calm tape)", direction="Short volatility",
                thesis="With the overlay off and risk low, harvest the vol-risk premium — sized small.",
                why_now=f"No risk overlay; risk_score={ctx.risk_score} (low).",
                evidence=[f"crisis={ctx.crisis}", f"risk_score={ctx.risk_score}"],
                invalidation="Any overlay re-trigger or a VIX spike — short-vol is the first casualty.",
                expression="Short-vol carry (e.g. VIX call-spread sale / SPX put-spread); enter at extremes only.",
                confidence="Low", data_mode=mode,
            ))

    # 2) Short USD / de-dollarization — reflationary regime and/or a reflation/stagflation expert.
    if reflationary or ctx.top_expert in ("Reflation", "Stagflation"):
        ev = [f"regime={ctx.regime or '?'}", f"inflation_score={ctx.inflation_score}"]
        if ctx.top_expert:
            ev.append(f"top_expert={ctx.top_expert}")
        ideas.append(TacticalIdea(
            theme="SHORT_USD", title="Short USD / de-dollarization", direction="Short USD",
            thesis="Sticky inflation + reserve diversification pressure the dollar; favor non-USD + gold.",
            why_now="Reflationary regime / reflation-stagflation expert tilt.",
            evidence=ev,
            invalidation="Growth re-accelerates with a hawkish Fed → USD bid; or a global risk-off USD squeeze.",
            expression="Long EUR/JPY futures (6E/6J) vs USD, or long gold (GLD); independent macro trade.",
            confidence="Medium", data_mode=mode,
        ))

    # 4) Curve steepener — reflation/expansion (not the deflationary bull-flattener).
    if reflationary and ctx.regime != "Deflationary Slowdown":
        ideas.append(TacticalIdea(
            theme="STEEPENER", title="Bond-curve steepener (futures)", direction="Steepener",
            thesis="Rising inflation / recovering growth steepens the curve (long-end cheapens or easing front-loads).",
            why_now=f"inflation_score={ctx.inflation_score}, regime={ctx.regime or '?'}.",
            evidence=[f"regime={ctx.regime or '?'}", f"inflation_score={ctx.inflation_score}", f"growth_score={ctx.growth_score}"],
            invalidation="Growth scare / curve inversion deepens (recession bull-flattening).",
            expression="US 2s10s steepener via futures (long ZT vs short ZN, duration-weighted); AU/EU analogues.",
            confidence="Medium", data_mode=mode,
        ))

    # 5) Commodity curve / RV — commodity-friendly regime and/or elevated CM sleeve.
    cm_sleeve = float(ctx.sleeve_weights.get("CM", 0.0) or 0.0)
    if reflationary or cm_sleeve >= 15.0:
        ideas.append(TacticalIdea(
            theme="CM_RV", title="Commodity curve / relative-value", direction="Long commodity RV",
            thesis="Commodity-supportive regime → outright/curve RV (e.g. oil product premium, soyoil share).",
            why_now=f"regime={ctx.regime or '?'}; policy-expert CM sleeve={cm_sleeve:g}%.",
            evidence=[f"regime={ctx.regime or '?'}", f"CM_sleeve={cm_sleeve:g}%"],
            invalidation="Demand shock / growth roll-over compresses the curve.",
            expression="CM futures curve RV / outright (crack spread, soyoil share); not via the base book.",
            confidence="Medium", data_mode=mode,
        ))

    # 6) Sector rotation — always available (regime-keyed), Medium confidence.
    favored = _REGIME_SECTORS.get(ctx.regime)
    if favored:
        ideas.append(TacticalIdea(
            theme="SECTOR_ROTATION", title=f"Sector rotation · {ctx.regime}", direction="Rotate sectors",
            thesis=f"Rotate toward the {ctx.regime}-favored sectors and fund from the laggards.",
            why_now=f"regime={ctx.regime}.",
            evidence=[f"regime={ctx.regime}", f"favored={favored}"],
            invalidation="Regime shift flips the sector leadership.",
            expression=f"Long {favored} vs short SPY (relative), or sector-ETF options as independent expressions.",
            confidence="Medium", data_mode=mode,
        ))

    # 7) Trend persistence / add exposure — risk-on + concentrated forward/trend conviction.
    if growth_up and not ctx.crisis and (ctx.expert_confidence >= 0.30 or (ctx.trend_probabilities.get(ctx.trend_top, 0.0) >= 0.30)):
        lead = ctx.top_expert or ctx.trend_top or "the leading regime"
        ideas.append(TacticalIdea(
            theme="TREND", title="Trend persistence — add trading exposure", direction="Add risk / stay invested",
            thesis="Risk-on with concentrated forward + momentum conviction — extend exposure / time in market.",
            why_now=f"growth_score={ctx.growth_score}; lead={lead} (expert_conf={ctx.expert_confidence:.0%}).",
            evidence=[f"growth_score={ctx.growth_score}", f"top_expert={ctx.top_expert}", f"trend_top={ctx.trend_top}"],
            invalidation="Risk overlay flips on, or the forward/trend leadership rolls over.",
            expression="Increase trading-sleeve exposure / index futures; trim hedges. Sized within risk limits.",
            confidence="Medium", data_mode=mode,
        ))

    return ideas
