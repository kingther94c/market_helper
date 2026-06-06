"""Portfolio Monitor dashboard surface (`/portfolio`).

One of the two parallel product lines (see ADR 0008 / 0009). The package is
split by responsibility:

- `state`   — page/form dataclasses, constants, IBKR probing, pure helpers.
- `routes`  — sandboxed artifact-serving FastAPI routes + URL resolution.
- `actions` — input-form converters, action-status helpers, remediation.
- `views`   — the always-visible page rendering (header, tabs, report iframe).
- `drawer`  — the slide-over "Operate" panel (forms, action console, logs).
- `page`    — `register_portfolio_page` + the `/portfolio` lifecycle.

Only `register_portfolio_page` is public.
"""

from market_helper.presentation.dashboard.pages.portfolio_monitor.page import register_portfolio_page

__all__ = ["register_portfolio_page"]
