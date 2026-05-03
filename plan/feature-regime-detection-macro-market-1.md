---
goal: Deliver config-driven macro regime and market regime detection while removing legacy regime support
version: 1.0
date_created: 2026-04-30
last_updated: 2026-04-30
owner: market_helper
status: 'In progress'
tags: [feature, regime-detection, macro, market, data]
---

# Introduction

![Status: In progress](https://img.shields.io/badge/status-In%20progress-yellow)

This plan replaces the current `macro_rules + legacy_rulebook` regime v2 path with two first-class methods: `macro_regime` and `market_regime`. Both methods classify each date into the existing growth/inflation quadrant space (`Goldilocks`, `Reflation`, `Stagflation`, `Deflationary Slowdown`) and emit an orthogonal risk-on/risk-off crisis overlay. The plan removes legacy 7-regime support from active workflows, configuration, notebooks, reports, and tests.

## 1. Requirements & Constraints

- **REQ-001**: Remove active support for `legacy_rulebook` from multi-method regime detection, CLI method selection, operator scripts, docs, notebooks, and generated report examples.
- **REQ-002**: Keep only two active regime methods: `macro_regime` and `market_regime`.
- **REQ-003**: `macro_regime` must use configurable fast/slow source buckets for both `growth` and `inflation`.
- **REQ-004**: `macro_regime` default bucket weights must be `fast = 0.70` and `slow = 0.30` per axis.
- **REQ-005**: `macro_regime` must support raw signed signal aggregation without rolling z-score as the default scoring mode.
- **REQ-006**: `macro_regime` must retain configurable optional normalization modes, including `none`, `centered`, `threshold`, and `zscore`, so future research can compare raw signs against normalized signs without code changes.
- **REQ-007**: `market_regime` must derive inflation from market-implied inflation proxies, with oil price momentum as the primary default driver.
- **REQ-008**: `market_regime` must derive growth from equity, sector, commodity, credit, and rate-sensitive market proxies.
- **REQ-009**: `market_regime` must include a risk-on/risk-off overlay using volatility and stress proxies, including VIX and MOVE by default.
- **REQ-010**: All data source selection, positive/negative sign mapping, weights, transforms, lookback windows, and thresholds must be configurable through YAML files under `configs/regime_detection/`.
- **REQ-011**: Generated snapshots must include per-method axis scores, per-series driver contributions, bucket-level contributions for macro, and crisis/risk-off diagnostics for market.
- **REQ-012**: Notebook review flow must compare macro and market regimes across at least GFC, COVID, 2022 inflation, 2023 disinflation, and the latest available sample in local data.
- **CON-001**: Do not introduce trading or execution logic; the project remains read-only.
- **CON-002**: Do not require online downloads during unit tests.
- **CON-003**: Keep FRED publication-lag handling for macro data to avoid lookahead bias.
- **CON-004**: Use existing `QuadrantSnapshot`, `GrowthInflationAxes`, `MethodResult`, and `MultiMethodRegimeSnapshot` models unless a field is required for bucket diagnostics.
- **CON-005**: Do not edit unrelated dirty worktree files: `.DS_Store`, `configs/portfolio_monitor/us_sector_lookthrough.json`, or `.claude/` worktrees.

## 2. Implementation Steps

### Implementation Phase 1

- GOAL-001: Freeze the new public contract and remove legacy from active method selection.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-001 | In `market_helper/regimes/multi_method_service.py`, replace `enable_macro_rules` and `enable_legacy_rulebook` with `enable_macro_regime` and `enable_market_regime`; set both defaults to `True`; remove imports and execution branches for `LegacyRulebookMethod`. | | |
| TASK-002 | In `market_helper/workflows/generate_multi_method_regime.py`, change `ALL_METHODS` from `("macro_rules", "legacy_rulebook")` to `("macro_regime", "market_regime")`; update validation messages and missing-input messages accordingly. | | |
| TASK-003 | In `market_helper/cli/main.py`, update `regime-detect-multi`, `regime-run-report`, and `regime-refresh-report` help text so method options are `macro_regime, market_regime`; remove user-facing references to `legacy_rulebook`. | | |
| TASK-004 | Keep old `regime-detect` deterministic v1 command only if it is explicitly marked deprecated in help text and docs; otherwise remove the command and its tests in the same change. | | |
| TASK-005 | Rename report labels in `market_helper/reporting/regime_html.py` and risk report regime sections from `macro_rules`/`legacy_rulebook` to `macro_regime`/`market_regime`. | | |

### Implementation Phase 2

- GOAL-002: Implement config-driven macro regime detection with fast/slow buckets.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-006 | Extend `market_helper/data_sources/fred/macro_panel.py::SeriesSpec` with `bucket: Literal["fast", "slow"]`, `direction: Literal["positive", "negative"]`, `neutral_level: float | None`, `threshold: float | None`, and `normalization: Literal["none", "centered", "threshold", "zscore"]`. | | |
| TASK-007 | Update `load_series_specs()`, `write_series_meta()`, and tests in `tests/unit/data_sources/test_fred_macro_panel.py` to validate and round-trip the new series fields. | | |
| TASK-008 | Replace `market_helper/regimes/methods/macro_rules.py` with `market_helper/regimes/methods/macro_regime.py` or rename in place; implement `MacroRegimeConfig` with `bucket_weights={"fast": 0.70, "slow": 0.30}`, per-axis `min_available_bucket_weight`, `normalization_defaults`, and `min_consecutive_days`. | | |
| TASK-009 | Implement macro scoring as: per-series signed signal -> per-bucket weighted average -> per-axis weighted average using bucket weights -> per-axis hysteresis -> quadrant. Default signal is raw signed value after transform and direction mapping, not z-score. | | |
| TASK-010 | Preserve optional z-score scoring by moving `_rolling_zscore()` into a reusable normalizer selected only when a series or config sets `normalization: zscore`. | | |
| TASK-011 | Update `configs/regime_detection/fred_series.yml` to include fast/slow buckets and explicit direction mapping for every series. | | |
| TASK-012 | Add macro defaults: inflation fast bucket includes `T5YIFR`, `T10YIE`, `oil_yoy_or_energy_proxy` if available from market data, `AHETPI`; inflation slow bucket includes `CPIAUCSL`, `CPILFESL`, `PCEPI`, `PCEPILFE`, `CORESTICKM159SFRBATL`. | | |
| TASK-013 | Add macro defaults: growth fast bucket includes `PAYEMS`, `UNRATE` inverted, `RSAFS`, `ICSA` inverted if added, `USSLIND`; growth slow bucket includes `INDPRO`, real GDP if added, corporate profits if added, and other quarterly/slow indicators only if publication lag is configured. | | |
| TASK-014 | Add unit tests in `tests/unit/regimes/test_macro_regime.py` for fast bucket dominance, slow bucket contribution at 30%, raw sign classification, optional z-score parity, missing bucket behavior, and all four quadrants. | | |

### Implementation Phase 3

- GOAL-003: Implement market regime detection from price-based signals and a risk-on/risk-off overlay.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-015 | Add `configs/regime_detection/market_regime.yml` with top-level sections `growth`, `inflation`, `risk_overlay`, `data_sources`, `normalization`, and `hysteresis`. | | |
| TASK-016 | Add `market_helper/data_sources/yahoo_finance/market_panel.py` or an equivalent service that downloads/caches adjusted close prices for configured Yahoo tickers and writes `data/interim/market_regime/market_panel.feather`. | | |
| TASK-017 | Add `market_helper/regimes/methods/market_regime.py` implementing `MarketRegimeMethod` that consumes the market panel and YAML config and emits `MethodResult`. | | |
| TASK-018 | Implement market transforms: `return_1m`, `return_3m`, `return_6m`, `return_12m`, `relative_return`, `spread`, `level_zscore`, `change_zscore`, and `realized_vol_zscore`. | | |
| TASK-019 | Configure market inflation defaults: `USO` or `CL=F` oil momentum positive to inflation, `DBE` energy basket positive to inflation, `GLD` optional positive to inflation fear, `TIP/IEF` or breakeven ETF proxy positive to inflation expectations where usable. | | |
| TASK-020 | Configure market growth defaults: `SPY`, `QQQ`, `IWM`, `XLY`, `XLK`, `XLI`, `XLF`, `HYG/LQD`, copper proxy `CPER` or `HG=F`, broad commodity `DBC`, and cyclicals-vs-defensives spreads such as `XLY/XLP`, `XLI/XLU`, `XLK/XLU`. | | |
| TASK-021 | Configure negative growth defaults: `TLT` outperformance versus `SPY` as defensive growth-negative evidence, `UUP` dollar strength as growth-negative evidence when enabled, and widening credit spreads proxied by `HYG/LQD` weakness. | | |
| TASK-022 | Configure risk overlay defaults: VIX `^VIX`, MOVE `^MOVE`, credit stress `HYG/LQD`, high-yield OAS if available from FRED, equity drawdown from `SPY`, and treasury flight-to-quality from `TLT/SPY`. | | |
| TASK-023 | Implement risk overlay output as `crisis_flag`, `crisis_intensity`, and diagnostics `risk_regime = "risk_on" | "risk_off" | "neutral"`, with configurable enter/exit thresholds and hysteresis. | | |
| TASK-024 | Use z-score normalization as the default for market signals because price returns and volatility levels are not naturally comparable; keep `raw_sign` available per signal for explicit binary momentum rules. | | |
| TASK-025 | Add unit tests in `tests/unit/regimes/test_market_regime.py` for growth/inflation sign mapping, z-score normalization, relative-return spreads, risk-off trigger, hysteresis exit, missing ticker handling, and JSON serialization. | | |

### Implementation Phase 4

- GOAL-004: Update workflows, scripts, generated artifacts, and reports to use the new methods.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-026 | Add a market data sync workflow `market_helper/workflows/sync_market_regime_panel.py` and CLI command `market-regime-sync` with `--config`, `--cache-dir`, `--start-date`, `--end-date`, `--force`, and `--period` arguments. | | |
| TASK-027 | Update `market_helper/workflows/run_regime_report.py` so `regime-refresh-report` refreshes FRED macro data and market price data, not legacy returns/proxy JSON inputs. | | |
| TASK-028 | Update `scripts/run_regime_detection.sh` and `scripts/run_fred_sync.sh`; add `scripts/run_market_regime_sync.sh` if operator workflow needs a standalone market-panel refresh. | | |
| TASK-029 | Change default artifact paths to `data/artifacts/regime_detection/regime_snapshots.json`, `data/interim/fred/macro_panel.feather`, and `data/interim/market_regime/market_panel.feather`. | | |
| TASK-030 | Update report rendering to show two method cards: Macro Regime and Market Regime; show macro fast/slow bucket contribution tables; show market growth/inflation/risk overlay driver tables. | | |
| TASK-031 | Update policy resolution to consume the ensemble quadrant and risk overlay without assuming a legacy native label. | | |
| TASK-032 | Remove or quarantine old generated examples that mention `legacy_rulebook`; do not delete raw local data files unless the user explicitly approves. | | |

### Implementation Phase 5

- GOAL-005: Update notebooks and validation documentation.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-033 | Replace `notebooks/regime_detection/regime_v2_sanity_review.ipynb` text and code so it runs `macro_regime` and `market_regime`, not `macro_rules` and `legacy_rulebook`. | | |
| TASK-034 | Add notebook cells that display macro fast/slow bucket scores by axis, per-series driver contributions, and raw sign versus optional z-score comparison for macro. | | |
| TASK-035 | Add notebook cells that display market signal z-scores, relative-return spreads, risk-on/risk-off overlay, and top positive/negative drivers by date. | | |
| TASK-036 | Add validation checkpoints for GFC, COVID crash/rebound, 2022 inflation shock, 2023 disinflation, and the latest locally available date. | | |
| TASK-037 | Clear notebook outputs before commit, per repository rule. | | |
| TASK-038 | Update `DEV_DOCS/PLAN.md`, `DEV_DOCS/docs/devplans/regime_detection_devplan.md`, README regime sections, and `CLAUDE.md` method descriptions. | | |

### Implementation Phase 6

- GOAL-006: Remove legacy tests and add regression coverage for the new active system.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-039 | Delete or mark deprecated `tests/unit/regimes/test_legacy_wrapper.py`; remove `legacy_rulebook` expectations from `tests/unit/regimes/test_multi_method_service.py`, `tests/e2e/test_cli_regime_detect_multi.py`, `tests/unit/reporting/test_regime_html.py`, `tests/unit/reporting/test_risk_html.py`, and `tests/unit/cli/test_main.py`. | | |
| TASK-040 | Add CLI tests proving `--methods all` means `macro_regime,market_regime`, `--methods legacy_rulebook` fails with a clear unsupported-method message, and missing market panel errors are actionable. | | |
| TASK-041 | Add e2e fixture panels for macro and market methods that produce deterministic `Goldilocks`, `Reflation`, `Stagflation`, and `Deflationary Slowdown` outcomes without network calls. | | |
| TASK-042 | Run `pytest tests/unit/regimes tests/unit/data_sources/test_fred_macro_panel.py tests/unit/cli/test_main.py tests/e2e/test_cli_regime_detect_multi.py` and fix all failures. | | |
| TASK-043 | Run full `pytest tests/unit` after targeted tests pass. | | |

## 3. Alternatives

- **ALT-001**: Keep `legacy_rulebook` as a hidden third method. Rejected because the current product direction is to stop supporting legacy and focus implementation energy on macro and market regime detection.
- **ALT-002**: Keep macro as z-score-only. Rejected because macro transformed data such as YoY growth, inverted unemployment change, and inflation expectations often has interpretable sign semantics; raw signed scoring must be the default for this method.
- **ALT-003**: Use raw signs for market signals. Rejected as the default because ETF returns, commodity returns, volatility levels, and credit spreads have different scales; market method needs z-score or percentile normalization by default, with raw sign only for explicitly configured momentum rules.
- **ALT-004**: Put macro and market definitions into one YAML file. Rejected for initial implementation because macro data and market price data have different source, cache, transform, and freshness semantics.
- **ALT-005**: Hard-code ticker lists in Python. Rejected because the user explicitly requires configurable source lists and sign mapping.

## 4. Dependencies

- **DEP-001**: Existing FRED macro panel code in `market_helper/data_sources/fred/macro_panel.py`.
- **DEP-002**: Existing Yahoo Finance client in `market_helper/data_sources/yahoo_finance/client.py`.
- **DEP-003**: Existing regime models in `market_helper/regimes/axes.py`, `market_helper/regimes/methods/base.py`, and `market_helper/regimes/models.py`.
- **DEP-004**: Existing HTML report renderer in `market_helper/reporting/regime_html.py`.
- **DEP-005**: Existing quadrant policy in `market_helper/suggest/quadrant_policy.py`.
- **DEP-006**: `pandas`, `numpy`, and `PyYAML`, already present in the project environment.

## 5. Files

- **FILE-001**: `market_helper/regimes/multi_method_service.py` - active method orchestration.
- **FILE-002**: `market_helper/regimes/methods/macro_regime.py` - new or renamed macro method implementation.
- **FILE-003**: `market_helper/regimes/methods/market_regime.py` - new market method implementation.
- **FILE-004**: `market_helper/regimes/methods/legacy_rulebook.py` - remove from active imports; delete only after tests and compatibility decision are complete.
- **FILE-005**: `market_helper/data_sources/fred/macro_panel.py` - macro series config schema and metadata.
- **FILE-006**: `market_helper/data_sources/yahoo_finance/market_panel.py` - new cached market panel builder.
- **FILE-007**: `market_helper/workflows/generate_multi_method_regime.py` - method selection and input loading.
- **FILE-008**: `market_helper/workflows/run_regime_report.py` - refresh/run report orchestration.
- **FILE-009**: `market_helper/workflows/sync_market_regime_panel.py` - new market data sync workflow.
- **FILE-010**: `market_helper/cli/main.py` - CLI help and dispatch.
- **FILE-011**: `market_helper/reporting/regime_html.py` - report labels and driver tables.
- **FILE-012**: `configs/regime_detection/fred_series.yml` - macro method config.
- **FILE-013**: `configs/regime_detection/market_regime.yml` - market method config.
- **FILE-014**: `notebooks/regime_detection/regime_v2_sanity_review.ipynb` - review notebook.
- **FILE-015**: `DEV_DOCS/PLAN.md` - project plan summary.
- **FILE-016**: `DEV_DOCS/docs/devplans/regime_detection_devplan.md` - regime devplan.
- **FILE-017**: `README.md` - user-facing regime workflow.
- **FILE-018**: `CLAUDE.md` - repo agent guidance.

## 6. Testing

- **TEST-001**: Unit test macro fast/slow weighting: fast bucket must contribute 70% and slow bucket 30% under default config.
- **TEST-002**: Unit test macro raw-sign mode: positive growth and negative inflation must classify as `Goldilocks` without z-score.
- **TEST-003**: Unit test macro optional z-score mode: a late positive spike must produce a positive axis score.
- **TEST-004**: Unit test market growth proxies: `SPY`, `QQQ`, and cyclicals outperforming defensives must produce positive growth.
- **TEST-005**: Unit test market inflation proxies: oil/energy momentum must produce positive inflation.
- **TEST-006**: Unit test market risk overlay: VIX and MOVE above configured enter thresholds must produce `crisis_flag=True` and `risk_regime="risk_off"`.
- **TEST-007**: Unit test market risk overlay exit hysteresis: risk-off must persist until exit thresholds are met for the configured number of days.
- **TEST-008**: CLI test unsupported legacy method: `--methods legacy_rulebook` must return exit code `2` and mention supported methods.
- **TEST-009**: E2E test `regime-detect-multi --methods all` using fixture macro and market panels writes snapshots with exactly `macro_regime` and `market_regime`.
- **TEST-010**: Report test ensures rendered HTML contains Macro Regime, Market Regime, fast/slow buckets, and risk-on/risk-off diagnostics.

## 7. Risks & Assumptions

- **RISK-001**: Macro raw-sign scoring can overweight indicators whose transformed values have persistent sign bias. Mitigation: require explicit `neutral_level`, `threshold`, or `direction` in config and keep optional z-score mode.
- **RISK-002**: Market proxies can encode both growth and inflation simultaneously, especially oil and broad commodities. Mitigation: allow the same ticker to appear under both axes with different transforms and weights, and expose driver-level diagnostics.
- **RISK-003**: Yahoo ticker availability varies for futures symbols such as `CL=F`, `HG=F`, and `^MOVE`. Mitigation: config must support ETF fallbacks such as `USO`, `CPER`, and cached local fixtures.
- **RISK-004**: Removing legacy can break old reports or notebooks that read existing snapshot JSON. Mitigation: update report loaders to fail with an explicit migration message for legacy-only payloads.
- **RISK-005**: Current ensemble alignment requires all methods to share common dates. Market data is daily, macro is release/forward-filled business daily; tests must verify date alignment after both panels are built.
- **ASSUMPTION-001**: The active product target is U.S. macro/market regime detection.
- **ASSUMPTION-002**: Default macro fast/slow weights are 70/30 per axis and must be configurable.
- **ASSUMPTION-003**: Macro defaults can start with FRED data already available or easily added through the existing FRED loader.
- **ASSUMPTION-004**: Market defaults can start with Yahoo Finance tickers and local cache, with FRED HY OAS optional for credit stress.

## 8. Related Specifications / Further Reading

[Regime Detection Devplan](/Users/kelvin/git_projects/market_helper/DEV_DOCS/docs/devplans/regime_detection_devplan.md)

[Project Plan](/Users/kelvin/git_projects/market_helper/DEV_DOCS/PLAN.md)

[FRED Series Config](/Users/kelvin/git_projects/market_helper/configs/regime_detection/fred_series.yml)

[Regime Review Notebook](/Users/kelvin/git_projects/market_helper/notebooks/regime_detection/regime_v2_sanity_review.ipynb)
