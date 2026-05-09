from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from market_helper.cli.main import main
from market_helper.data_sources.fred.macro_panel import SeriesSpec
from market_helper.regimes.engine_v2 import LayerConfig, RegimeEngineConfig, run_regime_engine_v2
from market_helper.regimes.methods.market_regime import MarketRegimeConfig, MarketSignalSpec
from market_helper.workflows.regime_calibration import (
    AnchorPeriod,
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
    daily = json.loads(artifacts.daily_json_path.read_text(encoding="utf-8"))
    assert daily
    assert "layer_outputs" not in daily[0]
    assert "top_contributors" not in daily[0]
    assert "risk_state" not in daily[0]
    html = html_path.read_text(encoding="utf-8")
    assert "Regime Engine v2 Calibration Report" in html
    assert "2025 April Liberation Day Tariff Shock" in html
    assert "Market Cover" in html
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    assert notebook["cells"]
    assert all("Observation:" in "".join(cell["source"]) for cell in notebook["cells"])
    assert all("Question:" in "".join(cell["source"]) for cell in notebook["cells"])


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
