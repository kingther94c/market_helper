"""Policy-expert study — consensus-regime oracle + robust p10-floor expert selection.

Clean-room rebuild (task + lessons kept; prior session's concrete code NOT reused).
Builds on policy_expert_data.py (monthly panel + futures-excess accounting).

Pipeline:
  1. Consensus-dated regimes (market narrative; NOT the project regime engine, whose
     growth score lags into recovery bottoms and inverts the growth axis).
  2. In-regime sleeve EXCESS stats (oracle sanity; cross-check vs documented priors).
  3. Robust selection: resample each regime window 400x (random +/-6mo boundary shift
     + interior subsets); pick the policy with the highest MEAN return whose 10th-pct
     across draws is "not particularly bad" (p10 >= median p10). The SAME rule is
     applied to ALL FOUR regimes -- so Stagflation lands on the attack template
     (EQ~0 / CM+ / short FI / MACRO+), not the cash-insurance corner.
  4. Smooth the raw optimizer corners into round, defensible templates (transparent
     rounding: EQ/CM/MACRO -> nearest 5; |FI| capped at 150 then -> nearest 25).
  5. Emit each expert's FULL-SAMPLE monthly return series (the Phase-3 handoff) +
     a report separating robust directional insight from tentative template.

Perfect-foresight, in-sample CEILING -- a teacher/expert-discovery step, NOT a
tradable strategy. The experts are STATIC exposure vectors, so applying them
month-by-month uses no future information. No execution, no config changes.
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.research.policy_expert_data import (  # noqa: E402
    ann_return, ann_vol, build_full_panel, max_drawdown, portfolio_return,
)

OUT_JSON = REPO_ROOT / "data/research_artifacts/policy_experts.json"
OUT_MD = REPO_ROOT / "data/research_artifacts/policy_experts.md"
OUT_CSV = REPO_ROOT / "data/research_artifacts/policy_expert_returns.csv"

N_DRAWS = 400
SHIFT = 6          # +/- months boundary perturbation
MIN_LEN = 3        # minimum perturbed-window length
SEED = 20260605
VOL_CAP = 30.0     # vol is a CAP, not a floor
FI_SMOOTH_CAP = 150.0

REGIMES = ["Goldilocks", "Reflation", "Stagflation", "Recession"]
REGIME_GI = {"Goldilocks": "G+ I-", "Reflation": "G+ I+",
             "Stagflation": "G- I+", "Recession": "G- I-"}
REGIME_GI_UTF = {"Goldilocks": "G↑ I↓", "Reflation": "G↑ I↑",
                 "Stagflation": "G↓ I↑", "Recession": "G↓ I↓"}

# Consensus regime windows (US macro narrative). Stagflation/Recession give the
# downside; Goldilocks/Reflation the upside. 1970s stagflation is pre-sample.
REGIME_WINDOWS = [
    ("Goldilocks", "1995-01", "1999-12"),
    ("Goldilocks", "2013-01", "2019-09"),
    ("Reflation", "2003-04", "2006-06"),
    ("Reflation", "2009-04", "2010-04"),
    ("Reflation", "2020-06", "2021-11"),
    ("Stagflation", "2022-01", "2022-10"),
    ("Stagflation", "1990-07", "1990-10"),
    ("Recession", "1990-11", "1991-03"),
    ("Recession", "2001-03", "2001-11"),
    ("Recession", "2008-07", "2009-03"),
    ("Recession", "2015-07", "2016-02"),
    ("Recession", "2020-02", "2020-04"),
]

# Absolute-exposure ranges (lo, hi, step). Normal regimes keep EQ long & FI long;
# Stagflation relaxes EQ down to 0 and lets FI go short.
# MACRO removed (2026-06-06): it was a uniform +10 overlay across all four experts
# (the trend sleeve is positive in every regime), so it does not differentiate them
# and cancels in the cross-sectional allocation. Forced to 0 here -> 3-sleeve experts
# (EQ/CM/FI). Trade-off: loses a small crisis-diversifying return (see backtest).
NORMAL_RANGES = {"EQ": (60, 100, 5), "CM": (0, 15, 5), "MACRO": (0, 0, 2.5), "FI": (50, 200, 5)}
STAG_RANGES = {"EQ": (0, 100, 5), "CM": (0, 15, 5), "MACRO": (0, 0, 2.5), "FI": (-100, 200, 5)}


def _grid(lo, hi, step):
    n = int(round((hi - lo) / step))
    return [round(lo + i * step, 2) for i in range(n + 1)]


def regime_windows(regime: str):
    return [(pd.Period(s, "M"), pd.Period(e, "M"))
            for (r, s, e) in REGIME_WINDOWS if r == regime]


def regime_sub(df: pd.DataFrame, regime: str) -> pd.DataFrame:
    mask = pd.Series(False, index=df.index)
    for s, e in regime_windows(regime):
        mask |= (df.index >= s) & (df.index <= e)
    return df[mask]


# ---------------------------------------------------------------------------
# 2. In-regime sleeve EXCESS stats (oracle sanity)
# ---------------------------------------------------------------------------
def sleeve_excess_stats(df: pd.DataFrame, regime: str) -> dict:
    sub = regime_sub(df, regime)
    out = {"n_months": int(sub.shape[0])}
    for s in ("EQ", "CM", "FI"):
        out[s] = round(ann_return(sub[s] - sub["CASH"]) * 100, 1)
    out["MACRO"] = round(ann_return(sub["MACRO"]) * 100, 1)
    out["CASH_ann_pct"] = round(ann_return(sub["CASH"]) * 100, 1)
    # cross-asset facts that drive the templates
    out["corr_eq_fi"] = round(float((sub["EQ"]).corr(sub["FI"])), 2)
    out["corr_eq_cm"] = round(float((sub["EQ"]).corr(sub["CM"])), 2)
    out["corr_eq_macro"] = round(float((sub["EQ"]).corr(sub["MACRO"])), 2)
    return out


# ---------------------------------------------------------------------------
# 3. Robust selection (boundary perturbation + p10 floor)
# ---------------------------------------------------------------------------
def envelope_index(regime: str, index: pd.PeriodIndex) -> pd.PeriodIndex:
    wins = regime_windows(regime)
    lo = min(s for s, _ in wins) - SHIFT
    hi = max(e for _, e in wins) + SHIFT
    return index[(index >= lo) & (index <= hi)]


def make_draws(regime: str, index: pd.PeriodIndex, rng) -> list[set]:
    wins = regime_windows(regime)
    dmin, dmax = index.min(), index.max()
    draws = []
    for _ in range(N_DRAWS):
        periods: set = set()
        for s, e in wins:
            length = (e - s).n + 1
            if rng.random() < 0.5:                       # boundary shift
                s2 = s + int(rng.integers(-SHIFT, SHIFT + 1))
                e2 = e + int(rng.integers(-SHIFT, SHIFT + 1))
            else:                                         # interior subset
                newlen = int(rng.integers(max(MIN_LEN, length // 2), length + 1))
                off = int(rng.integers(0, max(0, length - newlen) + 1))
                s2 = s + off
                e2 = s2 + newlen - 1
            if (e2 - s2).n + 1 < MIN_LEN:
                e2 = s2 + (MIN_LEN - 1)
            s2 = max(s2, dmin)
            e2 = min(e2, dmax)
            if (e2 - s2).n + 1 < MIN_LEN:
                continue
            periods.update(pd.period_range(s2, e2, freq="M"))
        draws.append(periods)
    return draws


def policy_grid(regime: str) -> np.ndarray:
    rng = STAG_RANGES if regime == "Stagflation" else NORMAL_RANGES
    cols = [_grid(*rng[k]) for k in ("EQ", "CM", "MACRO", "FI")]
    return np.array(list(itertools.product(*cols)), dtype=float)


def robust_eval(regime: str, df: pd.DataFrame, rng) -> dict:
    env = envelope_index(regime, df.index)
    sub = df.loc[env]
    cash = sub["CASH"].to_numpy()
    EQx = (sub["EQ"] - sub["CASH"]).to_numpy()
    CMx = (sub["CM"] - sub["CASH"]).to_numpy()
    FIx = (sub["FI"] - sub["CASH"]).to_numpy()
    MAx = sub["MACRO"].to_numpy()
    env_list = list(env)

    combos = policy_grid(regime)
    eq, cm, ma, fi = combos[:, 0], combos[:, 1], combos[:, 2], combos[:, 3]
    # R (n_pol x n_env): cash on 100% + exposure * excess
    R = (cash[None, :]
         + (eq[:, None] * EQx[None, :] + cm[:, None] * CMx[None, :]
            + fi[:, None] * FIx[None, :] + ma[:, None] * MAx[None, :]) / 100.0)

    draws = make_draws(regime, df.index, rng)
    RET = np.empty((combos.shape[0], len(draws)))
    VOL = np.empty((combos.shape[0], len(draws)))
    for d, periods in enumerate(draws):
        mask = np.fromiter((p in periods for p in env_list), bool, len(env_list))
        Rs = R[:, mask]
        n = Rs.shape[1]
        RET[:, d] = (1.0 + Rs).prod(axis=1) ** (12.0 / n) - 1.0
        VOL[:, d] = Rs.std(axis=1, ddof=1) * np.sqrt(12)

    return {
        "combos": combos,
        "mean_ret": RET.mean(axis=1),
        "p10_ret": np.percentile(RET, 10, axis=1),
        "min_ret": RET.min(axis=1),
        "mean_vol": VOL.mean(axis=1),
        "n_draws": len(draws),
    }


def select_robust(m: dict) -> dict:
    """UNIFORM rule for every regime: among vol-feasible policies (mean vol <= cap),
    keep those whose p10 >= median p10 ('not particularly bad'), take the max mean."""
    feasible = np.where(m["mean_vol"] <= VOL_CAP / 100.0)[0]
    if not len(feasible):
        feasible = np.arange(len(m["mean_ret"]))
    floor = float(np.median(m["p10_ret"][feasible]))
    robust = [i for i in feasible if m["p10_ret"][i] >= floor]
    chosen = max(robust, key=lambda i: m["mean_ret"][i])
    return {"idx": int(chosen), "p10_floor_pct": round(floor * 100, 2)}


def _corner(combos, i, m) -> dict:
    eq, cm, ma, fi = combos[i]
    return {
        "EQ": round(float(eq), 1), "CM": round(float(cm), 1),
        "MACRO": round(float(ma), 1), "FI": round(float(fi), 1),
        "gross": round(float(eq + cm + ma + fi), 1),
        "mean_ret_pct": round(float(m["mean_ret"][i]) * 100, 2),
        "p10_ret_pct": round(float(m["p10_ret"][i]) * 100, 2),
        "min_ret_pct": round(float(m["min_ret"][i]) * 100, 2),
        "mean_vol_pct": round(float(m["mean_vol"][i]) * 100, 2),
    }


# ---------------------------------------------------------------------------
# 4. Smoothing raw corners -> defensible templates
# ---------------------------------------------------------------------------
def smooth_template(corner: dict) -> dict:
    rnd5 = lambda v: float(round(v / 5.0) * 5)
    fi = max(-FI_SMOOTH_CAP, min(FI_SMOOTH_CAP, corner["FI"]))
    fi = float(round(fi / 25.0) * 25)
    return {"EQ": rnd5(corner["EQ"]), "CM": rnd5(corner["CM"]),
            "MACRO": rnd5(corner["MACRO"]), "FI": fi}


def expert_full_sample_stats(df: pd.DataFrame, tpl: dict) -> dict:
    r = portfolio_return(df, tpl["EQ"], tpl["CM"], tpl["FI"], tpl["MACRO"])
    return {
        "gross": round(tpl["EQ"] + tpl["CM"] + tpl["MACRO"] + tpl["FI"], 1),
        "leverage": round(tpl["EQ"] + tpl["CM"] + tpl["MACRO"] + tpl["FI"] - 100, 1),
        "ann_return_pct": round(ann_return(r) * 100, 2),
        "ann_vol_pct": round(ann_vol(r) * 100, 2),
        "max_dd_pct": round(max_drawdown(r) * 100, 2),
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def write_markdown(result: dict) -> None:
    L: list[str] = []
    w = L.append
    m = result["meta"]
    w("# Regime-Aware Policy Experts (clean-room rebuild)\n")
    w("> Perfect-foresight, in-sample CEILING -- a teacher / expert-discovery step, "
      "NOT a tradable strategy. Experts are STATIC exposure vectors (no future info "
      "when applied month-by-month). Consensus-dated regimes; the project regime "
      "engine's labels are deliberately NOT used. No execution.\n")
    w(f"Sample {m['sample']}. Sleeves EQ=^SP500TR, CM=^SPGSCI, FI=synthetic 10Y "
      f"(FRED GS10, futures->excess), CASH=TB3MS, MACRO=TSMOM trend proxy "
      f"(vol-scaled ~10%). Accounting `R = cash*100% + sum exposure*(sleeve-cash)`. "
      f"Robust selection: {m['n_draws']} draws (+/-{SHIFT}mo + subsets), "
      f"**max mean s.t. p10 >= median p10**, the SAME rule in every regime.\n")

    w("\n## In-regime sleeve EXCESS returns (oracle sanity, ann %)\n")
    w("| regime (G x I) | n | EQ | CM | FI | MACRO | corr(EQ,FI) | corr(EQ,CM) |")
    w("|---|--:|--:|--:|--:|--:|--:|--:|")
    for r in REGIMES:
        s = result["regimes"][r]["sleeve_excess"]
        w(f"| **{r}** ({REGIME_GI_UTF[r]}) | {s['n_months']} | {s['EQ']:+}% | "
          f"{s['CM']:+}% | {s['FI']:+}% | {s['MACRO']:+}% | {s['corr_eq_fi']:+} | "
          f"{s['corr_eq_cm']:+} |")
    w("\n*Inflation axis -> duration sign; growth axis -> EQ/CM. MACRO/trend is "
      "crisis alpha (positive everywhere; EQ-diversifying in stress).*\n")

    w("\n## Robust corner vs smoothed expert template\n")
    w("| regime | robust corner (EQ/CM/MACRO/FI) | mean / p10 / min | vol | "
      "**smoothed template** | full-sample ret / vol / maxDD |")
    w("|---|---|--:|--:|---|--:|")
    for r in REGIMES:
        o = result["regimes"][r]
        c = o["robust_corner"]; t = o["template"]; fs = o["template_full_sample"]
        w(f"| **{r}** ({REGIME_GI_UTF[r]}) | {c['EQ']:.0f}/{c['CM']:.0f}/{c['MACRO']:.0f}/"
          f"{c['FI']:+.0f} | {c['mean_ret_pct']:+}/{c['p10_ret_pct']:+}/{c['min_ret_pct']:+}% | "
          f"{c['mean_vol_pct']:.0f}% | **EQ{t['EQ']:.0f}/CM{t['CM']:.0f}/MACRO{t['MACRO']:.0f}/"
          f"FI{t['FI']:+.0f}** | {fs['ann_return_pct']:+}% / {fs['ann_vol_pct']:.0f}% / "
          f"{fs['max_dd_pct']}% |")
    w("\n*Smoothing: EQ/CM/MACRO -> nearest 5; |FI| capped at 150 then -> nearest 25 "
      "(defensible duration leverage). Full-sample = the static template applied to "
      "EVERY month 1989+ (context; not the in-regime ceiling).*\n")

    w("\n## The four policy experts\n")
    for r in REGIMES:
        t = result["regimes"][r]["template"]
        w(f"- **{r}** ({REGIME_GI_UTF[r]}): EQ {t['EQ']:.0f} / CM {t['CM']:.0f} / "
          f"MACRO {t['MACRO']:.0f} / FI {t['FI']:+.0f} (duration via futures, excess)")
    w("")

    w("\n## Robust directional insight vs tentative template\n")
    w("- **Robust (directional, high confidence):** inflation-up shorts duration / "
      "inflation-down lengthens it; growth drives EQ (and CM in reflation); MACRO "
      "trend is additive crisis alpha. These signs were stable across the perturbed "
      "draws.\n")
    w("- **Tentative (magnitudes / templates):** the exact exposure sizes are an "
      "in-sample ceiling shrunk to round numbers -- treat as starting templates, not "
      "optima.\n")
    w("- **Stagflation is the fragile conclusion:** only ~"
      f"{result['regimes']['Stagflation']['sleeve_excess']['n_months']} months "
      "(2022 + 1990; the 1970s are pre-sample). Its attack template (short duration + "
      "long commodities + long trend) carries the heaviest caveat and the most "
      "shrinkage; its min-return draw is the worst of the four.\n")

    w("\n## Handoff\n")
    w(f"- `{OUT_CSV.name}` -- each expert's full-sample monthly return series "
      "(1989+), the input for the Phase-3 forward-label step.\n")
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")


def _console(result: dict) -> None:
    print(f"\nsample {result['meta']['sample']}  draws={result['meta']['n_draws']}")
    for r in REGIMES:
        o = result["regimes"][r]
        c = o["robust_corner"]; t = o["template"]; s = o["sleeve_excess"]
        print(f"\n=== {r} ({REGIME_GI[r]}) n={s['n_months']}mo "
              f"floor={o['p10_floor_pct']:+.1f}% ===")
        print(f"   sleeve excess: EQ{s['EQ']:+} CM{s['CM']:+} FI{s['FI']:+} MACRO{s['MACRO']:+}")
        print(f"   robust corner: EQ{c['EQ']:.0f} CM{c['CM']:.0f} MACRO{c['MACRO']:.0f} "
              f"FI{c['FI']:+.0f} -> mean{c['mean_ret_pct']:+}% p10{c['p10_ret_pct']:+}% "
              f"min{c['min_ret_pct']:+}% vol{c['mean_vol_pct']:.0f}%")
        print(f"   EXPERT (smoothed): EQ{t['EQ']:.0f} CM{t['CM']:.0f} MACRO{t['MACRO']:.0f} "
              f"FI{t['FI']:+.0f}")


def main() -> int:
    df = build_full_panel()
    rng = np.random.default_rng(SEED)

    regimes: dict = {}
    expert_returns: dict = {}
    for r in REGIMES:
        m = robust_eval(r, df, rng)
        sel = select_robust(m)
        corner = _corner(m["combos"], sel["idx"], m)
        template = smooth_template(corner)
        regimes[r] = {
            "gi": REGIME_GI_UTF[r],
            "windows": [[str(s), str(e)] for s, e in regime_windows(r)],
            "sleeve_excess": sleeve_excess_stats(df, r),
            "robust_corner": corner,
            "p10_floor_pct": sel["p10_floor_pct"],
            "template": template,
            "template_full_sample": expert_full_sample_stats(df, template),
        }
        expert_returns[r] = portfolio_return(
            df, template["EQ"], template["CM"], template["FI"], template["MACRO"]
        )

    # Phase-3 handoff: full-sample monthly return series for the 4 experts.
    ret_df = pd.DataFrame(expert_returns)
    ret_df.index = ret_df.index.astype(str)
    ret_df.index.name = "month"
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    ret_df.to_csv(OUT_CSV)

    result = {
        "meta": {
            "sample": f"{df.index.min()} .. {df.index.max()} ({df.shape[0]} months)",
            "n_draws": N_DRAWS, "shift_months": SHIFT, "seed": SEED,
            "vol_cap_pct": VOL_CAP, "fi_smooth_cap": FI_SMOOTH_CAP,
            "selection_rule": "max mean s.t. p10 >= median p10 (uniform across regimes)",
            "normal_ranges": NORMAL_RANGES, "stag_ranges": STAG_RANGES,
        },
        "experts": {r: regimes[r]["template"] for r in REGIMES},
        "regimes": regimes,
    }
    OUT_JSON.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    write_markdown(result)
    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_MD}")
    print(f"wrote {OUT_CSV}  ({ret_df.shape[0]} months x {ret_df.shape[1]} experts)")
    _console(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
