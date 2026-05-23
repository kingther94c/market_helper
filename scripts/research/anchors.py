"""Shared consensus-anchor definitions for the macro calibration workflow.

All research scripts read from here so perturbations (boundary shifts,
leave-one-out, alternative labels) and downstream metrics stay in lock-step.

Anchor schema:
    name          str
    start, end    str (ISO date)
    g_consensus   "Up" | "Down" | "Neutral"
    i_consensus   "Up" | "Down" | "Neutral"
    risk_consensus "On" | "Off"
    confidence    "clear" | "defensible" | "definition-dependent"
    alt_g, alt_i  optional alternative consensus labels for sensitivity
    brief         one-line description

LEVEL-based framing: see DEV_DOCS/docs/devplans/regime_engine_devplan.md
or the HTML report Methodology section. Inflation labels reflect "CPI YoY
relative to 2.5% comfort", not "direction of change".

Confidence taxonomy (Q2):
  - clear: textbook-consensus, near-unanimous (GFC, COVID, 2021 reflation,
    2022 H1 inflation peak, 2025 tariff)
  - defensible: smart analysts could differ in either direction
    (2018 Q4, 2019 H2, 2010-12, 2015-16, 2017)
  - definition-dependent: hinges on the level-vs-direction framing
    (2020 COVID inflation, 2020H2 catch-up, 2023, 2024)

LATENCY_PROBES (Q3): each probe starts a lead-in window BEFORE the
canonical transition date and measures how many bdays until the engine
first labels the target state for at least `min_hold` consecutive days.
This catches "engine reacts fast enough to be operationally useful"
rather than the old degenerate probes that started on the transition.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class Anchor:
    name: str
    start: str
    end: str
    g_consensus: str
    i_consensus: str
    risk_consensus: str
    confidence: str  # clear | defensible | definition-dependent
    brief: str
    alt_g: str | None = None  # alternative consensus if confidence != clear
    alt_i: str | None = None


@dataclass(frozen=True)
class LatencyProbe:
    name: str
    lead_in_start: str  # probe starts here (BEFORE the canonical transition)
    transition_date: str  # the canonical day we expect the engine to flip by
    axis: str  # "growth" | "inflation"
    target: str  # "Up" | "Down" | "Neutral"
    min_hold: int = 5  # require the label to persist this many bdays


# ---------------------------------------------------------------------------
# Consensus anchors — LEVEL-based, sorted chronologically.
# ---------------------------------------------------------------------------
ANCHORS_LEVEL: Sequence[Anchor] = (
    Anchor(
        name="2008 GFC trough",
        start="2008-10-01", end="2009-03-31",
        g_consensus="Down", i_consensus="Down", risk_consensus="On",
        confidence="clear",
        brief="Lehman+ deep recession; oil bust drives YoY CPI to ~-2%",
    ),
    Anchor(
        name="2010-12 expansion",
        start="2010-06-01", end="2012-12-31",
        g_consensus="Up", i_consensus="Neutral", risk_consensus="Off",
        confidence="defensible",
        brief="Slow but steady job growth (PAYEMS YoY +1.5-2%), CPI ~2-3%",
        # CPI YoY 2010-12 oscillated 1%-4% — Neutral or borderline Up
        alt_i="Up",
    ),
    Anchor(
        name="2015-16 oil bust",
        start="2015-08-01", end="2016-02-29",
        g_consensus="Neutral", i_consensus="Down", risk_consensus="On",
        confidence="defensible",
        brief="Mfg recession, CPI YoY near zero, oil bust deflation",
        # PAYEMS YoY was still +2% in 2015-16 — could read Up
        alt_g="Up",
    ),
    Anchor(
        name="2017 Goldilocks",
        start="2017-04-01", end="2017-12-31",
        g_consensus="Up", i_consensus="Neutral", risk_consensus="Off",
        confidence="defensible",
        brief="PAYEMS +1.5% YoY, CPI ~2.1%",
    ),
    Anchor(
        name="2018 Q4 vol shock",
        start="2018-10-01", end="2018-12-31",
        g_consensus="Up", i_consensus="Neutral", risk_consensus="On",
        confidence="defensible",
        brief="Growth still strong YoY (PAYEMS +1.7%); market stress",
        # Market signals were screaming recession; some analysts call growth Down
        alt_g="Down",
    ),
    Anchor(
        name="2019 H2 slowdown",
        start="2019-07-01", end="2019-12-31",
        g_consensus="Neutral", i_consensus="Neutral", risk_consensus="Off",
        confidence="defensible",
        brief="Mixed: services strong, mfg recession; CPI ~1.8%",
        # PAYEMS YoY was still +1.5% — Up by labor view
        alt_g="Up",
    ),
    Anchor(
        name="2020 COVID recession",
        start="2020-02-24", end="2020-04-30",
        g_consensus="Down", i_consensus="Neutral", risk_consensus="On",
        confidence="definition-dependent",
        brief="Catastrophic growth shock; CPI YoY collapse but not deflation",
        # Markets priced deflation; ex-post CPI bottomed at 0.1% (Neutral)
        alt_i="Down",
    ),
    Anchor(
        name="2020H2 catch-up",
        start="2020-07-01", end="2020-12-31",
        g_consensus="Down", i_consensus="Down", risk_consensus="Off",
        confidence="definition-dependent",
        brief="Recovering but YoY still deep negative; CPI YoY ~1.4%",
        # Direction view says Up; level view says Down (we use Down)
        alt_g="Up", alt_i="Neutral",
    ),
    Anchor(
        name="2021 reflation",
        start="2021-04-01", end="2021-12-31",
        g_consensus="Up", i_consensus="Up", risk_consensus="Off",
        confidence="clear",
        brief="Strong recovery, CPI breaks above 5%",
    ),
    Anchor(
        name="2022 H1 inflation",
        start="2022-03-01", end="2022-09-30",
        g_consensus="Up", i_consensus="Up", risk_consensus="On",
        confidence="clear",
        brief="PAYEMS +5-6% YoY catch-up, CPI peaks at 9.1% in June",
        # Headline GDP says growth Down — minority view
        alt_g="Down",
    ),
    Anchor(
        name="2023 high inflation",
        start="2023-06-01", end="2023-12-31",
        g_consensus="Up", i_consensus="Up", risk_consensus="Off",
        confidence="definition-dependent",
        brief="Soft landing but CPI still 3-4%, payrolls +2.5%",
        # Direction view says inflation Down (cooling); level says Up
        alt_i="Down",
    ),
    Anchor(
        name="2024 disinflation",
        start="2024-01-01", end="2024-12-31",
        g_consensus="Up", i_consensus="Neutral", risk_consensus="Off",
        confidence="definition-dependent",
        brief="PAYEMS +1.5%, CPI fading to ~2.5-3% range",
        # Direction view says Down
        alt_i="Down",
    ),
    Anchor(
        name="2025 tariff shock",
        start="2025-04-02", end="2025-05-15",
        g_consensus="Neutral", i_consensus="Up", risk_consensus="On",
        confidence="clear",
        brief="Breakevens spike; equity drawdown; growth signals mixed",
    ),
)


# ---------------------------------------------------------------------------
# Real-latency probes (Q3 redesign).
# Lead-in starts 60 bdays before the canonical transition. The probe asks:
# starting from lead_in_start (when the regime was still in the prior state),
# how many bdays elapse until the engine first labels and HOLDS the target
# state for at least min_hold consecutive bdays?
# ---------------------------------------------------------------------------
LATENCY_PROBES: Sequence[LatencyProbe] = (
    # GFC inflation collapse — by Oct 2008 oil prices had crashed
    LatencyProbe(
        name="GFC inflation collapse",
        lead_in_start="2008-07-01",
        transition_date="2008-10-15",
        axis="inflation", target="Down", min_hold=5,
    ),
    # COVID growth turn — engine should call growth Down by mid-March
    LatencyProbe(
        name="COVID growth turn",
        lead_in_start="2020-01-02",
        transition_date="2020-03-10",
        axis="growth", target="Down", min_hold=5,
    ),
    # COVID inflation collapse — breakevens crashed in March
    LatencyProbe(
        name="COVID inflation collapse",
        lead_in_start="2020-01-02",
        transition_date="2020-03-15",
        axis="inflation", target="Down", min_hold=5,
    ),
    # 2021 reflation — inflation breaking out (CPI Apr 2021 print = 4.2%)
    LatencyProbe(
        name="2021 reflation start",
        lead_in_start="2021-01-04",
        transition_date="2021-05-12",  # April CPI release date
        axis="inflation", target="Up", min_hold=5,
    ),
    # 2022 stagflation — engine should call inflation Up by spring 2022
    LatencyProbe(
        name="2022 inflation surge",
        lead_in_start="2021-12-01",
        transition_date="2022-04-12",  # March CPI release
        axis="inflation", target="Up", min_hold=5,
    ),
    # 2023 disinflation transition (LEVEL framing: when does score cross
    # back into Neutral range as CPI YoY drops to ~3%?)
    LatencyProbe(
        name="2023→24 inflation cooling to Neutral",
        lead_in_start="2023-06-01",
        transition_date="2024-04-01",  # roughly when CPI YoY dipped to ~3%
        axis="inflation", target="Neutral", min_hold=10,
    ),
    # 2025 tariff shock — inflation expectations spike on Liberation Day
    LatencyProbe(
        name="2025 tariff inflation spike",
        lead_in_start="2025-02-01",
        transition_date="2025-04-02",
        axis="inflation", target="Up", min_hold=3,
    ),
)


# ---------------------------------------------------------------------------
# Perturbation strategies for Q1 robustness.
# Each yields a list of anchors (possibly modified) representing one
# alternative anchor set against which to re-rank configs.
# ---------------------------------------------------------------------------


def perturb_boundary_shifts(shift_bdays: int) -> list[Anchor]:
    """Shift every anchor's window by +/- shift_bdays. Useful to test that
    the recommendation isn't keyed to specific exact dates."""
    import pandas as pd

    out = []
    for a in ANCHORS_LEVEL:
        lo = pd.Timestamp(a.start) + pd.tseries.offsets.BDay(shift_bdays)
        hi = pd.Timestamp(a.end) + pd.tseries.offsets.BDay(shift_bdays)
        out.append(Anchor(
            name=a.name + f" (shift {shift_bdays:+d}bd)",
            start=str(lo.date()), end=str(hi.date()),
            g_consensus=a.g_consensus, i_consensus=a.i_consensus,
            risk_consensus=a.risk_consensus, confidence=a.confidence,
            brief=a.brief, alt_g=a.alt_g, alt_i=a.alt_i,
        ))
    return out


def perturb_leave_one_out() -> list[tuple[str, list[Anchor]]]:
    """Generate 13 anchor sets, each dropping one anchor."""
    return [
        (f"drop {a.name}", [x for x in ANCHORS_LEVEL if x is not a])
        for a in ANCHORS_LEVEL
    ]


def perturb_alt_consensus() -> list[Anchor]:
    """Swap in alternative consensus labels for anchors that have them.
    Anchors without alt labels stay unchanged."""
    out = []
    for a in ANCHORS_LEVEL:
        out.append(Anchor(
            name=a.name + " (alt labels)",
            start=a.start, end=a.end,
            g_consensus=a.alt_g if a.alt_g else a.g_consensus,
            i_consensus=a.alt_i if a.alt_i else a.i_consensus,
            risk_consensus=a.risk_consensus, confidence=a.confidence,
            brief=a.brief,
        ))
    return out


def anchor_to_tuple(a: Anchor) -> tuple:
    """Compatibility shim for older code that expected tuples."""
    return (a.name, a.start, a.end, a.g_consensus, a.i_consensus,
            a.risk_consensus, a.brief)


__all__ = [
    "Anchor",
    "LatencyProbe",
    "ANCHORS_LEVEL",
    "LATENCY_PROBES",
    "perturb_boundary_shifts",
    "perturb_leave_one_out",
    "perturb_alt_consensus",
    "anchor_to_tuple",
]
