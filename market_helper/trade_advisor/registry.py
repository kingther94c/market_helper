"""Advisor registry — the umbrella's plug point.

Register an :class:`~.base.Advisor` once; the GUI and report iterate the
registry generically, so adding a new advisor needs no UI work (Acceptance-Bar
item: "adding a new advisor needs no UI work").
"""

from __future__ import annotations

from .base import Advisor


class AdvisorRegistry:
    def __init__(self) -> None:
        self._advisors: dict[str, Advisor] = {}

    def register(self, advisor: Advisor) -> None:
        key = getattr(advisor, "key", None)
        if not key:
            raise ValueError("advisor must expose a non-empty 'key'")
        if key in self._advisors:
            raise ValueError(f"advisor {key!r} already registered")
        self._advisors[key] = advisor

    def get(self, key: str) -> Advisor:
        return self._advisors[key]

    def keys(self) -> list[str]:
        return list(self._advisors)

    def all(self) -> list[Advisor]:
        return list(self._advisors.values())

    def __contains__(self, key: str) -> bool:
        return key in self._advisors

    def __len__(self) -> int:
        return len(self._advisors)


def build_default_registry() -> AdvisorRegistry:
    """Registry of the built-in advisors available today.

    Imports are local so registering one advisor never drags in another's heavy
    deps. FX-hedge / roll / ideas adapters register here as they land (M4–M6).
    """
    from .adapters.fx_hedge import FxHedgeAdvisorPlugin
    from .adapters.futures_roll import FuturesRollPlugin
    from .adapters.ideas import TradeIdeasAdvisorPlugin
    from .adapters.option import OptionAdvisorPlugin
    from .adapters.roll import RollReminderPlugin

    registry = AdvisorRegistry()
    registry.register(OptionAdvisorPlugin())
    registry.register(RollReminderPlugin())
    registry.register(FuturesRollPlugin())
    registry.register(FxHedgeAdvisorPlugin())
    registry.register(TradeIdeasAdvisorPlugin())
    return registry
