from __future__ import annotations

"""Standalone HTML report for regime-detection artifacts."""

import html
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from market_helper.common.datetime_display import format_local_datetime
from market_helper.domain.regime_detection.policies.regime_policy import (
    load_regime_policy,
    resolve_policy,
)
from market_helper.domain.regime_detection.services.detection_service import (
    load_regime_snapshots,
)
from market_helper.regimes.models import MultiMethodRegimeSnapshot
from market_helper.reporting._design_tokens import design_tokens_css
from market_helper.suggest.quadrant_policy import (
    load_crisis_overlay,
    load_quadrant_policy,
    resolve_quadrant_policy,
)


@dataclass(frozen=True)
class RegimeHtmlMethodRow:
    method: str
    quadrant: str
    native_label: str


@dataclass(frozen=True)
class RegimeHtmlTimelineRow:
    as_of: str
    regime: str
    method_agreement: float | None
    crisis_flag: bool | None
    crisis_intensity: float | None
    duration_days: int | None


@dataclass(frozen=True)
class RegimeHtmlPolicySummary:
    vol_multiplier: float
    asset_class_targets: dict[str, float]
    notes: str


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
    policy: RegimeHtmlPolicySummary | None
    # P5 additions — derived from the same snapshots payload, no new I/O.
    axes_history: list[RegimeHtmlAxisHistoryPoint] = field(default_factory=list)
    method_vote_history: list[RegimeHtmlMethodVoteHistoryPoint] = field(default_factory=list)
    transitions: list[RegimeHtmlTransitionEvent] = field(default_factory=list)
    vol_multiplier: float | None = None  # convenience for ribbon header


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
    if str(latest.get("version") or "") == "regime-multi-v1" or isinstance(latest.get("ensemble"), dict):
        return _build_multi_method_view_model(payload, policy_path=policy_path)
    return _build_legacy_view_model(regime_path=regime_path, policy_path=policy_path)


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
        f"{_render_policy(view_model.policy)}"
        f"{_render_methods(view_model.methods)}"
        f"{_render_timeline(view_model.timeline)}"
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


def _build_multi_method_view_model(
    payload: list[Any],
    *,
    policy_path: str | Path | None,
) -> RegimeHtmlViewModel:
    snapshots = [
        MultiMethodRegimeSnapshot.from_dict(dict(row))
        for row in payload
        if isinstance(row, dict)
    ]
    if not snapshots:
        raise ValueError("No valid multi-method regime snapshots found")
    latest = snapshots[-1]
    ensemble = latest.ensemble
    diagnostics = ensemble.diagnostics or {}
    policy = resolve_quadrant_policy(
        ensemble,
        policy=load_quadrant_policy(policy_path),
        overlay=load_crisis_overlay(policy_path),
    )
    axes_history = [
        RegimeHtmlAxisHistoryPoint(
            as_of=snap.as_of,
            growth=getattr(snap.ensemble.axes, "growth_score", None),
            inflation=getattr(snap.ensemble.axes, "inflation_score", None),
        )
        for snap in snapshots[-180:]
    ]
    method_vote_history = [
        RegimeHtmlMethodVoteHistoryPoint(
            as_of=snap.as_of,
            quadrants={
                name: result.quadrant.quadrant for name, result in snap.per_method.items()
            },
            crisis_flag=snap.ensemble.crisis_flag,
        )
        for snap in snapshots[-30:]
    ]
    transitions: list[RegimeHtmlTransitionEvent] = []
    for prev, curr in zip(snapshots, snapshots[1:]):
        if prev.ensemble.quadrant != curr.ensemble.quadrant:
            transitions.append(
                RegimeHtmlTransitionEvent(
                    as_of=curr.as_of,
                    from_regime=prev.ensemble.quadrant,
                    to_regime=curr.ensemble.quadrant,
                    crisis_intensity=curr.ensemble.crisis_intensity,
                    duration_days=curr.ensemble.duration_days,
                )
            )
    transitions = transitions[-8:]
    return RegimeHtmlViewModel(
        schema=latest.version,
        as_of=latest.as_of,
        regime=ensemble.quadrant,
        scores={
            "GROWTH": ensemble.axes.growth_score,
            "INFLATION": ensemble.axes.inflation_score,
        },
        method_agreement=(
            float(diagnostics["method_agreement"])
            if diagnostics.get("method_agreement") is not None
            else None
        ),
        crisis_flag=ensemble.crisis_flag,
        crisis_intensity=ensemble.crisis_intensity,
        duration_days=ensemble.duration_days,
        methods=[
            RegimeHtmlMethodRow(
                method=name,
                quadrant=result.quadrant.quadrant,
                native_label=result.native_label or "",
            )
            for name, result in sorted(latest.per_method.items())
        ],
        timeline=[
            RegimeHtmlTimelineRow(
                as_of=snap.as_of,
                regime=snap.ensemble.quadrant,
                method_agreement=(
                    float(snap.ensemble.diagnostics["method_agreement"])
                    if snap.ensemble.diagnostics
                    and snap.ensemble.diagnostics.get("method_agreement") is not None
                    else None
                ),
                crisis_flag=snap.ensemble.crisis_flag,
                crisis_intensity=snap.ensemble.crisis_intensity,
                duration_days=snap.ensemble.duration_days,
            )
            for snap in snapshots[-60:]
        ],
        regime_counts=dict(Counter(snap.ensemble.quadrant for snap in snapshots)),
        policy=RegimeHtmlPolicySummary(
            vol_multiplier=policy.vol_multiplier,
            asset_class_targets=policy.asset_class_targets,
            notes=policy.notes,
        ),
        axes_history=axes_history,
        method_vote_history=method_vote_history,
        transitions=transitions,
        vol_multiplier=policy.vol_multiplier,
    )


def _build_legacy_view_model(
    *,
    regime_path: str | Path,
    policy_path: str | Path | None,
) -> RegimeHtmlViewModel:
    snapshots = load_regime_snapshots(regime_path)
    if not snapshots:
        raise ValueError("No valid legacy regime snapshots found")
    latest = snapshots[-1]
    decision = resolve_policy(latest, policy=load_regime_policy(policy_path))
    transitions: list[RegimeHtmlTransitionEvent] = []
    for prev, curr in zip(snapshots, snapshots[1:]):
        if prev.regime != curr.regime:
            transitions.append(
                RegimeHtmlTransitionEvent(
                    as_of=curr.as_of,
                    from_regime=prev.regime,
                    to_regime=curr.regime,
                    crisis_intensity=None,
                    duration_days=None,
                )
            )
    return RegimeHtmlViewModel(
        schema=latest.version,
        as_of=latest.as_of,
        regime=latest.regime,
        scores=dict(latest.scores),
        method_agreement=None,
        crisis_flag=bool(latest.flags.get("crisis_active")) if latest.flags else None,
        crisis_intensity=None,
        duration_days=None,
        methods=[],
        timeline=[
            RegimeHtmlTimelineRow(
                as_of=snap.as_of,
                regime=snap.regime,
                method_agreement=None,
                crisis_flag=bool(snap.flags.get("crisis_active")) if snap.flags else None,
                crisis_intensity=None,
                duration_days=None,
            )
            for snap in snapshots[-60:]
        ],
        regime_counts=dict(Counter(snap.regime for snap in snapshots)),
        policy=RegimeHtmlPolicySummary(
            vol_multiplier=decision.vol_multiplier,
            asset_class_targets=decision.asset_class_targets,
            notes=decision.notes,
        ),
        # Legacy snapshots don't carry per-axis or per-method data; new visuals stay empty.
        axes_history=[],
        method_vote_history=[],
        transitions=transitions[-8:],
        vol_multiplier=decision.vol_multiplier,
    )


def _render_status_cards(view_model: RegimeHtmlViewModel) -> str:
    cards = [
        ("Agreement", _format_percent(view_model.method_agreement)),
        ("Crisis", _format_bool(view_model.crisis_flag)),
        ("Intensity", _format_float(view_model.crisis_intensity)),
        ("Duration", _format_days(view_model.duration_days)),
    ]
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
    return (
        "<section class='panel regime-crisis'>"
        "<header class='regime-panel__header'>"
        "<h2>Crisis Intensity</h2>"
        f"<span class='regime-panel__meta'>threshold {threshold:.1f} · current {current_value:.2f} · {html.escape(current_when)}</span>"
        "</header>"
        "<div class='regime-crisis__chart'>"
        f"<svg viewBox='0 0 {width:.0f} {height:.0f}' preserveAspectRatio='none' role='img' aria-label='Crisis intensity over time'>"
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
    legend_items = [
        ("Goldilocks", "regime-cell--goldilocks"),
        ("Reflation", "regime-cell--reflation"),
        ("Stagflation", "regime-cell--stagflation"),
        ("Slowdown", "regime-cell--slowdown"),
        ("Crisis", "regime-cell--crisis"),
    ]
    legend = "".join(
        f"<span class='method-strip__legend-item'><span class='method-strip__cell {cls}'></span>{html.escape(label)}</span>"
        for label, cls in legend_items
    )
    return (
        "<section class='panel regime-method-strip-panel'>"
        "<header class='regime-panel__header'>"
        "<h2>Method-Vote Heat Strip</h2>"
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
            intensity_html = (
                f"<span class='tag tag--warning'>crisis {event.crisis_intensity:.2f}</span>"
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


def _render_policy(policy: RegimeHtmlPolicySummary | None) -> str:
    if policy is None:
        return ""
    targets = "".join(
        "<div class='target-row'>"
        f"<span>{html.escape(bucket)}</span>"
        f"<strong>{weight:.1%}</strong>"
        "</div>"
        for bucket, weight in sorted(policy.asset_class_targets.items())
    )
    return (
        "<section class='panel'>"
        "<h2>Policy Suggestion</h2>"
        "<div class='policy-layout'>"
        "<div>"
        "<span class='label'>Vol multiplier</span>"
        f"<strong class='large'>{policy.vol_multiplier:.2f}</strong>"
        f"<p class='muted'>{html.escape(policy.notes)}</p>"
        "</div>"
        f"<div class='target-grid'>{targets}</div>"
        "</div>"
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
        "<h2>Method Votes</h2>"
        "<table><thead><tr><th>Method</th><th>Quadrant</th><th>Native Label</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        "</section>"
    )


def _render_timeline(rows: list[RegimeHtmlTimelineRow]) -> str:
    if not rows:
        return ""
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
    return (
        "<section class='panel'>"
        "<h2>Recent History</h2>"
        "<table><thead><tr><th>Date</th><th>Regime</th><th>Agreement</th><th>Crisis</th><th>Intensity</th><th>Duration</th></tr></thead>"
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
    .status-grid {
      display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
    }
    .status-card {
      background: var(--surface); border: 1px solid var(--border-soft);
      border-radius: var(--r-2); padding: 10px 12px;
      box-shadow: var(--shadow-1);
    }
    .status-card span {
      display: block; font-size: 11px; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted-ink);
    }
    .status-card strong { display: block; margin-top: 4px; font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--ink); }
    .panel {
      background: var(--surface); border: 1px solid var(--border-soft);
      border-radius: var(--r-3); padding: 16px;
      box-shadow: var(--shadow-1);
    }
    .panel h2 { margin: 0 0 10px; font-size: 13px; font-weight: 700; letter-spacing: 0.02em; }
    .regime-panel__header { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
    .regime-panel__header h2 { margin: 0; }
    .regime-panel__meta { font-size: 12px; color: var(--muted-ink); font-variant-numeric: tabular-nums; }

    .score-grid, .target-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }
    .score-row, .target-row {
      display: grid; gap: 4px;
      border: 1px solid var(--border-soft); border-radius: var(--r-2);
      padding: 10px 12px; background: var(--surface);
    }
    .score-row span, .target-row span, .count-row span {
      font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted-ink);
    }
    .score-row strong, .target-row strong { font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums; }
    .score-spark svg { display: block; width: 100%; height: 28px; }

    .policy-layout { display: grid; grid-template-columns: minmax(220px, 0.45fr) minmax(0, 1fr); gap: 16px; align-items: start; }
    .large { display: block; font-size: 28px; font-weight: 700; line-height: 1; color: var(--accent); font-variant-numeric: tabular-nums; }
    .label { margin: 0 0 6px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted-ink); }

    .panel table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .panel th, .panel td { padding: 8px 10px; border-bottom: 1px solid var(--border-soft); text-align: left; vertical-align: top; }
    .panel th { color: var(--muted-ink); font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; background: var(--surface-2); }

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
      .regime-section__header, .policy-layout { grid-template-columns: 1fr; }
      .status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .regime-headline { font-size: 22px; }
      .count-row { grid-template-columns: 1fr; }
    }
    """


def _styles() -> str:
    """Combined `<style>` body for the standalone regime artifact."""
    return design_tokens_css() + regime_section_styles()


__all__ = [
    "RegimeHtmlAxisHistoryPoint",
    "RegimeHtmlMethodVoteHistoryPoint",
    "RegimeHtmlTransitionEvent",
    "RegimeHtmlViewModel",
    "build_regime_html_view_model",
    "regime_section_styles",
    "render_regime_html_report",
    "render_regime_section_body",
    "write_regime_html_report",
]
