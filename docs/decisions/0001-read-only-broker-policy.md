# ADR 0001: Read-only broker policy (V1)

**Status**: Accepted.

## Context

The platform is centered on IBKR for market research and portfolio analytics.
Live broker connectivity creates a risk surface (accidental order entry, API
misuse, regulatory exposure) that is not justified by V1's analytics-only
deliverables.

## Decision

V1 is strictly read-only. No order placement, cancellation, or modification
capability anywhere in the codebase.

Enforcement:
- Provider clients expose **read operations only**.
- Runtime guards validate the configured mode is `read_only`.
- Unsupported operations raise explicit `ReadOnlyViolationError`.
- Trading methods from third-party SDKs are **not** wrapped.

## Consequences

- All Flex / TWS / Client Portal adapters omit order-entry endpoints by
  construction.
- Tests + CI may safely target live endpoints without write risk.
- Trade execution can be added in a future version only through a **new
  interface** plus an explicit policy revision documented in a follow-on ADR.
