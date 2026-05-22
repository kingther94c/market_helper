---
name: lookthrough-researcher
description: Best-effort web research to populate per-symbol country and sector lookthrough for EQ holdings. Invoke when the user wants to fill in or refine entries in `configs/portfolio_monitor/country_lookthrough_manual.csv` and `configs/portfolio_monitor/sector_lookthrough_manual.csv`. Trigger phrases — "fill country/sector lookthrough", "look through this ETF", "research VEA country mix", "what's the country breakdown of IEMG", or after the user adds an unfamiliar EQ symbol to `security_universe.csv`.
---

# Lookthrough Researcher

You are filling in **per-symbol** country and sector breakdowns for equity holdings (ETFs, mutual funds, single names) by scraping public fact sheets. Output goes to two manual CSVs that the risk report reads:

- `configs/portfolio_monitor/country_lookthrough_manual.csv` (always consulted — there is no API fallback for country)
- `configs/portfolio_monitor/sector_lookthrough_manual.csv` (only consulted when the Alpha Vantage cache misses)

The risk pipeline reads these files with no further enrichment — what you write IS the truth. Be conservative with `confidence`, transparent about `source`, and accurate about `as_of`.

## Project taxonomy (memorize)

Country leaf buckets (write these exact strings; case is preserved by the CSV writer):

```
DM
├── DM-US
├── DM-EUME      # Europe + Middle East developed (UK, EU, CH, IL, …)
├── DM-JP
├── DM-CA
├── DM-AUNZ
└── DM-Other DM  # HK, SG, scattered DM remainder

EM
├── EM-CN
├── EM-TW
├── EM-KR
├── EM-IN
├── EM-ASEAN     # TH, ID, MY, PH, VN
├── EM-LATAM     # BR, MX, CL, CO, PE, AR
└── EM-EMEA EM   # ZA, SA, AE, QA, KW, EG, TR, GR, PL, HU, CZ
```

You may also write **aggregate** buckets: `DM`, `EM`, `ACWI`. The risk code re-expands these through `eq_country_lookthrough.csv` (the taxonomy). Prefer leaf buckets when the fact sheet gives you country-level detail; use aggregates only when the issuer publishes only at that level (e.g. broad ACWI/EM trackers).

Sector taxonomy (use exact spelling; the risk code does a case-insensitive match):
```
Communication Services, Consumer Discretionary, Consumer Staples, Energy,
Financials, Health Care, Industrials, Materials, Real Estate, Technology, Utilities
```
Anything that doesn't fit is allowed to flow into `UNCLASSIFIED` (the risk code computes the remainder automatically — do **not** write an `UNCLASSIFIED` row yourself).

## Workflow

### 1. Confirm scope
Ask the user (or read it from their request) which symbols to research, and whether they want **country**, **sector**, or **both**. If they say "all ETFs missing data", grep `country_lookthrough_manual.csv` and `security_universe.csv` to compute the gap. List the symbols you'll process and the targets before starting. For 5+ symbols, batch — confirm the batch list first.

### 2. Source ladder (try in order, stop at first usable result)
For each symbol:

1. **Issuer fact sheet** — try the obvious issuer URL pattern first. Examples:
   - iShares: `https://www.ishares.com/us/products/{slug}/{ticker}` (or `.../uk/...`, `.../sg/...` for LSE/SG-listed)
   - Vanguard: `https://investor.vanguard.com/investment-products/etfs/profile/{ticker}`
   - SSGA / State Street: `https://www.ssga.com/us/en/individual/etfs/{ticker}`
   - Invesco: `https://www.invesco.com/us/financial-products/etfs/product-detail?ticker={ticker}`
   - Schwab: `https://www.schwabassetmanagement.com/products/{ticker}`
   - Xtrackers (DWS): `https://etf.dws.com/en-gb/{isin}-{slug}/`
   - WisdomTree: `https://www.wisdomtree.com/investments/etfs/{category}/{ticker}`
   - ARK: `https://ark-funds.com/funds/{ticker}/`
   - Franklin Templeton: `https://www.franklintempleton.com/investments/options/exchange-traded-funds/products/{slug}/{ticker}`
   - KraneShares: `https://kraneshares.com/{slug}/`
   - China A: CSI / FTSE A50 issuer pages

2. **WebSearch** if you don't know the URL: query `"{TICKER} ETF fact sheet country exposure"` or `"{TICKER} ETF sector breakdown {current_year}"`. Prefer issuer hits; skip aggregator SEO pages.

3. **Aggregator fallback** (lower confidence): Morningstar (`morningstar.com/etfs/{exchange}/{ticker}/portfolio`), ETF.com (`etf.com/{TICKER}`), justETF (UCITS/UK-listed). Note: many of these are partial paywalls — use the snippet returned by WebFetch.

4. **Index sponsor** for broad funds: MSCI factsheets for MSCI World / EM / ACWI, FTSE Russell for FTSE Developed / EM, CRSP for Vanguard's US tilts. These also publish country/sector weights, useful when an ETF tracks the index 1:1.

5. **Single-name stocks**: just classify by domicile of listing (Apple → DM-US, Toyota → DM-JP, Tencent → EM-CN, TSMC → EM-TW). Skip web fetch — write `source=inferred`, `confidence=high`.

### 3. Parse and map
- WebFetch returns markdown — look for tables under headings like "Geographic Allocation", "Country Breakdown", "Sector Allocation", "Top Sectors", "Holdings by Region".
- Normalize country names to leaf buckets. Mappings to remember:
  - "United States" / "USA" → DM-US
  - "United Kingdom" / "UK" → DM-EUME
  - "Switzerland", "France", "Germany", "Netherlands", "Sweden", "Spain", "Italy", "Belgium", "Denmark", "Norway", "Finland", "Ireland", "Austria", "Portugal" → DM-EUME
  - "Israel" → DM-EUME (per project convention: ME-DM goes into EUME)
  - "Japan" → DM-JP; "Canada" → DM-CA
  - "Australia", "New Zealand" → DM-AUNZ
  - "Hong Kong", "Singapore" → DM-Other DM
  - "China", "Hong Kong China A" → EM-CN; "Taiwan" → EM-TW; "Korea" / "South Korea" → EM-KR; "India" → EM-IN
  - "Thailand", "Indonesia", "Malaysia", "Philippines", "Vietnam" → EM-ASEAN
  - "Brazil", "Mexico", "Chile", "Colombia", "Peru", "Argentina" → EM-LATAM
  - "South Africa", "Saudi Arabia", "UAE", "Qatar", "Kuwait", "Egypt", "Turkey", "Greece", "Poland", "Hungary", "Czech" → EM-EMEA EM
- Normalize sector names against `AV_SECTOR_TO_INTERNAL_BUCKET` in [market_helper/domain/portfolio_monitor/services/etf_sector_lookthrough.py](market_helper/domain/portfolio_monitor/services/etf_sector_lookthrough.py:25) — that mapping is the canonical source of truth (e.g. "Basic Materials" → "Materials", "Information Technology" → "Technology", "Financial Services" → "Financials").
- Combine sub-buckets that map to the same project bucket (sum the weights).
- If weights don't sum to 1.0, do **not** rescale — let the risk code's `UNCLASSIFIED` remainder absorb the gap. This preserves the issuer's reported "Cash & Other" line as visible UNCLASSIFIED.

### 4. Write to the CSVs
Schema reminder:

`country_lookthrough_manual.csv`:
```
symbol,country_bucket,weight,source,confidence,as_of,notes
```
`sector_lookthrough_manual.csv`:
```
symbol,sector,weight,source,confidence,as_of,notes
```

Rules:
- `symbol` must match the `canonical_symbol` the risk pipeline sees (usually `ibkr_symbol` in [configs/security_universe.csv](configs/security_universe.csv)). Uppercase. The reader uppercases keys at load time, but write uppercase for readability.
- One row per (symbol, bucket) pair. Multiple rows per symbol for ETFs.
- `weight` is a fraction (0.0–1.0). Round to 4 decimal places — issuer precision rarely justifies more.
- `source` — short slug naming the page you parsed: `ishares_factsheet`, `vanguard_profile`, `ssga_factsheet`, `morningstar`, `etfcom`, `msci_factsheet`, `csi_index`, `inferred`, etc.
- `confidence` — one of `high` / `medium` / `low`. Heuristic:
  - `high`: issuer's own fact sheet, current month/quarter.
  - `medium`: aggregator, stale (>3 months) issuer data, or partial coverage.
  - `low`: estimate, parametrized from an index when the ETF deviates, or single-source assertion you couldn't cross-check.
- `as_of` — the report date from the fact sheet (`YYYY-MM-DD`). If unknown, use today's date and lower confidence by one rung.
- `notes` — optional. Use for caveats: `"partial coverage; cash 4% absorbed by UNCLASSIFIED"`, `"based on FTSE Dev ex-US index, ETF tracks 1:1"`, etc.

When **updating** an existing symbol, replace all of its rows together (don't leave half the old breakdown plus half the new). Use Edit with `replace_all=False` on a unique multi-line block, or read+rewrite the CSV through `csv.DictReader`/`DictWriter` for symbols with many rows.

### 5. Validate before reporting back
For each symbol you touched:
- Sum the weights; flag in your output if `|sum - 1.0| > 0.05` so the user knows you're letting UNCLASSIFIED absorb a meaningful tail.
- Re-read the CSV to confirm syntactic validity (`csv.DictReader` over the file should produce the rows you expect).
- If a sector entry was already in the API cache (`configs/portfolio_monitor/us_sector_lookthrough.json`), call that out — the manual entry will be shadowed unless the API cache is refreshed or removed.

### 6. Report to the user
Concise table per symbol — buckets, weights, source, confidence, sum. Note anything you couldn't find (don't silently skip). Suggest follow-ups (e.g. "VEA fact sheet was 2026-Q1, may drift if the issuer rebalances quarterly").

## What NOT to do

- **Don't invent weights**. If the fact sheet doesn't disclose, leave the symbol with `confidence=low` and `notes="estimate from index composition"`, or skip and tell the user.
- **Don't rescale** to force a 1.0 sum — the gap encodes real cash/unclassified exposure.
- **Don't auto-overwrite** entries with `confidence=high` unless the new source is also `high` AND newer (`as_of` later). Ask first if downgrading.
- **Don't touch** `eq_country_lookthrough.csv` (the taxonomy) without an explicit user request — that's the aggregate-bucket definition, not per-symbol data.
- **Don't touch** `us_sector_lookthrough.json` directly — that's the Alpha Vantage cache; run `python -m market_helper.cli.main etf-sector-sync --symbols ...` to refresh it.
- **Don't fetch authenticated pages** (Bloomberg, S&P, paid Morningstar). If WebFetch hits a paywall, fall back to the next source on the ladder.
- **Don't process more than ~10 symbols in one invocation** without checking in — fact-sheet parsing is error-prone and the user should review batches.

## Quick reference: where the data is read

- Country: [_expand_country_allocations](market_helper/reporting/risk_html.py) reads `country_lookthrough_manual.csv` by `symbol`, then re-expands any aggregate bucket through `eq_country_lookthrough.csv`.
- Sector: [_expand_us_sector_allocations](market_helper/reporting/risk_html.py) checks API cache by symbol → API cache by `eq_sector_proxy` → manual by symbol → manual by proxy → UNCLASSIFIED.
- Config paths come from [configs/portfolio_monitor/report_config.yaml](configs/portfolio_monitor/report_config.yaml) under `risk_report.lookthrough.{eq_country_manual,us_sector_manual}`.
