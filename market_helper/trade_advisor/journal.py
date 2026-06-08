"""Decision journal — persist Proceed / Monitor / Reject decisions (+ a note).

Append-only JSONL under ``data/artifacts/trade_advisor/``. The ``note`` is a
**human annotation**, never interpreted by the system — so it does not breach
the "no free-form input" rule (that rule governs engine *controls*, not memos).
The journal feeds the dashboard **Inbox** and the static report snapshot.

Robust by design: a corrupt line is skipped, never crashes a read.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .contracts import Suggestion

# The operator's decision verbs are deliberately distinct from the system's triage
# labels (RESEARCH_READY/WATCHLIST/…) — these are what *you* choose to do with an idea,
# and none of them says "trade".
DECISIONS = ("PROMOTE", "WATCH", "DISMISS")
DECISION_ORDER = {"PROMOTE": 0, "WATCH": 1, "DISMISS": 2}


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


def decision_from_suggestion(s: Suggestion, decision: str, *, ts: str, note: str = "") -> Decision:
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
    )


class DecisionJournal:
    """Append-only JSONL store of decisions; last write per suggestion wins."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def record(self, decision: Decision) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(decision)) + "\n")

    def all(self) -> list[Decision]:
        if not self.path.exists():
            return []
        out: list[Decision] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(Decision(**json.loads(line)))
            except Exception:
                continue  # skip a corrupt line, never crash a read
        return out

    def latest_by_suggestion(self) -> dict[str, Decision]:
        latest: dict[str, Decision] = {}
        for decision in self.all():
            latest[decision.suggestion_id] = decision  # later lines overwrite earlier
        return latest

    def inbox(self, decisions: tuple[str, ...] = ("PROMOTE", "WATCH")) -> list[Decision]:
        """Latest decision per suggestion, filtered, Promote→Watch then recent-first."""
        items = [d for d in self.latest_by_suggestion().values() if d.decision in decisions]
        items.sort(key=lambda d: d.ts, reverse=True)               # recent first…
        items.sort(key=lambda d: DECISION_ORDER.get(d.decision, 9))  # …within decision order (stable)
        return items
