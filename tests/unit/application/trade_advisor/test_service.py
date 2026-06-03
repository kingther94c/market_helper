"""Trade-advisor orchestration: aggregation, inbox ordering, graceful failure."""

from __future__ import annotations

from market_helper.application.trade_advisor import TradeAdvisorService
from market_helper.trade_advisor.contracts import LABEL_ORDER, AdvisorContext
from market_helper.trade_advisor.registry import AdvisorRegistry


def _ctx():
    return AdvisorContext(
        as_of="2026-06-03",
        holdings={"NVDA": 100.0},
        aum=500_000.0,
        regime_label="Reflation",
        regime_confidence="Medium",
    )


def test_runs_option_via_service_and_builds_inbox():
    svc = TradeAdvisorService()
    run = svc.run(
        _ctx(),
        advisors=["option"],
        params_by_advisor={"option": {"overrides": {"NVDA": {"spot": 120.0, "iv": 0.45}}, "fetch_realized": False}},
    )
    assert "option" in run.results
    assert run.results["option"].suggestions
    inbox = run.inbox()
    assert inbox
    orders = [LABEL_ORDER[s.label] for s in inbox]
    assert orders == sorted(orders)  # PROCEED→MONITOR ordering


def test_failing_advisor_is_captured_not_raised():
    class _Boom:
        key = "boom"
        title = "Boom"

        def produce(self, context, **params):
            raise RuntimeError("kaboom")

    reg = AdvisorRegistry()
    reg.register(_Boom())
    run = TradeAdvisorService(registry=reg).run(_ctx())
    assert run.results["boom"].suggestions == []
    assert any("kaboom" in w for w in run.warnings())
