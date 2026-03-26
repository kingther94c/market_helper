# Read-Only Policy (V1)

## Mandatory Rule
V1 is strictly read-only. No order placement, cancellation, or modification capabilities are allowed.

## Enforcement
- Only read operations are exposed via provider clients.
- Runtime guards validate the configured mode is `read_only`.
- Unsupported operations raise explicit `ReadOnlyViolationError`.
- Trading methods from third-party SDKs are not wrapped in V1.

## Future Extension
Trade execution can be added in future versions only through new interfaces and explicit policy changes.
