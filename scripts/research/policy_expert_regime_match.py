"""Validation: does the regime IMPLIED by relative expert performance match the
hand-dated market-consensus regime periods?

For each month we ask "which of the 4 policy experts performed best" and compare it to
the consensus regime label (for months inside a consensus window). Two winner notions:

  - relative-return winner : argmax of the 4 experts' SAME-month total return. This is
    the literal "best performer", but it is biased toward the high-unconditional-return
    experts (Goldilocks/Reflation) -- in a secular bull market they win most months
    regardless of regime.
  - regime-signal winner    : argmax of each expert's return STANDARDIZED by its OWN
    full-sample mean/std (z-score). This removes the unconditional-level bias and asks
    "which expert is unusually good vs its own norm" -- a cleaner regime indicator.

We report: full-sample winner share, a consensus x winner confusion matrix + per-regime
match rate (both winner notions), and the dominant winner per consensus episode.

Reads data/research_artifacts/policy_expert_returns.csv. No execution. ASCII console.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.research.policy_expert_study import REGIMES, REGIME_WINDOWS, regime_windows  # noqa: E402

RET_CSV = REPO_ROOT / "data/research_artifacts/policy_expert_returns.csv"
OUT_JSON = REPO_ROOT / "data/research_artifacts/policy_expert_regime_match.json"
EXPERTS = ["Goldilocks", "Reflation", "Stagflation", "Recession"]


def load_returns() -> pd.DataFrame:
    df = pd.read_csv(RET_CSV)
    df["month"] = pd.PeriodIndex(df["month"], freq="M")
    return df.set_index("month")[EXPERTS].astype(float)


def consensus_label(index: pd.PeriodIndex) -> pd.Series:
    lab = pd.Series(index=index, dtype=object)
    for r in REGIMES:
        for s, e in regime_windows(r):
            lab[(index >= s) & (index <= e)] = r
    return lab


def confusion(consensus: pd.Series, winner: pd.Series) -> tuple[pd.DataFrame, dict]:
    sub = pd.DataFrame({"consensus": consensus, "winner": winner}).dropna()
    mat = pd.crosstab(sub["consensus"], sub["winner"]).reindex(index=REGIMES, columns=EXPERTS).fillna(0).astype(int)
    rates = {}
    for r in REGIMES:
        n = int(mat.loc[r].sum())
        rates[r] = {"n_months": n,
                    "match_pct": round(100 * mat.loc[r, r] / n, 0) if n else None,
                    "top_winner": mat.loc[r].idxmax() if n else None}
    overall = round(100 * sum(mat.loc[r, r] for r in REGIMES) / mat.values.sum(), 0)
    return mat, {"per_regime": rates, "overall_match_pct": overall, "n_window_months": int(mat.values.sum())}


def main() -> int:
    ret = load_returns()
    consensus = consensus_label(ret.index)

    rel_winner = ret.idxmax(axis=1)                                  # relative-return winner
    z = (ret - ret.mean()) / ret.std()                               # per-expert standardized
    sig_winner = z.idxmax(axis=1)                                    # regime-signal winner

    rel_mat, rel_stats = confusion(consensus, rel_winner)
    sig_mat, sig_stats = confusion(consensus, sig_winner)

    # per consensus episode: (a) window-MEAN winner [best avg return -- circular: the
    # experts were SELECTED to maximise this] and (b) the month-by-month dominant
    # relative-return winner [the real test].
    episodes = []
    for r, s, e in REGIME_WINDOWS:
        lo, hi = pd.Period(s, "M"), pd.Period(e, "M")
        mask = (ret.index >= lo) & (ret.index <= hi)
        win = rel_winner[mask]
        if not len(win):
            continue
        vc = win.value_counts()
        mean_winner = ret[mask].mean().idxmax()
        episodes.append({"regime": r, "window": f"{s}..{e}", "n": int(len(win)),
                         "window_mean_winner": mean_winner,
                         "mean_matches": bool(mean_winner == r),
                         "monthly_dominant": vc.index[0],
                         "monthly_dominant_share_pct": round(100 * vc.iloc[0] / len(win), 0),
                         "monthly_matches": bool(vc.index[0] == r)})

    full_share = {k: round(100 * float((rel_winner == k).mean()), 0) for k in EXPERTS}
    out = {
        "full_sample_relative_winner_share_pct": full_share,
        "relative_return_winner": rel_stats,
        "regime_signal_winner": sig_stats,
        "episodes": episodes,
    }
    OUT_JSON.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")

    def show(title, mat, stats):
        print(f"\n=== {title} (consensus rows x winner cols, in-window months) ===")
        print(mat.to_string())
        print("  per-regime match%: " + "  ".join(
            f"{r[:4]}={stats['per_regime'][r]['match_pct']}%(top {stats['per_regime'][r]['top_winner'][:4]})"
            for r in REGIMES))
        print(f"  overall match = {stats['overall_match_pct']}%  (n={stats['n_window_months']} window months)")

    print(f"full-sample relative-winner share: " + "  ".join(f"{k[:4]} {v:.0f}%" for k, v in full_share.items()))
    show("RELATIVE-RETURN winner (the honest read)", rel_mat, rel_stats)
    print("\nPer consensus episode  [window-MEAN winner | month-by-month dominant]:")
    for ep in episodes:
        mflag = "OK" if ep["mean_matches"] else "X "
        dflag = "OK" if ep["monthly_matches"] else "X "
        print(f"  {ep['regime']:11s} {ep['window']}  n={ep['n']:2d}  "
              f"| mean[{mflag}] {ep['window_mean_winner']:11s} "
              f"| monthly[{dflag}] {ep['monthly_dominant']} ({ep['monthly_dominant_share_pct']:.0f}%)")
    mean_match = round(100 * np.mean([ep["mean_matches"] for ep in episodes]), 0)
    monthly_match = round(100 * np.mean([ep["monthly_matches"] for ep in episodes]), 0)
    print(f"\nepisode-level: window-MEAN matches consensus {mean_match:.0f}% (circular -- "
          f"experts maximise this); month-by-month dominant matches {monthly_match:.0f}%.")
    print("(z-scored 'regime-signal' winner is a poor detector -- it amplifies the "
          "high-variance Stagflation expert; see JSON.)")
    print(f"\nwrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
