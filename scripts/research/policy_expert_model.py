"""Phase 4b -- ex-ante policy-expert predictor (walk-forward) + production artifact.

The predictor forecasts each expert's 6M-forward TOTAL return from ex-ante features,
then derives per-expert ATTRACTIVENESS = demeaned prediction (cross-sectional "which
expert outperforms"). Predicting total returns (not the zero-sum demeaned excess)
keeps the predictable common component and avoids the linearly-dependent target that
made a naive low-alpha Ridge overfit to noise.

Walk-forward discipline (no look-ahead):
  - At month t, train only on samples whose forward window is realized by t:
    s <= t - H (H=6 embargo around the overlapping targets). Expanding window,
    monthly refit, >= MIN_TRAIN rows.
  - Standardize on TRAIN only; **RidgeCV** picks alpha by efficient LOO each refit
    (adaptive shrinkage -> defaults toward the unconditional best when features are
    uninformative; no OOS peeking).

Honest skill is judged vs trivial baselines (always-best-static-expert, equal-weight)
and ultimately by the Phase-6 backtest -- not by top-1 accuracy alone.

Production artifact (numpy-only to apply): {feature schema, standardize mean/std,
per-expert linear coef+intercept, expert exposure vectors, softmax temp}. The package
predictor needs only numpy: standardize -> linear -> demean -> softmax -> blend.

Outputs (data/research_artifacts/): policy_expert_predictions.csv,
policy_expert_model.json, policy_expert_model_artifact.json. No execution.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

FEAT_CSV = REPO_ROOT / "data/research_artifacts/policy_expert_features.csv"
LAB_CSV = REPO_ROOT / "data/research_artifacts/policy_expert_labels.csv"
SCHEMA_JSON = REPO_ROOT / "data/research_artifacts/policy_expert_feature_schema.json"
EXPERTS_JSON = REPO_ROOT / "data/research_artifacts/policy_experts.json"
OUT_PRED = REPO_ROOT / "data/research_artifacts/policy_expert_predictions.csv"
OUT_JSON = REPO_ROOT / "data/research_artifacts/policy_expert_model.json"
OUT_ARTIFACT = REPO_ROOT / "data/research_artifacts/policy_expert_model_artifact.json"

EXPERTS = ["Goldilocks", "Reflation", "Stagflation", "Recession"]
H = 6
MIN_TRAIN = 120
ALPHAS = [10.0, 30.0, 100.0, 300.0, 1000.0, 3000.0]
SOFTMAX_TEMP = 0.03
VAL_WINDOW = 36       # months held out (embargoed) to select alpha within train


def _select_alpha(Xs: np.ndarray, Y: np.ndarray) -> float:
    """Pick Ridge alpha by an EMBARGOED time-series split inside the training window
    (no peeking): fit on the early block, validate on the last VAL_WINDOW months with
    an H-month embargo between them. Heavy shrinkage wins because the H-month targets
    are autocorrelated (a low-alpha fit overfits noise that flips OOS)."""
    n = len(Xs)
    val_start = n - VAL_WINDOW
    fit_end = max(1, val_start - H)
    if fit_end < 24 or (n - val_start) < 6:
        return 300.0
    Xf, Yf, Xv, Yv = Xs[:fit_end], Y[:fit_end], Xs[val_start:], Y[val_start:]
    best_a, best_mse = ALPHAS[-1], np.inf
    for a in ALPHAS:
        m = Ridge(alpha=a).fit(Xf, Yf)
        mse = float(((m.predict(Xv) - Yv) ** 2).mean())
        if mse < best_mse:
            best_mse, best_a = mse, a
    return best_a


def load_data():
    feat = pd.read_csv(FEAT_CSV).rename(columns={"Unnamed: 0": "month"})
    feat["month"] = pd.PeriodIndex(feat["month"], freq="M")
    feat = feat.set_index("month")
    lab = pd.read_csv(LAB_CSV)
    lab["month"] = pd.PeriodIndex(lab["month"], freq="M")
    lab = lab.set_index("month")
    fwd = lab[[f"fwd_{H}m_{k}" for k in EXPERTS]].copy()
    fwd.columns = EXPERTS
    feat_cols = list(feat.columns)
    data = feat.join(fwd, rsuffix="_fwd").dropna(subset=feat_cols + EXPERTS)
    return data, feat_cols


def _attractiveness(pred_fwd: np.ndarray) -> np.ndarray:
    return pred_fwd - pred_fwd.mean(axis=1, keepdims=True)


def walk_forward(data: pd.DataFrame, feat_cols: list[str]) -> pd.DataFrame:
    months = list(data.index)
    X_all = data[feat_cols].to_numpy(float)
    Y_all = data[EXPERTS].to_numpy(float)
    rows = []
    for i, t in enumerate(months):
        train_mask = np.array([(months[j] + H) <= t for j in range(len(months))])
        train_mask[i:] = False
        if train_mask.sum() < MIN_TRAIN:
            continue
        Xtr, Ytr = X_all[train_mask], Y_all[train_mask]
        mu, sd = Xtr.mean(0), Xtr.std(0)
        sd[sd == 0] = 1.0
        Xtr_s = (Xtr - mu) / sd
        alpha = _select_alpha(Xtr_s, Ytr)
        model = Ridge(alpha=alpha).fit(Xtr_s, Ytr)
        fwd_hat = model.predict(((X_all[i] - mu) / sd).reshape(1, -1))[0]
        rows.append((t, alpha, *fwd_hat))
    pred = pd.DataFrame(
        rows, columns=["month", "alpha"] + [f"fwd_hat_{k}" for k in EXPERTS]
    ).set_index("month")
    attract = _attractiveness(pred[[f"fwd_hat_{k}" for k in EXPERTS]].to_numpy())
    for j, k in enumerate(EXPERTS):
        pred[f"attract_{k}"] = attract[:, j]
    z = attract / SOFTMAX_TEMP
    z = z - z.max(axis=1, keepdims=True)
    ez = np.exp(z)
    sm = ez / ez.sum(axis=1, keepdims=True)
    for j, k in enumerate(EXPERTS):
        pred[f"alloc_{k}"] = sm[:, j]
    return pred


def evaluate(data: pd.DataFrame, pred: pd.DataFrame) -> dict:
    realized = data.loc[pred.index, EXPERTS].to_numpy()
    real_er = realized - realized.mean(axis=1, keepdims=True)   # cross-sectional excess
    attract = pred[[f"attract_{k}" for k in EXPERTS]].to_numpy()
    pred_best = attract.argmax(1)
    real_best = real_er.argmax(1)
    n = len(pred)
    ar = np.arange(n)
    captured = real_er[ar, pred_best]                            # following predicted best
    best_possible = real_er.max(1)
    # trivial baselines
    base_rates = [int((real_best == j).sum()) for j in range(len(EXPERTS))]
    always_static = real_er[:, int(np.argmax(base_rates))].mean()  # always the OOS-modal winner
    gold_capture = real_er[:, EXPERTS.index("Goldilocks")].mean()
    ic, _ = spearmanr(attract.ravel(), real_er.ravel())
    soft = pred[[f"alloc_{k}" for k in EXPERTS]].to_numpy()
    soft_capture = (soft * real_er).sum(1).mean()                # soft-allocation captured excess
    return {
        "n_oos_months": int(n),
        "oos_span": [str(pred.index.min()), str(pred.index.max())],
        "pooled_rank_ic": round(float(ic), 3),
        "top1_accuracy": round(float((pred_best == real_best).mean()), 3),
        "predicted_best_beats_equalweight_rate": round(float((captured > 0).mean()), 3),
        "mean_excess_captured_pct": round(float(captured.mean()) * 100, 2),
        "soft_alloc_captured_pct": round(float(soft_capture) * 100, 2),
        "mean_excess_best_possible_pct": round(float(best_possible.mean()) * 100, 2),
        "baseline_always_goldilocks_pct": round(float(gold_capture) * 100, 2),
        "winner_base_rates": {EXPERTS[j]: base_rates[j] for j in range(len(EXPERTS))},
    }


def build_artifact(data: pd.DataFrame, feat_cols: list[str], schema: dict) -> dict:
    X = data[feat_cols].to_numpy(float)
    Y = data[EXPERTS].to_numpy(float)
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    Xs = (X - mu) / sd
    alpha = _select_alpha(Xs, Y)
    model = Ridge(alpha=alpha).fit(Xs, Y)
    experts_def = json.loads(EXPERTS_JSON.read_text(encoding="utf-8"))["experts"]
    return {
        "model": "ridge_multi_output_forward_return",
        "horizon_months": H, "softmax_temp": SOFTMAX_TEMP,
        "alpha_selected": float(alpha),
        "experts": EXPERTS,
        "expert_exposures": {k: experts_def[k] for k in EXPERTS},
        "feature_names": feat_cols,
        "feature_schema": {c: schema.get(c, {}) for c in feat_cols},
        "standardize_mean": [round(float(x), 6) for x in mu],
        "standardize_std": [round(float(x), 6) for x in sd],
        "intercept": [round(float(x), 8) for x in np.atleast_1d(model.intercept_)],
        "coef": [[round(float(c), 8) for c in row] for row in np.atleast_2d(model.coef_)],
        "trained_rows": int(len(data)),
        "trained_span": [str(data.index.min()), str(data.index.max())],
    }


def main() -> int:
    data, feat_cols = load_data()
    schema = json.loads(SCHEMA_JSON.read_text(encoding="utf-8"))
    pred = walk_forward(data, feat_cols)
    metrics = evaluate(data, pred)
    artifact = build_artifact(data, feat_cols, schema)

    OUT_PRED.parent.mkdir(parents=True, exist_ok=True)
    p = pred.copy()
    p.index = p.index.astype(str)
    p.index.name = "month"
    p.to_csv(OUT_PRED)
    result = {
        "config": {"horizon": H, "min_train": MIN_TRAIN, "alphas": ALPHAS,
                   "softmax_temp": SOFTMAX_TEMP, "n_features": len(feat_cols),
                   "complete_case_rows": int(len(data)),
                   "complete_case_span": [str(data.index.min()), str(data.index.max())]},
        "oos_metrics": metrics,
        "final_alpha": artifact["alpha_selected"],
    }
    OUT_JSON.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    OUT_ARTIFACT.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(f"wrote {OUT_PRED} ({pred.shape[0]} OOS months)\nwrote {OUT_JSON}\nwrote {OUT_ARTIFACT}")
    print(f"\nOOS skill (6M, predict which expert outperforms; alpha*={artifact['alpha_selected']:.0f}):")
    for kk in ("n_oos_months", "oos_span", "pooled_rank_ic", "top1_accuracy",
               "predicted_best_beats_equalweight_rate", "mean_excess_captured_pct",
               "soft_alloc_captured_pct", "mean_excess_best_possible_pct",
               "baseline_always_goldilocks_pct", "winner_base_rates"):
        print(f"  {kk}: {metrics[kk]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
