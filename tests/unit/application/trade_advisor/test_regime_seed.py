"""current_regime_seed: map the latest regime snapshot onto the advisor controls."""

from __future__ import annotations

import json

from market_helper.application.trade_advisor.regime_seed import RegimeSeed, current_regime_seed


def _write(tmp_path, payload):
    p = tmp_path / "regime_snapshots.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_seed_from_latest_snapshot(tmp_path):
    p = _write(tmp_path, [
        {"date": "2026-05-01", "base_regime": "Goldilocks", "confidence": "Low", "risk_overlay_on": False},
        {"date": "2026-06-01", "base_regime": "Reflation", "confidence": "High", "risk_overlay_on": True},
    ])
    seed = current_regime_seed(p)
    assert seed == RegimeSeed(regime="Reflation", confidence="High", crisis=True)
    assert seed.is_seeded


def test_final_regime_suffix_is_stripped(tmp_path):
    p = _write(tmp_path, [{"final_regime": "Stagflation + Stress Overlay", "confidence": "Medium", "risk_overlay_on": True}])
    seed = current_regime_seed(p)
    assert seed.regime == "Stagflation" and seed.confidence == "Medium" and seed.crisis is True


def test_unknown_regime_and_confidence_drop_to_empty(tmp_path):
    p = _write(tmp_path, [{"base_regime": "Mystery", "confidence": "Vague", "risk_overlay_on": False}])
    seed = current_regime_seed(p)
    assert seed.regime == "" and seed.confidence == "" and seed.crisis is False
    assert not seed.is_seeded


def test_single_dict_snapshot_supported(tmp_path):
    p = _write(tmp_path, {"base_regime": "Deflationary Slowdown", "confidence": "Low", "risk_overlay_on": False})
    assert current_regime_seed(p) == RegimeSeed(regime="Deflationary Slowdown", confidence="Low", crisis=False)


def test_missing_file_is_empty_seed(tmp_path):
    assert current_regime_seed(tmp_path / "nope.json") == RegimeSeed()


def test_malformed_json_is_empty_seed(tmp_path):
    p = tmp_path / "regime_snapshots.json"
    p.write_text("{not json", encoding="utf-8")
    assert current_regime_seed(p) == RegimeSeed()


def test_empty_list_is_empty_seed(tmp_path):
    assert current_regime_seed(_write(tmp_path, [])) == RegimeSeed()
