"""Build the seven validation outputs after the Q2 concept-aggregation change."""
from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, "notebooks/regime_detection/.cal")
from cal_helpers import ANCHORS, load_results

from market_helper.data_sources.fred.macro_panel import (
    load_concept_specs,
    load_panel,
    load_series_specs,
)
from market_helper.regimes.methods.macro_regime import (
    compute_macro_axis_scores,
    load_macro_regime_config,
)

CFG_PATH = Path("configs/regime_detection/fred_series.yml")
PANEL = Path("data/interim/fred/macro_panel.feather")
ART_DIR = Path("notebooks/regime_detection/.cal")
ART_DIR.mkdir(parents=True, exist_ok=True)

# ---------- Load engine output and macro internals ----------
results = load_results("data/artifacts/regime_detection/regime_snapshots.json")
results = results[results["date"] >= "1995-01-01"].copy()

panel = load_panel(PANEL)
specs = load_series_specs(CFG_PATH)
concepts = load_concept_specs(CFG_PATH)
cfg = load_macro_regime_config(CFG_PATH)
macro = compute_macro_axis_scores(panel, specs, concepts, config=cfg)
macro = macro[macro["date"] >= "1995-01-01"].copy()

pd.options.display.float_format = "{:6.3f}".format
pd.options.display.width = 220

# ---------- (1) per-series contribution table ----------
def stats(s: pd.Series) -> dict[str, float]:
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        return {"mean": np.nan, "std": np.nan, "abs_p95": np.nan, "min": np.nan, "max": np.nan}
    return {"mean": float(s.mean()), "std": float(s.std()),
            "abs_p95": float(s.abs().quantile(0.95)),
            "min": float(s.min()), "max": float(s.max())}

series_rows = []
for col in [c for c in macro.columns if c.startswith("contrib:")]:
    sid = col.replace("contrib:", "")
    spec = next((s for s in specs if s.series_id == sid), None)
    series_rows.append({
        "series": sid,
        "axis": spec.axis if spec else "?",
        **stats(macro[col]),
    })
series_df = pd.DataFrame(series_rows).sort_values(["axis", "series"])
series_df.to_csv(ART_DIR / "q2_per_series.csv", index=False)
print("=== (1) Per-series contribution stats ===")
print(series_df.to_string(index=False))

# ---------- (2) per-concept contribution table ----------
concept_rows = []
for col in [c for c in macro.columns if c.startswith("concept:")]:
    parts = col.split(":")
    axis, name = parts[1], parts[2]
    matching = next((c for c in concepts if c.axis == axis and c.name == name), None)
    concept_rows.append({
        "axis": axis,
        "concept": name,
        "weight": matching.weight if matching else np.nan,
        **stats(macro[col]),
    })
concept_df = pd.DataFrame(concept_rows).sort_values(["axis", "concept"])
concept_df.to_csv(ART_DIR / "q2_per_concept.csv", index=False)
print("\n=== (2) Per-concept score stats ===")
print(concept_df.to_string(index=False))

# ---------- (3) per-axis score distribution (macro vs market vs final) ----------
axis_rows = []
for axis in ("growth", "inflation"):
    for layer, col in (("macro", f"{axis}"), ("market", f"market_{axis}_score"), ("final", f"final_{axis}_score")):
        source = macro if layer == "macro" and col in macro.columns else results
        s = pd.to_numeric(source[col], errors="coerce").dropna()
        axis_rows.append({"axis": axis, "layer": layer, **stats(s)})
axis_df = pd.DataFrame(axis_rows)
axis_df.to_csv(ART_DIR / "q2_axis_dist.csv", index=False)
print("\n=== (3) Per-axis distribution ===")
print(axis_df.to_string(index=False))

# ---------- (4) anchor period regime summary ----------
def anchor_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, lo, hi in ANCHORS:
        slc = df[(df["date"] >= lo) & (df["date"] < hi)]
        if slc.empty:
            rows.append({"period": label, "n": 0})
            continue
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
anchors.to_csv(ART_DIR / "q2_anchors.csv")
print("\n=== (4) Anchor period regime summary ===")
print(anchors.to_string())

# ---------- (5) macro vs market disagreement share (full sample, by year) ----------
disagree = results.set_index("date")[["disagreement_flag"]].copy()
disagree["year"] = disagree.index.year
yearly_disagree = disagree.groupby("year")["disagreement_flag"].mean()
yearly_disagree.to_csv(ART_DIR / "q2_disagreement_yearly.csv")
print(f"\n=== (5) Disagreement share — overall: {disagree['disagreement_flag'].mean():.3f}; "
      f"recent 5y: {disagree['disagreement_flag'].tail(252*5).mean():.3f} ===")
print(yearly_disagree.tail(15).to_string())

# ---------- (6) neutral regime frequency ----------
neutral_re = results["final_regime"].str.contains(r"Neutral", regex=True).fillna(False)
print(f"\n=== (6) Neutral-regime frequency: {neutral_re.mean():.3f} ===")
print("Top 10 most common labels (full sample):")
print(results["final_regime"].value_counts().head(10).to_string())

# ---------- (7) transition frequency / regime turnover ----------
res_sorted = results.sort_values("date").reset_index(drop=True)
flips = (res_sorted["final_regime"] != res_sorted["final_regime"].shift()).fillna(False)
n_flips = int(flips.sum()) - 1
duration = (res_sorted["date"].max() - res_sorted["date"].min()).days / 365.25
print(f"\n=== (7) Regime transitions: {n_flips} flips over {duration:.1f} years -> {n_flips/duration:.2f}/year ===")

# Run lengths
runs = []
start = 0
for i in range(1, len(res_sorted) + 1):
    if i == len(res_sorted) or res_sorted["final_regime"].iloc[i] != res_sorted["final_regime"].iloc[i-1]:
        runs.append({"regime": res_sorted["final_regime"].iloc[start],
                     "start": res_sorted["date"].iloc[start],
                     "end": res_sorted["date"].iloc[i-1],
                     "days": i - start})
        start = i
runs_df = pd.DataFrame(runs)
runs_df.to_csv(ART_DIR / "q2_runs.csv", index=False)
print(f"Run-length stats (business days):")
print(runs_df["days"].describe(percentiles=[.25, .5, .75, .95]).round(1).to_string())

# ---------- Plot: per-concept time series ----------
fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
g_concepts = [c.name for c in concepts if c.axis == "growth"]
i_concepts = [c.name for c in concepts if c.axis == "inflation"]

for ax, axis_name, names, palette in [
    (axes[0], "growth", g_concepts, plt.cm.Blues(np.linspace(0.4, 0.95, len(g_concepts)))),
    (axes[1], "inflation", i_concepts, plt.cm.viridis(np.linspace(0.1, 0.9, len(i_concepts)))),
]:
    for name, color in zip(names, palette):
        col = f"concept:{axis_name}:{name}"
        if col in macro.columns:
            ax.plot(macro["date"], macro[col], lw=0.7, color=color, alpha=0.9, label=name)
    th = 0.35 if axis_name == "growth" else 0.50
    ax.axhline( th, color="grey", ls="--", lw=0.5)
    ax.axhline(-th, color="grey", ls="--", lw=0.5)
    ax.axhline(0, color="black", lw=0.5)
    ax.set_title(f"{axis_name} concepts (post-Q2)")
    ax.set_ylim(-1.1, 1.1); ax.grid(alpha=0.3)
    ax.legend(loc="lower left", ncol=4, fontsize=8)
plt.tight_layout()
plt.savefig(ART_DIR / "q2_concepts_ts.png", dpi=120)

# Plot: macro vs market vs final
fig, axes = plt.subplots(2, 1, figsize=(13, 6.5), sharex=True)
for ax, axis_name, th in [(axes[0], "growth", 0.35), (axes[1], "inflation", 0.50)]:
    ax.plot(results["date"], results[f"macro_{axis_name}_score"], lw=0.7, color="#1f77b4", alpha=0.85, label="macro")
    ax.plot(results["date"], results[f"market_{axis_name}_score"], lw=0.7, color="#d62728", alpha=0.7, label="market")
    ax.plot(results["date"], results[f"final_{axis_name}_score"], lw=1.0, color="black", label="final")
    ax.axhline( th, color="grey", ls="--", lw=0.5)
    ax.axhline(-th, color="grey", ls="--", lw=0.5)
    ax.set_title(f"{axis_name} axis: macro vs market vs final (post-Q2)")
    ax.grid(alpha=0.3); ax.legend(ncol=3, fontsize=8, loc="lower left")
plt.tight_layout()
plt.savefig(ART_DIR / "q2_axes.png", dpi=120)

print("\nplots saved to", ART_DIR)
