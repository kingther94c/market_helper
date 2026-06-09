"""Trade Advisor dashboard surface (`/advisor`).

The second parallel product line (see ADR 0008 / 0009). The **v2 cockpit**: four
purpose-built module tabs, each owning its inputs (no global panel, no single Run).
Split by responsibility:

- `inputs`  — bounded option inputs + pure context builders + universe loader (unit-tested).
- `cards`   — idea cards, per-body detail builders/renderers, what-if, inbox (Option + Tactical).
- `ai_pane` — the reusable read-only AI Plus dialog any module embeds.
- `modules/`— the four module surfaces (option · fx_hedge · tactical · roll).
- `page`    — `register_trade_advisor_page` + the `/advisor` lifecycle (the 4-tab shell).

Only `register_trade_advisor_page` is public.
"""

from market_helper.presentation.dashboard.pages.trade_advisor.page import register_trade_advisor_page

__all__ = ["register_trade_advisor_page"]
