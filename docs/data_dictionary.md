# Data Dictionary

Track raw, interim, and processed datasets in this document.

## Security reference and holdings datasets

### `security_reference`
Canonical instrument master table.

| column | type | description |
| --- | --- | --- |
| internal_id | string | Canonical instrument ID used across the platform. |
| asset_class | string | Normalized class (`stk`, `etf`, `future`, etc.). |
| symbol | string | Display symbol (root symbol where relevant). |
| currency | string | Quote currency. |
| exchange | string | Primary venue or routing exchange. |
| description | string | Optional local symbol / description. |
| multiplier | float | Contract multiplier (e.g., futures point value). |
| metadata | json | Source-specific metadata. |

### `security_mapping`
Cross-source mapping table.

| column | type | description |
| --- | --- | --- |
| source | string | Data/provider source (`ibkr`, `bbg`, `yahoo`). |
| external_id | string | Source-native instrument identifier. |
| internal_id | string | Canonical ID referencing `security_reference.internal_id`. |

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
