"""Futures roll & carry calendar — roll reminders for held futures.

Extends the option-only Roll Reminder to **futures**, and supports **strategy
roll calendars** rather than just contract expiry:

* **Expiry schedule** (financial futures: bonds, FX, equity-index): roll a
  configurable number of days before the delivery month.
* **GSCI-like schedule** (commodities: NG, CL, …): the index methodology rolls
  the front contract in the **month prior** to delivery (≈ the 5th–9th business
  day), not at expiry — so the reminder fires on that prior-month window.

Pure + offline: it parses the held contract's month code (``NGQ26`` → Aug-2026)
and computes the roll target from config; no network, no curve feed. The
**F1/F7 deferred-carry** view is *intentionally* not fabricated — a real
front-vs-deferred basis needs a CME forward curve, which is not in-repo, so each
item carries an honest note rather than an invented carry number.

Read-only / advisory: it emits *reminders*, never orders.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # pragma: no cover - yaml is a project dependency
    import yaml
except Exception:  # pragma: no cover
    yaml = None

# CME/standard futures month codes.
MONTH_CODES = {
    "F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
    "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12,
}
_MONTH_ABBR = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
               7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}

SCHEDULE_GSCI = "gsci"
SCHEDULE_EXPIRY = "expiry"

DEFAULT_CONFIG: dict[str, Any] = {
    "default": {"schedule": SCHEDULE_EXPIRY, "roll_lead_days": 10, "roll_window_days": 14, "urgent_days": 3},
    "gsci_roll_day": 7,  # approximate GSCI roll target = ~7th day of the prior month
    "roots": {
        # Commodities roll on the GSCI-like prior-month schedule.
        "NG": {"schedule": SCHEDULE_GSCI},
        "CL": {"schedule": SCHEDULE_GSCI},
        "MCL": {"schedule": SCHEDULE_GSCI},
        # Quarterly financials roll a bit earlier before delivery.
        "ZN": {"schedule": SCHEDULE_EXPIRY, "roll_lead_days": 14},
        "ZF": {"schedule": SCHEDULE_EXPIRY, "roll_lead_days": 14},
        "ZT": {"schedule": SCHEDULE_EXPIRY, "roll_lead_days": 14},
    },
}

_DEFAULT_CONFIG_PATH = Path("configs/portfolio_monitor/futures_roll_calendar.yml")


@dataclass(frozen=True)
class FuturesRollConfig:
    default: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_CONFIG["default"]))
    gsci_roll_day: int = 7
    roots: dict[str, dict[str, Any]] = field(default_factory=dict)

    def for_root(self, root: str) -> dict[str, Any]:
        merged = dict(self.default)
        merged.update(self.roots.get((root or "").upper(), {}))
        return merged


def load_futures_roll_config(path: str | Path | None = None) -> FuturesRollConfig:
    cfg = {k: v for k, v in DEFAULT_CONFIG.items()}
    p = Path(path) if path is not None else _DEFAULT_CONFIG_PATH
    if p.exists() and yaml is not None:
        payload = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if isinstance(payload, dict):
            if isinstance(payload.get("default"), dict):
                cfg["default"] = {**DEFAULT_CONFIG["default"], **payload["default"]}
            if "gsci_roll_day" in payload:
                cfg["gsci_roll_day"] = payload["gsci_roll_day"]
            if isinstance(payload.get("roots"), dict):
                cfg["roots"] = {**DEFAULT_CONFIG["roots"], **payload["roots"]}
    return FuturesRollConfig(
        default=cfg["default"], gsci_roll_day=int(cfg.get("gsci_roll_day", 7)), roots=cfg.get("roots", {}),
    )


@dataclass(frozen=True)
class FuturesRollItem:
    root: str
    contract: str
    exchange: str
    qty: float
    schedule: str
    delivery_year: int | None
    delivery_month: int | None
    delivery_label: str
    roll_target: str | None
    days_to_roll: int | None
    label: str
    why: str
    note: str

    def as_detail(self) -> dict[str, Any]:
        return {
            "root": self.root, "contract": self.contract, "exchange": self.exchange, "qty": self.qty,
            "schedule": self.schedule, "delivery_label": self.delivery_label,
            "roll_target": self.roll_target, "days_to_roll": self.days_to_roll, "note": self.note,
        }


def parse_contract_month(root: str, contract: str) -> tuple[int, int] | None:
    """Parse a contract code's (year, month). ``NGQ26`` / ``Q26`` → (2026, 8). ``None`` if no code."""
    text = (contract or "").upper().replace(" ", "")
    root_u = (root or "").upper()
    if root_u and text.startswith(root_u):
        text = text[len(root_u):]
    if len(text) < 2 or text[0] not in MONTH_CODES:
        return None
    month = MONTH_CODES[text[0]]
    digits = "".join(ch for ch in text[1:] if ch.isdigit())
    if not digits:
        return None
    yy = int(digits[-2:]) if len(digits) >= 2 else int(digits)
    year = 2000 + yy if yy < 100 else yy
    return year, month


def _roll_target(year: int, month: int, schedule: str, cfg_root: dict, gsci_roll_day: int) -> _dt.date:
    anchor = _dt.date(year, month, 1)  # start of the delivery month
    if schedule == SCHEDULE_GSCI:
        py, pm = (year - 1, 12) if month == 1 else (year, month - 1)
        return _dt.date(py, pm, min(int(gsci_roll_day), 28))
    lead = int(cfg_root.get("roll_lead_days", 10))
    return anchor - _dt.timedelta(days=lead)


_DEFERRED_CARRY_NOTE = (
    "Deferred (F1/F7) carry needs a CME forward curve, which is not in-repo — "
    "this is a roll-timing reminder only, not a curve-basis number."
)


def compute_futures_roll(
    held_futures: list[dict],
    *,
    config: FuturesRollConfig | None = None,
    today: _dt.date | None = None,
) -> list[FuturesRollItem]:
    """Build roll reminders for each held future. Pure; ``today`` injectable for tests."""
    cfg = config or FuturesRollConfig(
        default=dict(DEFAULT_CONFIG["default"]), gsci_roll_day=DEFAULT_CONFIG["gsci_roll_day"],
        roots=dict(DEFAULT_CONFIG["roots"]),
    )
    now = today or _dt.date.today()
    items: list[FuturesRollItem] = []
    for fut in held_futures or []:
        root = str(fut.get("root", "") or "")
        contract = str(fut.get("contract", "") or "")
        cfg_root = cfg.for_root(root)
        schedule = str(cfg_root.get("schedule", SCHEDULE_EXPIRY))
        qty = float(fut.get("qty", 0.0) or 0.0)
        exchange = str(fut.get("exchange", "") or "")

        parsed = parse_contract_month(root, contract)
        if parsed is None:
            items.append(FuturesRollItem(
                root=root, contract=contract, exchange=exchange, qty=qty, schedule=schedule,
                delivery_year=None, delivery_month=None, delivery_label="?", roll_target=None,
                days_to_roll=None, label="INFO",
                why="No contract month parsed from the symbol — review the roll date manually.",
                note=_DEFERRED_CARRY_NOTE,
            ))
            continue

        year, month = parsed
        target = _roll_target(year, month, schedule, cfg_root, cfg.gsci_roll_day)
        days = (target - now).days
        urgent = int(cfg_root.get("urgent_days", 3))
        window = int(cfg_root.get("roll_window_days", 14))
        delivery_label = f"{_MONTH_ABBR.get(month, '?')} {year}"
        sched_txt = "GSCI-like prior-month roll" if schedule == SCHEDULE_GSCI else "expiry-based roll"
        if days <= urgent:
            label = "PROCEED"
            why = (f"Roll target {target.isoformat()} is {'overdue' if days < 0 else f'in {days}d'} "
                   f"({sched_txt}) — roll the {root} {delivery_label} now.")
        elif days <= window:
            label = "MONITOR"
            why = f"Roll window open: {days}d to the {target.isoformat()} target ({sched_txt})."
        else:
            label = "INFO"
            why = f"{days}d to the {target.isoformat()} roll target ({sched_txt}) — nothing due yet."
        items.append(FuturesRollItem(
            root=root, contract=contract, exchange=exchange, qty=qty, schedule=schedule,
            delivery_year=year, delivery_month=month, delivery_label=delivery_label,
            roll_target=target.isoformat(), days_to_roll=days, label=label, why=why,
            note=_DEFERRED_CARRY_NOTE,
        ))
    return items
