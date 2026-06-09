"""current_regime_seed: map the latest regime snapshot onto the advisor controls."""

from __future__ import annotations

import json

from market_helper.application.trade_advisor.regime_seed import (
    RegimeSeed,
    current_regime_seed,
    latest_regime_snapshot,
)


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


def test_tail_read_large_array_returns_last_without_full_parse(tmp_path):
    """The canonical artifact grows to 100s of MB; the reader must tail-read the last
    element of a pretty-printed (indent=2) array, not parse the whole thing."""
    filler = {"date": "1900-01-01", "base_regime": "Goldilocks", "confidence": "Low",
              "risk_overlay_on": False, "pad": "x" * 2000}
    last = {"date": "2026-06-09", "base_regime": "Reflation", "confidence": "High",
            "risk_overlay_on": True, "final_growth_score": 0.5}
    payload = [dict(filler) for _ in range(2600)] + [last]
    p = tmp_path / "regime_snapshots.json"
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")  # indent=2 → top-level `  {`/`  }`
    assert p.stat().st_size > 4 * 1024 * 1024  # on the tail-read path, not full-parse

    snap = latest_regime_snapshot(p)
    assert snap is not None and snap["date"] == "2026-06-09" and snap["base_regime"] == "Reflation"
    assert current_regime_seed(p) == RegimeSeed(regime="Reflation", confidence="High", crisis=True)


def test_snapshot_cache_refreshes_when_file_changes(tmp_path):
    p = tmp_path / "regime_snapshots.json"
    p.write_text(json.dumps([{"base_regime": "Goldilocks", "confidence": "Low"}]), encoding="utf-8")
    assert latest_regime_snapshot(p)["base_regime"] == "Goldilocks"
    # Rewrite with different content + size → the (mtime, size)-keyed cache must refresh.
    p.write_text(json.dumps([{"base_regime": "Reflation", "confidence": "High", "pad": "different-size"}]), encoding="utf-8")
    assert latest_regime_snapshot(p)["base_regime"] == "Reflation"
