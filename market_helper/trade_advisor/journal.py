"""Decision journal — the ex-ante record that makes the advisor *verifiable*.

Append-only JSONL under ``data/artifacts/trade_advisor/``. Two stores:

- **decisions** — when you Promote / Watch / Dismiss an idea, a snapshot of the idea
  *at that moment* is frozen: the ex-ante thesis, the four assessment axes, the label /
  tier / data_mode, plus a 30/60/90-day ``review_after`` schedule. This is what turns a
  pretty dashboard into something you can later grade — you compare the ex-ante thesis to
  what actually happened.
- **reviews** — the ex-post verdict you record at each milestone (worked / partly /
  wrong / noise + a note). :meth:`DecisionJournal.due_for_review` surfaces what's owed.

The ``note`` is a human annotation, never interpreted by the system (it does not breach
the "no free-form input" rule, which governs engine *controls*, not memos). Robust by
design: a corrupt line is skipped, never crashes a read.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .contracts import Suggestion

# The operator's decision verbs are deliberately distinct from the system's triage
# labels (RESEARCH_READY/WATCHLIST/…) — these are what *you* choose to do with an idea,
# and none of them says "trade".
DECISIONS = ("PROMOTE", "WATCH", "DISMISS")
DECISION_ORDER = {"PROMOTE": 0, "WATCH": 1, "DISMISS": 2}
ACTIVE_DECISIONS = ("PROMOTE", "WATCH")

# Ex-post review verdicts (graded against the ex-ante thesis).
REVIEW_VERDICTS = ("worked", "partly", "wrong", "noise")
DEFAULT_REVIEW_DAYS = (30, 60, 90)


@dataclass(frozen=True)
class Decision:
    ts: str                 # ISO timestamp the decision was recorded
    suggestion_id: str
    advisor: str
    subject: str
    title: str
    decision: str           # PROMOTE | WATCH | DISMISS
    note: str = ""
    score: float = 0.0
    as_of: str = ""         # the idea's as_of when decided
    # --- ex-ante snapshot (frozen at decision time, for later grading) ---
    ex_ante_thesis: str = ""
    label: str = ""
    decision_tier: str = ""
    data_mode: str = ""
    instrument_family: str = ""
    confidence: str = ""
    actionability: str = ""
    risk_boundedness: str = ""
    data_quality: str = ""
    risk: str = ""
    invalidation: str = ""
    review_after: list[str] = field(default_factory=list)   # ISO dates, e.g. ts+30/60/90


@dataclass(frozen=True)
class Review:
    ts: str                 # ISO timestamp the review was recorded
    suggestion_id: str
    milestone: str          # the review_after date being closed (or "ad_hoc")
    verdict: str            # one of REVIEW_VERDICTS
    note: str = ""


def review_dates(ts: str, days: tuple[int, ...] = DEFAULT_REVIEW_DAYS) -> list[str]:
    """ISO review dates at ts + N days (empty if ts is unparseable)."""
    try:
        base = date.fromisoformat(str(ts)[:10])
    except (ValueError, TypeError):
        return []
    return [(base + timedelta(days=int(n))).isoformat() for n in days]


def decision_from_suggestion(
    s: Suggestion, decision: str, *, ts: str, note: str = "", review_days: tuple[int, ...] = DEFAULT_REVIEW_DAYS
) -> Decision:
    """Freeze an ex-ante snapshot of the idea at decision time + schedule its reviews."""
    a = s.assessment
    return Decision(
        ts=ts,
        suggestion_id=s.suggestion_id,
        advisor=s.advisor,
        subject=s.subject,
        title=s.title,
        decision=decision,
        note=note,
        score=s.score,
        as_of=s.as_of,
        ex_ante_thesis=s.thesis,
        label=s.label,
        decision_tier=s.decision_tier,
        data_mode=s.data_mode,
        instrument_family=s.instrument_family,
        confidence=a.confidence,
        actionability=a.actionability,
        risk_boundedness=a.risk_boundedness,
        data_quality=a.data_quality,
        risk=s.risk,
        invalidation=s.invalidation,
        review_after=review_dates(ts, review_days) if decision in ACTIVE_DECISIONS else [],
    )


def _read_jsonl(path: Path, cls):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            out.append(cls(**{k: payload[k] for k in payload if k in cls.__dataclass_fields__}))
        except Exception:
            continue  # skip a corrupt / schema-drifted line, never crash a read
    return out


class DecisionJournal:
    """Append-only JSONL store of decisions (+ a sibling reviews log)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @property
    def reviews_path(self) -> Path:
        return self.path.with_name(f"{self.path.stem}_reviews{self.path.suffix or '.jsonl'}")

    def record(self, decision: Decision) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(decision)) + "\n")

    def record_review(self, review: Review) -> None:
        self.reviews_path.parent.mkdir(parents=True, exist_ok=True)
        with self.reviews_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(review)) + "\n")

    def all(self) -> list[Decision]:
        return _read_jsonl(self.path, Decision)

    def all_reviews(self) -> list[Review]:
        return _read_jsonl(self.reviews_path, Review)

    def latest_by_suggestion(self) -> dict[str, Decision]:
        latest: dict[str, Decision] = {}
        for decision in self.all():
            latest[decision.suggestion_id] = decision  # later lines overwrite earlier
        return latest

    def reviewed_keys(self) -> set[tuple[str, str]]:
        return {(r.suggestion_id, r.milestone) for r in self.all_reviews()}

    def inbox(self, decisions: tuple[str, ...] = ACTIVE_DECISIONS) -> list[Decision]:
        """Latest decision per suggestion, filtered, Promote→Watch then recent-first."""
        items = [d for d in self.latest_by_suggestion().values() if d.decision in decisions]
        items.sort(key=lambda d: d.ts, reverse=True)               # recent first…
        items.sort(key=lambda d: DECISION_ORDER.get(d.decision, 9))  # …within decision order (stable)
        return items

    def due_for_review(self, as_of: str) -> list[tuple[Decision, str]]:
        """(decision, milestone_date) for each scheduled review ≤ as_of not yet reviewed.

        Only active (Promote/Watch) decisions are reviewable; soonest-due first. This is
        the loop that keeps the system honest — every promoted idea comes back to be graded.
        """
        reviewed = self.reviewed_keys()
        due: list[tuple[Decision, str]] = []
        for d in self.latest_by_suggestion().values():
            if d.decision not in ACTIVE_DECISIONS:
                continue
            for milestone in d.review_after:
                if milestone <= as_of and (d.suggestion_id, milestone) not in reviewed:
                    due.append((d, milestone))
        due.sort(key=lambda dm: dm[1])
        return due
