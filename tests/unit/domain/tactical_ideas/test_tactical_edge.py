"""Tactical Edge brief parser + AdvisorIdea mapping (hermetic — injected text/cards)."""

from __future__ import annotations

from types import SimpleNamespace

from market_helper.domain.tactical_ideas.tactical_edge import load_tactical_edge, parse_tactical_edge
from market_helper.trade_advisor.adapters.tactical import TacticalIdeasPlugin
from market_helper.trade_advisor.contracts import AdvisorContext

_SAMPLE = """# Tactical Edge Daily — 2026-06-08

Some tape preamble that is not a card.

---

### #1. Permafrost steepener — BoJ thaw → US 5s30s — Developing

- **Theme**: Off-preset (flows + term premium)
- **Mechanism**: Japan repatriation cheapens the US long end so 5s30s steepens.
- **Research question**: Do Japanese institutions pull UST demand fast enough?
- **Signal sketch (leak-safe)**: BoJ hike prob > 70% AND JGB 10y-2y above 1y avg.
- **Universe & data**: FRED, BoJ calendar. Instruments: IEF/TLT.
- **Retail expression**: 5s30s steepener — long IEF vs short TLT, DV01-balanced.
- **Trigger / entry**: Build half this week pre-BoJ.
- **Risk / stop**: Risk-off bull-flattening. Stop if 5s30s flattens 8bp.
- **Skeptic's view**: Repatriation is glacial and well-telegraphed; the long end can rally faster.
- **Crowding · Capacity · Regime**: Low crowding · ample capacity.
- **Scores**: Novelty 4/5 · Mechanism 4/5 · Tradability 4/5 · Conviction-today 3/5
- **Next step**: Open half-size IEF/TLT pair this week.

---

### #2. Circuit-breaker dispersion — long RSP / short QQQ — Developing (act Mon)

- **Theme**: US sector/factor rotation
- **Mechanism**: Crowded mega-cap unwind so equal-weight outperforms cap-weight.
- **Retail expression**: Long RSP / short QQQ. Defined-risk options alt: RSP call spread.
- **Risk / stop**: AI dips bought relentlessly. Stop if relative momentum reverts.
- **Skeptic's view**: This pair has bled for three years.
- **Scores**: Novelty 3/5 · Mechanism 3/5 · Tradability 4/5 · Conviction-today 4/5
- **Next step**: Open half-size dollar-neutral Monday.

---

## Random draws this session

`fermentation · permafrost`
"""


def test_parse_extracts_cards_fields_and_scores():
    date, cards = parse_tactical_edge(_SAMPLE)
    assert date == "2026-06-08"
    assert [c.number for c in cards] == [1, 2]
    c1 = cards[0]
    assert c1.title == "Permafrost steepener — BoJ thaw → US 5s30s"   # greedy title, status split off
    assert c1.status == "Developing"
    assert "5s30s steepens" in c1.get("mechanism")
    assert "glacial" in c1.get("skeptic's view")
    assert c1.scores["conviction-today"] == 3
    assert all("Random draws" not in c.title for c in cards)          # trailing ## section is not a card


def test_adapter_maps_edge_cards_to_advisor_ideas():
    _, cards = parse_tactical_edge(_SAMPLE)
    res = TacticalIdeasPlugin().produce(
        AdvisorContext(as_of="2026-06-08"), edge_cards=cards,
        prediction=SimpleNamespace(available=False), trending=SimpleNamespace(available=False),
    )
    edge = [s for s in res.suggestions if s.body_kind == "tactical_edge"]
    assert len(edge) == 2
    s1 = edge[0]
    assert s1.label == "WATCHLIST" and s1.decision_tier.startswith("T4")   # external research, never a trade candidate
    assert s1.assessment.confidence == "low"                                # conviction 3/5
    assert s1.assessment.actionability == "watch"                           # "Developing" → not act
    assert "glacial" in (s1.detail.get("skeptic") or "")                    # why-not preserved
    assert "Why-not" in s1.journal_note
    s2 = edge[1]
    assert s2.assessment.actionability == "staged"                          # "act Mon"
    assert s2.assessment.confidence == "medium"                             # conviction 4/5
    assert s2.assessment.risk_boundedness == "capped"                       # "defined-risk options alt"


def test_load_is_graceful_without_root():
    date, cards = load_tactical_edge(root="")     # no root → never raises, no cards
    assert date == "" and cards == []
