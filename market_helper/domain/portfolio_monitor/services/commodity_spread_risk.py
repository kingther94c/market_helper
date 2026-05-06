from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.linear_model import HuberRegressor

from market_helper.app.paths import PORTFOLIO_ARTIFACTS_DIR
from market_helper.data_sources.yahoo_finance import YahooFinanceClient


DEFAULT_COMMODITY_SPREAD_CACHE_DIR = PORTFOLIO_ARTIFACTS_DIR / "commodity_spread_risk"
DEFAULT_COMMODITY_SPREAD_PRICE_PERIOD = "5y"
DEFAULT_COMMODITY_SPREAD_PRICE_INTERVAL = "1d"
COMMODITY_SPREAD_CACHE_VERSION = 2
MONTH_CODE_ORDER = {
    "F": 1,
    "G": 2,
    "H": 3,
    "J": 4,
    "K": 5,
    "M": 6,
    "N": 7,
    "Q": 8,
    "U": 9,
    "V": 10,
    "X": 11,
    "Z": 12,
}


@dataclass(frozen=True)
class CommoditySpreadParameters:
    window: int = 120
    half_life: float = 40.0
    clip_window: int = 60
    clip_z: float = 5.0
    huber_epsilon: float = 1.5
    min_observations: int = 30


@dataclass(frozen=True)
class CommoditySpreadRootConfig:
    root: str
    exchange: str
    front_yahoo_symbol: str
    contract_yahoo_suffix: str
    parameters: CommoditySpreadParameters = CommoditySpreadParameters()


@dataclass(frozen=True)
class CommoditySpreadRuntimeConfig:
    enabled: bool
    cache_ttl_days: int
    roots: Mapping[str, CommoditySpreadRootConfig]
    cache_dir: Path = DEFAULT_COMMODITY_SPREAD_CACHE_DIR


@dataclass(frozen=True)
class CommoditySpreadLeg:
    account: str
    root: str
    exchange: str
    local_symbol: str
    quantity: float
    multiplier: float
    latest_price: float
    market_value: float
    cm_sector: str = ""


@dataclass(frozen=True)
class CommoditySpreadRiskResult:
    cache_key: str
    account: str
    root: str
    exchange: str
    display_name: str
    display_quantity: float
    base_leg_local_symbol: str
    beta: float
    alpha: float
    signed_exposure_usd: float
    gross_exposure_usd: float
    beta_vol_usd: float
    residual_vol_usd: float
    total_vol_usd: float
    vol_ratio: float
    front_notional_usd: float
    as_of_price_date: str
    spread_return_series: pd.Series
    front_return_series: pd.Series
    from_cache: bool = False


def ewma_weights(n: int, half_life: float = 40.0) -> np.ndarray:
    if n <= 0:
        return np.array([], dtype=float)
    if half_life <= 0:
        raise ValueError("half_life must be positive")
    lam = 0.5 ** (1.0 / half_life)
    weights = lam ** np.arange(n, dtype=float)[::-1]
    return weights / weights.mean()


def rolling_clip(series: pd.Series, *, window: int = 60, z: float = 5.0) -> pd.Series:
    if window <= 0:
        raise ValueError("window must be positive")
    if z < 0:
        raise ValueError("z must be non-negative")
    materialized = pd.Series(series, dtype=float).copy()
    sigma = materialized.rolling(window, min_periods=min(20, window)).std()
    mask = sigma.notna()
    if not mask.any():
        return materialized
    materialized.loc[mask] = materialized.loc[mask].clip(
        lower=-z * sigma.loc[mask],
        upper=z * sigma.loc[mask],
    )
    return materialized


def robust_beta_huber(
    y: pd.Series,
    x: pd.Series,
    *,
    half_life: float = 40.0,
    epsilon: float = 1.5,
    min_observations: int = 30,
) -> tuple[float, float] | None:
    df = pd.concat([pd.Series(y, dtype=float).rename("y"), pd.Series(x, dtype=float).rename("x")], axis=1).dropna()
    if len(df) < min_observations:
        return None
    x_values = df["x"].to_numpy(dtype=float).reshape(-1, 1)
    y_values = df["y"].to_numpy(dtype=float)
    if not np.isfinite(x_values).all() or not np.isfinite(y_values).all():
        return None
    if np.nanstd(x_values) <= 0:
        return None
    model = HuberRegressor(
        epsilon=epsilon,
        alpha=0.0,
        fit_intercept=True,
        max_iter=500,
    )
    model.fit(x_values, y_values, sample_weight=ewma_weights(len(df), half_life))
    return float(model.intercept_), float(model.coef_[0])


def compute_or_load_commodity_spread_risk(
    legs: Sequence[CommoditySpreadLeg],
    *,
    config: CommoditySpreadRootConfig,
    yahoo_client: YahooFinanceClient,
    cache_dir: str | Path = DEFAULT_COMMODITY_SPREAD_CACHE_DIR,
    cache_ttl_days: int = 7,
    trading_days: int = 252,
    now: pd.Timestamp | None = None,
) -> CommoditySpreadRiskResult | None:
    materialized_legs = _sorted_legs(tuple(legs))
    if not _eligible_legs(materialized_legs, config=config):
        return None

    cache_key = commodity_spread_cache_key(materialized_legs, config=config, trading_days=trading_days)
    cache_path = commodity_spread_cache_path(cache_key, cache_dir=cache_dir, root=config.root, exchange=config.exchange)
    cached_payload = _load_cache_payload(cache_path)
    if cached_payload is not None and _is_cache_payload_fresh(
        cached_payload,
        cache_key=cache_key,
        cache_ttl_days=cache_ttl_days,
        now=now,
    ):
        cached = _result_from_cache_payload(cached_payload, materialized_legs, config=config)
        if cached is not None:
            return cached

    try:
        computed = _compute_commodity_spread_risk(
            materialized_legs,
            config=config,
            yahoo_client=yahoo_client,
            cache_key=cache_key,
            trading_days=trading_days,
        )
    except Exception:
        computed = None
    if computed is None:
        return None
    _write_cache_payload(cache_path, _result_to_cache_payload(computed, materialized_legs, config=config))
    return computed


def commodity_spread_cache_key(
    legs: Sequence[CommoditySpreadLeg],
    *,
    config: CommoditySpreadRootConfig,
    trading_days: int,
) -> str:
    payload = {
        "version": COMMODITY_SPREAD_CACHE_VERSION,
        "account": legs[0].account if legs else "",
        "root": config.root.upper(),
        "exchange": config.exchange.upper(),
        "front_yahoo_symbol": config.front_yahoo_symbol,
        "contract_yahoo_suffix": config.contract_yahoo_suffix,
        "trading_days": int(trading_days),
        "parameters": config.parameters.__dict__,
        "legs": [
            {
                "local_symbol": leg.local_symbol.upper(),
                "quantity": _rounded_float(leg.quantity),
                "multiplier": _rounded_float(leg.multiplier),
            }
            for leg in _sorted_legs(tuple(legs))
        ],
        "base_leg_local_symbol": _base_leg(_sorted_legs(tuple(legs))).local_symbol.upper() if legs else "",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def commodity_spread_cache_path(
    cache_key: str,
    *,
    cache_dir: str | Path = DEFAULT_COMMODITY_SPREAD_CACHE_DIR,
    root: str,
    exchange: str,
) -> Path:
    prefix = f"{_safe_file_token(root)}_{_safe_file_token(exchange)}"
    return Path(cache_dir) / f"{prefix}_{cache_key[:24]}.json"


def _compute_commodity_spread_risk(
    legs: tuple[CommoditySpreadLeg, ...],
    *,
    config: CommoditySpreadRootConfig,
    yahoo_client: YahooFinanceClient,
    cache_key: str,
    trading_days: int,
) -> CommoditySpreadRiskResult | None:
    try:
        leg_prices = {
            leg.local_symbol: _fetch_close_series(
                yahoo_client,
                _contract_yahoo_symbol(leg.local_symbol, config.contract_yahoo_suffix),
            )
            for leg in legs
        }
        front_prices = _fetch_close_series(yahoo_client, config.front_yahoo_symbol)
    except Exception:
        return None

    leg_pnl = []
    for leg in legs:
        prices = leg_prices.get(leg.local_symbol)
        if prices is None or prices.dropna().empty:
            return None
        leg_pnl.append((leg.quantity * leg.multiplier * prices.diff()).rename(leg.local_symbol))
    leg_pnl_frame = pd.concat(leg_pnl, axis=1)
    spread_pnl_raw = leg_pnl_frame.sum(axis=1, min_count=len(legs))
    front_multiplier = _base_leg(legs).multiplier
    front_pnl_raw = front_multiplier * front_prices.diff()

    parameters = config.parameters
    spread_pnl = rolling_clip(spread_pnl_raw, window=parameters.clip_window, z=parameters.clip_z)
    front_pnl = rolling_clip(front_pnl_raw, window=parameters.clip_window, z=parameters.clip_z)
    df = pd.concat(
        [spread_pnl.rename("spread_pnl"), front_pnl.rename("front_pnl")],
        axis=1,
    ).dropna()
    if len(df) < max(parameters.window, parameters.min_observations):
        return None

    regression = _rolling_robust_regression(
        df,
        parameters=parameters,
        trading_days=trading_days,
    )
    if regression is None:
        return None

    beta = regression["beta"]
    base = _base_leg(legs)
    exposure = _gross_exposure_from_beta(beta=beta, base_leg=base)
    front_notional_usd = _front_notional_usd(base)
    if exposure <= 0:
        return None
    total_vol_usd = regression["total_vol_usd"]
    if total_vol_usd <= 0:
        return None
    spread_return_series = regression["spread_pnl_series"] / exposure
    front_return_series = regression["front_pnl_series"] / front_notional_usd
    return CommoditySpreadRiskResult(
        cache_key=cache_key,
        account=base.account,
        root=config.root.upper(),
        exchange=config.exchange.upper(),
        display_name=_display_name(config.root, legs),
        display_quantity=-1.0 if beta < 0 else 1.0,
        base_leg_local_symbol=base.local_symbol,
        beta=beta,
        alpha=regression["alpha"],
        signed_exposure_usd=exposure,
        gross_exposure_usd=abs(exposure),
        beta_vol_usd=regression["beta_vol_usd"],
        residual_vol_usd=regression["residual_vol_usd"],
        total_vol_usd=total_vol_usd,
        vol_ratio=total_vol_usd / exposure,
        front_notional_usd=front_notional_usd,
        as_of_price_date=regression["as_of_price_date"],
        spread_return_series=spread_return_series,
        front_return_series=front_return_series,
        from_cache=False,
    )


def _rolling_robust_regression(
    df: pd.DataFrame,
    *,
    parameters: CommoditySpreadParameters,
    trading_days: int,
) -> dict[str, Any] | None:
    sample = df.tail(parameters.window)
    fitted = robust_beta_huber(
        sample["spread_pnl"],
        sample["front_pnl"],
        half_life=parameters.half_life,
        epsilon=parameters.huber_epsilon,
        min_observations=parameters.min_observations,
    )
    if fitted is None:
        return None
    alpha, beta = fitted

    result = df.copy()
    result["directional_pnl"] = alpha + beta * result["front_pnl"]
    result["residual_pnl"] = result["spread_pnl"] - result["directional_pnl"]
    ann = math.sqrt(trading_days)
    result["total_vol_usd"] = result["spread_pnl"].rolling(parameters.window).std() * ann
    result["beta_vol_usd"] = result["directional_pnl"].rolling(parameters.window).std() * ann
    result["residual_vol_usd"] = result["residual_pnl"].rolling(parameters.window).std() * ann

    latest = result.dropna(subset=["total_vol_usd"]).tail(1)
    if latest.empty:
        return None
    row = latest.iloc[0]
    values = {
        "alpha": float(alpha),
        "beta": float(beta),
        "total_vol_usd": float(row["total_vol_usd"]),
        "beta_vol_usd": _finite_float(row.get("beta_vol_usd")) or 0.0,
        "residual_vol_usd": _finite_float(row.get("residual_vol_usd")) or 0.0,
    }
    if not all(math.isfinite(value) for value in values.values()):
        return None
    if abs(values["beta"]) <= 1e-12:
        return None
    return {
        **values,
        "as_of_price_date": _normalize_date_key(latest.index[-1]),
        "spread_pnl_series": result["spread_pnl"].dropna(),
        "front_pnl_series": result["front_pnl"].dropna(),
    }


def _fetch_close_series(yahoo_client: YahooFinanceClient, symbol: str) -> pd.Series:
    history = yahoo_client.fetch_price_history(
        symbol,
        period=DEFAULT_COMMODITY_SPREAD_PRICE_PERIOD,
        interval=DEFAULT_COMMODITY_SPREAD_PRICE_INTERVAL,
    )
    prices = history.get("prices") if isinstance(history, Mapping) else None
    if not isinstance(prices, list):
        return pd.Series(dtype=float)
    rows: list[tuple[pd.Timestamp, float]] = []
    for row in prices:
        if not isinstance(row, Mapping):
            continue
        raw_timestamp = row.get("timestamp")
        raw_close = row.get("close")
        if raw_timestamp in (None, "") or raw_close in (None, ""):
            continue
        timestamp = pd.to_datetime(int(raw_timestamp), unit="s", utc=True).tz_localize(None).normalize()
        rows.append((timestamp, float(raw_close)))
    if not rows:
        return pd.Series(dtype=float)
    series = pd.Series(
        [price for _, price in rows],
        index=pd.DatetimeIndex([timestamp for timestamp, _ in rows]),
        dtype=float,
    ).sort_index()
    return series[~series.index.duplicated(keep="last")]


def _load_cache_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return loaded if isinstance(loaded, dict) else None


def _write_cache_payload(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _is_cache_payload_fresh(
    payload: Mapping[str, Any],
    *,
    cache_key: str,
    cache_ttl_days: int,
    now: pd.Timestamp | None,
) -> bool:
    if payload.get("cache_key") != cache_key:
        return False
    if payload.get("version") != COMMODITY_SPREAD_CACHE_VERSION:
        return False
    generated_at = _optional_timestamp(payload.get("generated_at"))
    if generated_at is None:
        return False
    reference = pd.Timestamp.utcnow() if now is None else pd.Timestamp(now)
    if reference.tzinfo is not None:
        reference = reference.tz_localize(None)
    age_days = (reference - generated_at).total_seconds() / 86400.0
    if age_days < 0 or age_days > cache_ttl_days:
        return False
    return all(
        _finite_float(payload.get(key)) is not None
        for key in ("alpha", "beta", "total_vol_usd", "beta_vol_usd", "residual_vol_usd")
    ) and bool(payload.get("front_pnl_series"))


def _result_from_cache_payload(
    payload: Mapping[str, Any],
    legs: tuple[CommoditySpreadLeg, ...],
    *,
    config: CommoditySpreadRootConfig,
) -> CommoditySpreadRiskResult | None:
    alpha = _finite_float(payload.get("alpha"))
    beta = _finite_float(payload.get("beta"))
    beta_vol_usd = _finite_float(payload.get("beta_vol_usd"))
    residual_vol_usd = _finite_float(payload.get("residual_vol_usd"))
    total_vol_usd = _finite_float(payload.get("total_vol_usd"))
    if None in {alpha, beta, beta_vol_usd, residual_vol_usd, total_vol_usd} or abs(beta or 0.0) <= 1e-12:
        return None
    base = _base_leg(legs)
    exposure = _gross_exposure_from_beta(beta=beta or 0.0, base_leg=base)
    if exposure <= 0 or total_vol_usd is None or total_vol_usd <= 0:
        return None
    spread_pnl_series = _dated_mapping_to_series(payload.get("spread_pnl_series", {}))
    front_pnl_series = _dated_mapping_to_series(payload.get("front_pnl_series", {}))
    front_notional_usd = _front_notional_usd(base)
    if front_pnl_series.empty or front_notional_usd <= 0:
        return None
    spread_return_series = spread_pnl_series / exposure if not spread_pnl_series.empty else pd.Series(dtype=float)
    front_return_series = front_pnl_series / front_notional_usd
    return CommoditySpreadRiskResult(
        cache_key=str(payload.get("cache_key") or ""),
        account=base.account,
        root=config.root.upper(),
        exchange=config.exchange.upper(),
        display_name=_display_name(config.root, legs),
        display_quantity=-1.0 if (beta or 0.0) < 0 else 1.0,
        base_leg_local_symbol=base.local_symbol,
        beta=float(beta or 0.0),
        alpha=float(alpha or 0.0),
        signed_exposure_usd=exposure,
        gross_exposure_usd=abs(exposure),
        beta_vol_usd=float(beta_vol_usd or 0.0),
        residual_vol_usd=float(residual_vol_usd or 0.0),
        total_vol_usd=total_vol_usd,
        vol_ratio=total_vol_usd / exposure,
        front_notional_usd=front_notional_usd,
        as_of_price_date=str(payload.get("as_of_price_date") or ""),
        spread_return_series=spread_return_series,
        front_return_series=front_return_series,
        from_cache=True,
    )


def _result_to_cache_payload(
    result: CommoditySpreadRiskResult,
    legs: tuple[CommoditySpreadLeg, ...],
    *,
    config: CommoditySpreadRootConfig,
) -> dict[str, Any]:
    return {
        "version": COMMODITY_SPREAD_CACHE_VERSION,
        "generated_at": pd.Timestamp.utcnow().tz_localize(None).isoformat(),
        "cache_key": result.cache_key,
        "account": result.account,
        "root": result.root,
        "exchange": result.exchange,
        "front_yahoo_symbol": config.front_yahoo_symbol,
        "contract_yahoo_suffix": config.contract_yahoo_suffix,
        "parameters": config.parameters.__dict__,
        "legs": [
            {
                "local_symbol": leg.local_symbol,
                "quantity": leg.quantity,
                "multiplier": leg.multiplier,
            }
            for leg in legs
        ],
        "base_leg_local_symbol": result.base_leg_local_symbol,
        "as_of_price_date": result.as_of_price_date,
        "alpha": result.alpha,
        "beta": result.beta,
        "display_quantity": result.display_quantity,
        "beta_vol_usd": result.beta_vol_usd,
        "residual_vol_usd": result.residual_vol_usd,
        "total_vol_usd": result.total_vol_usd,
        "front_notional_usd": result.front_notional_usd,
        "spread_pnl_series": {
            _normalize_date_key(index): float(value)
            for index, value in (result.spread_return_series * result.gross_exposure_usd).dropna().items()
        },
        "front_pnl_series": {
            _normalize_date_key(index): float(value)
            for index, value in (result.front_return_series * result.front_notional_usd).dropna().items()
        },
    }


def _eligible_legs(
    legs: tuple[CommoditySpreadLeg, ...],
    *,
    config: CommoditySpreadRootConfig,
) -> bool:
    if len(legs) < 2:
        return False
    roots = {leg.root.upper() for leg in legs}
    exchanges = {leg.exchange.upper() for leg in legs}
    accounts = {leg.account for leg in legs}
    if roots != {config.root.upper()} or exchanges != {config.exchange.upper()} or len(accounts) != 1:
        return False
    signs = {1 if leg.quantity > 0 else -1 if leg.quantity < 0 else 0 for leg in legs}
    return 1 in signs and -1 in signs and all(leg.local_symbol for leg in legs)


def _gross_exposure_from_beta(*, beta: float, base_leg: CommoditySpreadLeg) -> float:
    front_notional = _front_notional_usd(base_leg)
    if front_notional <= 0:
        return 0.0
    return abs(beta) * front_notional


def _front_notional_usd(base_leg: CommoditySpreadLeg) -> float:
    if base_leg.latest_price <= 0 or base_leg.multiplier <= 0:
        return 0.0
    return base_leg.latest_price * base_leg.multiplier


def _base_leg(legs: tuple[CommoditySpreadLeg, ...]) -> CommoditySpreadLeg:
    return _sorted_legs(legs)[0]


def _sorted_legs(legs: tuple[CommoditySpreadLeg, ...]) -> tuple[CommoditySpreadLeg, ...]:
    return tuple(sorted(legs, key=lambda leg: (_expiry_sort_key(leg.root, leg.local_symbol), leg.local_symbol)))


def _expiry_sort_key(root: str, local_symbol: str) -> tuple[int, int, str]:
    suffix = str(local_symbol).upper().removeprefix(str(root).upper())
    if len(suffix) >= 3:
        month = MONTH_CODE_ORDER.get(suffix[0])
        year_text = suffix[1:3]
        if month is not None and year_text.isdigit():
            year = 2000 + int(year_text)
            return year, month, suffix
    return 9999, 99, suffix


def _display_name(root: str, legs: tuple[CommoditySpreadLeg, ...]) -> str:
    tokens = []
    for leg in _sorted_legs(legs):
        suffix = leg.local_symbol.upper().removeprefix(root.upper())
        tokens.append(f"{_format_signed_quantity(leg.quantity)} {suffix or leg.local_symbol.upper()}")
    return f"{root.upper()}[{' '.join(tokens)}]"


def _format_signed_quantity(value: float) -> str:
    sign = "+" if value >= 0 else "-"
    magnitude = abs(value)
    if float(magnitude).is_integer():
        return f"{sign}{int(magnitude)}"
    return f"{sign}{magnitude:g}"


def _contract_yahoo_symbol(local_symbol: str, suffix: str) -> str:
    normalized_suffix = str(suffix).strip().lstrip(".")
    return f"{str(local_symbol).strip().upper()}.{normalized_suffix}"


def _safe_file_token(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(value).upper()).strip("_") or "SPREAD"


def _rounded_float(value: float) -> float:
    return round(float(value), 10)


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _optional_timestamp(value: Any) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    try:
        timestamp = pd.Timestamp(value)
    except Exception:
        return None
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_localize(None)
    return timestamp


def _dated_mapping_to_series(value: Any) -> pd.Series:
    if not isinstance(value, Mapping):
        return pd.Series(dtype=float)
    pairs = []
    for raw_date, raw_value in value.items():
        parsed = _finite_float(raw_value)
        if parsed is None:
            continue
        pairs.append((pd.to_datetime(str(raw_date)).normalize(), parsed))
    if not pairs:
        return pd.Series(dtype=float)
    pairs.sort(key=lambda item: item[0])
    return pd.Series(
        [item[1] for item in pairs],
        index=pd.DatetimeIndex([item[0] for item in pairs]),
        dtype=float,
    )


def _normalize_date_key(index: Any) -> str:
    return pd.Timestamp(index).normalize().date().isoformat()


__all__ = [
    "CommoditySpreadLeg",
    "CommoditySpreadParameters",
    "CommoditySpreadRiskResult",
    "CommoditySpreadRootConfig",
    "CommoditySpreadRuntimeConfig",
    "DEFAULT_COMMODITY_SPREAD_CACHE_DIR",
    "commodity_spread_cache_key",
    "compute_or_load_commodity_spread_risk",
    "ewma_weights",
    "robust_beta_huber",
    "rolling_clip",
]
