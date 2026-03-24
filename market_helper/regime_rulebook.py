from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Tuple


@dataclass
class ScoreResult:
    score: float
    details: Dict[str, float]


def _normalized_weighted_score(signals: Mapping[str, Tuple[float, float]], threshold: float = 0.0) -> ScoreResult:
    """Return weighted directional score in [-1, 1].

    signals: {name: (value, weight)}
    value > threshold -> +1, < -threshold -> -1, else 0.
    """
    if not signals:
        return ScoreResult(0.0, {})

    signed = {}
    total_weight = 0.0
    weighted_sum = 0.0

    for name, (value, weight) in signals.items():
        direction = 1.0 if value > threshold else (-1.0 if value < -threshold else 0.0)
        signed[name] = direction
        weighted_sum += direction * weight
        total_weight += weight

    if total_weight == 0:
        return ScoreResult(0.0, signed)

    return ScoreResult(weighted_sum / total_weight, signed)


def score_macro(macro: Mapping[str, float]) -> Dict[str, ScoreResult]:
    """Score macro growth and inflation from explicit rulebook inputs."""
    growth_inputs = {
        "gdp_nowcast_delta": (macro.get("gdp_nowcast_delta", 0.0), 1.0),
        "payrolls_3m_avg_delta": (macro.get("payrolls_3m_avg_delta", 0.0), 1.0),
        "unemployment_rate_delta_inverted": (-macro.get("unemployment_rate_delta", 0.0), 1.0),
        "ism_mfg_minus_50": (macro.get("ism_mfg_level", 50.0) - 50.0, 1.0),
    }

    inflation_inputs = {
        "cpi_yoy_minus_target": (macro.get("cpi_yoy_minus_target", 0.0), 1.0),
        "core_cpi_3m_annualized_delta": (macro.get("core_cpi_3m_annualized_delta", 0.0), 1.0),
        "wage_growth_3m_delta": (macro.get("wage_growth_3m_delta", 0.0), 1.0),
        "5y5y_infl_exp_delta": (macro.get("5y5y_infl_exp_delta", 0.0), 1.0),
    }

    return {
        "growth": _normalized_weighted_score(growth_inputs),
        "inflation": _normalized_weighted_score(inflation_inputs),
    }


def score_market(one_week_moves: Mapping[str, float]) -> Dict[str, ScoreResult]:
    """Score market-implied growth/inflation/risk from 1W returns and relative returns."""
    growth_inputs = {
        "spy": (one_week_moves.get("SPY", 0.0), 1.0),
        "small_vs_large": (one_week_moves.get("IWM_vs_SPY", 0.0), 1.0),
        "em_vs_dm": (one_week_moves.get("VWO_vs_VEA", 0.0), 0.75),
        "cyclical_vs_defensive": (one_week_moves.get("XLY_vs_XLP", 0.0), 0.75),
        "copper": (one_week_moves.get("COPX", 0.0), 0.75),
    }

    inflation_inputs = {
        "oil": (one_week_moves.get("USO", 0.0), 1.0),
        "copper": (one_week_moves.get("COPX", 0.0), 0.75),
        "tip_vs_ief": (one_week_moves.get("TIP_vs_IEF", 0.0), 1.0),
        "duration_inverse": (-one_week_moves.get("TLT", 0.0), 0.75),
    }

    risk_inputs = {
        "equity_beta": (one_week_moves.get("SPY", 0.0), 1.0),
        "credit_risk": (one_week_moves.get("HYG_vs_LQD", 0.0), 1.0),
        "small_vs_large": (one_week_moves.get("IWM_vs_SPY", 0.0), 0.75),
        "cyclical_vs_defensive": (one_week_moves.get("XLY_vs_XLP", 0.0), 0.75),
    }

    return {
        "growth": _normalized_weighted_score(growth_inputs),
        "inflation": _normalized_weighted_score(inflation_inputs),
        "risk": _normalized_weighted_score(risk_inputs),
    }


def classify_quadrant(growth_score: float, inflation_score: float) -> str:
    growth_up = growth_score >= 0
    inflation_up = inflation_score >= 0

    if growth_up and not inflation_up:
        return "Goldilocks"
    if growth_up and inflation_up:
        return "Overheating"
    if (not growth_up) and inflation_up:
        return "Stagflation"
    return "Disinflation Slowdown"


def combine_views(
    macro_scores: Dict[str, ScoreResult] | None,
    market_scores: Dict[str, ScoreResult] | None,
    macro_weight: float = 0.6,
) -> Dict[str, object]:
    """Combine macro + market views and output regime with confidence proxy."""
    macro_growth = macro_scores["growth"].score if macro_scores else 0.0
    macro_infl = macro_scores["inflation"].score if macro_scores else 0.0

    market_growth = market_scores["growth"].score if market_scores else 0.0
    market_infl = market_scores["inflation"].score if market_scores else 0.0
    market_risk = market_scores["risk"].score if market_scores else 0.0

    if macro_scores and market_scores:
        growth = macro_weight * macro_growth + (1 - macro_weight) * market_growth
        inflation = macro_weight * macro_infl + (1 - macro_weight) * market_infl
    elif macro_scores:
        growth = macro_growth
        inflation = macro_infl
    else:
        growth = market_growth
        inflation = market_infl

    quadrant = classify_quadrant(growth, inflation)
    risk_tag = "Risk On" if market_risk >= 0 else "Risk Off"

    confidence = (abs(growth) + abs(inflation) + abs(market_risk if market_scores else 0.0)) / 3.0

    return {
        "regime": quadrant,
        "risk_tag": risk_tag,
        "growth_score": round(growth, 3),
        "inflation_score": round(inflation, 3),
        "market_risk_score": round(market_risk, 3),
        "confidence_proxy": round(confidence, 3),
    }
