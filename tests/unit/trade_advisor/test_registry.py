"""Registry + Advisor-protocol conformance (no network)."""

from __future__ import annotations

import pytest

from market_helper.trade_advisor.base import Advisor
from market_helper.trade_advisor.registry import AdvisorRegistry, build_default_registry


def test_default_registry_has_option():
    reg = build_default_registry()
    assert "option" in reg
    assert "option" in reg.keys()
    assert len(reg) >= 1


def test_registered_advisors_satisfy_protocol():
    reg = build_default_registry()
    for advisor in reg.all():
        assert isinstance(advisor, Advisor)  # runtime_checkable structural check
        assert advisor.key and advisor.title


def test_duplicate_registration_raises():
    reg = build_default_registry()
    dup = reg.get("option")
    with pytest.raises(ValueError):
        reg.register(dup)


def test_register_requires_key():
    reg = AdvisorRegistry()

    class _NoKey:
        key = ""
        title = "x"

        def produce(self, context, **params):  # pragma: no cover - not called
            raise NotImplementedError

    with pytest.raises(ValueError):
        reg.register(_NoKey())
