# Data Dictionary

Track raw, interim, and processed datasets in this document.

## Security reference and holdings datasets

### `security_reference`
Generated wide instrument master table. This local cache lives at `data/artifacts/portfolio_monitor/security_reference.csv`
and is derived from `configs/security_universe.csv` for reporting/risk v1.

| column | type | description |
| --- | --- | --- |
| internal_id | string | Canonical instrument ID used across the platform, formatted as `{ibkr_sec_type}:{canonical_symbol}:{primary_exchange}` for curated rows. |
| is_active | bool | Whether the row is currently active in the curated universe. |
| universe_type | string | Curated universe bucket: `ETF`, `EQ`, `FX_FUT`, `FI_FUT`, `OTHER_FUT`, `CASH`. |
| canonical_symbol | string | Canonical product or listing symbol used inside the universe. |
| display_ticker | string | Presentation ticker used in reports. |
| display_name | string | Presentation name used in reports. |
| currency | string | Quote currency. |
| primary_exchange | string | Canonical primary venue / listing exchange. |
| multiplier | float | Contract multiplier (e.g., futures point value). |
| ibkr_sec_type | string | IBKR security type alias used for lookup. |
| ibkr_symbol | string | IBKR symbol / futures family root used for lookup. |
| ibkr_exchange | string | IBKR exchange alias used for lookup. |
| ibkr_conid | string/null | Stable IBKR `conId` when known. |
| google_symbol | string/null | Google Finance lookup alias. |
| yahoo_symbol | string/null | Yahoo Finance lookup alias. |
| bbg_symbol | string/null | Bloomberg lookup alias. |
| report_category | string | Report bucket shown in HTML report (for example `DMEQ`, `FI`, `MACRO`). |
| risk_bucket | string | Risk bucket used in risk calculations: `EQ`, `FI`, `GOLD`, `CM`, `CASH`, `MACRO`. |
| mod_duration | float/null | Fixed-income duration assumption where relevant. |
| default_expected_vol | float/null | Default expected-vol assumption when no live proxy override is available. |
| price_source_provider | string/null | Preferred live price source hint. |
| price_source_symbol | string/null | Preferred live price lookup symbol. |
| fx_source_provider | string/null | Preferred FX source hint if conversion is needed. |
| fx_source_symbol | string/null | Preferred FX lookup symbol. |

Runtime-only unmatched references reuse the canonical-looking `internal_id` shape, for example
`STK:AAPL:SMART`, while outside-scope instruments still use explicit markers such as
`OUTSIDE_SCOPE:OPT:SPY:AMEX`. When IBKR ingestion encounters unmatched rows, the report workflow
writes a sibling `security_reference_PROPOSED.csv` so the user can review and merge any approved
rows into the tracked curated universe CSV.

### `position_snapshot`
Normalized portfolio positions.

| column | type | description |
| --- | --- | --- |
| as_of | datetime | Snapshot timestamp (UTC). |
| account | string | Broker account ID. |
| internal_id | string | Canonical security ID. |
| source | string | Source system for position extraction. |
| quantity | float | Position size (signed). |
| avg_cost | float/null | Average acquisition cost per unit. |
| market_value | float/null | Source-reported market value. |

### `price_snapshot`
Normalized latest prices for risk engines.

| column | type | description |
| --- | --- | --- |
| as_of | datetime | Price timestamp (UTC). |
| internal_id | string | Canonical security ID. |
| source | string | Price source (`ibkr`, etc.). |
| last_price | float | Latest usable price. |

## FX hedging datasets

### `fx_hedge_allocation`
Target FX hedge allocation for the SGD-base investor's USD AUM. JSON artifact at
`data/artifacts/portfolio_monitor/fx_hedge/fx_hedge_allocation.json` (gitignored),
produced by the FX Hedging Advisor (Risk → FX). Conventions in
[ADR 0006](../decisions/0006-fx-hedge-regression-convention.md); instruments +
parameters in `configs/portfolio_monitor/fx_hedge_advisor.yml`. Cached and reused
for ≤ `max_age_days` (30); recomputed otherwise.

Top-level fields:

| field | type | description |
| --- | --- | --- |
| schema_version | int | Artifact schema version. |
| run_date | string (date) | Date the allocation was computed; drives the 30-day cache staleness check. |
| generated_at | string (datetime) | UTC timestamp of computation. |
| base_currency | string | Investor base currency (`SGD`). |
| hedge_target_pair | string | Hedged exposure label (`USD/SGD`). |
| hedge_target_yahoo | string | Yahoo symbol for the target spot (`SGD=X`). |
| target_definition | string | Explicit statement of the regression target + hedge direction. |
| return_convention | object | `price_basis` (usd_per_unit), `frequency` (W-FRI), `overlapping`, `return_method` (log), `lookback_weeks`. |
| data_source | string | Spot source (`yahoo_finance`). |
| hedge_notional_usd | float | USD notional being hedged. |
| hedge_notional_source | string | `funded_aum_usd` / `config_default` / `explicit_cli`. |
| data_window | object | `start`, `end` (dates) and `observations` (weekly count) of the regression sample. |
| regression | object | `r_squared`, `adj_r_squared`, `alpha_weekly`, `residual_vol_annualized`. |
| legs | array | Per-instrument hedge legs (see below). |
| totals | object | Gross/net realized notional, `rounding_residual_usd`, `hedge_quality_r_squared`, `statistical_unhedged_fraction` (1−R²), `statistical_unhedged_notional_usd`, `expected_annual_carry_usd`, `expected_annual_carry_bps`. |
| on_rates_as_of | string (date) | As-of of the configured ON rates used for carry. |
| on_rates_source | string | Provenance note for the ON rates. |
| max_age_days | int | Cache staleness threshold (30). |

Per-leg fields (`legs[]`):

| field | type | description |
| --- | --- | --- |
| currency | string | Foreign currency code (`EUR`/`GBP`/`AUD`/`JPY`/`CNH`). |
| instrument | string | Display label for the CME future (e.g. `EUR/USD (6E)`). |
| futures_root | string | CME futures root symbol. |
| yahoo_symbol | string | Spot return-estimation feed (CNH leg uses `CNY=X` as a proxy). |
| beta | float | Hedge ratio: weekly-return beta of SGD/USD on this instrument. |
| beta_std_error | float | OLS standard error of `beta`. |
| t_stat | float | `beta / beta_std_error`. |
| spot_usd_per_unit | float | Latest spot in USD per 1 unit (value-in-USD basis). |
| target_notional_usd | float | `beta × hedge_notional_usd` (signed; + = long foreign / short USD). |
| contract_size | float | CME contract size. |
| contract_size_currency | string | Units of `contract_size` (foreign currency, or `USD` for the USD-sized CNH future). |
| usd_notional_per_contract | float | USD notional per contract (`contract_size × spot` for foreign-sized; fixed for USD-sized CNH). |
| target_contracts | int | Nearest whole contracts (halves away from zero); signed. |
| realized_notional_usd | float | `target_contracts × usd_notional_per_contract`. |
| residual_notional_usd | float | `target_notional_usd − realized_notional_usd` (rounding residual). |
| on_rate | float | Configured overnight rate for the currency (annualised decimal). |
| expected_annual_carry_usd | float | Indicative carry = `realized_notional × (on_rate − USD on_rate)`. |
| expiry | string (date) | Front quarterly IMM expiry (third Wednesday of Mar/Jun/Sep/Dec). |
