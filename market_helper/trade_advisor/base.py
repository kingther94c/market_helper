"""The Advisor protocol every component implements.

An advisor is anything with a stable ``key``, a display ``title``, and a
``produce(context, **params) -> AdvisorResult``. ``params`` carries the
advisor-specific knobs the (bounded-control) UI exposes — see the devplan's
interaction-constraint rule: no free-form input, so each advisor will later
declare a control schema for those params.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .contracts import AdvisorContext, AdvisorResult


@runtime_checkable
class Advisor(Protocol):
    key: str
    title: str

    def produce(self, context: AdvisorContext, **params) -> AdvisorResult:
        """Produce ranked, labelled, audited suggestions for the given context."""
        ...
