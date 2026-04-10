# Architecture

High-level package layout and workflow ownership for market_helper.

## Position + Price ingestion (IBKR)

To support risk calculations we add a thin integration boundary under `market_helper/portfolio`:

- `security_reference.py`: curated CSV-backed **security reference table** for instrument metadata, report/risk assumptions, and source aliases.
- `ibkr.py`: normalization helpers that transform IBKR position/price payloads into internal snapshots.

### Canonical model

1. **SecurityReference** (one row per internal instrument)
   - curated identity: `internal_id`, `universe_type`, `canonical_symbol`, `display_ticker`, `display_name`
   - canonical ID format: `{ibkr_sec_type}:{canonical_symbol}:{primary_exchange}`
   - provider aliases: `ibkr_*`, `google_symbol`, `yahoo_symbol`, `bbg_symbol`
   - reporting assumptions: `report_category`, `risk_bucket`, `mod_duration`, `default_expected_vol`
3. **PositionSnapshot**
   - normalized holdings at an `as_of` timestamp
4. **PriceSnapshot**
   - normalized latest price at an `as_of` timestamp

### Ingestion flow

1. Pull positions from IBKR API (stocks, ETFs, futures).
2. For each IBKR contract:
   - resolve against the generated local `security_reference.csv` cache in strict order:
     - exact `ibkr_conid`
     - curated `(ibkr_symbol, ibkr_sec_type, ibkr_exchange)` alias
     - unique curated `(ibkr_symbol, ibkr_sec_type)` candidate when exchange-level matching is missing
     - curated `CASH` aliases for true cash rows
   - if `sec_type == OPT`, create a transient `OUTSIDE_SCOPE` runtime reference.
   - otherwise keep the canonical `internal_id` shape, mark the runtime row as `unmapped`, and emit a `security_reference_PROPOSED.csv` alongside the report output for human review.
   - normalization accepts either snake_case payloads (`con_id`) or IBKR-style camelCase (`conId`), including object-like rows from common IBKR wrappers.
3. Pull latest prices from IBKR market data.
4. Resolve conId to `internal_id`, then emit `PriceSnapshot`.
5. Join position snapshots with latest prices before risk calculations.

This design keeps broker-specific details at the edge, lets curated universe decisions live in tracked `security_universe.csv`, and still preserves visibility into unsupported/unmapped instruments without auto-growing the canonical universe.
