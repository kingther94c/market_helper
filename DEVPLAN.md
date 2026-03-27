# DEVPLAN

## PR Non-Negotiable
**Every PR must update DEVPLAN.md. Missing that update is a serious PR mistake.**
**During every PR, we must explicitly review what has been completed, reassess whether the current plan is still optimal, tighten or simplify the implementation plan where needed, and refresh the future roadmap before merging.**

## Process Rule
**Every PR must update DEVPLAN.md to reflect completed work, current status, and next steps.**

## Objective
Build a broker-agnostic, read-only IBKR integration layer for market monitoring and portfolio analytics, with IBKR Client Portal Web API as the primary path and clean extension points for future providers/services. The immediate delivery path is a reliable position-report workflow that can run from normalized snapshots, raw IBKR payloads, and live local TWS / IB Gateway sessions.

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
- Web API mapping utilities added for account summary, positions, and quote snapshots.
- Generic retry helper (`with_retry`) added for transient Web API operations.
- Web API session/auth + account-summary/positions/snapshot wrappers added with injectable transport seams.
- Config fields and setup docs added for IBKR username/password vs OAuth consumer-key usage.
- Local position-report CSV path added for normalized snapshots.
- Raw IBKR payload to CSV workflow added, including CLI support for direct report generation from IBKR JSON dumps.
- Live local Client Portal Gateway to CSV workflow added for authenticated read-only IBKR sessions.
- Executable `scripts/run_report.sh` wrapper added for snapshot, raw-IBKR, and live report runs.
- Live report path switched to TWS / IB Gateway via `ib_async`, including a thin adapter and portfolio-to-report mappers.
- Script-level live-account defaults moved to local gitignored config, with explicit `--account` override support.
- Report CSV now includes instrument metadata columns such as `con_id`, `symbol`, `local_symbol`, `exchange`, and `currency`.
- Mock e2e coverage added for the live TWS report path, including futures-shaped rows such as `ZFM6` and `ZNM6` and fixture-based CSV format assertions.
- Added a first-pass HTML risk report workflow that computes per-position historical vol (1M/3M geomean), asset-class proxy estimate vol (VIX/MOVE/GVZ/OVX), historical and estimated correlation matrices, portfolio-level risk, and allocation summary from the generated position CSV plus returns/proxy inputs.

- Implemented deterministic regime detection v1 (`market_helper/regimes`) with explicit factor computation, rulebook hysteresis/persistence, JSON snapshot models, and service orchestration for latest/full-history outputs.
- Added CLI commands `regime-detect` and `regime-report`, plus workflow wrapper and script updates for reproducible local runs.
- Integrated optional regime banner + factor-score display into the HTML risk report (`--regime`), preserving backward compatibility when regime data is absent.
- Added a separate regime policy layer (`market_helper/suggest/regime_policy.py`) mapping regime labels to risk multipliers and target asset-class tilts (suggestion only, no execution).
- Added minimal regime evaluation scaffold (`market_helper/backtest/regime_eval.py`) for basic performance/turnover metrics on regime-conditioned targets.
- Added unit/e2e tests for indicator transforms, rulebook hysteresis/mutual exclusivity, policy mapping, CLI dispatch, and CLI regime output schema.
- Added example configs: `configs/regime_config.example.yml` and `configs/regime_policy.example.yml`.
- Unit tests added and expanded across config, domain, providers, portfolio normalization, reporting, workflows, and read-only guard behavior.

## In Progress
- Tightening the live TWS / `ib_async` report path with better account metadata, richer report fields, stronger session ergonomics, and eventual broader provider coverage.
- Designing a persistent instrument-master and multi-source symbology mapping layer that can support IBKR, Yahoo Finance, Google Finance, Bloomberg, and manual overrides without leaking provider-specific IDs into downstream business logic.
- Hardening the new risk HTML workflow with richer asset-class bucketing, better derivatives treatment, and live market proxy ingestion.

## Next Steps
1. Add a persistent instrument master store for `security_reference` and `security_mapping` so mappings survive across runs.
2. Expand `security_mapping` beyond `(source, external_id)` to include concepts such as `id_type`, mapping level, mapping method, and confidence.
3. Split derivative symbology into family-level and contract-level mapping so cases like IBKR `ZNM6` vs Bloomberg `TYM6 Comdty` can resolve through a shared canonical futures family plus expiry.
4. Add tracked alias/rule files for common cross-vendor symbology, especially futures root-symbol differences across IBKR, Bloomberg, and Yahoo.
5. Add local manual-override files for account-specific or still-unverified mappings that should not be committed.
6. Add a resolver service that applies mappings in a strict order: strong provider IDs first, then manual overrides, then deterministic rules, then low-confidence heuristics.
7. Add clearer connection diagnostics and account-selection ergonomics for live TWS / IB Gateway runs.
8. Replace heuristic asset-class inference in risk reporting with mapping-driven classification (especially for futures/options).
9. Add data-library loaders for benchmark proxies (VIX/MOVE/GVZ/OVX) and historical return time series so risk metrics are sourced automatically.
10. Extend risk decomposition from simple weight*vol contributions to covariance-consistent marginal/component risk attribution.
11. Close the gap from the current flat CSV + HTML report to the two-sheet target workbook format in `outputs/reports/target_report.xlsx`.
12. Add fixture sets from real IBKR payloads to harden compatibility.
13. Optionally add a broader Client Portal Web API wrapper layer if we need more endpoints beyond position reporting.

## Instrument Mapping Plan
- Keep `internal_id` as a system-owned canonical key; do not let Yahoo, Bloomberg, Google, or IBKR identifiers become the system primary key.
- Treat ETF and stock mappings as mostly direct instrument aliases, but treat futures, options, and other derivatives as two-layer mappings: product family first, concrete contract second.
- Use strong provider-native IDs when available, especially IBKR `conId`, and store weaker vendor tickers as aliases rather than as the canonical identity.
- For derivatives, normalize and persist fields such as root symbol, local symbol, expiry, exchange, currency, multiplier, and other contract metadata needed to reconcile vendor naming differences.
- Store common cross-vendor futures symbology knowledge, such as IBKR-vs-Bloomberg root-symbol differences, in tracked rules rather than one-off code branches.
- Keep local, provisional, or account-specific mapping exceptions in gitignored override files until they are verified and worth promoting into tracked shared rules.

## Target Report Gap
- Current output is a single flat CSV with 16 columns, while `outputs/reports/target_report.xlsx` is a structured workbook with at least two sheets: `Position` and `Risk`.
- The `Position` sheet includes presentation-oriented portfolio sections and summaries that we do not compute yet, including AUM blocks, bucket totals such as `EQ`, `FI`, `GOLD`, `CM`, `CASH`, and allocation views such as `Dollar Allocation`.
- The `Position` sheet expects richer analytics columns than the current CSV, including display `Ticker`, display `Name`, `Multiplier`, `Exposure(USD)`, normalized instrument `Type`, duration-based fixed-income exposure fields, `FX`, `Expected Vol`, and `Vol Contribution`.
- The current report has raw `market_value`, `cost_basis`, and `weight`, but it does not yet compute target-style risk decomposition, cross-asset bucket rollups, or derivative-equivalent exposure transformations for futures and options.
- The current report does not yet distinguish between provider symbol fields and final presentation tickers such as `US`, `LON:SPYL`, or other venue-prefixed display codes expected by the target workbook.
- The `Risk` sheet in the target workbook introduces an additional analytics layer that we do not produce yet: market regime/risk indicators like `VIX`, `MOVE`, `GVZ`, `OVX`, trailing-window averages, estimated/tail levels, and portfolio risk-attribution summaries under different correlation assumptions.
- The target workbook is not just a data export; it is a formatted report artifact with multiple sections, derived metrics, and workbook-level layout concerns. We therefore need an explicit workbook-rendering layer instead of treating the current CSV as the final output format.
- A practical delivery sequence is: stabilize instrument mapping and exposure normalization first, add bucket/risk calculations second, then implement workbook generation and formatting last.

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
- Initial report output favors correctness and inspectability over presentation polish.

## Testing Status
- Unit-test command passes under `py313`: `conda run -n py313 python -m pytest -q tests/unit`

## Notes
- Execution/trading support remains intentionally unimplemented.
- Plan remains incremental; unrelated repo areas were not refactored.

## Known Limitations (Regime v1)
- Inputs currently rely on local JSON artifacts; direct FRED pull-through adapters are not yet wired into the regime service.
- Threshold defaults are practical heuristics and require calibration/validation across longer history.
- Backtest scaffold uses simple periodic target application and does not model execution costs/slippage/futures carry.
- Risk report regime integration is intentionally lightweight (banner + scores), without regime-conditioned covariance modeling yet.

## Next Suggested PRs (Regime Track)
1. Add explicit FRED adapter wiring + cached ingestion path for VIX-like, MOVE-like, HY OAS, and Treasury yield series.
2. Add calibration notebook/tests for threshold sensitivity and persistence settings by market episode.
3. Extend policy schema with DM_EQ/EM_EQ split and defensive bucket sub-allocation overlays.
4. Expand backtest scaffold into scenario validation with walk-forward windows and robustness checks.
5. Add report panels for regime transition history and drawdown behavior by regime segment.
