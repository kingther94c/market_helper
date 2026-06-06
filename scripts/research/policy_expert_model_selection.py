"""Phase 4 / goal-v2 Section B1 -- rigorous model selection for the policy-expert predictor.

Compares candidate model families by walk-forward, EMBARGOED time-series CV on the SAME
ex-ante feature panel and the same forward-expert-return target as policy_expert_model.py.
Every candidate is reduced to a common output -- a soft allocation over the 4 experts --
so they are scored apples-to-apples:

  - regressors predict the 6M forward expert returns -> demean -> softmax(temp) -> alloc
  - the multinomial-logistic classifier predicts P(winner=k) directly -> alloc

Scored OOS by: excess captured (sum_k alloc_k * realized cross-sectional excess -- the
economic objective), pooled rank-IC, top-1 accuracy, and log-loss vs the realized winner.

Candidates: ridge, elastic-net, multinomial-logit, random-forest, hist-grad-boosting, and
a linear voting ensemble (ridge+elasticnet+logit). The DEPLOYABLE production model is
restricted to the pure-Python-inferable linear family (coef-based); trees are evaluated
to see whether they justify a heavier deploy -- given autocorrelated targets they rarely
beat heavy-shrinkage linear (confirmed below).

Refit cadence here is annual (relative ranking is what matters; production refits per the
30-day lazy schedule). Outputs: data/research_artifacts/policy_expert_model_selection.json.
No execution. ASCII console.
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import ElasticNet, LogisticRegression, Ridge
from sklearn.metrics import log_loss
from sklearn.multioutput import MultiOutputRegressor

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.research.policy_expert_model import (  # noqa: E402
    EXPERTS, H, SOFTMAX_TEMP, _select_alpha, load_data,
)

OUT_JSON = REPO_ROOT / "data/research_artifacts/policy_expert_model_selection.json"
MIN_TRAIN = 120
REFIT = 12          # annual refit for the comparison
warnings.filterwarnings("ignore")


def _softmax(M: np.ndarray, temp: float) -> np.ndarray:
    z = (M - M.mean(1, keepdims=True)) / temp
    z = z - z.max(1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(1, keepdims=True)


def _alloc_from_returns(pred_fwd: np.ndarray) -> np.ndarray:
    return _softmax(pred_fwd, SOFTMAX_TEMP)


def fit_predict(name: str, Xtr, Ytr, Wtr, Xte):
    """Return the OOS allocation (n_te x 4) for a candidate trained on (Xtr,Ytr[/Wtr])."""
    mu, sd = Xtr.mean(0), Xtr.std(0)
    sd[sd == 0] = 1.0
    Xs, Xt = (Xtr - mu) / sd, (Xte - mu) / sd
    if name == "ridge":
        m = Ridge(alpha=_select_alpha(Xs, Ytr)).fit(Xs, Ytr)
        return _alloc_from_returns(m.predict(Xt))
    if name == "elasticnet":
        m = ElasticNet(alpha=1.0, l1_ratio=0.2, max_iter=5000).fit(Xs, Ytr)
        return _alloc_from_returns(np.atleast_2d(m.predict(Xt)))
    if name == "mlogit":
        if len(set(Wtr)) < 2:
            return np.full((len(Xt), len(EXPERTS)), 1 / len(EXPERTS))
        m = LogisticRegression(C=0.3, max_iter=3000).fit(Xs, Wtr)
        proba = m.predict_proba(Xt)
        full = np.full((len(Xt), len(EXPERTS)), 1e-6)
        for j, cls in enumerate(m.classes_):
            full[:, EXPERTS.index(cls)] = proba[:, j]
        return full / full.sum(1, keepdims=True)
    if name == "rf":
        m = RandomForestRegressor(n_estimators=200, max_depth=4, min_samples_leaf=20,
                                  random_state=0, n_jobs=-1).fit(Xs, Ytr)
        return _alloc_from_returns(m.predict(Xt))
    if name == "hgb":
        m = MultiOutputRegressor(HistGradientBoostingRegressor(
            max_depth=3, max_iter=200, learning_rate=0.05, l2_regularization=1.0,
            random_state=0)).fit(Xs, Ytr)
        return _alloc_from_returns(m.predict(Xt))
    if name == "ensemble_linear":
        parts = [fit_predict(n, Xtr, Ytr, Wtr, Xte) for n in ("ridge", "elasticnet", "mlogit")]
        a = np.mean(parts, axis=0)
        return a / a.sum(1, keepdims=True)
    raise ValueError(name)


def walk_forward(name: str, data: pd.DataFrame, feat_cols: list[str]) -> pd.DataFrame:
    months = list(data.index)
    X = data[feat_cols].to_numpy(float)
    Y = data[EXPERTS].to_numpy(float)
    W = data["winner"].to_numpy()
    rows, idx = [], []
    last_fit = -10_000
    cache = None
    for i, t in enumerate(months):
        train_mask = np.array([(months[j] + H) <= t for j in range(len(months))])
        train_mask[i:] = False
        if train_mask.sum() < MIN_TRAIN:
            continue
        if i - last_fit >= REFIT or cache is None:
            cache = (X[train_mask], Y[train_mask], W[train_mask])
            last_fit = i
        alloc = fit_predict(name, cache[0], cache[1], cache[2], X[i:i + 1])[0]
        rows.append(alloc)
        idx.append(t)
    out = pd.DataFrame(rows, columns=[f"alloc_{k}" for k in EXPERTS], index=pd.PeriodIndex(idx, freq="M"))
    return out


def evaluate(name: str, data: pd.DataFrame, alloc: pd.DataFrame) -> dict:
    realized = data.loc[alloc.index, EXPERTS].to_numpy()
    real_er = realized - realized.mean(1, keepdims=True)
    A = alloc.to_numpy()
    captured = (A * real_er).sum(1).mean()
    attract = A - A.mean(1, keepdims=True)
    ic, _ = spearmanr(attract.ravel(), real_er.ravel())
    pred_best = A.argmax(1)
    real_best = real_er.argmax(1)
    winners = data.loc[alloc.index, "winner"].to_numpy()
    labels_idx = np.array([EXPERTS.index(w) for w in winners])
    ll = log_loss(labels_idx, np.clip(A, 1e-6, 1), labels=list(range(len(EXPERTS))))
    disp = round(float(A.std(0).mean()), 4)        # allocation dispersion across months
    return {
        "model": name, "n_oos": int(len(alloc)),
        "excess_captured_pct": round(float(captured) * 100, 2),
        "rank_ic": round(float(ic), 3),
        "top1_acc": round(float((pred_best == real_best).mean()), 3),
        "log_loss": round(float(ll), 3),
        "alloc_dispersion": disp,
        "dynamic": disp > 0.02,                    # False => collapsed to a static mix
        "deployable_pure_python": name in ("ridge", "elasticnet", "mlogit", "ensemble_linear"),
    }


def main() -> int:
    data, feat_cols = load_data()
    data = data.copy()
    data["winner"] = data[EXPERTS].idxmax(axis=1)            # realized forward winner
    candidates = ["ridge", "elasticnet", "mlogit", "rf", "hgb", "ensemble_linear"]
    results = []
    for name in candidates:
        alloc = walk_forward(name, data, feat_cols)
        results.append(evaluate(name, data, alloc))
        r = results[-1]
        print(f"{name:16s} captured={r['excess_captured_pct']:+5.2f}%  IC={r['rank_ic']:+.3f}  "
              f"top1={r['top1_acc']:.3f}  logloss={r['log_loss']:.3f}  disp={r['alloc_dispersion']:.3f}  "
              f"{'[deployable]' if r['deployable_pure_python'] else '[tree]'}"
              f"{'' if r['dynamic'] else ' [STATIC-COLLAPSE]'}")
    # winner = best excess captured among DEPLOYABLE (pure-Python) AND genuinely dynamic
    # models (excludes the over-penalised ElasticNet that zeroes every coef and collapses
    # to the static unconditional ranking -- it "wins" capture only by becoming always-best).
    eligible = [r for r in results if r["deployable_pure_python"] and r["dynamic"]]
    winner = max(eligible, key=lambda r: r["excess_captured_pct"])
    best_overall = max(results, key=lambda r: r["excess_captured_pct"])
    out = {
        "config": {"horizon": H, "refit_months": REFIT, "min_train": MIN_TRAIN,
                   "n_features": len(feat_cols), "softmax_temp": SOFTMAX_TEMP},
        "candidates": results,
        "winner_deployable": winner["model"],
        "best_overall": best_overall["model"],
        "note": "Production model is restricted to pure-Python-inferable linear family; "
                "trees evaluated for comparison only.",
    }
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nwinner (deployable): {winner['model']}  |  best overall: {best_overall['model']}")
    print(f"wrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
