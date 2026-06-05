"""Phase 3 -- forward policy-expert performance labels.

Reads the committed expert return series (policy_expert_returns.csv) and builds the
supervised TARGETS for the Phase-4 predictor. Labels MAY use the future (they are the
target); the experts themselves are static and use no future info.

For each month t and horizon h in {3, 6 (primary), 12} months, the forward return of
expert k is the compounded return over t+1..t+h (predict at end of t, hold next h mo):

  fwd_h[k][t] = prod_{j=1..h}(1 + r_k[t+j]) - 1

Label families (all computed at every horizon; 6M is primary):
  (a) winner          : argmax_k fwd_h[k]            (hard class)
  (b) winner_margin   : winner if (top - 2nd) >= MARGIN else "Neutral"
  (c) softmax_k       : softmax(fwd_h / TEMP) over k (soft-label vector)
  (d) er_k            : fwd_h[k] - mean_k fwd_h      (cross-sectional excess; the
                        PREFERRED regression target -- "which expert outperforms")

Outputs (data/research_artifacts/):
  policy_expert_labels.csv   -- month x (fwd_/er_/softmax_ per expert + winner cols)
  policy_expert_labels.json  -- horizon meta + label distributions
No execution, no config changes. ASCII-only console.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

IN_CSV = REPO_ROOT / "data/research_artifacts/policy_expert_returns.csv"
OUT_CSV = REPO_ROOT / "data/research_artifacts/policy_expert_labels.csv"
OUT_JSON = REPO_ROOT / "data/research_artifacts/policy_expert_labels.json"

EXPERTS = ["Goldilocks", "Reflation", "Stagflation", "Recession"]
HORIZONS = [3, 6, 12]
PRIMARY_H = 6
MARGIN = 0.025      # winner-with-margin neutral band (top - 2nd), per horizon
TEMP = 0.05         # softmax temperature on forward returns


def load_expert_returns() -> pd.DataFrame:
    df = pd.read_csv(IN_CSV)
    df["month"] = pd.PeriodIndex(df["month"], freq="M")
    return df.set_index("month")[EXPERTS].astype(float)


def forward_return(r: pd.DataFrame, h: int) -> pd.DataFrame:
    """Compounded forward return over the next h months (t+1..t+h)."""
    logsum = np.log1p(r).rolling(h).sum().shift(-h)
    return np.expm1(logsum)


def build_labels() -> tuple[pd.DataFrame, dict]:
    r = load_expert_returns()
    out = pd.DataFrame(index=r.index)
    meta: dict = {"experts": EXPERTS, "horizons": HORIZONS, "primary_h": PRIMARY_H,
                  "margin": MARGIN, "softmax_temp": TEMP, "distributions": {}}

    for h in HORIZONS:
        fwd = forward_return(r, h)
        for k in EXPERTS:
            out[f"fwd_{h}m_{k}"] = fwd[k]
        valid = fwd.dropna()                       # drop the last h all-NaN months
        fv = valid.to_numpy()
        # (a) hard winner
        winner = pd.Series(valid.columns.to_numpy()[fv.argmax(axis=1)], index=valid.index)
        out[f"winner_{h}m"] = winner.reindex(r.index)
        # (b) winner with margin
        sv = np.sort(fv, axis=1)                    # ascending
        gap = sv[:, -1] - sv[:, -2]
        margin_winner = winner.where(gap >= MARGIN, other="Neutral")
        out[f"winner_margin_{h}m"] = margin_winner.reindex(r.index)
        # (c) softmax soft labels
        z = fv / TEMP
        z = z - z.max(axis=1, keepdims=True)
        ez = np.exp(z)
        sm = ez / ez.sum(axis=1, keepdims=True)
        for j, k in enumerate(EXPERTS):
            out[f"softmax_{h}m_{k}"] = pd.Series(sm[:, j], index=valid.index).reindex(r.index)
        # (d) cross-sectional excess (preferred regression target)
        er = valid.sub(valid.mean(axis=1), axis=0)
        for k in EXPERTS:
            out[f"er_{h}m_{k}"] = er[k].reindex(r.index)

        dist = winner.value_counts().to_dict()
        meta["distributions"][f"{h}m"] = {
            "n_labeled": int(valid.shape[0]),
            "winner_counts": {k: int(dist.get(k, 0)) for k in EXPERTS},
            "winner_margin_neutral": int((margin_winner == "Neutral").sum()),
        }
    return out, meta


def main() -> int:
    out, meta = build_labels()
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out_to_write = out.copy()
    out_to_write.index = out_to_write.index.astype(str)
    out_to_write.to_csv(OUT_CSV)
    OUT_JSON.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    print(f"wrote {OUT_CSV}  ({out.shape[0]} months x {out.shape[1]} cols)")
    print(f"wrote {OUT_JSON}")
    print(f"\nlabel distributions (winner argmax):")
    for h in HORIZONS:
        d = meta["distributions"][f"{h}m"]
        star = " (primary)" if h == PRIMARY_H else ""
        print(f"  {h}m{star}: n={d['n_labeled']}  "
              + "  ".join(f"{k}={d['winner_counts'][k]}" for k in EXPERTS)
              + f"  neutral={d['winner_margin_neutral']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
