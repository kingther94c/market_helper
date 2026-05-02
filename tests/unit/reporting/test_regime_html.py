from __future__ import annotations

import json
from pathlib import Path

from market_helper.reporting.regime_html import (
    build_regime_html_view_model,
    write_regime_html_report,
)


def _write_multi_payload(path: Path) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "as_of": "2026-01-02",
                    "version": "regime-multi-v1",
                    "ensemble": {
                        "as_of": "2026-01-02",
                        "quadrant": "Reflation",
                        "axes": {
                            "as_of": "2026-01-02",
                            "growth_score": 0.6,
                            "inflation_score": 0.4,
                            "growth_drivers": {},
                            "inflation_drivers": {},
                            "confidence": 1.0,
                        },
                        "crisis_flag": False,
                        "crisis_intensity": 0.0,
                        "duration_days": 1,
                        "diagnostics": {"method_agreement": 1.0},
                    },
                    "per_method": {},
                    "source_info": {},
                },
                {
                    "as_of": "2026-01-03",
                    "version": "regime-multi-v1",
                    "ensemble": {
                        "as_of": "2026-01-03",
                        "quadrant": "Goldilocks",
                        "axes": {
                            "as_of": "2026-01-03",
                            "growth_score": 0.7,
                            "inflation_score": -0.3,
                            "growth_drivers": {},
                            "inflation_drivers": {},
                            "confidence": 0.5,
                        },
                        "crisis_flag": True,
                        "crisis_intensity": 0.25,
                        "duration_days": 1,
                        "diagnostics": {"method_agreement": 0.5},
                    },
                    "per_method": {
                        "market_regime": {
                            "as_of": "2026-01-03",
                            "method_name": "market_regime",
                            "quadrant": {
                                "as_of": "2026-01-03",
                                "quadrant": "Reflation",
                                "axes": {
                                    "as_of": "2026-01-03",
                                    "growth_score": 0.4,
                                    "inflation_score": 0.2,
                                },
                                "crisis_flag": False,
                                "crisis_intensity": 0.0,
                                "duration_days": 2,
                                "diagnostics": {},
                            },
                            "native_label": "Reflation / neutral",
                            "native_detail": {},
                        },
                        "macro_regime": {
                            "as_of": "2026-01-03",
                            "method_name": "macro_regime",
                            "quadrant": {
                                "as_of": "2026-01-03",
                                "quadrant": "Goldilocks",
                                "axes": {
                                    "as_of": "2026-01-03",
                                    "growth_score": 1.0,
                                    "inflation_score": -0.8,
                                },
                                "crisis_flag": False,
                                "crisis_intensity": 0.0,
                                "duration_days": 1,
                                "diagnostics": {},
                            },
                            "native_label": "Goldilocks",
                            "native_detail": {},
                        },
                    },
                    "source_info": {},
                },
            ]
        ),
        encoding="utf-8",
    )


def test_build_regime_html_view_model_accepts_multi_payload(tmp_path: Path) -> None:
    regime_path = tmp_path / "regime_multi.json"
    _write_multi_payload(regime_path)

    view_model = build_regime_html_view_model(regime_path=regime_path)

    assert view_model.schema == "regime-multi-v1"
    assert view_model.regime == "Goldilocks"
    assert view_model.method_agreement == 0.5
    assert view_model.crisis_flag is True
    assert view_model.crisis_intensity == 0.25
    assert view_model.scores == {"GROWTH": 0.7, "INFLATION": -0.3}
    assert [row.method for row in view_model.methods] == [
        "macro_regime",
        "market_regime",
    ]
    assert view_model.regime_counts == {"Reflation": 1, "Goldilocks": 1}


def test_write_regime_html_report_outputs_self_contained_html(tmp_path: Path) -> None:
    regime_path = tmp_path / "regime_multi.json"
    output_path = tmp_path / "regime_report.html"
    _write_multi_payload(regime_path)

    result = write_regime_html_report(
        regime_path=regime_path,
        output_path=output_path,
    )

    assert result == output_path
    html = output_path.read_text(encoding="utf-8")
    assert "Regime Detection" in html
    assert "Goldilocks" in html
    assert "Method Votes" in html
    assert "Full-Sample Distribution" in html


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
        RegimeHtmlPolicySummary,
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
        policy=RegimeHtmlPolicySummary(
            vol_multiplier=1.0, asset_class_targets={"EQ": 0.6}, notes=""
        ),
        vol_multiplier=1.0,
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
