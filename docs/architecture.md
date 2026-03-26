# Architecture

High-level package layout and workflow ownership for market_helper.

## Position + Price ingestion (IBKR)

To support risk calculations we add a thin integration boundary under `market_helper/portfolio`:

- `security_reference.py`: canonical **security reference table** for instrument metadata and cross-source ID mapping.
- `ibkr.py`: normalization helpers that transform IBKR position/price payloads into internal snapshots.

### Canonical model

1. **SecurityReference** (one row per internal instrument)
   - `internal_id`, `asset_class`, `symbol`, `currency`, `exchange`, `multiplier`, `metadata`
2. **SecurityMapping** (many rows per internal instrument)
   - `(source, external_id) -> internal_id`
   - examples: `ibkr conId`, `bbg ticker`, `yahoo symbol`
3. **PositionSnapshot**
   - normalized holdings at an `as_of` timestamp
4. **PriceSnapshot**
   - normalized latest price at an `as_of` timestamp

### Ingestion flow

1. Pull positions from IBKR API (stocks, ETFs, futures).
2. For each IBKR contract:
   - resolve `ibkr:con_id` in security mapping table;
   - if missing, create a new `SecurityReference` + `SecurityMapping` row.
3. Pull latest prices from IBKR market data.
4. Resolve conId to `internal_id`, then emit `PriceSnapshot`.
5. Join position snapshots with latest prices before risk calculations.

This design keeps broker-specific details at the edge and gives downstream risk logic one unified security ID.
