# Refactor Blueprint (2026-03-29)

## 1) Project North Star

`market_helper` should converge to a **two-engine research and decision-support platform**:

1. **Portfolio Monitor Engine**
   - Source portfolio/account/position data from IBKR (Client Portal and/or TWS adapters).
   - Normalize and enrich positions using a curated `security_reference` table.
   - Produce portfolio-facing outputs: allocation, risk decomposition, concentration, and reporting artifacts.

2. **Regime Detection Engine**
   - Source market and macro time series (Yahoo/FRED or equivalent adapters).
   - Detect current and historical market regimes with deterministic/policy-first logic.
   - Produce regime-facing outputs: regime state dashboard, transition context, and policy tilt suggestions.

A final integration layer combines these two engines to support:
- regime-aware portfolio stress testing,
- scenario analysis,
- policy-constrained portfolio adjustment suggestions.

## 2) Product Outputs

### Portfolio Monitor outputs
- Enriched security reference table (`security_reference` as source-of-truth + operational override flow).
- Position-level normalized table with stable internal IDs and exposures.
- Portfolio report (CSV/HTML now; workbook/dashboard later) with:
  - allocation,
  - risk snapshot,
  - key diagnostics and mapping quality flags.

### Regime Detection outputs
- Regime time series with confidence/diagnostics.
- Regime dashboard oriented for “where the market is heading” interpretation.
- Policy tilt output: suggested over/under-weight asset classes when trend persistence assumptions hold.

### Combined outputs
- Regime-conditioned portfolio stress test.
- “What to change” suggestion set with policy + backtest context.

## 3) Architecture Boundaries

### A. Portfolio Monitor module
Primary package areas:
- `market_helper/portfolio`
- `market_helper/providers`
- `market_helper/reporting`
- `market_helper/workflows/generate_report.py`

Responsibilities:
- IBKR ingestion, mapping, and normalization.
- Security reference enrichment and mapping gap management.
- Portfolio analytics/report assembly.

### B. Regime Detection module
Primary package areas:
- `market_helper/regimes`
- `market_helper/data_library`
- `market_helper/workflows/detect_regimes.py`
- `market_helper/workflows/generate_regime.py`

Responsibilities:
- Market/macro data ingestion and feature transforms.
- Rulebook- and policy-based regime classification.
- Dashboard-ready regime state + trend outputs.

### C. Integration module (portfolio x regime)
Primary package areas:
- `market_helper/suggest`
- `market_helper/backtest`
- `market_helper/workflows/generate_suggestions.py`
- `market_helper/workflows/run_backtest.py`

Responsibilities:
- Policy mapping from regime -> target tilts.
- Simple backtester for validation and calibration.
- Stress/scenario and suggestion pipelines.

## 4) Shared Utility Layer (cross-engine)

Yes — a consolidated utility layer is recommended, but with strict scope boundaries.

### What should be centralized
- Pure, domain-agnostic helpers used by both engines, for example:
  - time/date/calendar helpers,
  - schema/io helpers (csv/json/parquet adapters),
  - validation/coercion helpers,
  - logging/telemetry wrappers,
  - caching/retry primitives that are provider-agnostic.

### What should stay in each engine
- Portfolio-only rules: position/exposure semantics, security-reference business logic, portfolio-specific transformations.
- Regime-only rules: factor construction, regime classification/rulebook logic, macro feature engineering.

### Placement convention
- Keep cross-engine helpers under `market_helper/utils/` and split by concern (e.g. `time.py`, `io.py`, `schema.py`, `validation.py`).
- Avoid a catch-all `helpers.py`; prefer small, intention-revealing modules.
- If a utility starts importing engine-specific models, move it back into that engine module.

### Promotion rule (to avoid premature abstraction)
A function should be promoted into shared utils only when all are true:
1. It is used in at least two modules/tracks.
2. It has no engine-specific business assumptions.
3. It has dedicated unit tests at the utility boundary.

## 5) Development Workflow (Notebook-first)

`notebooks/dev_lab/derive_sec_table.ipynb` is the current **DevLab entry point**.

Workflow contract:
1. Prototype in DevLab with representative samples.
2. Promote stable logic into package/workflow code.
3. Keep a runnable notebook example for regression-by-example.
4. Add/adjust tests to lock behavior.

Design intent:
- notebook = exploration and reproducible examples,
- library/workflow code = productionized logic,
- tests = behavior contracts.

## 6) Refactor sequencing

1. Align naming and ownership to the two-engine model.
2. Separate shared primitives (models/config/time) from engine-specific logic.
3. Standardize output schemas for monitor/regime/integration layers.
4. Introduce a minimal scenario/backtest API shared by suggestions and dashboards.
5. Tighten CLI + scripts so each engine and integration flow has one clear entrypoint.

## 7) Definition of done (refactor stage)

- Every module maps clearly to one of: Portfolio Monitor, Regime Detection, Integration.
- DevPlan is split into overall + per-module tracks.
- DevLab examples run end-to-end and correspond to workflow entrypoints.
- Core policy flow has at least one backtest validation path.
