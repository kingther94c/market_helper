from __future__ import annotations

from market_helper.common.models import RecommendationOutput


def generate_recommendations() -> RecommendationOutput:
    """Read-only recommendation scaffold."""
    return RecommendationOutput(
        rationale="TODO: implement portfolio/regime integration recommendation logic."
    )
