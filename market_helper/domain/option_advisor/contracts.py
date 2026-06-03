"""Data contracts for the option advisor.

Stdlib frozen dataclasses, ``float | None`` for nullable metrics,
``field(default_factory=...)`` for mutable defaults — matching the conventions
in ``reporting/risk_html.py`` and ``suggest/quadrant_policy.py``.

Two layers live here:

* **Market-data contracts** — :class:`OptionQuote`, :class:`ChainSnapshot`,
  :class:`VolSurfaceParams`, :class:`UnderlyingContext` — what providers return.
* **Advisory contracts** — :class:`OptionLeg`, :class:`OptionIdea`,
  :class:`OptionAdvisoryResult` and the small assessment records — what the
  advisor emits.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# String enums (plain str constants, matching the codebase's regime/asset_class
# convention rather than enum.Enum).
# --------------------------------------------------------------------------- #

# Idea categories — the trade's intent.
CATEGORY_INCOME = "INCOME"
CATEGORY_HEDGE = "HEDGE"
CATEGORY_DIRECTIONAL = "DIRECTIONAL"
CATEGORY_VOLATILITY = "VOLATILITY"
CATEGORY_CONVEXITY = "CONVEXITY"
CATEGORIES = (
    CATEGORY_INCOME,
    CATEGORY_HEDGE,
    CATEGORY_DIRECTIONAL,
    CATEGORY_VOLATILITY,
    CATEGORY_CONVEXITY,
)

# Structure templates.
STRUCTURE_COVERED_CALL = "COVERED_CALL"
STRUCTURE_CASH_SECURED_PUT = "CASH_SECURED_PUT"
STRUCTURE_PROTECTIVE_PUT = "PROTECTIVE_PUT"
STRUCTURE_COLLAR = "COLLAR"
STRUCTURE_CALL_SPREAD = "CALL_SPREAD"
STRUCTURE_PUT_SPREAD = "PUT_SPREAD"
STRUCTURE_LONG_CALL = "LONG_CALL"
STRUCTURE_LONG_PUT = "LONG_PUT"

# Triage labels.
LABEL_PROCEED = "PROCEED"
LABEL_MONITOR = "MONITOR"
LABEL_REJECT = "REJECT"

# Chain provenance — how honest is this data?
DATA_LIVE_CHAIN = "live_chain"                    # real per-strike quotes from a provider
DATA_LIVE_ANCHORED = "live_anchored_synthetic"    # synthetic strikes, but live spot + ATM IV anchor
DATA_SYNTHETIC = "synthetic"                       # spot + IV from a model/assumption only
DATA_USER_OVERRIDE = "user_override"               # user supplied spot and/or IV


# --------------------------------------------------------------------------- #
# Market-data contracts
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class OptionQuote:
    """One option contract's quote + Greeks at a point in time."""

    underlying: str
    expiry: str               # ISO "YYYY-MM-DD"
    dte: int                  # calendar days to expiry
    right: str                # "C" | "P"
    strike: float
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    iv: float | None = None   # annualized, decimal
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    open_interest: int | None = None
    volume: int | None = None
    source: str = ""          # "ibkr" | "yfinance" | "cboe" | "alphavantage" | "synthetic"
    status: str = "ok"        # "ok" | "model" | "stale" | "no_quote"

    @property
    def mid(self) -> float | None:
        if self.bid is not None and self.ask is not None and self.ask > 0 and self.bid > 0:
            return 0.5 * (self.bid + self.ask)
        return self.last

    @property
    def spread_pct(self) -> float | None:
        """Relative bid/ask spread (ask-bid)/mid, or ``None`` if not quotable."""
        if self.bid is None or self.ask is None or self.bid <= 0 or self.ask <= 0:
            return None
        mid = 0.5 * (self.bid + self.ask)
        if mid <= 0:
            return None
        return (self.ask - self.bid) / mid


@dataclass(frozen=True)
class VolSurfaceParams:
    """Parameters for a simple deterministic synthetic vol surface.

    In log-moneyness ``m = ln(K / forward)``::

        iv(K, T) = atm_iv + term_slope * (sqrt(T) - sqrt(t_ref))
                   + skew * (t_ref / T)**skew_decay * m     # skew flattens ~1/sqrt(T)
                   + smile * m**2

    Research-backed defaults (see ``docs/architecture/devplans/option_advisor.md``):
    equity index ≈ steeper negative skew / milder smile; single names ≈ flatter
    skew / fatter smile. The empirical ``1/sqrt(T)`` skew-decay is the dominant
    term-structure stylized fact.
    """

    atm_iv: float
    skew: float = -0.12          # ∂iv/∂m at the reference tenor (negative = put skew)
    smile: float = 0.40          # convexity in m**2
    skew_decay: float = 0.5      # skew(T) = skew * (t_ref / T)**skew_decay
    term_slope: float = 0.0      # atm level slope in sqrt-time
    t_ref_years: float = 30.0 / 365.0
    iv_floor: float = 0.01
    iv_cap: float = 3.0

    @classmethod
    def for_asset(cls, atm_iv: float, *, single_name: bool = False) -> "VolSurfaceParams":
        """Asset-class default surface. Index/ETF-like unless ``single_name``."""
        if single_name:
            return cls(atm_iv=atm_iv, skew=-0.06, smile=0.80)
        return cls(atm_iv=atm_iv, skew=-0.12, smile=0.40)


@dataclass(frozen=True)
class ChainSnapshot:
    """An option chain (real, synthetic, or hybrid) for one underlying."""

    underlying: str
    as_of: str
    spot: float
    quotes: list[OptionQuote] = field(default_factory=list)
    atm_iv: float | None = None
    iv_rank: float | None = None        # 0..1, percentile of ATM IV (~52w) where known
    realized_vol: float | None = None
    risk_free_rate: float = 0.04
    dividend_yield: float = 0.0
    data_mode: str = DATA_SYNTHETIC
    source: str = ""
    warnings: list[str] = field(default_factory=list)

    def expiries(self) -> list[str]:
        return sorted({q.expiry for q in self.quotes})

    def nearest_expiry(self, target_dte: int) -> str | None:
        exps = [(q.dte, q.expiry) for q in self.quotes]
        if not exps:
            return None
        return min(exps, key=lambda e: abs(e[0] - target_dte))[1]

    def quotes_for(self, expiry: str, right: str) -> list[OptionQuote]:
        return sorted(
            (q for q in self.quotes if q.expiry == expiry and q.right == right),
            key=lambda q: q.strike,
        )

    def nearest_by_delta(
        self, expiry: str, right: str, target_delta: float
    ) -> OptionQuote | None:
        """Closest quote to a target absolute delta within an expiry."""
        candidates = [q for q in self.quotes_for(expiry, right) if q.delta is not None]
        if not candidates:
            return None
        return min(candidates, key=lambda q: abs(abs(q.delta) - abs(target_delta)))

    def nearest_by_strike(
        self, expiry: str, right: str, target_strike: float
    ) -> OptionQuote | None:
        candidates = self.quotes_for(expiry, right)
        if not candidates:
            return None
        return min(candidates, key=lambda q: abs(q.strike - target_strike))


@dataclass(frozen=True)
class RealizedVolMetrics:
    """Realized-vol term structure for an underlying (annualized decimals)."""

    symbol: str
    as_of: str
    vol_1m: float | None = None
    vol_3m: float | None = None
    vol_6m: float | None = None
    vol_1y: float | None = None
    ewma_vol: float | None = None
    method: str = "log_close_252"


@dataclass(frozen=True)
class EventRisk:
    """Forward event exposure. ``event_status='unverified'`` until an earnings feed lands."""

    symbol: str
    next_earnings_date: str | None = None
    days_to_earnings: int | None = None
    ex_div_date: str | None = None
    event_status: str = "unverified"   # "known" | "none" | "unverified"


@dataclass(frozen=True)
class UnderlyingContext:
    """Everything the rules need about one underlying, assembled from existing artifacts."""

    internal_id: str
    symbol: str
    as_of: str
    spot: float | None = None
    realized_vol: RealizedVolMetrics | None = None
    atm_iv: float | None = None
    iv_rank: float | None = None
    rv_iv_ratio: float | None = None       # realized/implied — >1 means options look cheap
    trend_state: str = "unknown"           # "up" | "down" | "chop" | "unknown"
    regime_label: str = ""
    regime_confidence: str = ""            # "High" | "Medium" | "Low"
    crisis_flag: bool = False
    held_qty: float = 0.0
    held_delta_exposure_usd: float | None = None
    weight: float = 0.0                    # share of funded AUM (excludes opts/futures)
    sector: str = ""
    asset_class: str = ""
    dir_exposure: str = "L"                # "L" | "S"
    event_risk: EventRisk | None = None
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Advisory contracts
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class OptionLeg:
    """One leg of a proposed structure. Carries both the selection *rule* and,
    once resolved against a chain, the concrete strike/expiry + model estimates."""

    right: str                 # "C" | "P"
    action: str                # "buy" | "sell"
    strike_rule: str           # human-readable, e.g. "delta:0.30" | "pct_otm:0.05" | "abs:450"
    expiry_rule: str           # e.g. "dte:30-45"
    qty_ratio: int = 1
    resolved_strike: float | None = None
    resolved_expiry: str | None = None
    resolved_dte: int | None = None
    est_iv: float | None = None
    est_price: float | None = None     # BS model or live mid — see quote_status
    est_delta: float | None = None
    est_gamma: float | None = None
    est_theta: float | None = None
    est_vega: float | None = None
    quote_status: str = "model"        # "live" | "model"
    bid: float | None = None
    ask: float | None = None
    open_interest: int | None = None
    volume: int | None = None


@dataclass(frozen=True)
class LiquidityAssessment:
    status: str = "unknown_no_chain"   # "ok" | "thin" | "unknown_no_chain"
    worst_spread_pct: float | None = None
    min_open_interest: int | None = None
    min_volume: int | None = None
    notes: str = ""


@dataclass(frozen=True)
class SizingGuidance:
    basis: str = "max_loss_cap"        # "max_loss_cap" | "premium_budget" | "delta_budget"
    max_contracts: int | None = None
    notional_pct_of_aum: float | None = None
    capital_at_risk_usd: float | None = None
    notes: str = ""


@dataclass(frozen=True)
class FilterOutcome:
    """One row of the 'why generated / why rejected' audit trail."""

    filter_name: str
    passed: bool
    severity: str              # "hard" | "soft"
    detail: str = ""


@dataclass(frozen=True)
class OptionIdea:
    idea_id: str
    as_of: str
    underlying_id: str
    underlying_symbol: str
    category: str
    structure_type: str
    legs: list[OptionLeg]
    thesis: str = ""
    why_now: str = ""
    expiry_strike_logic: str = ""
    est_net_debit_credit: float | None = None   # per 1 structure unit (1 contract = ×100)
    est_max_loss: float | None = None
    est_max_gain: float | None = None
    est_breakevens: list[float] = field(default_factory=list)
    est_payoff_curve: list[tuple[float, float]] = field(default_factory=list)
    net_greeks: dict[str, float] = field(default_factory=dict)
    liquidity: LiquidityAssessment | None = None
    event_risk: EventRisk | None = None
    sizing: SizingGuidance | None = None
    score: float = 0.0
    label: str = LABEL_MONITOR
    rationale: str = ""
    drivers: list[tuple[str, float]] = field(default_factory=list)
    filters_applied: list[FilterOutcome] = field(default_factory=list)
    data_status: str = "model_only"    # "model_only" | "chain_validated"
    spot: float | None = None          # underlying spot at generation (drives what-if)


@dataclass(frozen=True)
class OptionAdvisoryResult:
    as_of: str
    ideas: list[OptionIdea]            # all labels; rejected kept for audit
    universe_scanned: list[str] = field(default_factory=list)
    data_mode: str = DATA_SYNTHETIC
    config_version: str = ""
    warnings: list[str] = field(default_factory=list)

    def proceed(self) -> list[OptionIdea]:
        return [i for i in self.ideas if i.label == LABEL_PROCEED]

    def monitor(self) -> list[OptionIdea]:
        return [i for i in self.ideas if i.label == LABEL_MONITOR]

    def rejected(self) -> list[OptionIdea]:
        return [i for i in self.ideas if i.label == LABEL_REJECT]
