"""Render a standalone preview of the dashboard Regime tab WITH the live
Policy-Expert Allocation (ML) panel attached.

This is what the combined dashboard report's Regime section shows once the model
artifact is present (the panel is attached on the combined-report path via
portfolio_html._attach_policy_allocation). Here we build a representative regime
view-model, attach the live prediction (market_helper.regimes.policy_expert_predictor),
and write a self-contained HTML you can open in a browser.

Output: data/research_artifacts/policy_expert_dashboard_preview.html
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from market_helper.regimes.policy_expert_predictor import predict_latest  # noqa: E402
from market_helper.regimes.policy_expert_trending import compute_trending  # noqa: E402
from market_helper.reporting.regime_html import (  # noqa: E402
    RegimeHtmlLayerRow,
    RegimeHtmlRiskOverlay,
    RegimeHtmlTimelineRow,
    RegimeHtmlViewModel,
    render_regime_html_report,
)

OUT = REPO_ROOT / "data/research_artifacts/policy_expert_dashboard_preview.html"


def representative_view_model() -> RegimeHtmlViewModel:
    layers = [
        RegimeHtmlLayerRow(
            layer_name="macro_nowcast", enabled=True, available=True, status="ok",
            growth_score=0.34, inflation_score=-0.08, growth_state="Up",
            inflation_state="Down", confidence="High",
            top_positive_contributors=["payrolls", "industrial production"],
            top_negative_contributors=["CPI momentum"],
        ),
        RegimeHtmlLayerRow(
            layer_name="market_implied", enabled=True, available=True, status="ok",
            growth_score=0.21, inflation_score=-0.02, growth_state="Up",
            inflation_state="Neutral", confidence="Medium",
            top_positive_contributors=["EQ momentum"],
            top_negative_contributors=["credit spread"],
        ),
    ]
    timeline = [
        RegimeHtmlTimelineRow(as_of=f"2026-{m:02d}", regime="Goldilocks",
                              method_agreement=0.8, crisis_flag=False,
                              crisis_intensity=0.1, duration_days=30 * i)
        for i, m in enumerate(range(1, 6), start=1)
    ]
    return RegimeHtmlViewModel(
        schema="regime-engine-v2", as_of="2026-05", regime="Goldilocks",
        scores={"GROWTH": 0.30, "INFLATION": -0.05, "RISK": 0.12},
        method_agreement=0.8, crisis_flag=False, crisis_intensity=0.12,
        duration_days=120, methods=[], timeline=timeline,
        regime_counts={"Goldilocks": 4, "Reflation": 1},
        confidence="High", layers=layers,
        risk_overlay=RegimeHtmlRiskOverlay(
            risk_score=0.12, liquidity_score=0.2, risk_overlay_on=False,
            risk_state="Risk On", confidence="Medium",
            top_positive_contributors=["low VIX"], top_negative_contributors=[],
        ),
        available_primary_layers=["macro_nowcast", "market_implied"],
    )


def main() -> int:
    vm = dataclasses.replace(
        representative_view_model(),
        policy_allocation=predict_latest(allow_retrain=False),
        policy_trending=compute_trending(),
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render_regime_html_report(vm), encoding="utf-8")
    pred = vm.policy_allocation
    print(f"wrote {OUT}  ({OUT.stat().st_size // 1024} KB)")
    if pred and pred.available:
        print(f"panel: lean {pred.top_expert} ({pred.confidence*100:.0f}%) as of {pred.as_of}; "
              f"sleeves {pred.sleeve_weights}")
    else:
        print(f"panel: unavailable ({pred.reason if pred else 'no prediction'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
