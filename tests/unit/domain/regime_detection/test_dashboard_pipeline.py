import json

from market_helper.domain.regime_detection.pipelines.generate_regime_dashboard import (
    generate_regime_dashboard,
)
from market_helper.regimes.taxonomy import REGIME_GOLDILOCKS


def test_generate_regime_dashboard_returns_latest_and_policy(tmp_path) -> None:
    regime_path = tmp_path / "regime.json"
    regime_path.write_text(
        json.dumps(
            [
                {
                    "as_of": "2026-03-20",
                    "regime": REGIME_GOLDILOCKS,
                    "scores": {},
                    "inputs": {},
                    "flags": {},
                }
            ]
        ),
        encoding="utf-8",
    )

    dashboard = generate_regime_dashboard(regime_path=regime_path)

    assert dashboard["latest"]["regime"] == REGIME_GOLDILOCKS
    assert "asset_class_targets" in dashboard["policy"]
