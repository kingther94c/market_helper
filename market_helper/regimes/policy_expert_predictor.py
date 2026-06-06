"""Policy-expert allocation predictor (allocation-layer, advisory).

Loads the committed numpy-only model artifact (trained offline by
``scripts/research/policy_expert_model.py``) plus the latest ex-ante feature row and
produces a soft allocation across the four policy experts and the resulting target
sleeve exposures. Pure-Python application (json + csv + math) -- no sklearn / numpy /
network in the render path; the FRED/Yahoo pulls happen offline in the research harness.

This is the realization of the spec's allocation-layer "ML predictor" (architecture
choice (b)): it sits ONE LEVEL UP from the regime engine's axis-layers and replaces the
removed ``macro_truth_ml`` / ``return_truth_ml`` SVM slots. Read-only; advisory.

Graceful degradation: every failure path returns ``PolicyExpertPrediction(available=
False, reason=...)`` -- never a fake number, never an exception to the caller.
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from market_helper.app.paths import (
    POLICY_EXPERT_FEATURES_PATH,
    POLICY_EXPERT_MODEL_ARTIFACT_PATH,
)

SLEEVES = ("EQ", "CM", "MACRO", "FI")


@dataclass(frozen=True)
class PolicyExpertPrediction:
    """Advisory allocation across the 4 policy experts + target sleeve exposures."""

    available: bool
    reason: str = ""
    as_of: str = ""
    model_name: str = ""
    horizon_months: int = 0
    top_expert: str = ""
    confidence: float = 0.0                       # max allocation weight (0..1)
    expert_allocation: dict[str, float] = field(default_factory=dict)  # expert -> weight
    sleeve_weights: dict[str, float] = field(default_factory=dict)     # sleeve -> exposure %


def _softmax(values: list[float], temp: float) -> list[float]:
    hi = max(values)
    exps = [math.exp((v - hi) / temp) for v in values]
    total = sum(exps)
    return [e / total for e in exps] if total else [1.0 / len(values)] * len(values)


def _latest_feature_row(features_path: Path, names: list[str]) -> tuple[str, list[float]] | None:
    with features_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in reversed(rows):                    # newest first
        try:
            vals = [float(row[n]) for n in names]
        except (KeyError, ValueError, TypeError):
            continue                              # missing / blank (NaN) feature -> skip
        if any(v != v for v in vals):             # NaN guard
            continue
        return str(row.get("month", "")), vals
    return None


def predict_latest(
    *,
    artifact_path: Path | None = None,
    features_path: Path | None = None,
) -> PolicyExpertPrediction:
    """Apply the trained linear model to the latest ex-ante feature row.

    fwd_hat_k = intercept_k + coef_k . standardize(x);  attractiveness = demean(fwd_hat);
    allocation = softmax(attractiveness / temp);  sleeve = sum_k alloc_k * expert_k.
    """
    art_p = Path(artifact_path) if artifact_path else POLICY_EXPERT_MODEL_ARTIFACT_PATH
    feat_p = Path(features_path) if features_path else POLICY_EXPERT_FEATURES_PATH
    if not art_p.exists():
        return PolicyExpertPrediction(False, reason="model artifact not found")
    try:
        art = json.loads(art_p.read_text(encoding="utf-8"))
        names = list(art["feature_names"])
        mean = art["standardize_mean"]
        std = art["standardize_std"]
        coef = art["coef"]
        intercept = art["intercept"]
        experts = list(art["experts"])
        exposures = art["expert_exposures"]
        temp = float(art.get("softmax_temp", 0.03))
        if not feat_p.exists():
            return PolicyExpertPrediction(False, reason="features file not found")
        latest = _latest_feature_row(feat_p, names)
        if latest is None:
            return PolicyExpertPrediction(False, reason="no complete feature row")
        month, x = latest
        xs = [(x[i] - mean[i]) / (std[i] or 1.0) for i in range(len(names))]
        fwd = [intercept[k] + sum(coef[k][i] * xs[i] for i in range(len(names)))
               for k in range(len(experts))]
        avg = sum(fwd) / len(fwd)
        attract = [f - avg for f in fwd]
        alloc = _softmax(attract, temp)
        alloc_map = {experts[k]: round(alloc[k], 4) for k in range(len(experts))}
        sleeves = {
            s: round(sum(alloc[k] * float(exposures[experts[k]][s]) for k in range(len(experts))), 1)
            for s in SLEEVES
        }
        top_k = max(range(len(experts)), key=lambda k: alloc[k])
        return PolicyExpertPrediction(
            available=True,
            as_of=month,
            model_name=str(art.get("model", "policy-expert")),
            horizon_months=int(art.get("horizon_months", 6)),
            top_expert=experts[top_k],
            confidence=round(alloc[top_k], 4),
            expert_allocation=alloc_map,
            sleeve_weights=sleeves,
        )
    except Exception as exc:  # noqa: BLE001 -- advisory surface must never raise
        return PolicyExpertPrediction(False, reason=f"predictor error: {type(exc).__name__}")


__all__ = ["PolicyExpertPrediction", "predict_latest"]
