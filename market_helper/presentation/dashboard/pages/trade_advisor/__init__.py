"""Trade Advisor dashboard surface (`/advisor`).

The second parallel product line (see ADR 0008 / 0009). Split by responsibility:

- `inputs`     — bounded input set + pure context builders (unit-tested).
- `cards`      — idea cards, body builders, what-if, results, inbox.
- `rule_based` — the deterministic advisor tab (inputs → run → cards).
- `ai`         — the opt-in AI+ synthesis tab.
- `page`       — `register_trade_advisor_page` + the `/advisor` lifecycle.

Only `register_trade_advisor_page` is public.
"""

from market_helper.presentation.dashboard.pages.trade_advisor.page import register_trade_advisor_page

__all__ = ["register_trade_advisor_page"]
