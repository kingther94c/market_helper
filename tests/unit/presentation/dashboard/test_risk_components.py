from __future__ import annotations

from market_helper.presentation.dashboard.components.risk import (
    build_breakdown_figure,
    build_policy_drift_figure,
)
from market_helper.reporting.risk_html import BreakdownRow, PolicyDriftRow


def test_build_policy_drift_figure_handles_empty_and_signed_rows() -> None:
    empty = build_policy_drift_figure([])
    figure = build_policy_drift_figure(
        [
            PolicyDriftRow(bucket="EQ", scope="PORTFOLIO", current_weight=0.7, policy_weight=0.6, active_weight=0.1, current_risk_contribution=0.2),
            PolicyDriftRow(bucket="FI", scope="PORTFOLIO", current_weight=0.2, policy_weight=0.3, active_weight=-0.1, current_risk_contribution=0.05),
        ]
    )

    assert empty["data"] == []
    assert figure["data"][0]["x"] == ["EQ", "FI"]
    assert figure["data"][0]["marker"]["color"] == ["#16a34a", "#dc2626"]


def test_build_breakdown_figure_renders_bucket_weights() -> None:
    figure = build_breakdown_figure(
        [
            BreakdownRow(bucket="US", bucket_label="", parent="EQ", exposure_usd=100.0, gross_exposure_usd=100.0, dollar_weight=0.7, risk_contribution_estimated=0.2),
            BreakdownRow(bucket="EM", bucket_label="", parent="EQ", exposure_usd=50.0, gross_exposure_usd=50.0, dollar_weight=0.3, risk_contribution_estimated=0.1),
        ],
        title="EQ Country Breakdown",
    )

    assert figure["layout"]["title"]["text"] == "EQ Country Breakdown"
    assert figure["data"][0]["x"] == ["US", "EM"]
    assert figure["data"][0]["y"] == [0.7, 0.3]
