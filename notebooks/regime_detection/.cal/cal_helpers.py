"""Calibration helpers — anchor periods, axis timeseries, contributor tables."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


ANCHORS = [
    ("2008 GFC",                   "2008-09-01", "2008-12-31"),
    ("2009-10 Recovery",           "2009-04-01", "2010-06-30"),
    ("2011 Euro / US downgrade",   "2011-07-01", "2011-12-31"),
    ("2014-16 Oil collapse",       "2014-09-01", "2016-03-31"),
    ("2017 Soft landing",          "2017-01-01", "2017-12-31"),
    ("2018 Q4 Selloff",            "2018-10-01", "2018-12-31"),
    ("2020 COVID shock",           "2020-02-15", "2020-04-30"),
    ("2020H2-21 Reopening",        "2020-07-01", "2021-12-31"),
    ("2022 Inflation / Tightening","2022-01-01", "2022-12-31"),
    ("2023-24 Disinflation",       "2023-06-01", "2024-12-31"),
    ("2025 Tariff shock (Apr)",    "2025-04-01", "2025-04-30"),
    ("2026 YTD",                   "2026-01-01", "2027-01-01"),
]


def load_results(path: str | Path) -> pd.DataFrame:
    rows = json.loads(Path(path).read_text())
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def anchor_summary(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for label, lo, hi in ANCHORS:
        slc = df[(df["date"] >= lo) & (df["date"] < hi)]
        if slc.empty:
            out.append({"period": label, "n": 0})
            continue
        regime_counts = Counter(slc["final_regime"].fillna("Unknown"))
        majority, share = regime_counts.most_common(1)[0]
        out.append({
            "period": label,
            "n": len(slc),
            "majority_regime": majority,
            "majority_share": share / len(slc),
            "stress_share": float(slc["risk_overlay_on"].mean() if "risk_overlay_on" in slc else float("nan")),
            "disagreement_share": float(slc["disagreement_flag"].mean() if "disagreement_flag" in slc else float("nan")),
            "macro_g_avg": _safe_mean(slc, "macro_growth_score"),
            "macro_i_avg": _safe_mean(slc, "macro_inflation_score"),
            "market_g_avg": _safe_mean(slc, "market_growth_score"),
            "market_i_avg": _safe_mean(slc, "market_inflation_score"),
            "final_g_avg": _safe_mean(slc, "final_growth_score"),
            "final_i_avg": _safe_mean(slc, "final_inflation_score"),
            "risk_avg": _safe_mean(slc, "risk_score"),
        })
    return pd.DataFrame(out)


def _safe_mean(df: pd.DataFrame, col: str) -> float:
    if col not in df:
        return float("nan")
    return float(pd.to_numeric(df[col], errors="coerce").mean())


def axis_timeseries(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "date",
        "final_regime",
        "macro_growth_score", "macro_inflation_score",
        "market_growth_score", "market_inflation_score",
        "final_growth_score", "final_inflation_score",
        "risk_score", "risk_overlay_on", "disagreement_flag",
    ]
    cols = [c for c in cols if c in df.columns]
    return df[cols].copy()


def regime_run_lengths(df: pd.DataFrame, by: str = "final_regime") -> pd.DataFrame:
    """Return run-length encoding of the regime column."""
    s = df[by].fillna("Unknown").reset_index(drop=True)
    runs = []
    start = 0
    for i in range(1, len(s) + 1):
        if i == len(s) or s[i] != s[i - 1]:
            runs.append({"regime": s[start], "start": df["date"].iloc[start], "end": df["date"].iloc[i - 1], "days": i - start})
            start = i
    return pd.DataFrame(runs)


def contributor_table_for_date(df: pd.DataFrame, target_date: str) -> tuple[pd.Series, pd.DataFrame]:
    """Return (final scores summary, contributor table) for the snapshot at target_date."""
    slc = df[df["date"] <= target_date].iloc[-1]
    summary = pd.Series({
        "as_of":               str(slc["date"].date()),
        "final_regime":        slc.get("final_regime"),
        "base_regime":         slc.get("base_regime"),
        "confidence":          slc.get("confidence"),
        "disagreement_flag":   slc.get("disagreement_flag"),
        "final_growth_score":  slc.get("final_growth_score"),
        "final_inflation_score": slc.get("final_inflation_score"),
        "risk_score":          slc.get("risk_score"),
        "risk_overlay_on":     slc.get("risk_overlay_on"),
    })
    contribs = []
    for layer in slc.get("layer_outputs", []) or []:
        layer_name = layer.get("layer_name")
        for sign, lst in (("+", layer.get("top_positive_contributors", [])),
                          ("-", layer.get("top_negative_contributors", []))):
            for name, value in lst or []:
                contribs.append({"layer": layer_name, "sign": sign, "driver": name, "value": value})
    risk_out = slc.get("risk_output") or {}
    for sign, lst in (("+", risk_out.get("top_positive_contributors", [])),
                      ("-", risk_out.get("top_negative_contributors", []))):
        for name, value in lst or []:
            contribs.append({"layer": "risk", "sign": sign, "driver": name, "value": value})
    return summary, pd.DataFrame(contribs)
