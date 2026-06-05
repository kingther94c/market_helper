"""FX Hedging Advisor — regression-based SGD/USD hedge allocation.

The investor's base currency is **SGD** but their AUM is **USD**-denominated, so
in SGD terms they are long USD vs SGD: their SGD wealth rises when USD
strengthens. There is no liquid SGD future, so the USD/SGD exposure is hedged
with a basket of liquid CME FX futures (EUR/GBP/AUD/JPY/CNH vs USD). Basket
weights come from a weekly-return regression of the SGD/USD spot return on the
candidate instruments' spot returns.

Conventions (load-bearing — see also ``configs/portfolio_monitor/fx_hedge_advisor.yml``
and ``docs/decisions/0006-fx-hedge-regression-convention.md``):

* **Price basis.** Every spot series is normalised to *USD per 1 unit of the
  foreign currency* (the currency's value in USD). ``invert`` flips a Yahoo
  quote expressed the other way (``SGD=X`` is USDSGD = SGD per USD → invert to
  USD per SGD). This is deliberately the inverse of the repo's ``fx_usdsgd_eod``
  (SGD per USD); the value-in-USD basis makes futures notional and hedge
  direction natural.
* **Target.** ``r_tgt = Δln(USD per SGD)``. The investor's SGD wealth
  ``W = A·(SGD per USD) = A / (USD per SGD)`` has exposure ``-A`` to ``r_tgt``;
  to neutralise it we take ``+A`` exposure, which the regression
  ``r_tgt ≈ α + Σ βᵢ·rᵢ`` replicates by holding ``+βᵢ·A`` USD notional of each
  leg. Positive beta ⇒ go **long** the foreign future (short USD).
* **Returns.** Weekly log returns on the Friday-resampled price (overlapping
  5-business-day windows optionally supported).
* **Second-order simplification (V1).** The hedge neutralises the first-order
  USD/SGD exposure of the AUM. The hedge instruments' own USD P&L → SGD
  conversion (a cross-currency second-order term) and carry are **not**
  optimised — carry is only *shown* from configured ON rates.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml

from market_helper.app.paths import CONFIGS_DIR, PORTFOLIO_ARTIFACTS_DIR
from market_helper.data_sources.yahoo_finance import (
    YahooFinanceClient,
    YahooFinanceTransientError,
)


logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

DEFAULT_FX_HEDGE_CONFIG_PATH = CONFIGS_DIR / "portfolio_monitor" / "fx_hedge_advisor.yml"
DEFAULT_FX_HEDGE_ARTIFACT_PATH = (
    PORTFOLIO_ARTIFACTS_DIR / "fx_hedge" / "fx_hedge_allocation.json"
)

# Daily history pulled before weekly resampling. ``max`` keeps the lookback
# window honest even for a long ``lookback_weeks``.
_DEFAULT_YAHOO_PERIOD = "max"

# A loader maps (yahoo_symbol, invert) -> a daily price Series (USD per unit),
# indexed by normalised (tz-naive, midnight) timestamps. Injectable so tests and
# the regression core never touch the network.
SpotPriceLoader = Callable[[str, bool], pd.Series]

FxHedgeMode = Literal["cached", "refresh-if-stale", "force-refresh"]


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FxInstrumentSpec:
    currency: str
    label: str
    futures_root: str
    yahoo_symbol: str
    invert: bool
    contract_size: float
    contract_size_currency: str
    usd_sized: bool
    on_rate: float


@dataclass(frozen=True)
class FxHedgeConfig:
    base_currency: str
    target_pair: str
    target_currency: str
    target_yahoo_symbol: str
    target_invert: bool
    price_basis: str
    frequency: str
    overlapping: bool
    return_method: str
    lookback_weeks: int
    min_observations: int
    max_age_days: int
    default_hedge_notional_usd: float
    on_rate_usd: float
    on_rates_as_of: str
    on_rates_source: str
    instruments: tuple[FxInstrumentSpec, ...]


def load_fx_hedge_config(path: str | Path | None = None) -> FxHedgeConfig:
    """Load the advisor config, applying defaults for any absent field."""
    config_path = Path(path) if path is not None else DEFAULT_FX_HEDGE_CONFIG_PATH
    payload: dict[str, Any] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError("FX hedge advisor config must be a mapping")
        payload = dict(loaded.get("fx_hedge_advisor", loaded))

    target = dict(payload.get("target", {}))
    conv = dict(payload.get("return_convention", {}))
    cache = dict(payload.get("cache", {}))
    on_rates = dict(payload.get("on_rates", {}))

    instruments_payload = payload.get("instruments", []) or []
    if not isinstance(instruments_payload, Sequence):
        raise ValueError("FX hedge advisor instruments must be a list")
    instruments = tuple(
        _parse_instrument(dict(entry)) for entry in instruments_payload
    )
    if not instruments:
        raise ValueError("FX hedge advisor config defines no instruments")

    return FxHedgeConfig(
        base_currency=str(payload.get("base_currency", "SGD")),
        target_pair=str(target.get("pair", "USD/SGD")),
        target_currency=str(target.get("currency", "SGD")),
        target_yahoo_symbol=str(target.get("yahoo_symbol", "SGD=X")),
        target_invert=bool(target.get("invert", True)),
        price_basis=str(conv.get("price_basis", "usd_per_unit")),
        frequency=str(conv.get("frequency", "W-FRI")),
        overlapping=bool(conv.get("overlapping", False)),
        return_method=str(conv.get("return_method", "log")),
        lookback_weeks=int(conv.get("lookback_weeks", 156)),
        min_observations=int(conv.get("min_observations", 52)),
        max_age_days=int(cache.get("max_age_days", 30)),
        default_hedge_notional_usd=float(
            payload.get("default_hedge_notional_usd", 1_000_000.0)
        ),
        on_rate_usd=float(on_rates.get("USD", 0.0)),
        on_rates_as_of=str(on_rates.get("as_of", "")),
        on_rates_source=str(on_rates.get("source", "configured")),
        instruments=instruments,
    )


def _parse_instrument(entry: Mapping[str, Any]) -> FxInstrumentSpec:
    currency = str(entry.get("currency", "")).strip().upper()
    if not currency:
        raise ValueError("FX hedge instrument requires a currency")
    contract_size = float(entry.get("contract_size", 0.0))
    if contract_size <= 0:
        raise ValueError(f"FX hedge instrument {currency} requires a positive contract_size")
    return FxInstrumentSpec(
        currency=currency,
        label=str(entry.get("label", currency)),
        futures_root=str(entry.get("futures_root", "")),
        yahoo_symbol=str(entry.get("yahoo_symbol", "")),
        invert=bool(entry.get("invert", False)),
        contract_size=contract_size,
        contract_size_currency=str(entry.get("contract_size_currency", currency)).upper(),
        usd_sized=bool(entry.get("usd_sized", False)),
        on_rate=float(entry.get("on_rate", 0.0)),
    )


# --------------------------------------------------------------------------- #
# Spot loading + weekly returns
# --------------------------------------------------------------------------- #
def make_yahoo_spot_loader(
    *,
    yahoo_client: YahooFinanceClient | None = None,
    period: str = _DEFAULT_YAHOO_PERIOD,
) -> SpotPriceLoader:
    """Default loader: pull daily close from Yahoo and normalise to USD/unit."""
    client = yahoo_client or YahooFinanceClient()

    def _load(symbol: str, invert: bool) -> pd.Series:
        history = client.fetch_price_history(symbol, period=period, interval="1d")
        series = _history_to_price_series(history)
        return _normalise_price(series, invert=invert)

    return _load


def _history_to_price_series(history: Mapping[str, Any]) -> pd.Series:
    prices = history.get("prices") if isinstance(history, Mapping) else None
    if not isinstance(prices, list) or not prices:
        return pd.Series(dtype=float)
    rows: list[tuple[pd.Timestamp, float]] = []
    for row in prices:
        if not isinstance(row, Mapping):
            continue
        raw_ts = row.get("timestamp")
        raw_close = row.get("close")
        if raw_ts in (None, "") or raw_close in (None, ""):
            continue
        timestamp = (
            pd.to_datetime(int(raw_ts), unit="s", utc=True).tz_localize(None).normalize()
        )
        rows.append((timestamp, float(raw_close)))
    if not rows:
        return pd.Series(dtype=float)
    series = pd.Series(
        data=[price for _, price in rows],
        index=pd.DatetimeIndex([ts for ts, _ in rows]),
        dtype=float,
    ).sort_index()
    return series[~series.index.duplicated(keep="last")]


def _normalise_price(series: pd.Series, *, invert: bool) -> pd.Series:
    if series.empty:
        return series
    cleaned = series[series > 0].dropna()
    return (1.0 / cleaned) if invert else cleaned


def build_weekly_return_panel(
    config: FxHedgeConfig,
    *,
    spot_loader: SpotPriceLoader,
) -> tuple[pd.Series, pd.DataFrame, dict[str, float]]:
    """Return ``(target_returns, regressor_returns, latest_spot_by_currency)``.

    All series are normalised to USD/unit, resampled to weekly (or overlapping
    5-business-day) log returns, and inner-joined on a common index so the
    regression sees one aligned panel. ``latest_spot_by_currency`` carries the
    most recent USD/unit price for each instrument (for contract notional).
    """
    target_price = spot_loader(config.target_yahoo_symbol, config.target_invert)
    if target_price.empty:
        raise FxHedgeComputationError(
            f"No spot history for target {config.target_yahoo_symbol}"
        )

    price_frame = pd.DataFrame({config.target_currency: target_price})
    latest_spot: dict[str, float] = {}
    for spec in config.instruments:
        series = spot_loader(spec.yahoo_symbol, spec.invert)
        if series.empty:
            raise FxHedgeComputationError(
                f"No spot history for {spec.currency} ({spec.yahoo_symbol})"
            )
        price_frame[spec.currency] = series
        latest_spot[spec.currency] = float(series.dropna().iloc[-1])

    returns = _prices_to_weekly_returns(price_frame, config=config)
    if len(returns) > config.lookback_weeks:
        returns = returns.iloc[-config.lookback_weeks :]
    returns = returns.dropna()
    if len(returns) < config.min_observations:
        raise FxHedgeComputationError(
            f"Only {len(returns)} aligned weekly observations "
            f"(min {config.min_observations}); widen the lookback or check the feeds"
        )

    target_returns = returns[config.target_currency]
    regressor_returns = returns[[spec.currency for spec in config.instruments]]
    return target_returns, regressor_returns, latest_spot


def _prices_to_weekly_returns(
    price_frame: pd.DataFrame, *, config: FxHedgeConfig
) -> pd.DataFrame:
    if config.return_method != "log":
        raise ValueError(f"Unsupported return_method: {config.return_method}")
    if config.overlapping:
        # Overlapping ~weekly returns: daily-aligned 5-business-day log changes.
        aligned = price_frame.sort_index().dropna(how="any")
        log_prices = np.log(aligned)
        return log_prices.diff(5).dropna(how="any")
    # Non-overlapping calendar weeks: resample to the Friday close, then log-diff.
    weekly = price_frame.sort_index().resample(config.frequency).last().dropna(how="any")
    log_prices = np.log(weekly)
    return log_prices.diff().dropna(how="any")


# --------------------------------------------------------------------------- #
# Regression
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class HedgeRegressionResult:
    betas: dict[str, float]
    beta_std_errors: dict[str, float]
    t_stats: dict[str, float]
    alpha_weekly: float
    r_squared: float
    adj_r_squared: float
    residual_vol_weekly: float
    residual_vol_annualized: float
    observations: int


def estimate_hedge_ratios(
    target_returns: pd.Series,
    regressor_returns: pd.DataFrame,
) -> HedgeRegressionResult:
    """OLS ``r_tgt = α + Σ βᵢ·rᵢ + ε`` with HC-free SEs and R².

    Uses ``numpy.linalg.lstsq`` (rank-robust against the collinearity of the FX
    majors) and the textbook ``σ²·(XᵀX)⁻¹`` covariance for standard errors.
    """
    columns = list(regressor_returns.columns)
    y = target_returns.to_numpy(dtype=float)
    x_raw = regressor_returns.to_numpy(dtype=float)
    n = y.shape[0]
    k = x_raw.shape[1] + 1  # + intercept
    if n <= k:
        raise FxHedgeComputationError(
            f"Not enough observations ({n}) for {k} parameters"
        )

    design = np.column_stack([np.ones(n), x_raw])
    coeffs, _, _, _ = np.linalg.lstsq(design, y, rcond=None)
    fitted = design @ coeffs
    residuals = y - fitted

    ss_res = float(residuals @ residuals)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    dof = n - k
    adj_r_squared = (
        1.0 - (1.0 - r_squared) * (n - 1) / dof if dof > 0 else r_squared
    )

    sigma2 = ss_res / dof if dof > 0 else float("nan")
    try:
        cov = sigma2 * np.linalg.pinv(design.T @ design)
        std_errors = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    except np.linalg.LinAlgError:
        std_errors = np.full(k, float("nan"))

    betas = {col: float(coeffs[i + 1]) for i, col in enumerate(columns)}
    beta_se = {col: float(std_errors[i + 1]) for i, col in enumerate(columns)}
    t_stats = {
        col: (betas[col] / beta_se[col] if beta_se[col] > 0 else float("nan"))
        for col in columns
    }
    resid_vol_weekly = float(np.sqrt(sigma2)) if dof > 0 else float("nan")

    return HedgeRegressionResult(
        betas=betas,
        beta_std_errors=beta_se,
        t_stats=t_stats,
        alpha_weekly=float(coeffs[0]),
        r_squared=float(r_squared),
        adj_r_squared=float(adj_r_squared),
        residual_vol_weekly=resid_vol_weekly,
        residual_vol_annualized=resid_vol_weekly * float(np.sqrt(52.0)),
        observations=n,
    )


# --------------------------------------------------------------------------- #
# Contract sizing + expiry
# --------------------------------------------------------------------------- #
def next_quarterly_imm_expiry(run_date: date) -> date:
    """Third Wednesday of the next IMM quarter (Mar/Jun/Sep/Dec).

    Picks the earliest quarterly expiry strictly more than a week ahead so we
    don't recommend a contract about to expire.
    """
    cutoff = run_date + timedelta(days=7)
    for year in (run_date.year, run_date.year + 1):
        for month in (3, 6, 9, 12):
            expiry = _third_wednesday(year, month)
            if expiry > cutoff:
                return expiry
    # Unreachable for sane dates, but keep a definite return.
    return _third_wednesday(run_date.year + 1, 3)


def _third_wednesday(year: int, month: int) -> date:
    first = date(year, month, 1)
    # weekday(): Mon=0 .. Wed=2. Days until the first Wednesday, then +2 weeks.
    offset = (2 - first.weekday()) % 7
    return first + timedelta(days=offset + 14)


def _round_contracts(raw: float) -> int:
    """Nearest whole contract, rounding halves away from zero (documented)."""
    if not np.isfinite(raw):
        return 0
    return int(np.sign(raw) * np.floor(np.abs(raw) + 0.5))


# --------------------------------------------------------------------------- #
# Allocation artifact
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FxHedgeLeg:
    currency: str
    instrument: str
    futures_root: str
    yahoo_symbol: str
    beta: float
    beta_std_error: float
    t_stat: float
    spot_usd_per_unit: float
    target_notional_usd: float
    contract_size: float
    contract_size_currency: str
    usd_notional_per_contract: float
    target_contracts: int
    realized_notional_usd: float
    residual_notional_usd: float
    on_rate: float
    expected_annual_carry_usd: float
    expiry: str


@dataclass(frozen=True)
class FxHedgeAllocation:
    schema_version: int
    run_date: str
    generated_at: str
    base_currency: str
    hedge_target_pair: str
    hedge_target_yahoo: str
    target_definition: str
    return_convention: dict[str, Any]
    data_source: str
    hedge_notional_usd: float
    hedge_notional_source: str
    data_window: dict[str, Any]
    regression: dict[str, Any]
    legs: tuple[FxHedgeLeg, ...]
    totals: dict[str, Any]
    on_rates_as_of: str
    on_rates_source: str
    max_age_days: int

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["legs"] = [asdict(leg) for leg in self.legs]
        return payload

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "FxHedgeAllocation":
        legs = tuple(
            FxHedgeLeg(**{k: leg[k] for k in _LEG_FIELDS if k in leg})
            for leg in payload.get("legs", [])
        )
        return cls(
            schema_version=int(payload.get("schema_version", SCHEMA_VERSION)),
            run_date=str(payload.get("run_date", "")),
            generated_at=str(payload.get("generated_at", "")),
            base_currency=str(payload.get("base_currency", "")),
            hedge_target_pair=str(payload.get("hedge_target_pair", "")),
            hedge_target_yahoo=str(payload.get("hedge_target_yahoo", "")),
            target_definition=str(payload.get("target_definition", "")),
            return_convention=dict(payload.get("return_convention", {})),
            data_source=str(payload.get("data_source", "yahoo_finance")),
            hedge_notional_usd=float(payload.get("hedge_notional_usd", 0.0)),
            hedge_notional_source=str(payload.get("hedge_notional_source", "")),
            data_window=dict(payload.get("data_window", {})),
            regression=dict(payload.get("regression", {})),
            legs=legs,
            totals=dict(payload.get("totals", {})),
            on_rates_as_of=str(payload.get("on_rates_as_of", "")),
            on_rates_source=str(payload.get("on_rates_source", "")),
            max_age_days=int(payload.get("max_age_days", 30)),
        )


_LEG_FIELDS = tuple(f for f in FxHedgeLeg.__dataclass_fields__)  # type: ignore[attr-defined]


class FxHedgeComputationError(RuntimeError):
    """Raised when the hedge allocation cannot be computed (data/fit failure)."""


def compute_fx_hedge_allocation(
    *,
    config: FxHedgeConfig,
    hedge_notional_usd: float,
    hedge_notional_source: str,
    spot_loader: SpotPriceLoader,
    now: datetime | None = None,
) -> FxHedgeAllocation:
    """Run the full advisor: load spot → weekly returns → regress → contracts."""
    reference = now or datetime.now(timezone.utc)
    run_date = reference.date()
    expiry = next_quarterly_imm_expiry(run_date).isoformat()

    target_returns, regressor_returns, latest_spot = build_weekly_return_panel(
        config, spot_loader=spot_loader
    )
    regression = estimate_hedge_ratios(target_returns, regressor_returns)

    legs: list[FxHedgeLeg] = []
    for spec in config.instruments:
        beta = regression.betas[spec.currency]
        spot = latest_spot[spec.currency]
        usd_per_contract = (
            spec.contract_size if spec.usd_sized else spec.contract_size * spot
        )
        target_notional = beta * hedge_notional_usd
        raw_contracts = (
            target_notional / usd_per_contract if usd_per_contract else 0.0
        )
        contracts = _round_contracts(raw_contracts)
        realized = contracts * usd_per_contract
        # Carry of a long-foreign / short-USD leg ~= notional x (foreign - USD) ON.
        carry = realized * (spec.on_rate - config.on_rate_usd)
        legs.append(
            FxHedgeLeg(
                currency=spec.currency,
                instrument=spec.label,
                futures_root=spec.futures_root,
                yahoo_symbol=spec.yahoo_symbol,
                beta=beta,
                beta_std_error=regression.beta_std_errors[spec.currency],
                t_stat=regression.t_stats[spec.currency],
                spot_usd_per_unit=spot,
                target_notional_usd=target_notional,
                contract_size=spec.contract_size,
                contract_size_currency=spec.contract_size_currency,
                usd_notional_per_contract=usd_per_contract,
                target_contracts=contracts,
                realized_notional_usd=realized,
                residual_notional_usd=target_notional - realized,
                on_rate=spec.on_rate,
                expected_annual_carry_usd=carry,
                expiry=expiry,
            )
        )

    totals = _build_totals(
        legs,
        hedge_notional_usd=hedge_notional_usd,
        r_squared=regression.r_squared,
    )

    window = {
        "start": str(target_returns.index.min().date()),
        "end": str(target_returns.index.max().date()),
        "observations": int(regression.observations),
    }
    return FxHedgeAllocation(
        schema_version=SCHEMA_VERSION,
        run_date=run_date.isoformat(),
        generated_at=reference.astimezone(timezone.utc).isoformat(),
        base_currency=config.base_currency,
        hedge_target_pair=config.target_pair,
        hedge_target_yahoo=config.target_yahoo_symbol,
        target_definition=(
            f"r_tgt = Δln(USD per {config.target_currency}); investor long USD AUM "
            f"⇒ SGD-wealth exposure -A to r_tgt ⇒ hedge = long Σβᵢ·A USD notional "
            "of the foreign-currency futures (short USD)."
        ),
        return_convention={
            "price_basis": config.price_basis,
            "frequency": config.frequency,
            "overlapping": config.overlapping,
            "return_method": config.return_method,
            "lookback_weeks": config.lookback_weeks,
        },
        data_source="yahoo_finance",
        hedge_notional_usd=float(hedge_notional_usd),
        hedge_notional_source=hedge_notional_source,
        data_window=window,
        regression={
            "r_squared": regression.r_squared,
            "adj_r_squared": regression.adj_r_squared,
            "alpha_weekly": regression.alpha_weekly,
            "residual_vol_annualized": regression.residual_vol_annualized,
        },
        legs=tuple(legs),
        totals=totals,
        on_rates_as_of=config.on_rates_as_of,
        on_rates_source=config.on_rates_source,
        max_age_days=config.max_age_days,
    )


def _build_totals(
    legs: Sequence[FxHedgeLeg],
    *,
    hedge_notional_usd: float,
    r_squared: float,
) -> dict[str, Any]:
    target_gross = sum(abs(leg.target_notional_usd) for leg in legs)
    realized_gross = sum(abs(leg.realized_notional_usd) for leg in legs)
    realized_net = sum(leg.realized_notional_usd for leg in legs)
    rounding_residual = sum(leg.residual_notional_usd for leg in legs)
    carry = sum(leg.expected_annual_carry_usd for leg in legs)
    # Statistical (basis) risk the basket can't span: vol-equivalent share of the
    # target left unhedged even with perfectly-sized continuous positions.
    unhedged_fraction = max(0.0, 1.0 - r_squared)
    statistical_unhedged_usd = hedge_notional_usd * float(np.sqrt(unhedged_fraction))
    return {
        "target_notional_usd_gross": target_gross,
        "realized_notional_usd_gross": realized_gross,
        "realized_notional_usd_net": realized_net,
        "rounding_residual_usd": rounding_residual,
        "hedge_quality_r_squared": r_squared,
        "statistical_unhedged_fraction": unhedged_fraction,
        "statistical_unhedged_notional_usd": statistical_unhedged_usd,
        "expected_annual_carry_usd": carry,
        "expected_annual_carry_bps": (
            10_000.0 * carry / hedge_notional_usd if hedge_notional_usd else 0.0
        ),
    }


# --------------------------------------------------------------------------- #
# Artifact I/O
# --------------------------------------------------------------------------- #
def write_fx_hedge_allocation(
    allocation: FxHedgeAllocation, path: str | Path
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(allocation.to_payload(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return destination


def load_fx_hedge_allocation(path: str | Path) -> FxHedgeAllocation | None:
    artifact_path = Path(path)
    if not artifact_path.exists():
        return None
    loaded = json.loads(artifact_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("FX hedge allocation artifact must be a JSON object")
    return FxHedgeAllocation.from_payload(loaded)


# --------------------------------------------------------------------------- #
# Provider (cache + staleness), mirroring the regime report provider
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FxHedgeArtifactState:
    """Tagged result of providing an FX hedge allocation to a consumer.

    ``computed_fresh`` answers the acceptance-criterion question — was the
    allocation recomputed this run, or loaded from cache?
    """

    state: Literal["ok", "stale", "missing", "error"]
    mode_used: FxHedgeMode
    allocation: FxHedgeAllocation | None
    computed_fresh: bool
    age_days: int | None
    last_run_at: datetime | None
    error_message: str | None

    @property
    def is_renderable(self) -> bool:
        return self.allocation is not None

    @property
    def source_label(self) -> str:
        if self.computed_fresh:
            return "Freshly computed"
        if self.age_days is not None:
            plural = "day" if self.age_days == 1 else "days"
            return f"Loaded from cache ({self.age_days} {plural} old)"
        return "Loaded from cache"


def provide_fx_hedge_allocation(
    *,
    artifact_path: str | Path = DEFAULT_FX_HEDGE_ARTIFACT_PATH,
    config: FxHedgeConfig | None = None,
    config_path: str | Path | None = None,
    mode: FxHedgeMode = "refresh-if-stale",
    hedge_notional_usd: float | None = None,
    hedge_notional_source: str = "config_default",
    spot_loader: SpotPriceLoader | None = None,
    now: datetime | None = None,
) -> FxHedgeArtifactState:
    """Resolve the hedge allocation per ``mode``; never raises.

    * ``cached`` — load whatever is on disk (no recompute).
    * ``refresh-if-stale`` — recompute when missing or older than
      ``max_age_days``; otherwise reuse the cached run.
    * ``force-refresh`` — always recompute.

    Compute failures are converted to ``state="error"`` and we fall back to any
    cached allocation so a consumer still renders.
    """
    resolved_now = now or datetime.now(timezone.utc)
    resolved_config = config or load_fx_hedge_config(config_path)
    path = Path(artifact_path)

    cached = _safe_load(path)
    age_days = _allocation_age_days(cached, now=resolved_now)

    should_refresh = False
    if mode == "force-refresh":
        should_refresh = True
    elif mode == "refresh-if-stale":
        should_refresh = cached is None or (
            age_days is not None and age_days > resolved_config.max_age_days
        )

    if should_refresh:
        notional = (
            hedge_notional_usd
            if hedge_notional_usd is not None
            else resolved_config.default_hedge_notional_usd
        )
        loader = spot_loader or make_yahoo_spot_loader()
        try:
            allocation = compute_fx_hedge_allocation(
                config=resolved_config,
                hedge_notional_usd=notional,
                hedge_notional_source=hedge_notional_source,
                spot_loader=loader,
                now=resolved_now,
            )
        except (FxHedgeComputationError, YahooFinanceTransientError, ValueError) as exc:
            logger.warning("FX hedge refresh (mode=%s) failed: %s", mode, exc)
            return _error_state(cached, mode=mode, age_days=age_days, exc=exc, path=path)
        write_fx_hedge_allocation(allocation, path)
        return FxHedgeArtifactState(
            state="ok",
            mode_used=mode,
            allocation=allocation,
            computed_fresh=True,
            age_days=0,
            last_run_at=resolved_now,
            error_message=None,
        )

    if cached is None:
        return FxHedgeArtifactState(
            state="missing",
            mode_used=mode,
            allocation=None,
            computed_fresh=False,
            age_days=None,
            last_run_at=None,
            error_message=f"FX hedge allocation artifact not found at {path}",
        )

    state: Literal["ok", "stale"] = (
        "stale"
        if age_days is not None and age_days > resolved_config.max_age_days
        else "ok"
    )
    return FxHedgeArtifactState(
        state=state,
        mode_used=mode,
        allocation=cached,
        computed_fresh=False,
        age_days=age_days,
        last_run_at=_artifact_mtime(path),
        error_message=None,
    )


def _safe_load(path: Path) -> FxHedgeAllocation | None:
    try:
        return load_fx_hedge_allocation(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load FX hedge allocation %s: %s", path, exc)
        return None


def _allocation_age_days(
    allocation: FxHedgeAllocation | None, *, now: datetime
) -> int | None:
    if allocation is None or not allocation.run_date:
        return None
    try:
        run = date.fromisoformat(allocation.run_date)
    except ValueError:
        return None
    return (now.date() - run).days


def _artifact_mtime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _error_state(
    cached: FxHedgeAllocation | None,
    *,
    mode: FxHedgeMode,
    age_days: int | None,
    exc: Exception,
    path: Path,
) -> FxHedgeArtifactState:
    return FxHedgeArtifactState(
        state="error",
        mode_used=mode,
        allocation=cached,
        computed_fresh=False,
        age_days=age_days if cached is not None else None,
        last_run_at=_artifact_mtime(path) if cached is not None else None,
        error_message=str(exc),
    )


__all__ = [
    "DEFAULT_FX_HEDGE_ARTIFACT_PATH",
    "DEFAULT_FX_HEDGE_CONFIG_PATH",
    "FxHedgeAllocation",
    "FxHedgeArtifactState",
    "FxHedgeComputationError",
    "FxHedgeConfig",
    "FxHedgeLeg",
    "FxHedgeMode",
    "FxInstrumentSpec",
    "HedgeRegressionResult",
    "build_weekly_return_panel",
    "compute_fx_hedge_allocation",
    "estimate_hedge_ratios",
    "load_fx_hedge_allocation",
    "load_fx_hedge_config",
    "make_yahoo_spot_loader",
    "next_quarterly_imm_expiry",
    "provide_fx_hedge_allocation",
    "write_fx_hedge_allocation",
]
