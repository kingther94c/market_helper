# Market Helper

先从 **data utility** 开始，不急着做完整 regime engine。

This repository now provides a Python utility module to source free/open market and macro data for later regime work.

## Current scope (Phase 1: Data Utility)

- Source ETF prices from **Yahoo Finance**
- Source yields / inflation / growth / jobs data from **FRED**
- Expose reusable utility functions and a snapshot helper

## File

- `data_utility.py`

## Data coverage

### Yahoo Finance (prices)
Default ETF universe includes:
- SPY, QQQ, IWM, EFA, EEM
- TLT, IEF, LQD, HYG
- GLD, USO, DBC
- XLE, XLK, XLF

### FRED (macro)
- Bond/yield/curve: `DGS10`, `DGS2`, `T10Y2Y`, `DFF`
- Inflation: `CPIAUCSL`, `CPILFESL`, `PCEPI`, `PCEPILFE`, `T5YIE`
- Growth/jobs: `GDPC1`, `INDPRO`, `PAYEMS`, `UNRATE`, `RSAFS`

## Quick start

```bash
python data_utility.py
```

This prints a simple snapshot with:
- latest ETF prices
- latest bond/curve values
- latest inflation values
- latest growth/jobs values

## Main utility functions

- `fetch_yahoo_price_history(symbol, start, end, interval)`
- `fetch_yahoo_latest_prices(symbols)`
- `fetch_fred_series(series_id, start, end)`
- `fetch_fred_latest(series_ids)`
- `get_common_market_snapshot()`

## Next

After this utility layer is stable, next step can be:
- cleaning/alignment utilities (frequency alignment, missing handling)
- simple derived features (YoY inflation, 3m trend, curve slope changes)
- then regime rulebook layer on top
