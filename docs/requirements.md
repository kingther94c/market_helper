# Requirements

## Product Goal
Create a read-only IBKR integration layer for monitoring and portfolio analytics, prioritizing the IBKR Client Portal Web API while keeping business logic broker-agnostic.

## Functional Requirements
1. Read accounts, positions, account summary, and market quotes.
2. Support three provider paths:
   - Client Portal Web API (primary)
   - TWS/IB Gateway via `ib_async` (thin adapter only)
   - Flex Web Service (archival/report ingestion)
3. Normalize provider payloads into internal domain models before analytics/reporting.
4. Compute allocation and risk metrics using normalized models.
5. Generate static HTML monitoring output.

## Non-Functional Requirements
- Python >= 3.13.
- Typed interfaces and focused modules.
- Read-only safety checks must be explicit.
- Tests should run without live broker connectivity by default.

## Delivery Strategy
Use phased, incremental implementation with test coverage added in each phase and synchronized updates to `DEVPLAN.md`.
