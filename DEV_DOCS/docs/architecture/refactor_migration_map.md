# Refactor Migration Map

This document records the pragmatic migration from the legacy module layout to the new domain-driven structure.

| Old location | New location | Action |
| --- | --- | --- |
| `market_helper/utils/time.py` | `market_helper/common/time.py` | move + compatibility shim |
| `market_helper/safety/read_only_guards.py` | `market_helper/common/read_only.py` | move + compatibility shim |
| `market_helper/config/settings.py` | `market_helper/app/settings.py` | move + compatibility shim |
| `market_helper/portfolio/security_reference.py` | `market_helper/common/models/security_reference.py` + `market_helper/domain/portfolio_monitor/services/security_reference_table.py` | split |
| `market_helper/portfolio/ibkr.py` | `market_helper/data_sources/ibkr/adapters/normalizers.py` | wrap |
| `market_helper/portfolio/client_portal.py` | `market_helper/data_sources/ibkr/client_portal/client.py` | wrap |
| `market_helper/providers/web_api/*` | `market_helper/data_sources/ibkr/adapters/client_portal.py` | wrap |
| `market_helper/providers/tws_ib_async/*` | `market_helper/data_sources/ibkr/tws/*` | wrap |
| `market_helper/regimes/*` | `market_helper/domain/regime_detection/*` | wrap + regroup |
| `market_helper/suggest/regime_policy.py` | `market_helper/domain/regime_detection/policies/regime_policy.py` | wrap |
| `market_helper/backtest/regime_eval.py` | `market_helper/domain/regime_detection/services/policy_backtester.py` | wrap |
| `market_helper/reporting/tables.py` | `market_helper/presentation/tables/portfolio_report.py` | wrap |
| `market_helper/reporting/csv_export.py` | `market_helper/presentation/exporters/csv.py` | wrap |
| `market_helper/reporting/mapping_table.py` | `market_helper/presentation/exporters/security_reference_seed.py` | wrap |
| `market_helper/reporting/risk_html.py` | `market_helper/domain/portfolio_monitor/services/risk_analysis.py` + `market_helper/presentation/html/portfolio_risk_report.py` | split facade |
| `market_helper/workflows/generate_report.py` | `market_helper/domain/portfolio_monitor/pipelines/generate_portfolio_report.py` | move + compatibility shim |
| `market_helper/workflows/generate_regime.py` | `market_helper/domain/regime_detection/pipelines/run_regime_detection.py` | move + compatibility shim |
