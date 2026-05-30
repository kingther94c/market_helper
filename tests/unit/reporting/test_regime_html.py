from __future__ import annotations

import json
from pathlib import Path

from market_helper.reporting.regime_html import (
    build_regime_html_view_model,
    render_regime_section_body,
    write_regime_html_report,
)





def test_build_regime_html_view_model_accepts_v2_payload(tmp_path: Path) -> None:
    regime_path = tmp_path / "regime_v2.json"
    regime_path.write_text(
        json.dumps(
            [
                {
                    "date": "2026-01-03",
                    "version": "regime-engine-v2",
                    "data_mode": "market_only",
                    "available_primary_layers": ["market_implied"],
                    "missing_primary_layers": ["macro_nowcast"],
                    "final_regime": "Reflation + Stress Overlay",
                    "base_regime": "Reflation",
                    "confidence": "Medium",
                    "disagreement_flag": True,
                    "disagreement_summary": "Layer disagreement",
                    "final_growth_score": 0.4,
                    "final_inflation_score": 0.6,
                    "macro_growth_score": -0.5,
                    "macro_inflation_score": 0.4,
                    "market_growth_score": 0.9,
                    "market_inflation_score": 0.8,
                    "risk_score": 0.8,
                    "risk_overlay_on": True,
                    "top_contributors": [
                        {"name": "credit spreads", "value": 0.42},
                        {"name": "commodities", "value": 0.25},
                    ],
                    "layer_outputs": [
                        {
                            "layer_name": "macro_nowcast",
                            "enabled": True,
                            "available": True,
                            "growth_score": -0.5,
                            "inflation_score": 0.4,
                            "growth_state": "Down",
                            "inflation_state": "Up",
                            "confidence": 0.5,
                            "top_negative_contributors": [
                                {"name": "payroll trend", "value": -0.2}
                            ],
                        },
                        {
                            "layer_name": "market_implied",
                            "enabled": True,
                            "available": True,
                            "growth_score": 0.9,
                            "inflation_score": 0.8,
                            "growth_state": "Up",
                            "inflation_state": "Up",
                            "confidence": "Medium",
                        },
                        {
                            "layer_name": "macro_truth_ml",
                            "enabled": False,
                            "available": False,
                            "growth_state": "Disabled",
                            "inflation_state": "Disabled",
                        },
                    ],
                    "risk_output": {
                        "risk_score": 0.8,
                        "liquidity_score": -0.2,
                        "risk_overlay_on": True,
                        "risk_state": "Stress",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    view_model = build_regime_html_view_model(regime_path=regime_path)

    assert view_model.schema == "regime-engine-v2"
    assert view_model.regime == "Reflation + Stress Overlay"
    assert view_model.confidence == "Medium"
    assert view_model.disagreement_flag is True
    assert view_model.risk_state == "Stress"
    assert view_model.scores == {"GROWTH": 0.4, "INFLATION": 0.6, "RISK": 0.8}
    assert view_model.base_regime == "Reflation"
    assert [layer.layer_name for layer in view_model.layers] == [
        "macro_nowcast",
        "market_implied",
        "macro_truth_ml",
    ]
    assert view_model.layers[2].status == "Disabled"
    assert view_model.risk_overlay is not None
    assert view_model.risk_overlay.risk_overlay_on is True
    assert view_model.data_mode == "market_only"
    assert view_model.missing_primary_layers == ["macro_nowcast"]

    fragment = render_regime_section_body(view_model)
    assert "Regime Engine v2" in fragment
    assert "Base Regime" in fragment
    assert "Growth / Inflation Axes" in fragment
    assert "Independent Risk Overlay" in fragment
    assert "Risk Overlay Score" in fragment
    assert "Layer-State Heat Strip" in fragment
    assert "Method disagreement: Yes" in fragment
    assert "data mode: market only; missing macro_nowcast" in fragment
    assert "credit spreads: +0.42" in fragment
    assert "Crisis Intensity" not in fragment


def test_crisis_intensity_chart_metadata_uses_view_model_as_of(tmp_path: Path) -> None:
    """B3: chart's `current` metadata reads from `view_model.as_of` /
    `view_model.crisis_intensity`, not from the last filtered timeline point.

    With the old logic, a timeline of all-None intensities would drop the chart
    entirely; or, if any historical spike was present, the metadata strip would
    show that spike's date as `current`. This test pins the new behaviour:
    even when the most recent snapshot has a `None` intensity, the chart still
    renders and the metadata reflects the live ensemble state.
    """
    from market_helper.reporting.regime_html import (
        RegimeHtmlTimelineRow,
        RegimeHtmlViewModel,
        render_regime_section_body,
    )

    timeline = [
        RegimeHtmlTimelineRow(
            as_of="2026-01-30",
            regime="Slowdown",
            method_agreement=0.7,
            crisis_flag=True,
            crisis_intensity=0.74,
            duration_days=3,
        ),
        # Everything after the spike has no published intensity.
        *[
            RegimeHtmlTimelineRow(
                as_of=f"2026-{m:02d}-15",
                regime="Goldilocks",
                method_agreement=0.85,
                crisis_flag=False,
                crisis_intensity=None,
                duration_days=30,
            )
            for m in range(2, 6)
        ],
    ]

    vm = RegimeHtmlViewModel(
        schema="regime-multi-v1",
        as_of="2026-04-27",
        regime="Goldilocks",
        scores={"GROWTH": 0.4, "INFLATION": -0.1},
        method_agreement=0.85,
        crisis_flag=False,
        crisis_intensity=0.0,  # <-- live state, not the historical spike
        duration_days=85,
        methods=[],
        timeline=timeline,
        regime_counts={"Goldilocks": 4, "Slowdown": 1},
    )

    fragment = render_regime_section_body(vm)

    # Crisis chart still renders even though only one historical point had a
    # non-None intensity.
    assert "Crisis Intensity" in fragment
    # Metadata strip reads from the live state — `current 0.00` and the
    # report-as-of date, not the Jan-30 spike date.
    assert "current 0.00" in fragment
    assert "2026-04-27" in fragment
    assert "current 0.74" not in fragment


def _q5_v2_payload_with_concepts() -> list[dict]:
    """Minimal v2 payload with the Q5-era concept diagnostics + confidence
    plumbing so the new derivations can be exercised end-to-end."""
    return [
        {
            "date": "2026-05-10",
            "version": "regime-engine-v2",
            "final_regime": "Neutral/Mixed Growth / Up Inflation",
            "base_regime": "Neutral/Mixed Growth / Up Inflation",
            "confidence": "Low",
            "confidence_strength": 0.05,
            "confidence_thresholds": {"medium": 0.20, "high": 0.45},
            "disagreement_flag": True,
            "disagreement_penalty_active": True,
            "disagreement_summary": "macro_nowcast: Up/Down; market_implied: Down/Up",
            "final_growth_score": 0.05,
            "final_inflation_score": 0.30,
            "risk_score": 0.10,
            "risk_overlay_on": False,
            "macro_growth_score": 0.40,
            "macro_inflation_score": -0.30,
            "market_growth_score": -0.30,
            "market_inflation_score": 0.40,
            "ml_macro_growth_score": None,
            "ml_macro_inflation_score": None,
            "ml_return_growth_score": None,
            "ml_return_inflation_score": None,
            "risk_output": {
                "risk_score": 0.10,
                "risk_overlay_on": False,
                "risk_state": "Neutral",
                "liquidity_score": None,
                "confidence": None,
                "top_positive_contributors": [],
                "top_negative_contributors": [],
                "diagnostics": {},
            },
            "layer_outputs": [
                {
                    "layer_name": "macro_nowcast",
                    "enabled": True,
                    "available": True,
                    "growth_score": 0.40,
                    "inflation_score": -0.30,
                    "growth_state": "Up",
                    "inflation_state": "Down",
                    "confidence": "Medium",
                    "top_positive_contributors": [["labor", 0.5]],
                    "top_negative_contributors": [["realized_broad", -0.4]],
                    "diagnostics": {
                        "concept_scores": {
                            "growth": {"labor": 0.6, "consumption": 0.15},
                            "inflation": {"realized_broad": -0.4, "persistence": -0.1},
                        },
                        "concept_weights": {
                            "growth": {"labor": 1.0, "consumption": 1.0},
                            "inflation": {"realized_broad": 1.0, "persistence": 1.0},
                        },
                    },
                },
                {
                    "layer_name": "market_implied",
                    "enabled": True,
                    "available": True,
                    "growth_score": -0.30,
                    "inflation_score": 0.40,
                    "growth_state": "Down",
                    "inflation_state": "Up",
                    "confidence": "Medium",
                    "top_positive_contributors": [["commodity_inflation", 0.7]],
                    "top_negative_contributors": [["broad_equity_momentum", -0.5]],
                    "diagnostics": {
                        "concept_scores": {
                            "growth": {"broad_equity_momentum": -0.5},
                            "inflation": {"commodity_inflation": 0.7},
                            "risk": {"volatility": 0.1},
                        },
                        "concept_weights": {
                            "growth": {"broad_equity_momentum": 0.8},
                            "inflation": {"commodity_inflation": 1.0},
                            "risk": {"volatility": 1.0},
                        },
                    },
                },
            ],
            "top_contributors": [],
        }
    ]


def test_view_model_emits_concept_rows_from_layer_diagnostics(tmp_path: Path) -> None:
    p = tmp_path / "regime_v2.json"
    p.write_text(json.dumps(_q5_v2_payload_with_concepts()), encoding="utf-8")
    vm = build_regime_html_view_model(regime_path=p)
    # Macro: 2 growth concepts + 2 inflation concepts = 4 rows; market: 1+1+1 = 3.
    assert len(vm.concept_rows) == 7
    layers = {r.layer for r in vm.concept_rows}
    assert layers == {"macro_nowcast", "market_implied"}
    # State classification uses ±0.20 thresholds.
    by_concept = {(r.layer, r.concept): r for r in vm.concept_rows}
    assert by_concept[("macro_nowcast", "labor")].state == "Up"
    assert by_concept[("macro_nowcast", "consumption")].state == "Neutral/Mixed"
    assert by_concept[("macro_nowcast", "realized_broad")].state == "Down"
    # Contribution = score * weight / sum(axis_weights).
    labor = by_concept[("macro_nowcast", "labor")]
    assert labor.contribution == 0.6 * (1.0 / 2.0)  # two growth concepts, weights 1.0 each


def test_view_model_emits_axis_disagreement_breakdown(tmp_path: Path) -> None:
    p = tmp_path / "regime_v2.json"
    p.write_text(json.dumps(_q5_v2_payload_with_concepts()), encoding="utf-8")
    vm = build_regime_html_view_model(regime_path=p)
    rows = {r.axis: r for r in vm.axis_disagreement}
    assert set(rows) == {"growth", "inflation"}
    # Macro Up vs Market Down on growth -> disagrees.
    assert rows["growth"].macro_state == "Up"
    assert rows["growth"].market_state == "Down"
    assert rows["growth"].disagrees is True
    # Macro Down vs Market Up on inflation -> also disagrees.
    assert rows["inflation"].macro_state == "Down"
    assert rows["inflation"].market_state == "Up"
    assert rows["inflation"].disagrees is True


def test_confidence_reasoning_surfaces_thresholds_and_penalty(tmp_path: Path) -> None:
    p = tmp_path / "regime_v2.json"
    p.write_text(json.dumps(_q5_v2_payload_with_concepts()), encoding="utf-8")
    vm = build_regime_html_view_model(regime_path=p)
    assert vm.confidence == "Low"
    assert vm.confidence_strength == 0.05
    assert vm.confidence_threshold_medium == 0.20
    assert vm.confidence_threshold_high == 0.45
    reasoning = vm.confidence_reasoning or ""
    assert "below medium threshold" in reasoning
    assert "disagreement penalty" in reasoning


def test_regime_section_body_renders_concept_panel_and_breakdown(tmp_path: Path) -> None:
    p = tmp_path / "regime_v2.json"
    p.write_text(json.dumps(_q5_v2_payload_with_concepts()), encoding="utf-8")
    vm = build_regime_html_view_model(regime_path=p)
    fragment = render_regime_section_body(vm)
    # New concept-contribution panel renders concept names from both layers.
    assert "Concept Contributions" in fragment
    assert "labor" in fragment
    assert "commodity_inflation" in fragment
    # Per-axis disagreement table appears inside the disagreement section.
    assert "regime-v2-axis-disagreement" in fragment
    # Confidence-reasoning blurb is visible.
    assert "Low" in fragment
    assert "below medium threshold" in fragment


def test_v2_heat_strip_maps_neutral_mixed_states_to_regime_classes(tmp_path: Path) -> None:
    regime_path = tmp_path / "regime_v2_heat_strip.json"
    regime_path.write_text(
        json.dumps(
            [
                {
                    "date": "2026-05-04",
                    "version": "regime-engine-v2",
                    "final_regime": "Neutral/Mixed Growth / Up Inflation",
                    "base_regime": "Neutral/Mixed Growth / Up Inflation",
                    "confidence": "Low",
                    "disagreement_flag": False,
                    "disagreement_summary": "",
                    "final_growth_score": 0.1,
                    "final_inflation_score": 0.8,
                    "risk_score": -0.1,
                    "risk_overlay_on": False,
                    "layer_outputs": [
                        {
                            "layer_name": "market_implied",
                            "enabled": True,
                            "available": True,
                            "growth_score": 0.1,
                            "inflation_score": 0.8,
                            "growth_state": "Neutral/Mixed",
                            "inflation_state": "Up",
                            "confidence": 1.0,
                        },
                        {
                            "layer_name": "macro_nowcast",
                            "enabled": True,
                            "available": True,
                            "growth_score": 0.7,
                            "inflation_score": 0.0,
                            "growth_state": "Up",
                            "inflation_state": "Neutral/Mixed",
                            "confidence": 0.7,
                        },
                    ],
                    "risk_output": {
                        "risk_score": -0.1,
                        "risk_overlay_on": False,
                        "risk_state": "Risk On",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    view_model = build_regime_html_view_model(regime_path=regime_path)

    fragment = render_regime_section_body(view_model)
    assert "title='2026-05-04 · Neutral/Mixed / Up'" in fragment
    assert "title='2026-05-04 · Up / Neutral/Mixed'" in fragment
    assert "regime-cell--stagflation" in fragment
    assert "regime-cell--goldilocks" in fragment
