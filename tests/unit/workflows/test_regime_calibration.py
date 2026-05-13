from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from market_helper.cli.main import main
from market_helper.data_sources.fred.macro_panel import SeriesSpec
from market_helper.regimes.engine_v2 import LayerConfig, RegimeEngineConfig, run_regime_engine_v2
from market_helper.regimes.methods.macro_regime import MacroRegimeConfig
from market_helper.regimes.methods.market_regime import MarketRegimeConfig, MarketSignalSpec
from market_helper.workflows.regime_calibration import (
    AnchorPeriod,
    build_calibration_audit,
    run_regime_v2_calibration,
    summarize_anchor_period_rows,
    summarize_anchor_periods,
)


def _macro_panel(n: int = 120) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({"date": dates, "G": [1.0] * n, "I": [0.1] * n})


def _macro_specs() -> list[SeriesSpec]:
    return [
        SeriesSpec(series_id="G", axis="growth", transform="level"),
        SeriesSpec(series_id="I", axis="inflation", transform="level"),
    ]


def _macro_concepts():
    from market_helper.data_sources.fred.macro_panel import ConceptSpec
    return [
        ConceptSpec(name="g", axis="growth", weight=1.0, members={"G": 1.0}),
        ConceptSpec(name="i", axis="inflation", weight=1.0, members={"I": 1.0}),
    ]


def _tariff_shock_market_panel(n: int = 120) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=n)
    spy = []
    uso = []
    vix = []
    for idx, date in enumerate(dates):
        if pd.Timestamp("2025-04-01") <= date <= pd.Timestamp("2025-04-25"):
            shock_idx = len([d for d in dates[: idx + 1] if pd.Timestamp("2025-04-01") <= d <= pd.Timestamp("2025-04-25")])
            spy.append(150.0 * (0.5 ** shock_idx))
            uso.append(80.0 * (1.5 ** shock_idx))
            vix.append(18.0 + shock_idx * 1.2)
        elif date > pd.Timestamp("2025-04-25"):
            relief_idx = len([d for d in dates[: idx + 1] if d > pd.Timestamp("2025-04-25")])
            spy.append(125.0 + relief_idx * 1.0)
            uso.append(102.0 - relief_idx * 0.2)
            vix.append(max(18.0, 42.0 - relief_idx * 1.2))
        else:
            spy.append(100.0 + idx * 0.2)
            uso.append(70.0 + idx * 0.05)
            vix.append(16.0)
    return pd.DataFrame({"date": dates, "SPY": spy, "USO": uso, "VIX": vix})


def _market_config() -> MarketRegimeConfig:
    return MarketRegimeConfig(
        signals=[
            MarketSignalSpec(name="spy", axis="growth", symbol="SPY", transform="raw_sign", lookback_days=1),
            MarketSignalSpec(name="oil", axis="inflation", symbol="USO", transform="raw_sign", lookback_days=1),
            MarketSignalSpec(name="vix", axis="risk", symbol="VIX", transform="raw_sign", lookback_days=1),
        ],
        min_consecutive_days=1,
        risk_min_consecutive_days=1,
        risk_enter_threshold=0.02,
        risk_exit_threshold=0.0,
    )


def test_liberation_day_style_window_surfaces_market_stagflation_dislocation() -> None:
    from market_helper.regimes.engine_v2 import RiskOverlayConfig

    cfg = RegimeEngineConfig(
        layers={
            "macro_nowcast": LayerConfig(enabled=True, weight_growth=0.5, weight_inflation=0.5),
            "market_implied": LayerConfig(enabled=True, weight_growth=0.5, weight_inflation=0.5),
            "macro_truth_ml": LayerConfig(enabled=False, model_type="svm"),
            "return_truth_ml": LayerConfig(enabled=False, model_type="svm"),
        },
        risk_overlay=RiskOverlayConfig(
            enabled=True,
            independent=True,
            enter_threshold=0.02,
            exit_threshold=0.0,
            min_consecutive_days=1,
        ),
    )
    results = run_regime_engine_v2(
        config=cfg,
        macro_panel=_macro_panel(),
        macro_specs=_macro_specs(),
        macro_concepts=_macro_concepts(),
        market_panel=_tariff_shock_market_panel(),
        market_config=_market_config(),
    )
    april = [row for row in results if "2025-04-10" <= row.date <= "2025-04-25"]

    assert april
    assert any(row.market_growth_score is not None and row.market_growth_score < 0 for row in april)
    assert any(row.market_inflation_score is not None and row.market_inflation_score > 0 for row in april)
    assert any(row.risk_overlay_on for row in april)
    assert any(row.disagreement_flag for row in april)


def test_calibration_workflow_writes_html_summary_and_question_notebook(tmp_path: Path) -> None:
    macro_panel = tmp_path / "macro_panel.feather"
    fred_config = tmp_path / "fred_series.yml"
    html_path = tmp_path / "report.html"
    notebook_path = tmp_path / "questions.ipynb"
    _macro_panel(n=80).to_feather(macro_panel)
    fred_config.write_text(
        yaml.safe_dump(
            {
                "series": [
                    {"series_id": "G", "axis": "growth", "transform": "level"},
                    {"series_id": "I", "axis": "inflation", "transform": "level"},
                ],
                "growth_concepts": {"g": {"weight": 1.0, "series": {"G": 1.0}}},
                "inflation_concepts": {"i": {"weight": 1.0, "series": {"I": 1.0}}},
            }
        ),
        encoding="utf-8",
    )

    artifacts = run_regime_v2_calibration(
        macro_panel_path=macro_panel,
        fred_series_config=fred_config,
        market_panel_path=tmp_path / "missing_market_panel.feather",
        market_regime_config=tmp_path / "missing_market_regime.yml",
        output_dir=tmp_path / "calibration",
        html_output=html_path,
        notebook_output=notebook_path,
    )

    assert artifacts.html_path == html_path
    assert artifacts.notebook_path == notebook_path
    assert html_path.exists()
    assert artifacts.daily_json_path.exists()
    assert artifacts.audit_json_path.exists()
    assert artifacts.q7_notebook_path.name == "regime_v2_calibration_q7.ipynb"
    daily = json.loads(artifacts.daily_json_path.read_text(encoding="utf-8"))
    assert daily
    assert "data_mode" in daily[0]
    assert "layer_outputs" not in daily[0]
    assert "top_contributors" not in daily[0]
    assert "risk_state" not in daily[0]
    audit_payload = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    assert {item["round"] for item in audit_payload["decisions"]} >= {"Q1", "Q2", "Q3", "Q4"}
    html = html_path.read_text(encoding="utf-8")
    assert "Regime Engine v2 Calibration Report" in html
    assert "Q1-Q6 Decision Audit" in html
    assert "2025 April Liberation Day Tariff Shock" in html
    assert "Market Cover" in html
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    assert notebook["cells"]
    assert all("Observation:" in "".join(cell["source"]) for cell in notebook["cells"])
    assert all("Question:" in "".join(cell["source"]) for cell in notebook["cells"])


def test_calibration_workflow_loads_and_passes_macro_method_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from market_helper.regimes.engine_v2 import run_regime_engine_v2 as real_run_regime_engine_v2

    macro_panel = tmp_path / "macro_panel.feather"
    fred_config = tmp_path / "fred_series.yml"
    _macro_panel(n=80).to_feather(macro_panel)
    fred_config.write_text(
        yaml.safe_dump(
            {
                "engine": {
                    "compression": "tanh",
                    "compression_k": 0.5,
                    "min_consecutive_days": 3,
                },
                "series": [
                    {"series_id": "G", "axis": "growth", "transform": "level"},
                    {"series_id": "I", "axis": "inflation", "transform": "level"},
                ],
                "growth_concepts": {"g": {"weight": 1.0, "series": {"G": 1.0}}},
                "inflation_concepts": {"i": {"weight": 1.0, "series": {"I": 1.0}}},
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def _capturing_run_regime_engine_v2(**kwargs):
        captured["macro_method_config"] = kwargs.get("macro_method_config")
        return real_run_regime_engine_v2(**kwargs)

    monkeypatch.setattr(
        "market_helper.workflows.regime_calibration.run_regime_engine_v2",
        _capturing_run_regime_engine_v2,
    )

    run_regime_v2_calibration(
        macro_panel_path=macro_panel,
        fred_series_config=fred_config,
        market_panel_path=tmp_path / "missing_market_panel.feather",
        market_regime_config=tmp_path / "missing_market_regime.yml",
        output_dir=tmp_path / "calibration",
        html_output=tmp_path / "report.html",
        notebook_output=tmp_path / "questions.ipynb",
    )

    macro_method_config = captured.get("macro_method_config")
    assert isinstance(macro_method_config, MacroRegimeConfig)
    assert macro_method_config.compression == "tanh"
    assert macro_method_config.compression_k == 0.5
    assert macro_method_config.min_consecutive_days == 3


def test_summarize_anchor_periods_reports_missing_windows() -> None:
    cfg = RegimeEngineConfig(
        layers={
            "macro_nowcast": LayerConfig(enabled=True, weight_growth=1.0, weight_inflation=1.0),
            "market_implied": LayerConfig(enabled=False),
            "macro_truth_ml": LayerConfig(enabled=False, model_type="svm"),
            "return_truth_ml": LayerConfig(enabled=False, model_type="svm"),
        }
    )
    results = run_regime_engine_v2(
        config=cfg,
        macro_panel=_macro_panel(n=30),
        macro_specs=_macro_specs(),
        macro_concepts=_macro_concepts(),
    )
    summaries = summarize_anchor_periods(
        results,
        anchors=[AnchorPeriod("Missing", "2000-01-01", "2000-01-31", "Expected", "Question?")],
    )

    assert summaries[0]["available"] is False
    assert "No engine rows" in summaries[0]["observation"]


def test_summarize_anchor_periods_exposes_layer_coverage_limits() -> None:
    cfg = RegimeEngineConfig(
        layers={
            "macro_nowcast": LayerConfig(enabled=True, weight_growth=1.0, weight_inflation=1.0),
            "market_implied": LayerConfig(enabled=False),
            "macro_truth_ml": LayerConfig(enabled=False, model_type="svm"),
            "return_truth_ml": LayerConfig(enabled=False, model_type="svm"),
        }
    )
    results = run_regime_engine_v2(
        config=cfg,
        macro_panel=_macro_panel(n=30),
        macro_specs=_macro_specs(),
        macro_concepts=_macro_concepts(),
    )
    summaries = summarize_anchor_periods(
        results,
        anchors=[AnchorPeriod("Covered Macro Only", "2025-01-01", "2025-01-31", "Expected", "Question?")],
    )

    assert summaries[0]["available"] is True
    assert summaries[0]["macro_coverage_share"] == 1.0
    assert summaries[0]["market_coverage_share"] == 0.0
    assert summaries[0]["risk_coverage_share"] == 0.0
    assert "coverage macro/market/risk 100%/0%/0%" in summaries[0]["observation"]


def test_anchor_summary_can_reuse_prepared_rows_without_full_result_dicts() -> None:
    rows = [
        {
            "date": "2025-01-02",
            "final_regime": "Reflation",
            "base_regime": "Reflation",
            "confidence": "High",
            "disagreement_flag": False,
            "final_growth_score": 1.0,
            "final_inflation_score": 1.0,
            "risk_score": 0.0,
            "risk_overlay_on": False,
            "macro_growth_score": 1.0,
            "macro_inflation_score": 1.0,
            "market_growth_score": None,
            "market_inflation_score": None,
            "top_contributors": [["macro_nowcast:G", 1.0]],
            "risk_state": "Not available",
        }
    ]

    summaries = summarize_anchor_period_rows(
        rows,
        anchors=[AnchorPeriod("Prepared", "2025-01-01", "2025-01-31", "Expected", "Question?")],
    )

    assert summaries[0]["available"] is True
    assert summaries[0]["macro_coverage_share"] == 1.0
    assert summaries[0]["market_coverage_share"] == 0.0
    assert summaries[0]["top_contributors"] == [("macro_nowcast:G", 1.0)]


def test_anchor_summary_exposes_phase_and_response_metrics() -> None:
    rows = []
    labels = [
        "Neutral/Mixed Growth / Neutral/Mixed Inflation",
        "Reflation",
        "Reflation",
        "Neutral/Mixed Growth / Neutral/Mixed Inflation",
        "Goldilocks / Expansion",
        "Neutral/Mixed Growth / Neutral/Mixed Inflation",
    ]
    for idx, date in enumerate(pd.bdate_range("2020-07-01", periods=len(labels))):
        rows.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "data_mode": "full_ensemble" if idx < 4 else "market_only",
                "final_regime": labels[idx],
                "base_regime": labels[idx],
                "confidence": "Medium",
                "disagreement_flag": False,
                "final_growth_score": 0.2,
                "final_inflation_score": 0.2,
                "risk_score": 0.0,
                "risk_overlay_on": False,
                "macro_growth_score": 0.2,
                "macro_inflation_score": 0.2,
                "market_growth_score": 0.2,
                "market_inflation_score": 0.2,
                "top_contributors": [],
                "risk_state": "Neutral",
            }
        )

    summaries = summarize_anchor_period_rows(
        rows,
        anchors=[
            AnchorPeriod(
                "2020 H2-2021 Reopening",
                "2020-07-01",
                "2020-07-08",
                "Reflation.",
                "Question?",
            )
        ],
    )
    summary = summaries[0]

    assert summary["first_target_match_date"] == "2020-07-02"
    assert summary["target_response_lag_bdays"] == 1
    assert summary["target_match_share"] == 0.5
    assert dict(summary["data_mode_counts"]) == {"full_ensemble": 4, "market_only": 2}
    assert dict(summary["phase_counts"]["early"]) == {
        "Neutral/Mixed Growth / Neutral/Mixed Inflation": 1,
        "Reflation": 1,
    }
    assert dict(summary["phase_counts"]["late"]) == {
        "Goldilocks / Expansion": 1,
        "Neutral/Mixed Growth / Neutral/Mixed Inflation": 1,
    }


def test_q7_audit_marks_q1_to_q4_decision_statuses() -> None:
    audit = build_calibration_audit(
        [
            {"name": "2008-09 GFC", "stress_share": 0.29, "final_regime_majority": "Slowdown"},
            {"name": "2018 Q4 Selloff", "stress_share": 0.09, "final_regime_majority": "Slowdown"},
            {
                "name": "2025 April Liberation Day Tariff Shock",
                "stress_share": 0.11,
                "final_regime_majority": "Down Growth / Neutral/Mixed Inflation",
            },
        ],
        {
            "macro_panel": {"end": "2026-04-29"},
            "market_panel": {"end": "2026-05-08"},
        },
    )

    statuses = {row["round"]: row["status"] for row in audit}
    assert statuses["Q1"] == "still_valid"
    assert statuses["Q2"] == "still_valid"
    assert statuses["Q3"] == "superseded"
    assert statuses["Q4"] == "needs_retest"
    assert set(statuses.values()) <= {"still_valid", "superseded", "needs_retest"}
    q4 = next(row for row in audit if row["round"] == "Q4")
    assert "GFC 29%" in q4["current_evidence"]


def test_cli_regime_calibrate_v2_dispatches(tmp_path: Path) -> None:
    macro_panel = tmp_path / "macro_panel.feather"
    fred_config = tmp_path / "fred_series.yml"
    output_dir = tmp_path / "out"
    notebook = tmp_path / "questions.ipynb"
    html = tmp_path / "report.html"
    _macro_panel(n=80).to_feather(macro_panel)
    fred_config.write_text(
        yaml.safe_dump(
            {
                "series": [
                    {"series_id": "G", "axis": "growth", "transform": "level"},
                    {"series_id": "I", "axis": "inflation", "transform": "level"},
                ],
                "growth_concepts": {"g": {"weight": 1.0, "series": {"G": 1.0}}},
                "inflation_concepts": {"i": {"weight": 1.0, "series": {"I": 1.0}}},
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "regime-calibrate",
            "--macro-panel",
            str(macro_panel),
            "--fred-series-config",
            str(fred_config),
            "--market-panel",
            str(tmp_path / "missing_market_panel.feather"),
            "--market-regime-config",
            str(tmp_path / "missing_market_regime.yml"),
            "--output-dir",
            str(output_dir),
            "--html-output",
            str(html),
            "--notebook-output",
            str(notebook),
        ]
    )

    assert exit_code == 0
    assert html.exists()
    assert notebook.exists()
