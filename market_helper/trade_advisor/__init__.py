"""Trade Advisor umbrella.

One advisory surface over a family of read-only advisors (options, FX hedging,
rolls, trade ideas, …). This package owns the **shared contract** every advisor
speaks (:mod:`.contracts`), the :class:`~.base.Advisor` protocol, and a
:class:`~.registry.AdvisorRegistry`. Component engines live in ``domain/`` and
are wrapped by thin adapters in :mod:`.adapters`.

Read-only / advisory-only by construction (ADR 0001 / 0007): advisors emit
labelled *ideas*, never orders. See ``docs/architecture/devplans/trade_advisor.md``.
"""

from .contracts import (
    AdvisorContext,
    AdvisorResult,
    AuditEntry,
    Sizing,
    Suggestion,
)
from .registry import AdvisorRegistry, build_default_registry

__all__ = [
    "AdvisorContext",
    "AdvisorResult",
    "AuditEntry",
    "Sizing",
    "Suggestion",
    "AdvisorRegistry",
    "build_default_registry",
]
