"""Run advisors over a shared context; aggregate into a cross-advisor inbox.

One bad advisor must never sink the run — failures are captured as warnings on
that advisor's result (graceful degradation, Acceptance-Bar item).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from market_helper.trade_advisor.contracts import (
    LABEL_MONITOR,
    LABEL_ORDER,
    LABEL_PROCEED,
    AdvisorContext,
    AdvisorResult,
    Suggestion,
)
from market_helper.trade_advisor.registry import AdvisorRegistry, build_default_registry


@dataclass(frozen=True)
class TradeAdvisorRun:
    """Aggregated output of running one or more advisors."""

    as_of: str
    results: dict[str, AdvisorResult] = field(default_factory=dict)

    def all_suggestions(self) -> list[Suggestion]:
        out: list[Suggestion] = []
        for result in self.results.values():
            out.extend(result.suggestions)
        return out

    def inbox(self, labels: tuple[str, ...] = (LABEL_PROCEED, LABEL_MONITOR)) -> list[Suggestion]:
        """Cross-advisor 'what should I look at' list, sorted PROCEED→MONITOR then score."""
        items = [s for s in self.all_suggestions() if s.label in labels]
        items.sort(key=lambda s: (LABEL_ORDER.get(s.label, 9), -s.score))
        return items

    def warnings(self) -> list[str]:
        out: list[str] = []
        for key, result in self.results.items():
            out.extend(f"{key}: {w}" for w in result.warnings)
        return out


class TradeAdvisorService:
    """Orchestrates the advisor registry for a given context."""

    def __init__(self, registry: AdvisorRegistry | None = None) -> None:
        self.registry = registry or build_default_registry()

    def run(
        self,
        context: AdvisorContext,
        *,
        advisors: list[str] | None = None,
        params_by_advisor: dict[str, dict] | None = None,
    ) -> TradeAdvisorRun:
        keys = advisors if advisors is not None else self.registry.keys()
        params_by_advisor = params_by_advisor or {}
        results: dict[str, AdvisorResult] = {}
        for key in keys:
            advisor = self.registry.get(key)
            params = params_by_advisor.get(key, {})
            try:
                results[key] = advisor.produce(context, **params)
            except Exception as exc:  # noqa: BLE001 — one advisor failing must not sink the run
                results[key] = AdvisorResult(
                    advisor=key,
                    as_of=context.as_of,
                    warnings=[f"{type(exc).__name__}: {str(exc)[:200]}"],
                )
        return TradeAdvisorRun(as_of=context.as_of, results=results)
