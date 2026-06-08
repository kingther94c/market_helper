"""Tactical Edge — ingest the external daily research brief.

Reads ``MARKET_HELPER_GDRIVE_ROOT/Tactical_Edge/latest.md`` (root resolved via
:func:`market_helper.config.local_env.read_gdrive_root`), a daily *Tactical Edge*
brief of structured idea cards, and parses each ``### #N. Title — Status`` block into
a :class:`TacticalEdgeCard`. The tactical adapter maps these onto the AdvisorIdea
contract (T4 research, WATCHLIST) — the card's **Skeptic's view** becomes the forced
"why not trade".

Offline + graceful: parsing is pure-string (unit-tested on injected text), and
:func:`load_tactical_edge` returns no cards when the file is absent or unreadable —
the tactical module never hard-depends on the external brief.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Title may itself contain em-dashes; the STATUS is the last " — …" segment → greedy title.
_CARD_RE = re.compile(r"^###\s+#(\d+)\.\s+(.*)\s+[—–-]\s+(.*?)\s*$")
_FIELD_RE = re.compile(r"^[-*]\s+\*\*(.+?)\*\*\s*[:：]\s*(.*)$")
_DATE_RE = re.compile(r"Tactical Edge Daily\s*[—–-]\s*(\S+)")
_SCORE_RE = re.compile(r"([A-Za-z][A-Za-z\- ]*?)\s+(\d)\s*/\s*5")


def _norm(label: str) -> str:
    """Normalize a bold field label to a stable key (drop parentheticals / separators)."""
    out = label.strip().lower()
    for sep in (" (", " · ", " / "):
        out = out.split(sep)[0]
    return out.strip()


@dataclass(frozen=True)
class TacticalEdgeCard:
    """One parsed idea card from the daily Tactical Edge brief."""

    number: int
    title: str
    status: str
    fields: dict[str, str] = field(default_factory=dict)   # normalized label -> value
    scores: dict[str, int] = field(default_factory=dict)   # e.g. {"conviction-today": 3}

    def get(self, *keys: str, default: str = "") -> str:
        for key in keys:
            val = self.fields.get(key, "")
            if val:
                return val
        return default


def _parse_scores(text: str) -> dict[str, int]:
    return {m.group(1).strip().lower(): int(m.group(2)) for m in _SCORE_RE.finditer(text)}


def parse_tactical_edge(md: str) -> tuple[str, list[TacticalEdgeCard]]:
    """Parse the brief markdown → (date, cards). Pure; safe on partial/garbage input."""
    date = ""
    dm = _DATE_RE.search(md or "")
    if dm:
        date = dm.group(1)

    cards: list[TacticalEdgeCard] = []
    cur: tuple[int, str, str] | None = None
    cur_fields: dict[str, str] = {}
    cur_scores: dict[str, int] = {}

    def flush() -> None:
        nonlocal cur, cur_fields, cur_scores
        if cur is not None:
            cards.append(TacticalEdgeCard(cur[0], cur[1], cur[2], dict(cur_fields), dict(cur_scores)))
        cur, cur_fields, cur_scores = None, {}, {}

    for line in (md or "").splitlines():
        card_match = _CARD_RE.match(line)
        if card_match:
            flush()
            cur = (int(card_match.group(1)), card_match.group(2).strip(), card_match.group(3).strip())
            continue
        if cur is None:
            continue
        if line.startswith("## ") or line.startswith("### "):
            flush()
            continue
        field_match = _FIELD_RE.match(line)
        if field_match:
            key, val = _norm(field_match.group(1)), field_match.group(2).strip()
            cur_fields[key] = val
            if key == "scores":
                cur_scores = _parse_scores(val)
    flush()
    return date, cards


def tactical_edge_path(root: str | Path | None = None, *, filename: str = "latest.md") -> Path | None:
    """Resolve the brief path under the GDrive root (or ``None`` if no root)."""
    if root is None:
        from market_helper.config.local_env import read_gdrive_root

        root = read_gdrive_root()
    if not root:
        return None
    return Path(root) / "Tactical_Edge" / filename


def load_tactical_edge(root: str | Path | None = None) -> tuple[str, list[TacticalEdgeCard]]:
    """Load + parse the brief. Returns ``("", [])`` when absent/unreadable (graceful)."""
    path = tactical_edge_path(root)
    if path is None or not path.is_file():
        return "", []
    try:
        return parse_tactical_edge(path.read_text(encoding="utf-8"))
    except OSError:
        return "", []


__all__ = ["TacticalEdgeCard", "parse_tactical_edge", "tactical_edge_path", "load_tactical_edge"]
