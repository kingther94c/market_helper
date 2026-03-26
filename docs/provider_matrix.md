# Provider Matrix

| Provider Path | Primary Use | V1 Status | Notes |
|---|---|---|---|
| IBKR Client Portal Web API | Accounts/positions/quotes/session + streaming | In progress | Main custom integration focus |
| TWS / IB Gateway via `ib_async` | Live position-report reads from local TWS / IB Gateway | In progress | Thin adapter added for read-only live report generation |
| Flex Web Service | Reports/archive/reconciliation ingestion | Planned | Not a real-time data path |

## Shared Constraints
- Provider code must map payloads into internal domain models.
- Business services must remain broker-agnostic.
- Read-only guardrails apply to all providers.
