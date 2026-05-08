from __future__ import annotations

"""Standalone HTML report for regime-detection artifacts."""

import html
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from market_helper.common.datetime_display import format_local_datetime
from market_helper.reporting._design_tokens import design_tokens_css


@dataclass(frozen=True)
class RegimeHtmlMethodRow:
    method: str
    quadrant: str
    native_label: str


@dataclass(frozen=True)
class RegimeHtmlLayerRow:
    layer_name: str
    enabled: bool
    available: bool
    status: str
    growth_score: float | None
    inflation_score: float | None
    growth_state: str
    inflation_state: str
    confidence: str | None = None
    top_positive_contributors: list[str] = field(default_factory=list)
    top_negative_contributors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RegimeHtmlRiskOverlay:
    risk_score: float | None
    liquidity_score: float | None
    risk_overlay_on: bool | None
    risk_state: str
    confidence: str | None = None
    top_positive_contributors: list[str] = field(default_factory=list)
    top_negative_contributors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RegimeHtmlTimelineRow:
    as_of: str
    regime: str
    method_agreement: float | None
    crisis_flag: bool | None
    crisis_intensity: float | None
    duration_days: int | None


@dataclass(frozen=True)
class RegimeHtmlAxisHistoryPoint:
    """One snapshot's axis scores — for sparklines under each factor's KPI."""
    as_of: str
    growth: float | None
    inflation: float | None


@dataclass(frozen=True)
class RegimeHtmlMethodVoteHistoryPoint:
    """One snapshot's per-method quadrant call — for the heat-strip visual."""
    as_of: str
    quadrants: dict[str, str]
    crisis_flag: bool | None


@dataclass(frozen=True)
class RegimeHtmlTransitionEvent:
    """A regime label change between two consecutive snapshots."""
    as_of: str
    from_regime: str
    to_regime: str
    crisis_intensity: float | None
    duration_days: int | None


@dataclass(frozen=True)
class RegimeHtmlViewModel:
    schema: str
    as_of: str
    regime: str
    scores: dict[str, float]
    method_agreement: float | None
    crisis_flag: bool | None
    crisis_intensity: float | None
    duration_days: int | None
    methods: list[RegimeHtmlMethodRow]
    timeline: list[RegimeHtmlTimelineRow]
    regime_counts: dict[str, int]
    # P5 additions — derived from the same snapshots payload, no new I/O.
    axes_history: list[RegimeHtmlAxisHistoryPoint] = field(default_factory=list)
    method_vote_history: list[RegimeHtmlMethodVoteHistoryPoint] = field(default_factory=list)
    transitions: list[RegimeHtmlTransitionEvent] = field(default_factory=list)
    confidence: str | None = None
    disagreement_flag: bool | None = None
    disagreement_summary: str | None = None
    risk_state: str | None = None
    base_regime: str | None = None
    layers: list[RegimeHtmlLayerRow] = field(default_factory=list)
    risk_overlay: RegimeHtmlRiskOverlay | None = None
    top_contributors: list[str] = field(default_factory=list)


def build_regime_html_view_model(
    *,
    regime_path: str | Path,
    policy_path: str | Path | None = None,
) -> RegimeHtmlViewModel:
    payload = json.loads(Path(regime_path).read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("Regime HTML report requires a non-empty JSON array")
    latest = payload[-1]
    if not isinstance(latest, dict):
        raise ValueError("Regime HTML report requires object rows")
    return _build_v2_view_model(payload)


def render_regime_section_body(
    view_model: RegimeHtmlViewModel,
    *,
    parent_as_of: str | None = None,
) -> str:
    """Render the regime section as a body fragment.

    Used both by the standalone CLI artifact (wrapped in a minimal HTML shell by
    :func:`render_regime_html_report`) and by the combined portfolio report
    (embedded directly as a `ReportSection.body_html`). When `parent_as_of` is
    supplied and the regime view-model's `as_of` lags by more than one day, a
    small `regime stale` tag is appended to the headline so the reader knows the
    regime call may not match the report's positions/perf as-of (P3).
    """
    stale_tag = ""
    if _regime_is_stale(view_model.as_of, parent_as_of):
        stale_tag = " <span class='tag tag--warning regime-stale-tag'>regime stale</span>"
    if _is_v2_view_model(view_model):
        return _render_v2_regime_section_body(view_model, stale_tag=stale_tag)
    return (
        "<header class='regime-section__header'>"
        "<div>"
        "<p class='regime-eyebrow'>Regime Detection</p>"
        f"<h2 class='regime-headline'>{html.escape(view_model.regime)}{stale_tag}</h2>"
        f"<p class='regime-meta'>As of {html.escape(format_local_datetime(view_model.as_of))} · {html.escape(view_model.schema)}</p>"
        "</div>"
        f"{_render_status_cards(view_model)}"
        "</header>"
        f"{_render_scores(view_model)}"
        f"{_render_crisis_intensity_chart(view_model)}"
        f"{_render_method_vote_strip(view_model)}"
        f"{_render_transitions(view_model)}"
        f"{_render_methods(view_model.methods)}"
        f"{_render_timeline(view_model.timeline)}"
        f"{_render_counts(view_model.regime_counts)}"
    )


def _render_v2_regime_section_body(
    view_model: RegimeHtmlViewModel,
    *,
    stale_tag: str,
) -> str:
    base_line = ""
    if view_model.base_regime:
        base_line = (
            "<p class='regime-base-line'>"
            f"<span>Base Regime</span><strong>{html.escape(view_model.base_regime)}</strong>"
            "</p>"
        )
    return (
        "<header class='regime-v2-hero'>"
        "<div class='regime-v2-hero__main'>"
        "<p class='regime-eyebrow'>Regime Engine v2</p>"
        f"<h2 class='regime-headline'>{html.escape(view_model.regime)}{stale_tag}</h2>"
        f"{base_line}"
        f"<p class='regime-meta'>As of {html.escape(format_local_datetime(view_model.as_of))} · two macro axes with independent risk overlay</p>"
        "</div>"
        f"{_render_status_cards(view_model)}"
        "</header>"
        f"{_render_v2_disagreement(view_model)}"
        f"{_render_v2_axis_panel(view_model)}"
        f"{_render_v2_layer_detail(view_model)}"
        f"{_render_v2_risk_overlay(view_model)}"
        f"{_render_v2_top_contributors(view_model)}"
        f"{_render_crisis_intensity_chart(view_model)}"
        f"{_render_method_vote_strip(view_model)}"
        f"{_render_transitions(view_model)}"
        f"{_render_timeline(view_model.timeline, is_v2=True)}"
        f"{_render_counts(view_model.regime_counts)}"
    )


def _regime_is_stale(regime_as_of: str | None, parent_as_of: str | None) -> bool:
    """Return True when the regime as-of lags the parent report's as-of by > 1 day."""
    if not regime_as_of or not parent_as_of:
        return False
    try:
        from datetime import datetime as _dt, timedelta as _td

        def _parse(value: str) -> "_dt":
            return _dt.fromisoformat(value.replace("Z", "+00:00"))

        regime_dt = _parse(regime_as_of)
        parent_dt = _parse(parent_as_of)
    except (ValueError, TypeError):
        return False
    # Reconcile mixed tz-aware / tz-naive inputs by stripping tzinfo from the
    # aware one — for the >1-day staleness check, sub-day timezone offsets are
    # noise.
    if (regime_dt.tzinfo is None) != (parent_dt.tzinfo is None):
        regime_dt = regime_dt.replace(tzinfo=None)
        parent_dt = parent_dt.replace(tzinfo=None)
    return parent_dt - regime_dt > _td(days=1)


def render_regime_html_report(view_model: RegimeHtmlViewModel) -> str:
    return (
        "<!doctype html>"
        "<html lang='en'>"
        "<head>"
        "<meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Regime Report</title>"
        f"<style>{_styles()}</style>"
        "</head>"
        "<body class='regime-standalone'>"
        "<main class='regime-shell'>"
        f"{render_regime_section_body(view_model)}"
        "</main>"
        "</body>"
        "</html>"
    )


def write_regime_html_report(
    *,
    regime_path: str | Path,
    output_path: str | Path,
    policy_path: str | Path | None = None,
) -> Path:
    view_model = build_regime_html_view_model(
        regime_path=regime_path,
        policy_path=policy_path,
    )
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_regime_html_report(view_model), encoding="utf-8")
    return out


def _build_v2_view_model(payload: list[Any]) -> RegimeHtmlViewModel:
    rows = [dict(row) for row in payload if isinstance(row, dict)]
    latest = rows[-1]
    latest_layer_outputs = (
        latest.get("layer_outputs") if isinstance(latest.get("layer_outputs"), list) else []
    )
    layers = [
        _build_v2_layer_row(layer)
        for layer in latest_layer_outputs
        if isinstance(layer, dict)
    ]
    axes_history = [
        RegimeHtmlAxisHistoryPoint(
            as_of=str(row.get("date") or ""),
            growth=_optional_float(row.get("final_growth_score")),
            inflation=_optional_float(row.get("final_inflation_score")),
        )
        for row in rows[-180:]
    ]
    method_vote_history = [
        RegimeHtmlMethodVoteHistoryPoint(
            as_of=str(row.get("date") or ""),
            quadrants={
                str(layer.get("layer_name")): _layer_label(layer)
                for layer in row.get("layer_outputs", [])
                if isinstance(layer, dict)
            },
            crisis_flag=bool(row.get("risk_overlay_on")),
        )
        for row in rows[-30:]
    ]
    transitions: list[RegimeHtmlTransitionEvent] = []
    for prev, curr in zip(rows, rows[1:]):
        if prev.get("final_regime") != curr.get("final_regime"):
            transitions.append(
                RegimeHtmlTransitionEvent(
                    as_of=str(curr.get("date") or ""),
                    from_regime=str(prev.get("final_regime") or "Unknown"),
                    to_regime=str(curr.get("final_regime") or "Unknown"),
                    crisis_intensity=_optional_float(curr.get("risk_score")),
                    duration_days=None,
                )
            )
    risk_output = latest.get("risk_output") if isinstance(latest.get("risk_output"), dict) else {}
    risk_overlay_on = _optional_bool(
        latest.get("risk_overlay_on", risk_output.get("risk_overlay_on"))
    )
    risk_overlay = RegimeHtmlRiskOverlay(
        risk_score=_optional_float(risk_output.get("risk_score", latest.get("risk_score"))),
        liquidity_score=_optional_float(risk_output.get("liquidity_score")),
        risk_overlay_on=risk_overlay_on,
        risk_state=str(risk_output.get("risk_state") or latest.get("risk_state") or ""),
        confidence=_format_confidence(risk_output.get("confidence")),
        top_positive_contributors=_contributors_to_strings(
            risk_output.get("top_positive_contributors")
        ),
        top_negative_contributors=_contributors_to_strings(
            risk_output.get("top_negative_contributors")
        ),
    )
    return RegimeHtmlViewModel(
        schema=str(latest.get("version") or "regime-engine-v2"),
        as_of=str(latest.get("date") or ""),
        regime=str(latest.get("final_regime") or "Unknown"),
        scores={
            "GROWTH": float(latest.get("final_growth_score") or 0.0),
            "INFLATION": float(latest.get("final_inflation_score") or 0.0),
            "RISK": float(latest.get("risk_score") or 0.0),
        },
        method_agreement=None,
        crisis_flag=risk_overlay_on,
        crisis_intensity=_optional_float(latest.get("risk_score")),
        duration_days=None,
        methods=[
            RegimeHtmlMethodRow(
                method=str(layer.get("layer_name") or "unknown"),
                quadrant=_layer_label(layer),
                native_label=_layer_status(layer),
            )
            for layer in latest_layer_outputs
            if isinstance(layer, dict)
        ],
        timeline=[
            RegimeHtmlTimelineRow(
                as_of=str(row.get("date") or ""),
                regime=str(row.get("final_regime") or "Unknown"),
                method_agreement=None,
                crisis_flag=_optional_bool(row.get("risk_overlay_on")),
                crisis_intensity=_optional_float(row.get("risk_score")),
                duration_days=None,
            )
            for row in rows[-60:]
        ],
        regime_counts=dict(Counter(str(row.get("final_regime") or "Unknown") for row in rows)),
        axes_history=axes_history,
        method_vote_history=method_vote_history,
        transitions=transitions[-8:],
        confidence=str(latest.get("confidence") or ""),
        disagreement_flag=_optional_bool(latest.get("disagreement_flag")),
        disagreement_summary=str(latest.get("disagreement_summary") or ""),
        risk_state=risk_overlay.risk_state,
        base_regime=str(latest.get("base_regime") or ""),
        layers=layers,
        risk_overlay=risk_overlay,
        top_contributors=_contributors_to_strings(latest.get("top_contributors")),
    )


def _render_status_cards(view_model: RegimeHtmlViewModel) -> str:
    cards: list[tuple[str, str]] = []
    if view_model.confidence:
        cards.append(("Confidence", view_model.confidence))
    if view_model.disagreement_flag is not None:
        cards.append(("Disagreement", "Yes" if view_model.disagreement_flag else "No"))
    if _is_v2_view_model(view_model):
        cards.extend(
            [
                ("Risk Overlay", _format_bool(view_model.crisis_flag)),
                ("Risk State", view_model.risk_state or "n/a"),
            ]
        )
    elif view_model.risk_state:
        cards.append(("Risk", view_model.risk_state))
    if view_model.method_agreement is not None:
        cards.append(("Agreement", _format_percent(view_model.method_agreement)))
    if not _is_v2_view_model(view_model):
        cards.extend(
            [
                ("Crisis", _format_bool(view_model.crisis_flag)),
                ("Intensity", _format_float(view_model.crisis_intensity)),
                ("Duration", _format_days(view_model.duration_days)),
            ]
        )
    return (
        "<section class='status-grid'>"
        + "".join(
            "<div class='status-card'>"
            f"<span>{html.escape(label)}</span>"
            f"<strong>{html.escape(value)}</strong>"
            "</div>"
            for label, value in cards
        )
        + "</section>"
    )


def _render_v2_disagreement(view_model: RegimeHtmlViewModel) -> str:
    if view_model.disagreement_flag is None and not view_model.disagreement_summary:
        return ""
    tone = "is-on" if view_model.disagreement_flag else "is-off"
    label = "Disagreement: Yes" if view_model.disagreement_flag else "Disagreement: No"
    summary = view_model.disagreement_summary or (
        "Layer outputs are aligned enough for the current ensemble."
    )
    return (
        f"<section class='panel regime-v2-disagreement {tone}'>"
        "<div>"
        f"<h2>{html.escape(label)}</h2>"
        f"<p>{html.escape(summary)}</p>"
        "</div>"
        "</section>"
    )


def _render_v2_axis_panel(view_model: RegimeHtmlViewModel) -> str:
    growth = view_model.scores.get("GROWTH")
    inflation = view_model.scores.get("INFLATION")
    rows = [
        _render_v2_axis_card("Growth", growth, _axis_state(growth)),
        _render_v2_axis_card("Inflation", inflation, _axis_state(inflation)),
    ]
    return (
        "<section class='panel regime-v2-axis-panel'>"
        "<header class='regime-panel__header'>"
        "<h2>Growth / Inflation Axes</h2>"
        "<span class='regime-panel__meta'>final ensemble scores</span>"
        "</header>"
        f"<div class='regime-v2-axis-grid'>{''.join(rows)}</div>"
        "</section>"
    )


def _render_v2_axis_card(name: str, value: float | None, state: str) -> str:
    numeric = float(value or 0.0)
    clamped = max(-1.0, min(1.0, numeric))
    width = abs(clamped) * 50.0
    if clamped >= 0:
        fill = (
            f"<i class='axis-meter__fill axis-meter__fill--pos' "
            f"style='left:50%;width:{width:.1f}%'></i>"
        )
    else:
        fill = (
            f"<i class='axis-meter__fill axis-meter__fill--neg' "
            f"style='left:{50.0 - width:.1f}%;width:{width:.1f}%'></i>"
        )
    return (
        "<article class='regime-v2-axis-card'>"
        f"<span>{html.escape(name)}</span>"
        f"<strong>{_format_signed(value)}</strong>"
        f"<em>{html.escape(state)}</em>"
        "<div class='axis-meter'>"
        "<b class='axis-meter__mid'></b>"
        f"{fill}"
        "</div>"
        "</article>"
    )


def _render_v2_layer_detail(view_model: RegimeHtmlViewModel) -> str:
    if not view_model.layers:
        return _render_methods(view_model.methods)
    rows = []
    for layer in view_model.layers:
        status_class = _status_class(layer.status)
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(layer.layer_name)}</strong></td>"
            f"<td><span class='status-pill {status_class}'>{html.escape(layer.status)}</span></td>"
            f"<td>{html.escape(layer.growth_state or 'n/a')} <span class='num-muted'>{_format_signed(layer.growth_score)}</span></td>"
            f"<td>{html.escape(layer.inflation_state or 'n/a')} <span class='num-muted'>{_format_signed(layer.inflation_score)}</span></td>"
            f"<td>{html.escape(layer.confidence or 'n/a')}</td>"
            "</tr>"
        )
    return (
        "<section class='panel regime-v2-layer-detail'>"
        "<header class='regime-panel__header'>"
        "<h2>Layer Detail</h2>"
        "<span class='regime-panel__meta'>enabled + available layers with positive weights drive the ensemble</span>"
        "</header>"
        "<table><thead><tr><th>Layer</th><th>Status</th><th>Growth</th><th>Inflation</th><th>Confidence</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        "</section>"
    )


def _render_v2_risk_overlay(view_model: RegimeHtmlViewModel) -> str:
    risk = view_model.risk_overlay
    if risk is None:
        return ""
    state = risk.risk_state or "n/a"
    overlay = _format_bool(risk.risk_overlay_on)
    metrics = [
        ("Overlay", overlay),
        ("State", state),
        ("Risk Score", _format_float(risk.risk_score)),
    ]
    if risk.liquidity_score is not None:
        metrics.append(("Liquidity", _format_float(risk.liquidity_score)))
    if risk.confidence:
        metrics.append(("Confidence", risk.confidence))
    contributors = _render_inline_contributors(
        risk.top_positive_contributors,
        risk.top_negative_contributors,
    )
    return (
        "<section class='panel regime-v2-risk'>"
        "<header class='regime-panel__header'>"
        "<h2>Independent Risk Overlay</h2>"
        "<span class='regime-panel__meta'>risk is shown separately from growth and inflation</span>"
        "</header>"
        "<div class='regime-v2-risk__grid'>"
        + "".join(
            "<div class='mini-stat'>"
            f"<span>{html.escape(label)}</span><strong>{html.escape(value)}</strong>"
            "</div>"
            for label, value in metrics
        )
        + "</div>"
        f"{contributors}"
        "</section>"
    )


def _render_v2_top_contributors(view_model: RegimeHtmlViewModel) -> str:
    if not view_model.top_contributors:
        layer_contributors: list[str] = []
        for layer in view_model.layers:
            layer_contributors.extend(layer.top_positive_contributors[:2])
            layer_contributors.extend(layer.top_negative_contributors[:2])
        contributors = layer_contributors[:8]
    else:
        contributors = view_model.top_contributors[:10]
    if not contributors:
        return ""
    return (
        "<section class='panel regime-v2-contributors'>"
        "<h2>Top Contributors</h2>"
        "<div class='contributor-list'>"
        + "".join(f"<span>{html.escape(item)}</span>" for item in contributors)
        + "</div>"
        "</section>"
    )


def _render_scores(view_model: RegimeHtmlViewModel) -> str:
    if not view_model.scores:
        return ""
    history_by_axis: dict[str, list[float | None]] = {}
    if view_model.axes_history:
        history_by_axis = {
            "GROWTH": [point.growth for point in view_model.axes_history],
            "INFLATION": [point.inflation for point in view_model.axes_history],
        }
    rows = []
    for name, value in sorted(view_model.scores.items()):
        spark = _render_axis_sparkline(history_by_axis.get(name) or [], axis_label=name)
        tone = "tone-positive" if value > 0 else ("tone-negative" if value < 0 else "tone-muted")
        rows.append(
            "<div class='score-row'>"
            f"<span>{html.escape(name)}</span>"
            f"<strong class='{tone}'>{value:+.2f}</strong>"
            f"<div class='score-spark'>{spark}</div>"
            "</div>"
        )
    return (
        "<section class='panel'>"
        "<h2>Factor Scores</h2>"
        f"<div class='score-grid'>{''.join(rows)}</div>"
        "</section>"
    )


def _render_axis_sparkline(values: list[float | None], *, axis_label: str = "") -> str:
    series = [float(v) for v in values if v is not None]
    if len(series) < 2:
        return ""
    width, height = 100.0, 28.0
    lo = min(series)
    hi = max(series)
    span = max(hi - lo, 1e-9)
    step = width / max(len(series) - 1, 1)
    points = " ".join(
        f"{i * step:.1f},{height - ((value - lo) / span) * height:.1f}"
        for i, value in enumerate(series)
    )
    first = series[0]
    last = series[-1]
    stroke = "var(--pos)" if last > 0 else ("var(--neg)" if last < 0 else "var(--muted-2)")
    # P10/M3: announce the sparkline as a meaningful image rather than hiding it.
    # The label includes axis name + trend direction so screen-reader users get
    # the same gist as a sighted reader sees from the polyline shape.
    direction = "rising" if last > first else ("falling" if last < first else "flat")
    pretty_axis = axis_label.title() if axis_label else "axis"
    aria_label = f"{pretty_axis} score history ({direction}, latest {last:+.2f})"
    return (
        f"<svg viewBox='0 0 {width:.0f} {height:.0f}' preserveAspectRatio='none' "
        f"role='img' aria-label='{html.escape(aria_label)}'>"
        f"<polyline fill='none' stroke='{stroke}' stroke-width='1.5' points='{points}'/>"
        "</svg>"
    )


_QUADRANT_CLASSES = {
    "Goldilocks": "regime-cell--goldilocks",
    "Reflation": "regime-cell--reflation",
    "Stagflation": "regime-cell--stagflation",
    "Slowdown": "regime-cell--slowdown",
    "Deflationary Slowdown": "regime-cell--slowdown",
    "Crisis": "regime-cell--crisis",
    "Up / Down": "regime-cell--goldilocks",
    "Up / Neutral": "regime-cell--goldilocks",
    "Up / Mixed": "regime-cell--goldilocks",
    "Up / Up": "regime-cell--reflation",
    "Down / Up": "regime-cell--stagflation",
    "Down / Down": "regime-cell--slowdown",
    "Down / Neutral": "regime-cell--slowdown",
    "Neutral / Up": "regime-cell--stagflation",
    "Neutral / Down": "regime-cell--slowdown",
    "Neutral / Neutral": "regime-cell--unknown",
    "Disabled": "regime-cell--unknown",
    "Not available": "regime-cell--unknown",
}


def _render_crisis_intensity_chart(view_model: RegimeHtmlViewModel) -> str:
    timeline = view_model.timeline
    if not timeline:
        return ""
    # Plot the full timeline (treating None as 0.0) so the X-axis runs through
    # the latest snapshot rather than stopping at the last historical spike (B3).
    # The metadata strip's "current" reflects the live ensemble state from
    # `view_model.crisis_intensity` / `view_model.as_of`, not the filtered series.
    points = list(reversed(timeline))  # timeline is newest-first; chart oldest-first
    width, height = 600.0, 96.0
    threshold = 0.6
    series = [float(row.crisis_intensity if row.crisis_intensity is not None else 0.0) for row in points]
    step = width / max(len(series) - 1, 1)
    line = " ".join(
        f"{i * step:.1f},{height - min(max(value, 0.0), 1.0) * height:.1f}"
        for i, value in enumerate(series)
    )
    threshold_y = height - threshold * height
    last_x = (len(series) - 1) * step
    last_y = height - min(max(series[-1], 0.0), 1.0) * height
    current_value = view_model.crisis_intensity if view_model.crisis_intensity is not None else 0.0
    current_when = format_local_datetime(view_model.as_of)
    is_v2 = _is_v2_view_model(view_model)
    title = "Risk Overlay Score" if is_v2 else "Crisis Intensity"
    aria_label = "Risk overlay score over time" if is_v2 else "Crisis intensity over time"
    return (
        "<section class='panel regime-crisis'>"
        "<header class='regime-panel__header'>"
        f"<h2>{html.escape(title)}</h2>"
        f"<span class='regime-panel__meta'>threshold {threshold:.1f} · current {current_value:.2f} · {html.escape(current_when)}</span>"
        "</header>"
        "<div class='regime-crisis__chart'>"
        f"<svg viewBox='0 0 {width:.0f} {height:.0f}' preserveAspectRatio='none' role='img' aria-label='{html.escape(aria_label)}'>"
        f"<line x1='0' y1='{threshold_y:.1f}' x2='{width:.0f}' y2='{threshold_y:.1f}' stroke='var(--neg-soft)' stroke-dasharray='3 3'/>"
        f"<polyline fill='none' stroke='var(--neg)' stroke-width='1.5' points='{line}'/>"
        f"<polygon fill='var(--neg-soft)' opacity='0.6' points='{line} {last_x:.1f},{height:.1f} 0,{height:.1f}'/>"
        f"<circle cx='{last_x:.1f}' cy='{last_y:.1f}' r='3' fill='var(--neg)'/>"
        "</svg>"
        "</div>"
        "</section>"
    )


def _render_method_vote_strip(view_model: RegimeHtmlViewModel) -> str:
    history = view_model.method_vote_history
    if not history:
        return ""
    method_names: list[str] = []
    for point in history:
        for name in point.quadrants.keys():
            if name not in method_names:
                method_names.append(name)
    if not method_names:
        return ""
    rows_html: list[str] = ["<div class='method-strip__head'>"]
    rows_html.append("<span class='method-strip__lbl'>&nbsp;</span>")
    for idx in range(len(history)):
        rows_html.append(
            f"<span class='method-strip__col-head'>{idx + 1 if (idx + 1) % 5 == 0 else ''}</span>"
        )
    rows_html.append("</div>")
    for method in method_names:
        rows_html.append("<div class='method-strip__row'>")
        rows_html.append(f"<span class='method-strip__lbl'>{html.escape(method)}</span>")
        for point in history:
            quadrant = point.quadrants.get(method, "")
            # Each cell reflects only its own method's vote — the crisis overlay has
            # its own dedicated row + the crisis-intensity chart, so we no longer
            # repaint every cell red on a crisis-flagged session (B2). Doing so
            # made the title (the literal vote) disagree with the colour.
            cls = _QUADRANT_CLASSES.get(quadrant, "regime-cell--unknown")
            label = quadrant or "n/a"
            rows_html.append(
                f"<span class='method-strip__cell {cls}' title='{html.escape(point.as_of)} · {html.escape(label)}'></span>"
            )
        rows_html.append("</div>")
    if _is_v2_view_model(view_model):
        legend_items = [
            ("Up / Down", "regime-cell--goldilocks"),
            ("Up / Up", "regime-cell--reflation"),
            ("Down / Up", "regime-cell--stagflation"),
            ("Down / Down", "regime-cell--slowdown"),
            ("Disabled / N/A", "regime-cell--unknown"),
        ]
        title = "Layer-State Heat Strip"
    else:
        legend_items = [
            ("Goldilocks", "regime-cell--goldilocks"),
            ("Reflation", "regime-cell--reflation"),
            ("Stagflation", "regime-cell--stagflation"),
            ("Slowdown", "regime-cell--slowdown"),
            ("Crisis", "regime-cell--crisis"),
        ]
        title = "Method-Vote Heat Strip"
    legend = "".join(
        f"<span class='method-strip__legend-item'><span class='method-strip__cell {cls}'></span>{html.escape(label)}</span>"
        for label, cls in legend_items
    )
    return (
        "<section class='panel regime-method-strip-panel'>"
        "<header class='regime-panel__header'>"
        f"<h2>{html.escape(title)}</h2>"
        f"<span class='regime-panel__meta'>last {len(history)} sessions</span>"
        "</header>"
        f"<div class='method-strip' style='--method-strip-cols: {len(history)};'>"
        f"{''.join(rows_html)}"
        "</div>"
        f"<div class='method-strip__legend'>{legend}</div>"
        "</section>"
    )


def _render_transitions(view_model: RegimeHtmlViewModel) -> str:
    if not view_model.transitions:
        return ""
    rows = []
    for event in reversed(view_model.transitions):
        intensity_html = ""
        if event.crisis_intensity is not None:
            risk_label = "risk" if _is_v2_view_model(view_model) else "crisis"
            intensity_html = (
                f"<span class='tag tag--warning'>{risk_label} {event.crisis_intensity:.2f}</span>"
            )
        rows.append(
            "<div class='transition-row'>"
            f"<span class='transition-row__date'>{html.escape(format_local_datetime(event.as_of))}</span>"
            f"<span class='transition-row__body'><b>{html.escape(event.from_regime)}</b> "
            f"<span class='transition-row__arrow'>→</span> <b>{html.escape(event.to_regime)}</b></span>"
            f"<span class='transition-row__meta'>{intensity_html}</span>"
            "</div>"
        )
    return (
        "<section class='panel'>"
        "<h2>Regime Transitions</h2>"
        f"<div class='transition-log'>{''.join(rows)}</div>"
        "</section>"
    )


def _render_methods(methods: list[RegimeHtmlMethodRow]) -> str:
    if not methods:
        return ""
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(row.method)}</td>"
        f"<td>{html.escape(row.quadrant)}</td>"
        f"<td>{html.escape(row.native_label or 'n/a')}</td>"
        "</tr>"
        for row in methods
    )
    return (
        "<section class='panel'>"
        "<h2>Layer Detail</h2>"
        "<table><thead><tr><th>Layer</th><th>State</th><th>Status</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        "</section>"
    )


def _render_timeline(rows: list[RegimeHtmlTimelineRow], *, is_v2: bool = False) -> str:
    if not rows:
        return ""
    if is_v2:
        body = "".join(
            "<tr>"
            f"<td>{html.escape(format_local_datetime(row.as_of))}</td>"
            f"<td>{html.escape(row.regime)}</td>"
            f"<td>{html.escape(_format_bool(row.crisis_flag))}</td>"
            f"<td>{html.escape(_format_float(row.crisis_intensity))}</td>"
            "</tr>"
            for row in reversed(rows)
        )
        headers = "<th>Date</th><th>Final Regime</th><th>Risk Overlay</th><th>Risk Score</th>"
    else:
        body = "".join(
            "<tr>"
            f"<td>{html.escape(format_local_datetime(row.as_of))}</td>"
            f"<td>{html.escape(row.regime)}</td>"
            f"<td>{html.escape(_format_percent(row.method_agreement))}</td>"
            f"<td>{html.escape(_format_bool(row.crisis_flag))}</td>"
            f"<td>{html.escape(_format_float(row.crisis_intensity))}</td>"
            f"<td>{html.escape(_format_days(row.duration_days))}</td>"
            "</tr>"
            for row in reversed(rows)
        )
        headers = "<th>Date</th><th>Regime</th><th>Agreement</th><th>Crisis</th><th>Intensity</th><th>Duration</th>"
    return (
        "<section class='panel'>"
        "<h2>Recent History</h2>"
        f"<table><thead><tr>{headers}</tr></thead>"
        f"<tbody>{body}</tbody></table>"
        "</section>"
    )


def _render_counts(counts: dict[str, int]) -> str:
    if not counts:
        return ""
    total = max(1, sum(counts.values()))
    rows = "".join(
        "<div class='count-row'>"
        f"<span>{html.escape(regime)}</span>"
        "<div class='bar'><i style='width:"
        f"{100.0 * count / total:.1f}%"
        "'></i></div>"
        f"<strong>{count}</strong>"
        "</div>"
        for regime, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )
    return (
        "<section class='panel'>"
        "<h2>Full-Sample Distribution</h2>"
        f"<div class='count-grid'>{rows}</div>"
        "</section>"
    )


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.0%}"


def _format_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def _format_bool(value: bool | None) -> str:
    if value is None:
        return "n/a"
    return "on" if value else "off"


def _format_days(value: int | None) -> str:
    if value is None:
        return "n/a"
    return f"{value}d"


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "y", "1", "on"}:
            return True
        if normalized in {"false", "no", "n", "0", "off"}:
            return False
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _is_v2_view_model(view_model: RegimeHtmlViewModel) -> bool:
    return view_model.schema == "regime-engine-v2"


def _build_v2_layer_row(layer: dict[str, Any]) -> RegimeHtmlLayerRow:
    enabled = bool(layer.get("enabled"))
    available = bool(layer.get("available"))
    return RegimeHtmlLayerRow(
        layer_name=str(layer.get("layer_name") or "unknown"),
        enabled=enabled,
        available=available,
        status=_layer_status_label(layer),
        growth_score=_optional_float(layer.get("growth_score")),
        inflation_score=_optional_float(layer.get("inflation_score")),
        growth_state=str(layer.get("growth_state") or ("Disabled" if not enabled else "n/a")),
        inflation_state=str(layer.get("inflation_state") or ("Disabled" if not enabled else "n/a")),
        confidence=_format_confidence(layer.get("confidence")),
        top_positive_contributors=_contributors_to_strings(
            layer.get("top_positive_contributors")
        ),
        top_negative_contributors=_contributors_to_strings(
            layer.get("top_negative_contributors")
        ),
    )


def _layer_status_label(layer: dict[str, Any]) -> str:
    if not bool(layer.get("enabled")):
        return "Disabled"
    if not bool(layer.get("available")):
        return "Not available"
    return "Available"


def _format_confidence(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    numeric = _optional_float(value)
    if numeric is None:
        return str(value)
    return f"{numeric:.2f}"


def _contributors_to_strings(value: object) -> list[str]:
    if not value:
        return []
    if isinstance(value, dict):
        return [
            f"{key}: {_format_contributor_value(val)}"
            for key, val in value.items()
        ]
    if isinstance(value, (list, tuple)):
        return [_contributor_to_string(item) for item in value if item is not None]
    return [str(value)]


def _contributor_to_string(item: object) -> str:
    if isinstance(item, dict):
        name = item.get("name") or item.get("signal") or item.get("feature") or item.get("label")
        value = (
            item.get("value")
            if item.get("value") is not None
            else item.get("score", item.get("contribution"))
        )
        if name and value is not None:
            return f"{name}: {_format_contributor_value(value)}"
        if name:
            return str(name)
        return ", ".join(f"{key}: {_format_contributor_value(val)}" for key, val in item.items())
    if isinstance(item, (list, tuple)) and item:
        if len(item) >= 2:
            return f"{item[0]}: {_format_contributor_value(item[1])}"
        return str(item[0])
    return str(item)


def _format_contributor_value(value: object) -> str:
    numeric = _optional_float(value)
    if numeric is not None:
        return f"{numeric:+.2f}"
    return str(value)


def _axis_state(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value >= 0.35:
        return "Up"
    if value <= -0.35:
        return "Down"
    return "Neutral / Mixed"


def _format_signed(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.2f}"


def _status_class(status: str) -> str:
    normalized = status.lower()
    if "disabled" in normalized:
        return "status-pill--muted"
    if "not available" in normalized or "unavailable" in normalized:
        return "status-pill--warning"
    return "status-pill--ok"


def _render_inline_contributors(
    positive: list[str],
    negative: list[str],
) -> str:
    if not positive and not negative:
        return ""
    groups = []
    if positive:
        groups.append(
            "<div><span>Positive</span>"
            + "".join(f"<b>{html.escape(item)}</b>" for item in positive[:5])
            + "</div>"
        )
    if negative:
        groups.append(
            "<div><span>Negative</span>"
            + "".join(f"<b>{html.escape(item)}</b>" for item in negative[:5])
            + "</div>"
        )
    return f"<div class='inline-contributors'>{''.join(groups)}</div>"


def _layer_label(layer: dict[str, Any]) -> str:
    if not bool(layer.get("enabled")):
        return "Disabled"
    if not bool(layer.get("available")):
        return "Not available"
    return f"{layer.get('growth_state', 'n/a')} / {layer.get('inflation_state', 'n/a')}"


def _layer_status(layer: dict[str, Any]) -> str:
    if not bool(layer.get("enabled")):
        return "Disabled"
    if not bool(layer.get("available")):
        diagnostics = layer.get("diagnostics") if isinstance(layer.get("diagnostics"), dict) else {}
        return str(diagnostics.get("reason") or "Not available")
    confidence = layer.get("confidence")
    formatted = _format_confidence(confidence)
    return f"confidence {formatted}" if formatted is not None else "Available"


def regime_section_styles() -> str:
    """Regime-section CSS that layers on top of `design_tokens_css()`.

    Public so the combined-report shell can include it once when the regime section
    is folded in (P5). The standalone CLI artifact (:func:`render_regime_html_report`)
    composes both blocks.
    """
    return """
    .regime-shell { max-width: 1180px; margin: 0 auto; padding: 24px 16px 40px; display: grid; gap: 16px; color: var(--ink); }
    body.regime-standalone { margin: 0; background: var(--bg); font-family: var(--font-ui); font-size: 14px; line-height: 1.45; }
    .regime-section__header {
      display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 16px; align-items: end;
      padding: 20px 0 8px;
    }
    .regime-eyebrow {
      margin: 0 0 6px; font-size: 11px; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.04em; color: var(--accent);
    }
    .regime-headline { margin: 0; font-size: 28px; line-height: 1.1; font-weight: 700; }
    .regime-stale-tag { margin-left: 12px; font-size: 11px; vertical-align: middle; }
    .regime-meta { margin: 8px 0 0; font-size: 12px; color: var(--muted-ink); }
    .regime-v2-hero {
      display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, 460px);
      gap: 16px; align-items: stretch; padding: 20px 0 8px;
    }
    .regime-v2-hero__main {
      background: var(--surface); border: 1px solid var(--border-soft);
      border-radius: 8px; padding: 18px 20px; box-shadow: var(--shadow-1);
    }
    .regime-base-line {
      display: inline-flex; align-items: center; gap: 8px; margin: 12px 0 0;
      padding: 5px 9px; border-radius: 999px; background: var(--surface-2);
      color: var(--muted-ink); font-size: 12px;
    }
    .regime-base-line span { font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; font-size: 10px; }
    .regime-base-line strong { color: var(--ink); font-weight: 700; }
    .status-grid {
      display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
    }
    .status-card {
      background: var(--surface); border: 1px solid var(--border-soft);
      border-radius: 8px; padding: 10px 12px;
      box-shadow: var(--shadow-1);
    }
    .status-card span {
      display: block; font-size: 11px; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted-ink);
    }
    .status-card strong { display: block; margin-top: 4px; font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--ink); }
    .panel {
      background: var(--surface); border: 1px solid var(--border-soft);
      border-radius: 8px; padding: 16px;
      box-shadow: var(--shadow-1);
    }
    .panel h2 { margin: 0 0 10px; font-size: 13px; font-weight: 700; letter-spacing: 0.02em; }
    .regime-panel__header { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
    .regime-panel__header h2 { margin: 0; }
    .regime-panel__meta { font-size: 12px; color: var(--muted-ink); font-variant-numeric: tabular-nums; }

    .score-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }
    .score-row {
      display: grid; gap: 4px;
      border: 1px solid var(--border-soft); border-radius: 8px;
      padding: 10px 12px; background: var(--surface);
    }
    .score-row span, .count-row span {
      font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted-ink);
    }
    .score-row strong { font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums; }
    .score-spark svg { display: block; width: 100%; height: 28px; }

    .label { margin: 0 0 6px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted-ink); }

    .panel table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .panel th, .panel td { padding: 8px 10px; border-bottom: 1px solid var(--border-soft); text-align: left; vertical-align: top; }
    .panel th { color: var(--muted-ink); font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; background: var(--surface-2); }

    .regime-v2-disagreement { border-left: 4px solid var(--border-soft); }
    .regime-v2-disagreement.is-on { border-left-color: var(--warn); background: var(--warn-soft); }
    .regime-v2-disagreement.is-off { border-left-color: var(--pos); }
    .regime-v2-disagreement h2 { margin-bottom: 4px; }
    .regime-v2-disagreement p { margin: 0; color: var(--ink-2); }

    .regime-v2-axis-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .regime-v2-axis-card {
      display: grid; grid-template-columns: 1fr auto; gap: 8px 12px;
      padding: 14px; border: 1px solid var(--border-soft); border-radius: 8px; background: var(--surface);
    }
    .regime-v2-axis-card span {
      font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted-ink);
    }
    .regime-v2-axis-card strong { font-size: 24px; line-height: 1; font-variant-numeric: tabular-nums; }
    .regime-v2-axis-card em { justify-self: end; font-style: normal; font-size: 12px; font-weight: 700; color: var(--ink-2); }
    .axis-meter { position: relative; grid-column: 1 / -1; height: 10px; border-radius: 999px; background: var(--surface-2); overflow: hidden; }
    .axis-meter__mid { position: absolute; left: 50%; top: 0; bottom: 0; width: 1px; background: var(--muted-2); z-index: 2; }
    .axis-meter__fill { position: absolute; top: 0; bottom: 0; }
    .axis-meter__fill--pos { background: var(--pos); }
    .axis-meter__fill--neg { background: var(--neg); }

    .status-pill {
      display: inline-flex; align-items: center; padding: 3px 8px; border-radius: 999px;
      font-size: 11px; font-weight: 700; white-space: nowrap;
    }
    .status-pill--ok { color: var(--pos); background: var(--pos-soft); }
    .status-pill--warning { color: var(--warn); background: var(--warn-soft); }
    .status-pill--muted { color: var(--muted-ink); background: var(--surface-2); }
    .num-muted { color: var(--muted-ink); font-family: var(--font-num); font-size: 12px; margin-left: 6px; }

    .regime-v2-risk__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
    .mini-stat { border: 1px solid var(--border-soft); border-radius: 8px; padding: 10px 12px; background: var(--surface); }
    .mini-stat span { display: block; color: var(--muted-ink); font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; }
    .mini-stat strong { display: block; margin-top: 4px; font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; }
    .inline-contributors { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 12px; }
    .inline-contributors div { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
    .inline-contributors span { color: var(--muted-ink); font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; }
    .inline-contributors b, .contributor-list span {
      display: inline-flex; padding: 4px 8px; border-radius: 999px;
      background: var(--surface-2); color: var(--ink-2); font-size: 12px; font-weight: 600;
    }
    .contributor-list { display: flex; flex-wrap: wrap; gap: 8px; }

    .count-grid { display: grid; gap: 8px; }
    .count-row { display: grid; grid-template-columns: 200px minmax(160px, 1fr) 56px; gap: 12px; align-items: center; }
    .count-row .bar { height: 8px; background: var(--border-soft); border-radius: 999px; overflow: hidden; }
    .count-row .bar i { display: block; height: 100%; background: var(--accent); }
    .count-row strong { font-variant-numeric: tabular-nums; font-weight: 600; }

    /* Crisis intensity chart */
    .regime-crisis__chart { width: 100%; }
    .regime-crisis__chart svg { display: block; width: 100%; height: 96px; }

    /* Method-vote heat strip */
    .method-strip { display: grid; gap: 1px; background: var(--border-soft); padding: 1px; border-radius: var(--r-2); overflow: hidden; }
    .method-strip__head, .method-strip__row {
      display: grid; grid-template-columns: 160px repeat(var(--method-strip-cols, 30), minmax(0, 1fr));
      gap: 1px; background: var(--border-soft);
    }
    .method-strip__lbl { background: var(--surface); padding: 6px 10px; font-size: 12px; font-weight: 600; }
    .method-strip__col-head { background: transparent; font-size: 10px; color: var(--muted-ink); padding: 2px 0; text-align: center; }
    .method-strip__cell { background: var(--surface); display: inline-block; min-height: 18px; }
    .regime-cell--goldilocks { background: var(--accent-soft); }
    .regime-cell--reflation { background: #fde68a; }
    .regime-cell--stagflation { background: #fed7aa; }
    .regime-cell--slowdown { background: #bfdbfe; }
    .regime-cell--crisis { background: var(--neg-soft); }
    .regime-cell--unknown { background: var(--surface-2); }
    .method-strip__legend { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 10px; font-size: 11px; color: var(--muted-ink); }
    .method-strip__legend-item { display: inline-flex; align-items: center; gap: 6px; }
    .method-strip__legend-item .method-strip__cell { width: 12px; height: 12px; border-radius: 2px; }

    /* Transition log */
    .transition-log { display: grid; gap: 2px; }
    .transition-row {
      display: grid; grid-template-columns: 110px 1fr auto;
      align-items: center; gap: 12px;
      padding: 8px 0; border-bottom: 1px dashed var(--border-soft); font-size: 13px;
    }
    .transition-row:last-child { border-bottom: 0; }
    .transition-row__date { color: var(--muted-ink); font-family: var(--font-num); font-size: 12px; }
    .transition-row__arrow { color: var(--muted-2); margin: 0 4px; }
    .transition-row__meta { text-align: right; }

    @media (max-width: 760px) {
      .regime-section__header { grid-template-columns: 1fr; }
      .regime-v2-hero { grid-template-columns: 1fr; }
      .status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .regime-headline { font-size: 22px; }
      .count-row { grid-template-columns: 1fr; }
      .regime-v2-axis-grid, .inline-contributors { grid-template-columns: 1fr; }
    }
    """


def _styles() -> str:
    """Combined `<style>` body for the standalone regime artifact."""
    return design_tokens_css() + regime_section_styles()


__all__ = [
    "RegimeHtmlAxisHistoryPoint",
    "RegimeHtmlLayerRow",
    "RegimeHtmlMethodVoteHistoryPoint",
    "RegimeHtmlRiskOverlay",
    "RegimeHtmlTransitionEvent",
    "RegimeHtmlViewModel",
    "build_regime_html_view_model",
    "regime_section_styles",
    "render_regime_html_report",
    "render_regime_section_body",
    "write_regime_html_report",
]
