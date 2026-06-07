"""Futures Roll & Carry Calendar advisor → umbrella adapter.

Reads ``context.held_futures`` (seeded from the positions CSV) and emits a roll
reminder per held future, using the strategy-calendar engine
(``futures_roll_calendar``): commodities roll on the GSCI-like prior-month
schedule, financials on an expiry-lead schedule. No network — pure rule
evaluation. Together with the option-only Roll Reminder, this is the cockpit's
**Roll & Carry Calendar** module.
"""

from __future__ import annotations

import datetime as _dt

from market_helper.domain.portfolio_monitor.services.futures_roll_calendar import (
    compute_futures_roll,
    load_futures_roll_config,
)

from ..contracts import (
    LABEL_INFO,
    LABEL_MONITOR,
    LABEL_PROCEED,
    AdvisorContext,
    AdvisorResult,
    AuditEntry,
    Suggestion,
)

_SCORE = {"PROCEED": 0.88, "MONITOR": 0.58, "INFO": 0.30}
_LABELS = {"PROCEED": LABEL_PROCEED, "MONITOR": LABEL_MONITOR, "INFO": LABEL_INFO}


def _score(label: str, days: int | None) -> float:
    base = _SCORE.get(label, 0.30)
    if days is not None:
        base += max(0.0, (30 - min(max(days, 0), 30)) / 300.0)  # nearer the roll → higher
    return round(base, 3)


class FuturesRollPlugin:
    """Umbrella advisor for futures roll & carry-calendar reminders."""

    key = "futures_roll"
    title = "Roll & Carry Calendar"

    def produce(
        self,
        context: AdvisorContext,
        *,
        today: str | None = None,
        config_path=None,
    ) -> AdvisorResult:
        as_of = context.as_of
        futs = list(getattr(context, "held_futures", None) or [])
        if not futs:
            return AdvisorResult(
                advisor=self.key, as_of=as_of, data_mode="portfolio",
                suggestions=[Suggestion(
                    advisor=self.key, suggestion_id="futures_roll:none", as_of=as_of,
                    title="No futures positions to manage", subject="—", category="ROLL",
                    label=LABEL_INFO, thesis="No held futures were found.",
                    why_now="Load your portfolio (futures positions) to see roll reminders.",
                    body_kind="futures_roll",
                )],
                meta={"n_positions": 0},
            )
        cfg = load_futures_roll_config(config_path)
        now = _dt.date.fromisoformat(today) if today else None
        items = compute_futures_roll(futs, config=cfg, today=now)
        return AdvisorResult(
            advisor=self.key, as_of=as_of, data_mode="portfolio",
            suggestions=[self._to_suggestion(it, as_of) for it in items],
            meta={"n_positions": len(futs)},
        )

    def _to_suggestion(self, it, as_of: str) -> Suggestion:
        audit = [AuditEntry("roll_schedule", True, "info", f"{it.schedule} · target {it.roll_target or 'n/a'}")]
        if it.days_to_roll is not None:
            audit.append(AuditEntry("days_to_roll", it.label != "PROCEED", "info", f"{it.days_to_roll}d to roll target"))
        return Suggestion(
            advisor=self.key,
            suggestion_id=f"futures_roll:{it.root}:{it.contract or it.delivery_label}",
            as_of=as_of,
            title=f"Roll {it.root} {it.delivery_label}",
            subject=it.root,
            category="ROLL",
            label=_LABELS.get(it.label, LABEL_INFO),
            score=_score(it.label, it.days_to_roll),
            thesis=f"{abs(it.qty):g}x {it.root} ({it.contract or '—'}) on {it.exchange or 'exchange'} · {it.delivery_label} delivery.",
            why_now=it.why,
            rationale="Roll to the next scheduled contract per the calendar. " + it.note,
            headline_metrics={
                "qty": f"{it.qty:g}",
                "delivery": it.delivery_label,
                "to_roll": (f"{it.days_to_roll}d" if it.days_to_roll is not None else "—"),
                "schedule": "GSCI" if it.schedule == "gsci" else "expiry",
            },
            audit=audit,
            data_mode="portfolio",
            body_kind="futures_roll",
            detail=it.as_detail(),
        )
