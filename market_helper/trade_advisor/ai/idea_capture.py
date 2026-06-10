"""Capture structured ideas out of an AI Plus dialog — closing the accumulate loop.

The tactical AI pane previously produced prose that evaporated with the dialog.
This module defines a tiny structured-text protocol (mirroring the tool-call
protocol's philosophy: structured *text*, gateway-agnostic): the AI is asked to
emit each proposed idea as a fenced ``idea`` block —

    ```idea
    TITLE: Short USD vs Asia FX basket
    STANCE: short
    SUBJECT: USD
    THESIS: ...
    EXPRESSION: ...
    CONFIDENCE: medium
    RISK: ...
    INVALIDATION: ...
    HORIZON: 1-3 months
    ```

``parse_idea_blocks`` extracts them (tolerant: lowercase keys, garbage between
blocks, malformed blocks skipped — never raises) and ``captured_suggestion``
maps one onto the shared :class:`Suggestion` contract so the journal /
Promote-Watch machinery works natively on captured ideas.

Honesty: a captured idea is **T4 research, WATCHLIST-capped, data_quality
"synthetic"** — it is an AI-asserted hypothesis, not verified data. Read-only:
the protocol has no order/size fields, and sizes in free text are not parsed.
"""

from __future__ import annotations

import re

from ..contracts import (
    CONFIDENCE_LEVELS,
    LABEL_WATCHLIST,
    TIER_RESEARCH,
    IdeaAssessment,
    Suggestion,
    cap_label_for_tier,
)

# Appended to the AI pane's system framing so replies carry capturable blocks.
IDEA_BLOCK_INSTRUCTIONS = (
    "\n\nWhen you propose trade ideas, ALSO emit each one as a fenced block so it can be "
    "captured into the idea journal — exactly this shape (one block per idea, keys on their "
    "own lines, no order/size fields):\n"
    "```idea\n"
    "TITLE: <short headline>\n"
    "STANCE: <long|short|neutral>\n"
    "SUBJECT: <ticker / theme>\n"
    "THESIS: <one or two sentences>\n"
    "EXPRESSION: <how a retail account would express it — instrument, NOT a size>\n"
    "CONFIDENCE: <high|medium|low|speculative>\n"
    "RISK: <principal risk>\n"
    "INVALIDATION: <what observable would prove it wrong>\n"
    "HORIZON: <e.g. 1-3 months>\n"
    "```"
)

_FENCE_RE = re.compile(r"```idea\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_KEY_RE = re.compile(
    r"^(TITLE|STANCE|SUBJECT|THESIS|EXPRESSION|CONFIDENCE|RISK|INVALIDATION|HORIZON)\s*:\s*(.*)$",
    re.IGNORECASE,
)


def parse_idea_blocks(text: str) -> list[dict]:
    """All well-formed ``idea`` blocks in ``text`` → list of lowercase-key dicts.

    A block needs at least TITLE + THESIS to count; continuation lines extend the
    previous key's value. Tolerant by design — malformed blocks are skipped, the
    function never raises.
    """
    out: list[dict] = []
    for match in _FENCE_RE.finditer(text or ""):
        fields: dict[str, str] = {}
        current: str | None = None
        for line in match.group(1).splitlines():
            km = _KEY_RE.match(line.strip())
            if km:
                current = km.group(1).lower()
                fields[current] = km.group(2).strip()
            elif current and line.strip():
                fields[current] = (fields[current] + " " + line.strip()).strip()
        if fields.get("title") and fields.get("thesis"):
            out.append(fields)
    return out


def _slug(text: str, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")[:n] or "idea"


def captured_suggestion(fields: dict, *, as_of: str) -> Suggestion:
    """Map one parsed idea block onto the shared contract (T4 · WATCHLIST-capped).

    The assessment is deliberately conservative: confidence comes from the block
    (defaulting to speculative), actionability is *watch*, risk boundedness is
    *undefined* (free-text risk is not a defined structure), and data quality is
    *synthetic* — an AI-asserted hypothesis until the operator verifies it.
    """
    conf = str(fields.get("confidence", "")).strip().lower()
    if conf not in CONFIDENCE_LEVELS:
        conf = "speculative"
    title = str(fields.get("title", "")).strip()
    horizon = str(fields.get("horizon", "")).strip()
    detail = {
        "direction": str(fields.get("stance", "—")).strip() or "—",
        "confidence": conf,
        "expression": str(fields.get("expression", "—")).strip() or "—",
        "source": "ai_plus_capture",
    }
    return Suggestion(
        advisor="tactical",
        suggestion_id=f"tactical_ai:{_slug(title)}:{as_of}",
        as_of=as_of,
        title=f"AI idea: {title}",
        subject=str(fields.get("subject", "")).strip() or "Macro",
        category="TACTICAL",
        label=cap_label_for_tier(LABEL_WATCHLIST, TIER_RESEARCH),
        decision_tier=TIER_RESEARCH,
        score=0.40,
        thesis=str(fields.get("thesis", "")).strip(),
        why_now=f"Captured from the AI Plus dialog ({as_of})" + (f" · horizon {horizon}" if horizon else ""),
        data_mode="synthetic",
        assessment=IdeaAssessment(
            confidence=conf,
            actionability="watch",
            risk_boundedness="undefined",
            data_quality="synthetic",
            notes={"data_quality": "AI-asserted hypothesis — unverified capture"},
        ),
        instrument_family="tactical",
        risk=str(fields.get("risk", "")).strip(),
        invalidation=str(fields.get("invalidation", "")).strip(),
        body_kind="tactical",
        detail=detail,
    )
