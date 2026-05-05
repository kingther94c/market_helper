"""Research-only calibration artifacts for Regime Engine v2."""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from market_helper.data_sources.fred.macro_panel import (
    DEFAULT_CACHE_DIR as FRED_DEFAULT_CACHE_DIR,
    DEFAULT_PANEL_FILENAME as FRED_DEFAULT_PANEL_FILENAME,
    load_panel,
    load_series_specs,
)
from market_helper.data_sources.yahoo_finance.market_panel import (
    DEFAULT_MARKET_CACHE_DIR,
    DEFAULT_MARKET_PANEL_FILENAME,
    load_market_panel,
)
from market_helper.regimes.engine_v2 import FinalRegimeResult, load_regime_engine_config, run_regime_engine_v2
from market_helper.regimes.methods.market_regime import MarketRegimeConfig, load_market_regime_config


DEFAULT_CALIBRATION_DIR = Path("data/artifacts/regime_detection/calibration")
DEFAULT_NOTEBOOK_PATH = Path("notebooks/regime_detection/regime_v2_calibration_questions.ipynb")
DEFAULT_REGIME_ENGINE_CONFIG = Path("configs/regime_detection/regime_engine_v2.yml")
DAILY_ROW_KEYS = (
    "date",
    "final_regime",
    "base_regime",
    "confidence",
    "disagreement_flag",
    "final_growth_score",
    "final_inflation_score",
    "risk_score",
    "risk_overlay_on",
    "macro_growth_score",
    "macro_inflation_score",
    "market_growth_score",
    "market_inflation_score",
)


@dataclass(frozen=True)
class AnchorPeriod:
    name: str
    start: str
    end: str
    expected_behavior: str
    review_question: str


@dataclass(frozen=True)
class CalibrationArtifacts:
    html_path: Path
    notebook_path: Path
    daily_json_path: Path
    summary_json_path: Path
    result_count: int
    market_panel_available: bool


ANCHOR_PERIODS: tuple[AnchorPeriod, ...] = (
    AnchorPeriod(
        "2008-09 GFC",
        "2008-09-01",
        "2009-06-30",
        "Growth Down; inflation falling or Down; Stress Overlay On.",
        "Does v2 show a deflationary slowdown/stress phase without needing risk to redefine the macro axes?",
    ),
    AnchorPeriod(
        "2009-10 Recovery",
        "2009-07-01",
        "2010-12-31",
        "Recovery or Reflation; stress fading.",
        "Should early-cycle recovery be allowed to appear as Reflation before macro growth fully confirms?",
    ),
    AnchorPeriod(
        "2011 Euro Debt / US Downgrade",
        "2011-07-01",
        "2011-12-31",
        "Market stress and possible macro/market disagreement.",
        "Is disagreement here useful context rather than a reason to force consensus?",
    ),
    AnchorPeriod(
        "2014-16 Oil Collapse",
        "2014-07-01",
        "2016-02-29",
        "Disinflationary slowdown pressure.",
        "Should collapsing oil dominate market-implied inflation, or should core inflation persistence dampen it?",
    ),
    AnchorPeriod(
        "2017 Soft Landing",
        "2017-01-01",
        "2017-12-31",
        "Goldilocks / Expansion or benign Reflation.",
        "Does the engine distinguish healthy expansion from overheating inflation pressure?",
    ),
    AnchorPeriod(
        "2018 Q4 Selloff",
        "2018-10-01",
        "2018-12-31",
        "Market stress/disagreement; macro slower.",
        "Should this be treated as a market-implied warning that does not require immediate macro confirmation?",
    ),
    AnchorPeriod(
        "2020 COVID Shock",
        "2020-02-15",
        "2020-05-31",
        "Stress Overlay On; market leads macro deterioration.",
        "Is macro lag acceptable here, or should the macro fast bucket become more reactive?",
    ),
    AnchorPeriod(
        "2020 H2-2021 Reopening",
        "2020-07-01",
        "2021-12-31",
        "Reflation.",
        "Does the inflation axis rise early enough without turning every expansion into Reflation?",
    ),
    AnchorPeriod(
        "2022 Inflation Shock / Tightening",
        "2022-01-01",
        "2022-12-31",
        "Inflation Up with weakening growth; Stagflation-like is acceptable.",
        "Should realized CPI/PCE persistence carry more weight than commodity rollover in late 2022?",
    ),
    AnchorPeriod(
        "2023-24 Disinflation / Soft Landing",
        "2023-01-01",
        "2024-12-31",
        "Growth resilient; inflation easing.",
        "Should the base label lean Goldilocks when inflation is easing but still above normal?",
    ),
    AnchorPeriod(
        "2025 April Liberation Day Tariff Shock",
        "2025-04-01",
        "2025-05-31",
        "Market briefly worries about stagflation/stress, then stress eases as the tariff path softens.",
        "Should this be classified as meaningful short-lived market-implied dislocation, false alarm, or correct stagflation warning?",
    ),
)


def run_regime_v2_calibration(
    *,
    regime_engine_config: str | Path | None = None,
    macro_panel_path: str | Path | None = None,
    fred_series_config: str | Path | None = None,
    market_panel_path: str | Path | None = None,
    market_regime_config: str | Path | None = None,
    output_dir: str | Path = DEFAULT_CALIBRATION_DIR,
    html_output: str | Path | None = None,
    notebook_output: str | Path | None = None,
) -> CalibrationArtifacts:
    """Run v2 over local data and write research calibration artifacts.

    This workflow intentionally does not tune configs or write normal dashboard
    outputs. Missing market data is reported as a calibration limitation instead
    of being papered over.
    """

    cfg_path = Path(regime_engine_config) if regime_engine_config else DEFAULT_REGIME_ENGINE_CONFIG
    cfg = load_regime_engine_config(cfg_path if cfg_path.exists() else None)
    macro_specs = None
    macro_panel = None
    specs_path = Path(fred_series_config) if fred_series_config else Path("configs/regime_detection/fred_series.yml")
    panel_path = Path(macro_panel_path) if macro_panel_path else Path(FRED_DEFAULT_CACHE_DIR) / FRED_DEFAULT_PANEL_FILENAME
    if specs_path.exists() and panel_path.exists():
        macro_specs = load_series_specs(specs_path)
        macro_panel = load_panel(panel_path, columns=_macro_panel_columns(macro_specs))

    market_config = None
    market_panel = None
    market_cfg_path = Path(market_regime_config) if market_regime_config else Path("configs/regime_detection/market_regime.yml")
    market_panel_input = Path(market_panel_path) if market_panel_path else Path(DEFAULT_MARKET_CACHE_DIR) / DEFAULT_MARKET_PANEL_FILENAME
    if market_cfg_path.exists() and market_panel_input.exists():
        market_config = load_market_regime_config(market_cfg_path)
        market_panel = load_market_panel(market_panel_input, columns=_market_panel_columns(market_config))

    results = run_regime_engine_v2(
        config=cfg,
        macro_panel=macro_panel,
        macro_specs=macro_specs,
        market_panel=market_panel,
        market_config=market_config,
    )
    if not results:
        raise ValueError("Regime Engine v2 produced no calibration rows.")

    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    html_path = Path(html_output) if html_output else output_root / "regime_v2_calibration_report.html"
    notebook_path = Path(notebook_output) if notebook_output else DEFAULT_NOTEBOOK_PATH
    daily_json_path = output_root / "regime_v2_calibration_daily.json"
    summary_json_path = output_root / "regime_v2_calibration_summary.json"

    summary_rows = [_summary_row(result) for result in results]
    daily_rows = [_daily_row_from_summary_row(row) for row in summary_rows]
    summaries = summarize_anchor_period_rows(summary_rows, ANCHOR_PERIODS)
    diagnostics = _input_diagnostics(
        macro_panel=macro_panel,
        market_panel=market_panel,
        macro_panel_path=panel_path,
        market_panel_path=market_panel_input,
    )
    recommendations = _recommendations(summaries, diagnostics)

    daily_json_path.write_text(json.dumps(daily_rows, separators=(",", ":")), encoding="utf-8")
    summary_json_path.write_text(
        json.dumps(
            {
                "anchors": summaries,
                "diagnostics": diagnostics,
                "recommendations": recommendations,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_html_report(
        html_path,
        summaries=summaries,
        diagnostics=diagnostics,
        recommendations=recommendations,
        latest=summary_rows[-1],
    )
    _write_review_notebook(
        notebook_path,
        summaries=summaries,
        diagnostics=diagnostics,
        recommendations=recommendations,
        html_path=html_path,
        daily_json_path=daily_json_path,
    )

    return CalibrationArtifacts(
        html_path=html_path,
        notebook_path=notebook_path,
        daily_json_path=daily_json_path,
        summary_json_path=summary_json_path,
        result_count=len(results),
        market_panel_available=market_panel is not None,
    )


def summarize_anchor_periods(
    results: Sequence[FinalRegimeResult],
    anchors: Sequence[AnchorPeriod] = ANCHOR_PERIODS,
) -> list[dict[str, Any]]:
    return summarize_anchor_period_rows([_summary_row(result) for result in results], anchors)


def summarize_anchor_period_rows(
    rows: Sequence[Mapping[str, Any]],
    anchors: Sequence[AnchorPeriod] = ANCHOR_PERIODS,
) -> list[dict[str, Any]]:
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    summaries: list[dict[str, Any]] = []
    for anchor in anchors:
        start = pd.Timestamp(anchor.start)
        end = pd.Timestamp(anchor.end)
        window = frame[(frame["date"] >= start) & (frame["date"] <= end)]
        if window.empty:
            summaries.append(
                {
                    "name": anchor.name,
                    "start": anchor.start,
                    "end": anchor.end,
                    "available": False,
                    "expected_behavior": anchor.expected_behavior,
                    "review_question": anchor.review_question,
                    "observation": "No engine rows are available for this window.",
                }
            )
            continue
        final_counts = _value_counts(window["final_regime"])
        base_counts = _value_counts(window["base_regime"])
        stress_share = float(window["risk_overlay_on"].mean())
        disagreement_share = float(window["disagreement_flag"].mean())
        macro_growth = _mean_optional(window["macro_growth_score"])
        macro_inflation = _mean_optional(window["macro_inflation_score"])
        market_growth = _mean_optional(window["market_growth_score"])
        market_inflation = _mean_optional(window["market_inflation_score"])
        macro_coverage = _score_coverage(window, "macro_growth_score", "macro_inflation_score")
        market_coverage = _score_coverage(window, "market_growth_score", "market_inflation_score")
        risk_coverage = float((window["risk_state"] != "Not available").mean())
        top_contributors = _aggregate_top_contributors(window["top_contributors"])
        observation = _anchor_observation(
            anchor,
            final_counts=final_counts,
            stress_share=stress_share,
            disagreement_share=disagreement_share,
            macro_coverage=macro_coverage,
            market_coverage=market_coverage,
            risk_coverage=risk_coverage,
            macro_growth=macro_growth,
            macro_inflation=macro_inflation,
            market_growth=market_growth,
            market_inflation=market_inflation,
        )
        summaries.append(
            {
                "name": anchor.name,
                "start": anchor.start,
                "end": anchor.end,
                "available": True,
                "row_count": int(len(window)),
                "expected_behavior": anchor.expected_behavior,
                "review_question": anchor.review_question,
                "observation": observation,
                "final_regime_majority": final_counts[0][0] if final_counts else "",
                "final_regime_counts": final_counts,
                "base_regime_counts": base_counts,
                "stress_share": stress_share,
                "disagreement_share": disagreement_share,
                "macro_coverage_share": macro_coverage,
                "market_coverage_share": market_coverage,
                "risk_coverage_share": risk_coverage,
                "macro_growth_mean": macro_growth,
                "macro_inflation_mean": macro_inflation,
                "market_growth_mean": market_growth,
                "market_inflation_mean": market_inflation,
                "top_contributors": top_contributors,
            }
        )
    return summaries


def _input_diagnostics(
    *,
    macro_panel: pd.DataFrame | None,
    market_panel: pd.DataFrame | None,
    macro_panel_path: Path,
    market_panel_path: Path,
) -> dict[str, Any]:
    return {
        "macro_panel": _panel_diagnostic(macro_panel, macro_panel_path),
        "market_panel": _panel_diagnostic(market_panel, market_panel_path),
    }


def _macro_panel_columns(specs: Sequence[Any]) -> list[str]:
    return ["date", *(str(spec.series_id) for spec in specs)]


def _market_panel_columns(config: MarketRegimeConfig) -> list[str]:
    columns: list[str] = ["date"]
    for signal in config.signals:
        for value in (signal.symbol, signal.numerator, signal.denominator):
            if value and value not in columns:
                columns.append(str(value))
    return columns


def _panel_diagnostic(panel: pd.DataFrame | None, path: Path) -> dict[str, Any]:
    if panel is None:
        return {"available": False, "path": str(path), "reason": "file not found or config unavailable"}
    dates = pd.to_datetime(panel["date"]) if "date" in panel.columns else pd.Series(dtype="datetime64[ns]")
    return {
        "available": True,
        "path": str(path),
        "rows": int(len(panel)),
        "start": dates.min().strftime("%Y-%m-%d") if not dates.empty else None,
        "end": dates.max().strftime("%Y-%m-%d") if not dates.empty else None,
        "columns": [str(col) for col in panel.columns],
    }


def _summary_row(result: FinalRegimeResult) -> dict[str, Any]:
    return {
        "date": result.date,
        "final_regime": result.final_regime,
        "base_regime": result.base_regime,
        "confidence": result.confidence,
        "disagreement_flag": result.disagreement_flag,
        "final_growth_score": result.final_growth_score,
        "final_inflation_score": result.final_inflation_score,
        "risk_score": result.risk_score,
        "risk_overlay_on": result.risk_overlay_on,
        "macro_growth_score": result.macro_growth_score,
        "macro_inflation_score": result.macro_inflation_score,
        "market_growth_score": result.market_growth_score,
        "market_inflation_score": result.market_inflation_score,
        "top_contributors": [list(item) for item in result.top_contributors],
        "risk_state": result.risk_output.risk_state,
    }


def _daily_row_from_summary_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in DAILY_ROW_KEYS}


def _recommendations(summaries: Sequence[Mapping[str, Any]], diagnostics: Mapping[str, Any]) -> list[str]:
    recs: list[str] = []
    if not diagnostics.get("market_panel", {}).get("available"):
        recs.append("Run market-regime-sync before accepting market_implied or risk-overlay calibration.")
    unavailable = [item["name"] for item in summaries if not item.get("available")]
    if unavailable:
        recs.append(f"Treat unavailable anchor windows as data-coverage gaps: {', '.join(unavailable)}.")
    high_disagreement = [
        item["name"]
        for item in summaries
        if item.get("available") and float(item.get("disagreement_share") or 0.0) >= 0.75
    ]
    if high_disagreement:
        recs.append(f"Review whether these high-disagreement windows are desirable dislocations: {', '.join(high_disagreement)}.")
    weak_market = [
        item["name"]
        for item in summaries
        if item.get("available") and float(item.get("market_coverage_share") or 0.0) < 0.80
    ]
    if weak_market:
        recs.append(
            "Market layer coverage is insufficient in at least one anchor; avoid market_implied calibration until full-history market data is present."
        )
    weak_risk = [
        item["name"]
        for item in summaries
        if item.get("available") and float(item.get("risk_coverage_share") or 0.0) < 0.80
    ]
    if weak_risk:
        recs.append("Risk overlay coverage is incomplete in at least one anchor; stress-share conclusions are coverage-limited.")
    recs.append("Prefer config-only changes first: thresholds, layer weights, market lookbacks, and macro bucket weights.")
    return recs


def _write_html_report(
    path: Path,
    *,
    summaries: Sequence[Mapping[str, Any]],
    diagnostics: Mapping[str, Any],
    recommendations: Sequence[str],
    latest: Mapping[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "<!doctype html>",
                '<html lang="en">',
                "<head>",
                '<meta charset="utf-8">',
                "<title>Regime Engine v2 Calibration Report</title>",
                "<style>",
                _html_css(),
                "</style>",
                "</head>",
                "<body>",
                "<main>",
                "<h1>Regime Engine v2 Calibration Report</h1>",
                '<p class="lede">Research-only sanity check for macro_nowcast and market_implied across historical anchor periods. This report does not produce trading signals or allocation changes.</p>',
                _render_latest(latest),
                _render_diagnostics(diagnostics),
                _render_anchor_table(summaries),
                _render_recommendations(recommendations),
                _render_period_cards(summaries),
                "</main>",
                "</body>",
                "</html>",
            ]
        ),
        encoding="utf-8",
    )


def _write_review_notebook(
    path: Path,
    *,
    summaries: Sequence[Mapping[str, Any]],
    diagnostics: Mapping[str, Any],
    recommendations: Sequence[str],
    html_path: Path,
    daily_json_path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cells = [
        _markdown_cell(
            "# Regime Engine v2 Calibration Questions\n\n"
            f"Observation: The static HTML report is `{html_path}` and the daily calibration JSON is `{daily_json_path}`.\n\n"
            "Question: Should the next iteration prioritize config-only threshold/weight changes, or deeper signal normalization changes?"
        ),
        _markdown_cell(
            "## Data Coverage\n\n"
            f"Observation: Macro panel is {_availability_text(diagnostics.get('macro_panel', {}))}; market panel is {_availability_text(diagnostics.get('market_panel', {}))}.\n\n"
            "Question: Should we require full-history market coverage before making any market_implied or risk-overlay calibration decision?"
        ),
    ]
    for summary in summaries:
        cells.append(
            _markdown_cell(
                f"## {summary['name']}\n\n"
                f"Observation: {summary.get('observation', '')}\n\n"
                f"Question: {summary.get('review_question', '')}"
            )
        )
    cells.append(
        _markdown_cell(
            "## Recommended Next Config Pass\n\n"
            f"Observation: {' '.join(recommendations)}\n\n"
            "Question: Which recommendation should be implemented first in the next calibration iteration?"
        )
    )
    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "pygments_lexer": "ipython3"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path.write_text(json.dumps(notebook, indent=2), encoding="utf-8")


def _render_latest(latest: Mapping[str, Any]) -> str:
    return (
        '<section class="panel">'
        "<h2>Latest Engine Row</h2>"
        '<div class="kpis">'
        f"<div><span>Date</span><strong>{escape(str(latest.get('date', '')))}</strong></div>"
        f"<div><span>Final Regime</span><strong>{escape(str(latest.get('final_regime', '')))}</strong></div>"
        f"<div><span>Confidence</span><strong>{escape(str(latest.get('confidence', '')))}</strong></div>"
        f"<div><span>Disagreement</span><strong>{'Yes' if latest.get('disagreement_flag') else 'No'}</strong></div>"
        "</div>"
        "</section>"
    )


def _render_diagnostics(diagnostics: Mapping[str, Any]) -> str:
    rows = []
    for name in ("macro_panel", "market_panel"):
        item = diagnostics.get(name, {})
        rows.append(
            "<tr>"
            f"<td>{escape(name)}</td>"
            f"<td>{'Available' if item.get('available') else 'Missing'}</td>"
            f"<td>{escape(str(item.get('start') or ''))}</td>"
            f"<td>{escape(str(item.get('end') or ''))}</td>"
            f"<td>{escape(str(item.get('rows') or ''))}</td>"
            f"<td><code>{escape(str(item.get('path') or ''))}</code></td>"
            "</tr>"
        )
    return (
        '<section class="panel">'
        "<h2>Input Coverage</h2>"
        "<table><thead><tr><th>Panel</th><th>Status</th><th>Start</th><th>End</th><th>Rows</th><th>Path</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        "</section>"
    )


def _render_anchor_table(summaries: Sequence[Mapping[str, Any]]) -> str:
    rows = []
    for item in summaries:
        rows.append(
            "<tr>"
            f"<td>{escape(str(item['name']))}</td>"
            f"<td>{escape(str(item['start']))} to {escape(str(item['end']))}</td>"
            f"<td>{escape(str(item.get('final_regime_majority') or 'Unavailable'))}</td>"
            f"<td>{_fmt_pct(item.get('stress_share'))}</td>"
            f"<td>{_fmt_pct(item.get('disagreement_share'))}</td>"
            f"<td>{_fmt_pct(item.get('macro_coverage_share'))}</td>"
            f"<td>{_fmt_pct(item.get('market_coverage_share'))}</td>"
            f"<td>{_fmt_pct(item.get('risk_coverage_share'))}</td>"
            f"<td>{_fmt_num(item.get('macro_growth_mean'))} / {_fmt_num(item.get('macro_inflation_mean'))}</td>"
            f"<td>{_fmt_num(item.get('market_growth_mean'))} / {_fmt_num(item.get('market_inflation_mean'))}</td>"
            "</tr>"
        )
    return (
        '<section class="panel">'
        "<h2>Anchor Period Summary</h2>"
        "<table><thead><tr><th>Period</th><th>Window</th><th>Majority Regime</th><th>Stress</th><th>Disagreement</th><th>Macro Cover</th><th>Market Cover</th><th>Risk Cover</th><th>Macro G/I</th><th>Market G/I</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        "</section>"
    )


def _render_recommendations(recommendations: Sequence[str]) -> str:
    items = "".join(f"<li>{escape(item)}</li>" for item in recommendations)
    return f'<section class="panel"><h2>Recommended Config Review</h2><ul>{items}</ul></section>'


def _render_period_cards(summaries: Sequence[Mapping[str, Any]]) -> str:
    cards = []
    for item in summaries:
        contributors = ", ".join(
            f"{name} ({value:.2f})" for name, value in item.get("top_contributors", [])[:5]
        )
        cards.append(
            '<article class="period-card">'
            f"<h3>{escape(str(item['name']))}</h3>"
            f"<p><strong>Expected:</strong> {escape(str(item.get('expected_behavior', '')))}</p>"
            f"<p><strong>Observation:</strong> {escape(str(item.get('observation', '')))}</p>"
            f"<p><strong>Question:</strong> {escape(str(item.get('review_question', '')))}</p>"
            f"<p><strong>Top contributors:</strong> {escape(contributors or 'Not available')}</p>"
            "</article>"
        )
    return f'<section class="periods"><h2>Review Notes</h2>{"".join(cards)}</section>'


def _html_css() -> str:
    return """
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #172033; background: #f7f8fa; }
main { max-width: 1180px; margin: 0 auto; padding: 32px 24px 56px; }
h1 { margin: 0 0 8px; font-size: 32px; letter-spacing: 0; }
h2 { margin: 0 0 16px; font-size: 20px; }
h3 { margin: 0 0 10px; font-size: 17px; }
.lede { max-width: 860px; color: #526070; margin: 0 0 24px; }
.panel, .period-card { background: #fff; border: 1px solid #d9dee7; border-radius: 8px; padding: 18px; margin: 18px 0; }
.kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.kpis div { border: 1px solid #e1e6ee; border-radius: 6px; padding: 12px; background: #fbfcfe; }
.kpis span { display: block; color: #667085; font-size: 12px; margin-bottom: 6px; }
.kpis strong { font-size: 15px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 9px 8px; border-bottom: 1px solid #e3e7ee; vertical-align: top; }
th { color: #475467; background: #f1f4f8; }
code { font-size: 12px; }
ul { margin: 0; padding-left: 20px; }
.periods { margin-top: 22px; }
@media (max-width: 800px) { .kpis { grid-template-columns: 1fr; } table { display: block; overflow-x: auto; } }
"""


def _markdown_cell(source: str) -> dict[str, Any]:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def _availability_text(item: Mapping[str, Any]) -> str:
    if not item.get("available"):
        return f"missing at `{item.get('path', '')}`"
    return f"available from {item.get('start')} to {item.get('end')} with {item.get('rows')} rows"


def _anchor_observation(
    anchor: AnchorPeriod,
    *,
    final_counts: Sequence[tuple[str, int]],
    stress_share: float,
    disagreement_share: float,
    macro_coverage: float,
    market_coverage: float,
    risk_coverage: float,
    macro_growth: float | None,
    macro_inflation: float | None,
    market_growth: float | None,
    market_inflation: float | None,
) -> str:
    majority = final_counts[0][0] if final_counts else "Unavailable"
    macro = "macro unavailable" if macro_growth is None and macro_inflation is None else f"macro G/I {macro_growth:.2f}/{macro_inflation:.2f}"
    market = "market unavailable" if market_growth is None and market_inflation is None else f"market G/I {market_growth:.2f}/{market_inflation:.2f}"
    return (
        f"{anchor.name} majority regime is {majority}; stress share {stress_share:.0%}; "
        f"disagreement share {disagreement_share:.0%}; coverage macro/market/risk "
        f"{macro_coverage:.0%}/{market_coverage:.0%}/{risk_coverage:.0%}; {macro}; {market}."
    )


def _value_counts(series: pd.Series) -> list[tuple[str, int]]:
    counts = series.fillna("").astype(str).value_counts()
    return [(str(key), int(value)) for key, value in counts.items()]


def _mean_optional(series: pd.Series) -> float | None:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return None
    return float(clean.mean())


def _score_coverage(frame: pd.DataFrame, growth_col: str, inflation_col: str) -> float:
    growth = pd.to_numeric(frame[growth_col], errors="coerce")
    inflation = pd.to_numeric(frame[inflation_col], errors="coerce")
    return float((growth.notna() & inflation.notna()).mean())


def _aggregate_top_contributors(series: pd.Series) -> list[tuple[str, float]]:
    totals: dict[str, float] = {}
    for row in series:
        if not isinstance(row, list):
            continue
        for item in row:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                totals[str(item[0])] = totals.get(str(item[0]), 0.0) + abs(float(item[1]))
    return sorted(totals.items(), key=lambda item: item[1], reverse=True)[:8]


def _fmt_pct(value: object) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.0%}"
    except (TypeError, ValueError):
        return ""


def _fmt_num(value: object) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return ""


__all__ = [
    "ANCHOR_PERIODS",
    "AnchorPeriod",
    "CalibrationArtifacts",
    "run_regime_v2_calibration",
    "summarize_anchor_periods",
    "summarize_anchor_period_rows",
]
