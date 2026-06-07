"""Shared contract every advisor speaks.

The umbrella's whole point is uniformity: Option / FX-hedge / Roll / Ideas all
produce the *same* :class:`Suggestion` shape, so one GUI renders them all and a
new advisor needs no UI work. Advisor-specific richness rides in
``Suggestion.detail`` (a JSON-serializable payload) tagged by ``body_kind`` so
the UI knows which detail renderer to use.

Stdlib frozen dataclasses, matching the codebase convention.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Triage labels (shared across advisors).
LABEL_PROCEED = "PROCEED"
LABEL_MONITOR = "MONITOR"
LABEL_REJECT = "REJECT"
LABEL_INFO = "INFO"          # non-actionable context (e.g. a roll reminder with nothing due)
LABELS = (LABEL_PROCEED, LABEL_MONITOR, LABEL_INFO, LABEL_REJECT)

# Sort order for presentation (PROCEED first).
LABEL_ORDER = {LABEL_PROCEED: 0, LABEL_MONITOR: 1, LABEL_INFO: 2, LABEL_REJECT: 3}


@dataclass(frozen=True)
class AuditEntry:
    """One row of the 'why generated / why filtered' trail."""

    name: str
    passed: bool
    severity: str          # "hard" | "soft" | "info"
    detail: str = ""


@dataclass(frozen=True)
class Sizing:
    """How much, framed against funded AUM (which excludes options/futures)."""

    basis: str = ""                       # "held_lots" | "max_loss_cap" | "notional_budget" | ...
    max_units: int | None = None          # contracts / lots / shares as appropriate
    capital_at_risk_usd: float | None = None
    notional_pct_of_aum: float | None = None
    notes: str = ""


@dataclass(frozen=True)
class Suggestion:
    """One advisor output, uniform across advisor types."""

    advisor: str                          # producing advisor key, e.g. "option"
    suggestion_id: str
    as_of: str
    title: str                            # headline, e.g. "COLLAR · SPY"
    subject: str                          # what it's about: symbol / ccy / account
    category: str                         # advisor-specific bucket (INCOME/HEDGE/…)
    label: str = LABEL_MONITOR            # PROCEED | MONITOR | INFO | REJECT
    score: float = 0.0
    thesis: str = ""
    why_now: str = ""
    rationale: str = ""
    headline_metrics: dict[str, str] = field(default_factory=dict)  # collapsed-card one-liners
    drivers: list[tuple[str, float]] = field(default_factory=list)
    audit: list[AuditEntry] = field(default_factory=list)
    data_mode: str = ""                   # live / live_anchored / synthetic / user_override / cached / stale
    sizing: Sizing | None = None
    body_kind: str = "generic"            # which detail renderer the UI should use
    detail: dict = field(default_factory=dict)  # JSON-serializable advisor-specific payload


@dataclass(frozen=True)
class AdvisorResult:
    """A single advisor's run output."""

    advisor: str
    as_of: str
    suggestions: list[Suggestion] = field(default_factory=list)
    data_mode: str = ""
    warnings: list[str] = field(default_factory=list)
    config_version: str | None = None
    meta: dict = field(default_factory=dict)

    def by_label(self, label: str) -> list[Suggestion]:
        return [s for s in self.suggestions if s.label == label]

    def actionable(self) -> list[Suggestion]:
        return [s for s in self.suggestions if s.label in (LABEL_PROCEED, LABEL_MONITOR)]


@dataclass(frozen=True)
class AdvisorContext:
    """Common inputs assembled once and handed to every advisor (the context bus).

    Advisors read what they need and ignore the rest. Kept deliberately small in
    M1; richer accessors (artifact paths, market-data handles) land as advisors
    require them.
    """

    as_of: str = ""
    holdings: dict[str, float] = field(default_factory=dict)   # symbol -> shares held
    aum: float | None = None                                   # funded AUM (excl. options/futures)
    watchlist: list[str] = field(default_factory=list)
    regime_label: str = ""
    regime_confidence: str = ""
    crisis_flag: bool = False
    sectors: dict[str, str] = field(default_factory=dict)
    held_options: list[dict] = field(default_factory=list)  # {underlying,right,strike,expiry,qty,underlying_price,delta,iv}
    held_futures: list[dict] = field(default_factory=list)  # {root,contract,exchange,asset_class,qty,latest_price,market_value}
    extras: dict = field(default_factory=dict)

    def symbols(self) -> list[str]:
        """Distinct scan universe = holdings ∪ watchlist (holdings first)."""
        out: list[str] = []
        for sym in (*self.holdings.keys(), *self.watchlist):
            if sym not in out:
                out.append(sym)
        return out
