from __future__ import annotations

import json
import math
from pathlib import Path

from market_helper.regimes.policy_expert_predictor import (
    PolicyExpertPrediction,
    predict_latest,
)


def _write_artifact(path: Path) -> None:
    """Two features, two experts; coef = identity so the math is hand-checkable."""
    path.write_text(json.dumps({
        "model": "test-model",
        "horizon_months": 6,
        "softmax_temp": 1.0,
        "experts": ["A", "B"],
        "expert_exposures": {
            "A": {"EQ": 100, "CM": 0, "MACRO": 0, "FI": 0},
            "B": {"EQ": 0, "CM": 0, "MACRO": 0, "FI": 100},
        },
        "feature_names": ["f1", "f2"],
        "standardize_mean": [0.0, 0.0],
        "standardize_std": [1.0, 1.0],
        "intercept": [0.0, 0.0],
        "coef": [[1.0, 0.0], [0.0, 1.0]],
    }), encoding="utf-8")


def test_predict_latest_matches_hand_computation(tmp_path: Path) -> None:
    art = tmp_path / "artifact.json"
    feat = tmp_path / "features.csv"
    _write_artifact(art)
    feat.write_text("month,f1,f2\n2026-04,0.0,0.0\n2026-05,1.0,0.0\n", encoding="utf-8")

    pred = predict_latest(artifact_path=art, features_path=feat)

    assert pred.available is True
    assert pred.as_of == "2026-05"          # newest complete row
    assert pred.top_expert == "A"
    # fwd = [1, 0] -> demean [0.5, -0.5] -> softmax(temp=1)
    expected_a = math.exp(0.5) / (math.exp(0.5) + math.exp(-0.5))
    assert abs(pred.expert_allocation["A"] - expected_a) < 1e-3
    assert abs(sum(pred.expert_allocation.values()) - 1.0) < 1e-6
    # sleeve EQ = alloc_A * 100 ; FI = alloc_B * 100
    assert abs(pred.sleeve_weights["EQ"] - expected_a * 100) < 0.2
    assert abs(pred.sleeve_weights["FI"] - (1 - expected_a) * 100) < 0.2


def test_predict_latest_skips_incomplete_rows(tmp_path: Path) -> None:
    art = tmp_path / "a.json"
    feat = tmp_path / "f.csv"
    _write_artifact(art)
    # last row has a blank (NaN) feature -> must fall back to the prior complete row
    feat.write_text("month,f1,f2\n2026-04,2.0,0.0\n2026-05,1.0,\n", encoding="utf-8")

    pred = predict_latest(artifact_path=art, features_path=feat)

    assert pred.available is True
    assert pred.as_of == "2026-04"


def test_predict_latest_missing_artifact_is_graceful(tmp_path: Path) -> None:
    pred = predict_latest(artifact_path=tmp_path / "nope.json",
                          features_path=tmp_path / "nope.csv")
    assert isinstance(pred, PolicyExpertPrediction)
    assert pred.available is False
    assert "not found" in pred.reason


def test_predict_latest_missing_features_is_graceful(tmp_path: Path) -> None:
    art = tmp_path / "a.json"
    _write_artifact(art)
    pred = predict_latest(artifact_path=art, features_path=tmp_path / "missing.csv")
    assert pred.available is False
    assert "features" in pred.reason


def test_predict_latest_on_committed_artifact_is_sane() -> None:
    """The real committed artifact + features produce a valid allocation."""
    pred = predict_latest()
    assert pred.available is True
    assert pred.top_expert in {"Goldilocks", "Reflation", "Stagflation", "Recession"}
    assert abs(sum(pred.expert_allocation.values()) - 1.0) < 1e-3
    assert set(pred.sleeve_weights) == {"EQ", "CM", "MACRO", "FI"}
