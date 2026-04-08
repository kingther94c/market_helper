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
