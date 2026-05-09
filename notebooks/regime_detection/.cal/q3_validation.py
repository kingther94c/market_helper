"""Q3 validation outputs (post-tanh-on-market + lower thresholds + label hysteresis)."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, "notebooks/regime_detection/.cal")
from cal_helpers import ANCHORS, load_results

from market_helper.data_sources.fred.macro_panel import (
    load_concept_specs, load_panel, load_series_specs,
)
from market_helper.regimes.methods.macro_regime import (
    compute_macro_axis_scores, load_macro_regime_config,
)

ART = Path("notebooks/regime_detection/.cal")
results = load_results("data/artifacts/regime_detection/regime_snapshots.json")
results = results[results["date"] >= "1995-01-01"].copy()

panel = load_panel("data/interim/fred/macro_panel.feather")
specs = load_series_specs("configs/regime_detection/fred_series.yml")
concepts = load_concept_specs("configs/regime_detection/fred_series.yml")
cfg = load_macro_regime_config("configs/regime_detection/fred_series.yml")
macro = compute_macro_axis_scores(panel, specs, concepts, config=cfg)
macro = macro[macro["date"] >= "1995-01-01"].copy()

pd.options.display.float_format = "{:6.3f}".format
pd.options.display.width = 220


def stats(s):
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        return {"mean": np.nan, "std": np.nan, "abs_p95": np.nan, "min": np.nan, "max": np.nan}
    return {"mean": float(s.mean()), "std": float(s.std()),
            "abs_p95": float(s.abs().quantile(0.95)),
            "min": float(s.min()), "max": float(s.max())}


# (1) Per-series
rows = []
for col in [c for c in macro.columns if c.startswith("contrib:")]:
    sid = col.replace("contrib:", "")
    spec = next((s for s in specs if s.series_id == sid), None)
    rows.append({"series": sid, "axis": spec.axis if spec else "?", **stats(macro[col])})
pd.DataFrame(rows).sort_values(["axis", "series"]).to_csv(ART / "q3_per_series.csv", index=False)
print("(1) per-series saved")
print(pd.DataFrame(rows).sort_values(["axis", "series"]).to_string(index=False))

# (2) Per-concept
rows = []
for col in [c for c in macro.columns if c.startswith("concept:")]:
    parts = col.split(":")
    axis, name = parts[1], parts[2]
    matching = next((c for c in concepts if c.axis == axis and c.name == name), None)
    rows.append({"axis": axis, "concept": name,
                 "weight": matching.weight if matching else np.nan, **stats(macro[col])})
print("\n(2) per-concept")
print(pd.DataFrame(rows).sort_values(["axis", "concept"]).to_string(index=False))
pd.DataFrame(rows).sort_values(["axis", "concept"]).to_csv(ART / "q3_per_concept.csv", index=False)

# (3) Per-axis distribution
rows = []
for axis in ("growth", "inflation"):
    macro_col = pd.to_numeric(macro[axis], errors="coerce")
    rows.append({"axis": axis, "layer": "macro", **stats(macro_col)})
    for layer, col in (("market", f"market_{axis}_score"), ("final", f"final_{axis}_score")):
        rows.append({"axis": axis, "layer": layer, **stats(results[col])})
pd.DataFrame(rows).to_csv(ART / "q3_axis_dist.csv", index=False)
print("\n(3) per-axis")
print(pd.DataFrame(rows).to_string(index=False))


# (4) Anchors
def anchor_summary(df):
    rows = []
    for label, lo, hi in ANCHORS:
        slc = df[(df["date"] >= lo) & (df["date"] < hi)]
        if slc.empty:
            rows.append({"period": label, "n": 0}); continue
        rc = Counter(slc["final_regime"].fillna("Unknown"))
        majority, share = rc.most_common(1)[0]
        rows.append({
            "period": label, "n": len(slc),
            "majority_regime": majority,
            "majority_share": share / len(slc),
            "stress_share": float(slc["risk_overlay_on"].mean()),
            "disagreement_share": float(slc["disagreement_flag"].mean()),
            "macro_g": float(pd.to_numeric(slc["macro_growth_score"], errors="coerce").mean()),
            "macro_i": float(pd.to_numeric(slc["macro_inflation_score"], errors="coerce").mean()),
            "market_g": float(pd.to_numeric(slc["market_growth_score"], errors="coerce").mean()),
            "market_i": float(pd.to_numeric(slc["market_inflation_score"], errors="coerce").mean()),
            "final_g": float(pd.to_numeric(slc["final_growth_score"], errors="coerce").mean()),
            "final_i": float(pd.to_numeric(slc["final_inflation_score"], errors="coerce").mean()),
        })
    return pd.DataFrame(rows).set_index("period")
anchors = anchor_summary(results)
anchors.to_csv(ART / "q3_anchors.csv")
print("\n(4) anchors")
print(anchors.to_string())

# (5) Disagreement
disagree = results.set_index("date")[["disagreement_flag"]].copy()
disagree["year"] = disagree.index.year
yr = disagree.groupby("year")["disagreement_flag"].mean()
yr.to_csv(ART / "q3_disagreement_yearly.csv")
print(f"\n(5) disagreement — overall {disagree['disagreement_flag'].mean():.3f}, "
      f"recent 5y {disagree['disagreement_flag'].tail(252*5).mean():.3f}")
print(yr.tail(15).to_string())

# (6) Neutral frequency
neutral = results["final_regime"].str.contains("Neutral", regex=True).fillna(False)
print(f"\n(6) neutral fraction: {neutral.mean():.3f}")
print(results["final_regime"].value_counts().head(10).to_string())

# (7) Transitions
res = results.sort_values("date").reset_index(drop=True)
flips = (res["final_regime"] != res["final_regime"].shift()).fillna(False)
n_flips = int(flips.sum()) - 1
duration = (res["date"].max() - res["date"].min()).days / 365.25
print(f"\n(7) transitions {n_flips} over {duration:.1f}y -> {n_flips/duration:.2f}/year")
runs = []; start = 0
for i in range(1, len(res) + 1):
    if i == len(res) or res["final_regime"].iloc[i] != res["final_regime"].iloc[i-1]:
        runs.append({"regime": res["final_regime"].iloc[start],
                     "start": res["date"].iloc[start],
                     "end": res["date"].iloc[i-1],
                     "days": i - start})
        start = i
runs_df = pd.DataFrame(runs)
runs_df.to_csv(ART / "q3_runs.csv", index=False)
print(runs_df["days"].describe(percentiles=[.25, .5, .75, .95]).round(1).to_string())

# Plots
fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
g_concepts = [c.name for c in concepts if c.axis == "growth"]
i_concepts = [c.name for c in concepts if c.axis == "inflation"]
for ax, axis_name, names, palette in [
    (axes[0], "growth", g_concepts, plt.cm.Blues(np.linspace(0.4, 0.95, max(len(g_concepts), 2)))),
    (axes[1], "inflation", i_concepts, plt.cm.viridis(np.linspace(0.1, 0.9, max(len(i_concepts), 2)))),
]:
    for name, color in zip(names, palette):
        col = f"concept:{axis_name}:{name}"
        if col in macro.columns:
            ax.plot(macro["date"], macro[col], lw=0.7, color=color, alpha=0.9, label=name)
    th = 0.20
    ax.axhline(th, color="grey", ls="--", lw=0.5)
    ax.axhline(-th, color="grey", ls="--", lw=0.5)
    ax.axhline(0, color="black", lw=0.5)
    ax.set_title(f"{axis_name} concepts (post-Q3)")
    ax.set_ylim(-1.1, 1.1); ax.grid(alpha=0.3)
    ax.legend(loc="lower left", ncol=4, fontsize=8)
plt.tight_layout(); plt.savefig(ART / "q3_concepts_ts.png", dpi=120)

fig, axes = plt.subplots(2, 1, figsize=(13, 6.5), sharex=True)
for ax, axis_name in [(axes[0], "growth"), (axes[1], "inflation")]:
    ax.plot(results["date"], results[f"macro_{axis_name}_score"], lw=0.7, color="#1f77b4", alpha=0.85, label="macro")
    ax.plot(results["date"], results[f"market_{axis_name}_score"], lw=0.7, color="#d62728", alpha=0.7, label="market")
    ax.plot(results["date"], results[f"final_{axis_name}_score"], lw=1.0, color="black", label="final")
    ax.axhline(0.20, color="grey", ls="--", lw=0.5)
    ax.axhline(-0.20, color="grey", ls="--", lw=0.5)
    ax.set_title(f"{axis_name} axis: macro vs market vs final (post-Q3, threshold ±0.20)")
    ax.grid(alpha=0.3); ax.legend(ncol=3, fontsize=8, loc="lower left")
    ax.set_ylim(-1.5, 1.5)
plt.tight_layout(); plt.savefig(ART / "q3_axes.png", dpi=120)

# Regime label time-strip
fig, ax = plt.subplots(figsize=(13, 2.6))
res_post = results[results["date"] >= "1995-01-01"].copy()
all_regimes = res_post["final_regime"].unique().tolist()
palette = plt.cm.tab20.colors
color_map = {r: palette[i % len(palette)] for i, r in enumerate(sorted(all_regimes))}
prev = None; start = res_post["date"].iloc[0]
for i in range(len(res_post)):
    cur = res_post["final_regime"].iloc[i]
    if prev is not None and cur != prev:
        ax.axvspan(start, res_post["date"].iloc[i], color=color_map[prev], alpha=0.7, ec="none")
        start = res_post["date"].iloc[i]
    prev = cur
ax.axvspan(start, res_post["date"].iloc[-1], color=color_map[prev], alpha=0.7, ec="none")
ax.set_yticks([]); ax.set_title("Regime time-strip (post-Q3)")
ax.grid(alpha=0.3)
plt.tight_layout(); plt.savefig(ART / "q3_regime_strip.png", dpi=120)
print("\nplots saved.")
