"""Policy-Expert Trending -- descriptive exponential-weighted momentum view (goal-v2 E).

Reads the committed daily expert-return series and computes:
  - exponentially-weighted (halflife ~30 trading days) relative performance of the 4
    experts -> cross-sectional softmax -> probabilities (the current "trend" mix),
  - the recent probability trend (for a chart),
  - trailing 3M / 1M / 1W simple performance per expert.

This is BACKWARD-looking momentum -- distinct from the forward ML predictor
(policy_expert_predictor). pandas read of a committed CSV; no network, no sklearn.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from market_helper.app.paths import RESEARCH_ARTIFACTS_DIR

EXPERTS = ["Goldilocks", "Reflation", "Stagflation", "Recession"]
DAILY_CSV = RESEARCH_ARTIFACTS_DIR / "policy_expert_daily_returns.csv"
HALFLIFE = 30          # trading-day halflife for the EW momentum
TEMP = 0.10            # softmax temperature on annualised EW relative performance
HISTORY_DAYS = 126     # ~6 months of probability history for the trend chart


@dataclass(frozen=True)
class PolicyExpertTrending:
    available: bool
    reason: str = ""
    as_of: str = ""
    halflife_days: int = HALFLIFE
    probabilities: dict[str, float] = field(default_factory=dict)
    trail_3m: dict[str, float] = field(default_factory=dict)
    trail_1m: dict[str, float] = field(default_factory=dict)
    trail_1w: dict[str, float] = field(default_factory=dict)
    history_dates: list[str] = field(default_factory=list)
    history: dict[str, list[float]] = field(default_factory=dict)   # expert -> probs


def _softmax_rows(M: np.ndarray) -> np.ndarray:
    z = (M - M.mean(1, keepdims=True)) / TEMP
    z = z - z.max(1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(1, keepdims=True)


def compute_trending(*, daily_csv: Path | None = None) -> PolicyExpertTrending:
    path = Path(daily_csv) if daily_csv else DAILY_CSV
    if not path.exists():
        return PolicyExpertTrending(False, reason="daily returns file not found")
    try:
        df = pd.read_csv(path)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")[EXPERTS].astype(float).dropna()
        if len(df) < HISTORY_DAYS:
            return PolicyExpertTrending(False, reason="insufficient daily history")
        ew_ann = df.ewm(halflife=HALFLIFE).mean() * 252.0          # EW recent perf, annualised
        rel = ew_ann.sub(ew_ann.mean(axis=1), axis=0)              # cross-sectional relative
        probs = pd.DataFrame(_softmax_rows(rel.to_numpy()), index=df.index, columns=EXPERTS)
        latest = probs.iloc[-1]
        hist = probs.tail(HISTORY_DAYS)

        def trail(win: int) -> dict[str, float]:
            return {k: round(float((1 + df[k]).tail(win).prod() - 1) * 100, 1) for k in EXPERTS}

        return PolicyExpertTrending(
            available=True,
            as_of=df.index[-1].date().isoformat(),
            probabilities={k: round(float(latest[k]), 4) for k in EXPERTS},
            trail_3m=trail(63), trail_1m=trail(21), trail_1w=trail(5),
            history_dates=[d.date().isoformat() for d in hist.index],
            history={k: [round(float(x), 4) for x in hist[k]] for k in EXPERTS},
        )
    except Exception as exc:  # noqa: BLE001 -- advisory surface must never raise
        return PolicyExpertTrending(False, reason=f"trending error: {type(exc).__name__}")


__all__ = ["PolicyExpertTrending", "compute_trending"]
