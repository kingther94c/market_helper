# Current Plan

Active initiatives only. Future work lives in [`backlog.md`](backlog.md).
Track-level architecture detail lives in
[`../docs/architecture/devplans/`](../docs/architecture/devplans/). Cold
context is in `memory/archive/` (gitignored, not read by default).

## Portfolio Monitor

**State**: stable. No near-term scope open.

Recent landed work (one-liners; full detail in
`memory/archive/landed/portfolio_monitor_landed.md`):
- Combined report restructured (slim KPI strip, single regime section).
- Performance overview + benchmark comparison vs cash + SPY (USD/SGD).
- FX history coverage fix (`DEFAULT_YAHOO_FX_PERIOD` `2y` → `max`).
- EQ lookthrough redesign (per-symbol country mix, DM/EM taxonomy).
- Sector benchmark switched SPY → ACWI.
- Country × Sector heatmap (with amber approximate disclaimer).
- Actionable warning surface complete — `pm-error` banners with inline
  "Run Flex Refresh" / "Refresh Benchmark Cache" buttons.
- Env-first secret resolution end-to-end + Windows agent-shell ROOT
  inheritance auto-recovery in `market_helper.config.local_env`.
- Architectural route confirmed (no separate snapshot/Playwright pipeline —
  see ADR 0002).

Further portfolio-monitor work rotates in through [`backlog.md`](backlog.md)
as discrete asks land.

## Regime Engine

**State**: calibrated through Q8 (macro-axis grid). Engine + concept
aggregation + symmetric tanh + beta-adjusted returns + label hysteresis +
anchor-period sanity harness + auto-sync + historical baseline + per-
frequency decay all landed. See `memory/archive/landed/regime_engine_landed.md`
and `data/research_artifacts/` for the calibration record.

Open near-term work:

1. **Direction-honest velocity layer (Q9 candidate)**
   The engine's YoY + threshold scoring is structurally level-based: it
   cannot read "inflation is falling toward target" as Down while CPI YoY
   is still above 2.5%. Add a MoM-velocity or 6m-change transform / concept
   to capture the **direction** axis alongside the existing **level** axis.
   - Pick the transform (probably `mom_zscore_*` or `change_6m` normalization).
   - Add a "velocity" concept to `inflation_concepts:` with a modest blend
     weight vs the existing level concepts.
   - Calibration: help 2022-H2 → 2023 disinflation without breaking
     2022-H1 (YoY still rising)?
   - Run as Q9 grid against existing macro anchors + new ones from
     `macro_scout_after.json`.

2. **(Optional)** Pin per-anchor macro fixtures from `macro_scout_after.json`
   into the anchor-period harness for a CI guardrail on the macro layer.
   Not blocking — the full-history macro scout is the offline measurement
   harness today.

3. **Standing guardrail** — Keep ML layers (`macro_truth_ml`,
   `return_truth_ml`) unavailable / zero-weight until model artifacts and
   feature schemas are explicit. Do not emit fake ML outputs.

Detail: `docs/architecture/devplans/regime_engine.md`.

## Repository governance

Canonical layered-memory layout landed in ADR
[0003](../docs/decisions/0003-layered-memory-canonical-homes.md). See
[`AGENTS.md`](../AGENTS.md) for governance rules and reading order.
