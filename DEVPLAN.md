# DEVPLAN

## PR Non-Negotiable
**Every PR must update DEVPLAN.md. Missing that update is a serious PR mistake.**
**During every PR, we must explicitly review what has been completed, reassess whether the current plan is still optimal, tighten or simplify the implementation plan where needed, and refresh the future roadmap before merging.**

## Process Rule
**Every PR must update DEVPLAN.md to reflect completed work, current status, and next steps.**

## Objective
Build a broker-agnostic, read-only IBKR integration layer for market monitoring and portfolio analytics, with IBKR Client Portal Web API as the primary path and clean extension points for future providers/services.

## In Scope
- Read-only provider adapters for:
  - Client Portal Web API (primary, custom wrapper)
  - TWS / IB Gateway via `ib_async` (thin wrapper only)
  - Flex Web Service (archival/reconciliation)
- Domain normalization before business logic.
- Allocation/risk/reporting services built on broker-agnostic models.
- Static HTML monitor output (non-interactive V1).

## Out of Scope
- Any order placement/cancel/modify capability in V1.
- Raw TWS socket client implementation.
- Full interactive frontend app in this phase.

## Completed
- Phase 0 guardrail docs added (`requirements`, `read_only_policy`, `provider_matrix`).
- Foundation utilities/config loading with strict read-only mode validation.
- Domain models added: account/contract/position/quote/allocation/risk/monitor view.
- Provider base protocols and fake provider test seam added.
- Runtime read-only guards added in `safety/read_only_guards.py`.
- Web API skeleton client added with read-only guard checks.
- **New in this PR:** Web API mapping utilities for account summary, positions, and quote snapshots.
- **New in this PR:** generic retry helper (`with_retry`) for transient Web API operations.
- **New in this PR:** Web API session/auth + account-summary/positions/snapshot wrappers with injectable transport seams.
- **New in this PR:** config fields and setup docs for IBKR username/password vs OAuth consumer-key usage.
- Unit tests added/expanded for config/domain/provider/safety + web API mapper/retry behavior.

## In Progress
- Wiring the new Web API wrapper to a real HTTP transport, localhost TLS handling, and stable fixture coverage.

## Next Steps
1. Add a real HTTP transport for the Web API wrapper, including localhost SSL/session ergonomics.
2. Add websocket streaming wrapper with normalized quote events.
3. Introduce Web API fixture payload sets for integration-style tests.
4. Decide whether institutional OAuth support is needed beyond the local username/password gateway path.

## Backlog / Future Phases
- Implement TWS thin adapters via `ib_async` (`client`, `portfolio`, `market_data`, `mapper`).
- Implement Flex fetch/parse/map archival flow.
- Build broker-agnostic business services (portfolio/quote/allocation/risk/monitor).
- Build HTML monitor rendering and snapshot tests.
- Add e2e workflow coverage across Web API, TWS, and Flex.

## Risks / Blockers / Assumptions
- IBKR payload/field variability (especially market-data field codes) requires robust fixtures.
- Session/auth behavior may vary by account configuration and runtime environment.
- Existing legacy modules and new provider layer will coexist temporarily during migration.
- Read-only policy must remain explicit in config + runtime guards to avoid accidental drift.

## Testing Status
- Web API wrapper smoke checks pass under `py313` for default transport, canned endpoint payloads, and retry behavior.
- Unit-test command passes under `py313`: `conda run -n py313 python -m pytest -q tests/unit/config tests/unit/domain tests/unit/providers tests/unit/test_read_only_guards.py`

## Notes
- Execution/trading support remains intentionally unimplemented.
- Plan remains incremental; unrelated repo areas were not refactored.
