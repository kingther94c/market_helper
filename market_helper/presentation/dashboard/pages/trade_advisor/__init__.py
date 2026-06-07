"""Trade Advisor dashboard surface (`/advisor`).

The second parallel product line (see ADR 0008 / 0009). A multi-module advisory
**cockpit** (Option Strategy / FX Carry / Tactical Trade Ideas / Roll & Carry
Calendar tabs over one bounded-input run). Split by responsibility:

- `inputs`  — bounded input set + pure context builders (unit-tested).
- `cards`   — idea cards, per-body detail builders/renderers, what-if, inbox.
- `cockpit` — shared inputs → one run → the four module tabs (+ Tactical AI brief).
- `page`    — `register_trade_advisor_page` + the `/advisor` lifecycle.

Only `register_trade_advisor_page` is public.
"""

from market_helper.presentation.dashboard.pages.trade_advisor.page import register_trade_advisor_page

__all__ = ["register_trade_advisor_page"]
