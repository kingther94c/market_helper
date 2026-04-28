from __future__ import annotations

"""Standalone HTML report for regime-detection artifacts."""

import html
import json
from collections import Counter
from dataclasses import dataclass
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
        "<body>"
        "<main class='shell'>"
        "<header class='header'>"
        "<div>"
        "<p class='eyebrow'>Regime Detection</p>"
        f"<h1>{html.escape(view_model.regime)}</h1>"
        f"<p class='muted'>As of {html.escape(format_local_datetime(view_model.as_of))} · {html.escape(view_model.schema)}</p>"
        "</div>"
        f"{_render_status_cards(view_model)}"
        "</header>"
        f"{_render_scores(view_model)}"
        f"{_render_policy(view_model.policy)}"
        f"{_render_methods(view_model.methods)}"
        f"{_render_timeline(view_model.timeline)}"
        f"{_render_counts(view_model.regime_counts)}"
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
    return (
        "<section class='panel'>"
        "<h2>Scores</h2>"
        "<div class='score-grid'>"
        + "".join(
            "<div class='score-row'>"
            f"<span>{html.escape(name)}</span>"
            f"<strong>{value:.2f}</strong>"
            "</div>"
            for name, value in sorted(view_model.scores.items())
        )
        + "</div>"
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


def _styles() -> str:
    return """
    :root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color:#172033; background:#f6f8fb; }
    body { margin:0; }
    .shell { width:min(1180px, calc(100vw - 40px)); margin:0 auto; padding:32px 0 48px; display:grid; gap:18px; }
    .header { display:grid; grid-template-columns:minmax(0, 1fr) minmax(360px, 0.8fr); gap:18px; align-items:end; }
    .eyebrow, .label { margin:0 0 8px; font-size:12px; line-height:1.3; font-weight:800; text-transform:uppercase; letter-spacing:0.08em; color:#0f766e; }
    h1 { margin:0; font-size:42px; line-height:1.05; letter-spacing:0; color:#111827; }
    h2 { margin:0 0 14px; font-size:20px; line-height:1.2; letter-spacing:0; color:#172033; }
    .muted { color:#607089; margin:8px 0 0; }
    .panel, .status-card { background:#ffffff; border:1px solid #dbe3ef; border-radius:8px; box-shadow:0 10px 28px rgba(15, 23, 42, 0.05); }
    .panel { padding:20px; overflow:auto; }
    .status-grid { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:12px; }
    .status-card { padding:16px; }
    .status-card span, .score-row span, .target-row span, .count-row span { display:block; color:#607089; font-size:12px; font-weight:700; text-transform:uppercase; }
    .status-card strong { display:block; margin-top:6px; font-size:24px; color:#111827; }
    .score-grid, .target-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:10px; }
    .score-row, .target-row { border:1px solid #e3e9f2; border-radius:8px; padding:12px; background:#fbfcfe; }
    .score-row strong, .target-row strong { display:block; margin-top:6px; font-size:20px; }
    .policy-layout { display:grid; grid-template-columns:minmax(220px, 0.45fr) minmax(0, 1fr); gap:18px; align-items:start; }
    .large { display:block; font-size:40px; line-height:1; color:#0f766e; }
    table { width:100%; border-collapse:collapse; font-size:14px; }
    th, td { padding:11px 10px; border-bottom:1px solid #e5eaf2; text-align:left; vertical-align:top; }
    th { color:#4b5e76; font-size:12px; text-transform:uppercase; letter-spacing:0.06em; background:#f8fafc; }
    .count-grid { display:grid; gap:10px; }
    .count-row { display:grid; grid-template-columns:220px minmax(160px, 1fr) 60px; gap:12px; align-items:center; }
    .bar { height:12px; background:#e5eaf2; border-radius:999px; overflow:hidden; }
    .bar i { display:block; height:100%; background:linear-gradient(90deg, #0f766e, #2563eb); }
    @media (max-width: 760px) {
      .shell { width:min(100vw - 24px, 1180px); padding-top:20px; }
      .header, .policy-layout { grid-template-columns:1fr; }
      .status-grid { grid-template-columns:1fr; }
      h1 { font-size:32px; }
      .count-row { grid-template-columns:1fr; }
    }
    """


__all__ = [
    "RegimeHtmlViewModel",
    "build_regime_html_view_model",
    "render_regime_html_report",
    "write_regime_html_report",
]
