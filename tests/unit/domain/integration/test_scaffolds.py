from market_helper.common.models import RecommendationOutput
from market_helper.domain.integration.pipelines.generate_combined_report import (
    generate_combined_report,
)
from market_helper.domain.integration.pipelines.generate_rebalance_suggestions import (
    generate_recommendations,
)
from market_helper.domain.integration.pipelines.run_stress_tests import run_stress_tests


def test_integration_scaffolds_return_read_only_shapes() -> None:
    combined = generate_combined_report(
        portfolio_snapshot={"weights": {"EQ": 0.6}},
        regime_snapshot={"composite_regime": "Goldilocks"},
    )
    stress = run_stress_tests(
        current_state={"weights": {"EQ": 0.6}},
        stress_assumptions={"shock": "rates_up"},
    )
    recommendation = generate_recommendations()

    assert "mapping_notes" in combined
    assert "notes" in stress
    assert isinstance(recommendation, RecommendationOutput)
