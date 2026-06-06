"""Production training pipeline for the policy-expert ML predictor (goal-v2 Section B).

Rebuilds the monthly market+macro EX-ANTE feature panel + the forward-expert-return
labels from live keyless data (FRED + Yahoo), fits the model-selected **ElasticNet**
(see scripts/research/policy_expert_model_selection.py: best OOS excess-captured + rank-IC
among the deployable pure-Python family), and writes a DATED numpy-only artifact +
the refreshed feature panel.

Used by the lazy 30-day retrain in ``policy_expert_predictor.predict_latest``. Heavy deps
(sklearn, network) live HERE (training only); inference is pure-Python (coef-based).

The experts are EQ/CM/FI exposures (MACRO removed). The artifact stores the feature
schema + standardisation + linear coef so inference needs only numpy/stdlib.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from market_helper.app.paths import (
    POLICY_EXPERT_FEATURES_PATH,
    POLICY_EXPERT_MODEL_ARTIFACT_PATH,
    RESEARCH_ARTIFACTS_DIR,
)
from market_helper.data_library.loader import download_fred_series_csv
from market_helper.data_sources.yahoo_finance.client import YahooFinanceClient

EXPERTS = ["Goldilocks", "Reflation", "Stagflation", "Recession"]
SLEEVES = ("EQ", "CM", "FI")
H = 6                       # primary forward horizon (months)
SOFTMAX_TEMP = 0.03
MACRO_LAG = 1               # publication-lag guard on FRED-derived features
ALPHAS = [10.0, 30.0, 100.0, 300.0, 1000.0, 3000.0]   # Ridge L2 grid (heavy shrinkage)
VAL_WINDOW = 36             # embargoed validation window for alpha selection
EXPERTS_PATH = RESEARCH_ARTIFACTS_DIR / "policy_experts.json"
_CACHE = RESEARCH_ARTIFACTS_DIR / "_policy_expert_cache"


# --------------------------------------------------------------------------- data
def _yahoo_monthly_level(symbol: str) -> pd.Series:
    _CACHE.mkdir(parents=True, exist_ok=True)
    cache = _CACHE / f"yahoo_{symbol.replace('^', '_').replace('=', '_')}.feather"
    if cache.exists():
        d = pd.read_feather(cache)
    else:
        pl = YahooFinanceClient().fetch_price_history(symbol, period="max", interval="1mo")
        d = pd.DataFrame(pl["prices"])
        d["date"] = pd.to_datetime(d["timestamp"], unit="s").dt.normalize()
        d = d[["date", "adjclose"]].dropna().sort_values("date").reset_index(drop=True)
        d.to_feather(cache)
    return d.set_index("date")["adjclose"].astype(float).resample("ME").last()


def _fred_monthly(series_id: str) -> pd.Series:
    _CACHE.mkdir(parents=True, exist_ok=True)
    cache = _CACHE / f"fred_{series_id}.feather"
    if cache.exists():
        d = pd.read_feather(cache)
    else:
        es = download_fred_series_csv(series_id, observation_start="1950-01-01", timeout=60)
        d = pd.DataFrame([(o.date, o.value) for o in es.observations], columns=["date", "val"])
        d["date"] = pd.to_datetime(d["date"])
        d = d.dropna().reset_index(drop=True)
        d.to_feather(cache)
    return d.set_index("date")["val"].astype(float).sort_index()


def _to_period(s: pd.Series) -> pd.Series:
    s = s.copy()
    s.index = pd.to_datetime(s.index).to_period("M")
    return s


def _par_dur_conv(y: float, n_years: int = 10, m: int = 2) -> tuple[float, float]:
    per, r, coupon = n_years * m, y / m, y / m * 100.0
    t = np.arange(1, per + 1)
    cf = np.full(per, coupon, dtype=float)
    cf[-1] += 100.0
    pv = cf * (1.0 + r) ** (-t)
    price = pv.sum()
    mod_dur = ((t / m * pv).sum() / price) / (1.0 + r)
    conv = ((cf * t * (t + 1) * (1.0 + r) ** (-(t + 2))).sum() / price) / (m ** 2)
    return mod_dur, conv


def _synth_10y(gs10_pct: pd.Series) -> pd.Series:
    y = (gs10_pct / 100.0).sort_index()
    out = pd.Series(index=y.index, dtype=float)
    yv = y.to_numpy()
    for i in range(1, len(yv)):
        d, c = _par_dur_conv(yv[i - 1])
        out.iloc[i] = yv[i - 1] / 12.0 - d * (yv[i] - yv[i - 1]) + 0.5 * c * (yv[i] - yv[i - 1]) ** 2
    return out


def build_panel() -> pd.DataFrame:
    eq = _to_period(_yahoo_monthly_level("^SP500TR").pct_change())
    cm = _to_period(_yahoo_monthly_level("^SPGSCI").pct_change())
    fi = _to_period(_synth_10y(_fred_monthly("GS10")))
    cash = _to_period(_fred_monthly("TB3MS") / 100.0 / 12.0)
    df = pd.DataFrame({"EQ": eq, "CM": cm, "FI": fi, "CASH": cash}).dropna()
    return df[df.index >= pd.Period("1988-01", "M")]


# ----------------------------------------------------------------------- features
def _yoy(level: pd.Series) -> pd.Series:
    return (level / level.shift(12) - 1.0) * 100.0


def _fred_period(series_id: str) -> pd.Series:
    s = _fred_monthly(series_id)
    s.index = pd.to_datetime(s.index)
    if s.index.to_series().diff().median() < pd.Timedelta(days=20):
        s = s.resample("ME").mean()
    s.index = s.index.to_period("M")
    return s.sort_index()


def build_features(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    idx = panel.index
    feat = pd.DataFrame(index=idx)
    schema: dict = {}

    def macro(name, series, transform, group):
        feat[name] = series.reindex(idx)
        schema[name] = {"source": "FRED", "transform": transform, "lag_months": MACRO_LAG, "group": group}

    def market(name, series, transform, group):
        feat[name] = series.reindex(idx)
        schema[name] = {"source": "market", "transform": transform, "lag_months": 0, "group": group}

    cpi = _fred_period("CPIAUCSL")
    cpi_yoy = _yoy(cpi)
    macro("infl_yoy", cpi_yoy, "CPIAUCSL YoY %", "inflation")
    macro("infl_accel", cpi_yoy - cpi_yoy.shift(6), "CPI YoY 6m change", "inflation")
    macro("core_infl_yoy", _yoy(_fred_period("PCEPILFE")), "core PCE YoY %", "inflation")
    unrate = _fred_period("UNRATE")
    macro("unrate", unrate, "UNRATE level", "growth")
    macro("unrate_chg6", unrate - unrate.shift(6), "UNRATE 6m change", "growth")
    macro("payems_yoy", _yoy(_fred_period("PAYEMS")), "payrolls YoY %", "growth")
    macro("indpro_yoy", _yoy(_fred_period("INDPRO")), "industrial prod YoY %", "growth")
    ff = _fred_period("FEDFUNDS")
    macro("policy_rate", ff, "fed funds level", "policy")
    macro("policy_rate_chg6", ff - ff.shift(6), "fed funds 6m change", "policy")
    gs10 = _fred_period("GS10")
    macro("real_yield", gs10 - cpi_yoy, "GS10 - CPI YoY", "rates")
    macro("curve_slope", gs10 - _fred_period("GS2"), "GS10 - GS2", "rates")
    macro("credit_spread", _fred_period("BAA") - _fred_period("AAA"), "BAA - AAA", "credit")
    try:
        market("vix", _to_period(_yahoo_monthly_level("^VIX")), "VIX monthly close level", "risk")
    except Exception:  # noqa: BLE001
        pass

    for s in ("EQ", "CM", "FI"):
        mom = (1 + panel[s]).rolling(12).apply(lambda v: v.prod() - 1, raw=True) * 100
        market(f"{s.lower()}_mom12", mom, f"{s} trailing 12m return %", "momentum")
    try:
        dxy = _to_period(_yahoo_monthly_level("DX-Y.NYB").pct_change())
        market("usd_mom12", (1 + dxy).rolling(12).apply(lambda v: v.prod() - 1, raw=True) * 100,
               "USD (DXY) trailing 12m %", "momentum")
    except Exception:  # noqa: BLE001
        pass

    eq_level = (1 + panel["EQ"]).cumprod()
    market("eq_drawdown", (eq_level / eq_level.cummax() - 1) * 100, "EQ drawdown %", "stress")
    fi_level = (1 + panel["FI"]).cumprod()
    market("fi_drawdown", (fi_level / fi_level.cummax() - 1) * 100, "FI drawdown %", "stress")
    market("move_proxy", panel["FI"].rolling(3).std() * np.sqrt(12) * 100, "FI 3m realized vol %", "stress")
    market("eqfi_corr12", panel["EQ"].rolling(12).corr(panel["FI"]), "rolling 12m corr(EQ,FI)", "cross")
    ex = pd.DataFrame({s: panel[s] - panel["CASH"] for s in ("EQ", "CM", "FI")})
    trend = np.sign((1 + ex).rolling(12).apply(lambda v: v.prod() - 1, raw=True))
    market("trend_breadth", trend.sum(axis=1), "n positive 12m trends (-3..3)", "trend")

    macro_cols = [c for c, m in schema.items() if m["lag_months"] == MACRO_LAG]
    feat[macro_cols] = feat[macro_cols].shift(MACRO_LAG)
    return feat, schema


# ------------------------------------------------------------------------- labels
def expert_returns(panel: pd.DataFrame, experts: dict) -> pd.DataFrame:
    cash = panel["CASH"]
    out = {}
    for k in EXPERTS:
        e = experts[k]
        out[k] = cash + (e["EQ"] * (panel["EQ"] - cash) + e["CM"] * (panel["CM"] - cash)
                         + e["FI"] * (panel["FI"] - cash)) / 100.0
    return pd.DataFrame(out)


def forward_returns(rets: pd.DataFrame, h: int = H) -> pd.DataFrame:
    return np.expm1(np.log1p(rets).rolling(h).sum().shift(-h))


# -------------------------------------------------------------------------- train
def _select_alpha(Xs: np.ndarray, Y: np.ndarray) -> float:
    """Ridge alpha by an embargoed time-series split (heavy shrinkage; the H-month
    targets are autocorrelated, so a low alpha overfits). Same discipline as the
    research walk-forward predictor. Ridge L2 shrinks but keeps non-zero coefficients,
    so the model stays dynamic + interpretable (unlike an over-penalised ElasticNet,
    which zeroes every coef and collapses to the static unconditional ranking)."""
    from sklearn.linear_model import Ridge
    n = len(Xs)
    val_start = n - VAL_WINDOW
    fit_end = max(1, val_start - H)
    if fit_end < 24 or (n - val_start) < 6:
        return 300.0
    Xf, Yf, Xv, Yv = Xs[:fit_end], Y[:fit_end], Xs[val_start:], Y[val_start:]
    best_a, best_mse = ALPHAS[-1], float("inf")
    for a in ALPHAS:
        m = Ridge(alpha=a).fit(Xf, Yf)
        mse = float(((m.predict(Xv) - Yv) ** 2).mean())
        if mse < best_mse:
            best_mse, best_a = mse, a
    return best_a


def train(write: bool = True) -> dict:
    """Rebuild features/labels from live data, fit the model-selected Ridge (embargoed-CV
    alpha) on ALL complete data, and (optionally) write the dated artifact + features."""
    from sklearn.linear_model import Ridge  # training-only dep

    experts = json.loads(EXPERTS_PATH.read_text(encoding="utf-8"))["experts"]
    panel = build_panel()
    feat, schema = build_features(panel)
    fwd = forward_returns(expert_returns(panel, experts))
    fwd.columns = [f"fwd_{H}m_{k}" for k in EXPERTS]

    feat_cols = list(feat.columns)
    data = feat.join(fwd).dropna(subset=feat_cols + list(fwd.columns))
    X = data[feat_cols].to_numpy(float)
    Y = data[[f"fwd_{H}m_{k}" for k in EXPERTS]].to_numpy(float)
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    Xs = (X - mu) / sd
    alpha = _select_alpha(Xs, Y)
    model = Ridge(alpha=alpha).fit(Xs, Y)
    coef = np.atleast_2d(model.coef_)
    intercept = np.atleast_1d(model.intercept_)

    artifact = {
        "model": "ridge",
        "trained_at": datetime.now(timezone.utc).date().isoformat(),
        "horizon_months": H, "softmax_temp": SOFTMAX_TEMP,
        "alpha": float(alpha),
        "experts": EXPERTS,
        "expert_exposures": {k: experts[k] for k in EXPERTS},
        "feature_names": feat_cols,
        "feature_schema": {c: schema.get(c, {}) for c in feat_cols},
        "standardize_mean": [round(float(x), 6) for x in mu],
        "standardize_std": [round(float(x), 6) for x in sd],
        "intercept": [round(float(x), 8) for x in intercept],
        "coef": [[round(float(c), 8) for c in row] for row in coef],
        "trained_rows": int(len(data)),
        "trained_span": [str(data.index.min()), str(data.index.max())],
    }
    if write:
        POLICY_EXPERT_MODEL_ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
        POLICY_EXPERT_MODEL_ARTIFACT_PATH.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
        out = feat.copy()
        out.index = out.index.astype(str)
        out.index.name = "month"
        out.to_csv(POLICY_EXPERT_FEATURES_PATH)
    return artifact


if __name__ == "__main__":
    art = train()
    print(f"trained_at={art['trained_at']} rows={art['trained_rows']} "
          f"span={art['trained_span']} features={len(art['feature_names'])}")
