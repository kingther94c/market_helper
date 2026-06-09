"""Roll Reminder advisor — manage *existing* option positions.

Reads ``context.held_options`` (sourced from the portfolio) and flags each held
option by days-to-expiry, in/out-of-the-money, and short-ITM assignment risk,
with a roll suggestion. No chain fetch, no network — pure rule evaluation over
the held book. Emits the same :class:`~..contracts.Suggestion` shape as every
other advisor, so the UI renders it with zero advisor-specific code.
"""

from __future__ import annotations

import datetime as _dt

from ..contracts import (
    LABEL_INFO,
    LABEL_RESEARCH_READY,
    LABEL_WATCHLIST,
    TIER_OPERATIONAL,
    AdvisorContext,
    AdvisorResult,
    AuditEntry,
    IdeaAssessment,
    Suggestion,
)

_LABEL_BASE = {LABEL_RESEARCH_READY: 0.90, LABEL_WATCHLIST: 0.60, LABEL_INFO: 0.30}


def _roll_score(label: str, dte: int | None) -> float:
    base = _LABEL_BASE.get(label, 0.30)
    if dte is not None and dte >= 0:
        base += max(0.0, (30 - min(dte, 30)) / 300.0)  # nudge: nearer expiry ranks higher
    return round(base, 3)


def _dte(expiry: str | None, today: _dt.date) -> int | None:
    if not expiry:
        return None
    try:
        return (_dt.date.fromisoformat(expiry) - today).days
    except ValueError:
        return None


class RollReminderPlugin:
    """Umbrella advisor for managing held option positions."""

    key = "roll"
    title = "Roll Reminder"

    def produce(
        self,
        context: AdvisorContext,
        *,
        roll_dte: int = 21,
        urgent_dte: int = 7,
        today: str | None = None,
    ) -> AdvisorResult:
        as_of = context.as_of
        now = _dt.date.fromisoformat(today) if today else _dt.date.today()
        held = list(context.held_options or [])
        if not held:
            return AdvisorResult(
                advisor=self.key,
                as_of=as_of,
                data_mode="portfolio",
                suggestions=[
                    Suggestion(
                        advisor=self.key, suggestion_id="roll:none", as_of=as_of,
                        title="No option positions to manage", subject="—", category="ROLL",
                        label=LABEL_INFO, decision_tier=TIER_OPERATIONAL,
                        assessment=IdeaAssessment(confidence="high", actionability="parked",
                                                  risk_boundedness="defined", data_quality="recent"),
                        thesis="No held option positions were found.",
                        why_now="Load your portfolio (held options) to see roll reminders.",
                        body_kind="roll",
                    )
                ],
                meta={"n_positions": 0},
            )

        suggestions = [self._evaluate(opt, now, roll_dte, urgent_dte, as_of) for opt in held]
        return AdvisorResult(
            advisor=self.key, as_of=as_of, data_mode="portfolio",
            suggestions=[s for s in suggestions if s is not None],
            meta={"n_positions": len(held)},
        )

    def _evaluate(self, opt: dict, today: _dt.date, roll_dte: int, urgent_dte: int, as_of: str) -> Suggestion:
        underlying = str(opt.get("underlying", "?"))
        right = str(opt.get("right", "C")).upper()[:1] or "C"
        strike = float(opt.get("strike", 0) or 0)
        expiry = opt.get("expiry")
        qty = float(opt.get("qty", 0) or 0)
        und = opt.get("underlying_price")
        dte = _dte(expiry, today)
        short = qty < 0

        itm: bool | None = None
        if und is not None and strike:
            itm = (right == "C" and und >= strike) or (right == "P" and und <= strike)

        expired = dte is not None and dte < 0
        in_window = dte is not None and 0 <= dte <= roll_dte
        urgent = dte is not None and 0 <= dte <= urgent_dte
        assignment = bool(short and itm and dte is not None and 0 <= dte <= roll_dte)

        audit = [AuditEntry("dte_window", bool(in_window or expired), "info", f"{dte} DTE (roll window ≤{roll_dte})")]
        if itm is not None:
            audit.append(AuditEntry("moneyness", True, "info", f"{'ITM' if itm else 'OTM'} (underlying {und}, strike {strike:g})"))
        if assignment:
            audit.append(AuditEntry("assignment_risk", False, "soft", f"short {right} ITM with {dte} DTE — assignment risk"))

        if expired:
            label, why = LABEL_RESEARCH_READY, f"Expired ({dte} DTE) — close or roll now."
        elif assignment and urgent:
            label, why = LABEL_RESEARCH_READY, f"Short {right} ITM, {dte} DTE — high assignment risk; roll out or close."
        elif in_window:
            label, why = LABEL_WATCHLIST, f"{dte} DTE within the {roll_dte}-day roll window — consider rolling out."
        else:
            label, why = LABEL_INFO, (f"{dte} DTE — outside the roll window; nothing to do yet." if dte is not None
                                      else "No expiry parsed — review manually.")

        side = "short" if short else "long"
        metrics = {
            "dte": f"{dte}d" if dte is not None else "—",
            "qty": f"{qty:g}",
            "moneyness": ("ITM" if itm else "OTM") if itm is not None else "—",
        }
        return Suggestion(
            advisor=self.key,
            suggestion_id=f"roll:{underlying}:{right}{strike:g}:{expiry}",
            as_of=as_of,
            title=f"Roll {side} {right}{strike:g} {expiry}",
            subject=underlying,
            category="ROLL",
            label=label,
            decision_tier=TIER_OPERATIONAL,
            score=_roll_score(label, dte),
            thesis=f"{side.capitalize()} {abs(qty):g}x {underlying} {right}{strike:g} exp {expiry} ({dte} DTE).",
            why_now=why,
            rationale="Roll out to the next monthly (keep ~same delta), or close if the thesis is done.",
            headline_metrics=metrics,
            audit=audit,
            data_mode="portfolio",
            assessment=IdeaAssessment(
                confidence="high",                          # a deterministic expiry/DTE fact
                actionability="act_now" if label == LABEL_RESEARCH_READY else "watch",
                risk_boundedness="defined",                 # rolling is a known operation
                data_quality="recent",
            ),
            instrument_family="option_roll",
            invalidation=why,
            body_kind="roll",
            detail={
                "underlying": underlying, "right": right, "strike": strike, "expiry": expiry,
                "qty": qty, "dte": dte, "itm": itm, "underlying_price": und,
            },
        )
