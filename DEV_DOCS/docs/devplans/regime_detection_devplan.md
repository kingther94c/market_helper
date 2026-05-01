# Regime Detection Devplan

## Current Focus
- Stop investing in the legacy 7-regime rulebook as an active method.
- Deliver two active regime-detection approaches: `macro_regime` and `market_regime`.
- Keep the existing growth/inflation quadrant taxonomy, but make the crisis/risk overlay orthogonal and market-driven.
- Make both approaches config-driven so source lists, fast/slow buckets, sign mapping, transforms, weights, thresholds, and hysteresis can be changed without code edits.

## Near-Term Next Steps
1. Replace current `macro_rules + legacy_rulebook` defaults with `macro_regime + market_regime` across the orchestrator, CLI, workflows, reports, tests, and notebook.
2. Update macro config so growth and inflation inputs are separated into `fast` and `slow` buckets, with default bucket weights of `fast = 0.70` and `slow = 0.30`.
3. Change macro scoring default from rolling z-score to raw signed signal aggregation, while retaining configurable `zscore` normalization for research comparisons.
4. Add a market-regime config and cached market-price panel sourced from Yahoo Finance tickers.
5. Build market growth/inflation scores from ETF, sector, commodity, credit, and rate-sensitive price proxies.
6. Build market risk-on/risk-off overlay from VIX, MOVE, credit stress, drawdown, and flight-to-quality proxies.
7. Refresh the regime review notebook so it validates macro and market methods across GFC, COVID, 2022 inflation, 2023 disinflation, and latest local data.
8. Track the full implementation in `plan/feature-regime-detection-macro-market-1.md`.

## Method Targets

### Macro Regime

- Inflation fast bucket defaults: market-implied inflation expectations such as `T5YIFR` and `T10YIE`, wage pressure such as `AHETPI`, and an energy proxy if added to the macro panel.
- Inflation slow bucket defaults: `CPIAUCSL`, `CPILFESL`, `PCEPI`, `PCEPILFE`, and `CORESTICKM159SFRBATL`.
- Growth fast bucket defaults: `PAYEMS`, inverted `UNRATE`, `RSAFS`, `USSLIND`, and inverted initial claims if added.
- Growth slow bucket defaults: `INDPRO`, real GDP if added, and other quarterly slow indicators only when publication lag is explicitly configured.
- Default scoring: transformed raw value -> direction mapping -> optional neutral/threshold adjustment -> per-bucket weighted average -> 70/30 fast/slow axis score -> hysteresis -> quadrant.

### Market Regime

- Inflation defaults: oil or energy momentum (`CL=F` or `USO`, `DBE`), breakeven or inflation-sensitive proxies where reliable, and optional gold as an inflation/fear diagnostic rather than a dominant signal.
- Growth defaults: broad equity (`SPY`, `QQQ`, `IWM`), sector leadership (`XLK`, `XLY`, `XLI`, `XLF`), cyclicals versus defensives (`XLY/XLP`, `XLI/XLU`, `XLK/XLU`), copper or industrial commodity proxies (`HG=F` or `CPER`), broad commodities (`DBC`), and credit risk appetite (`HYG/LQD`).
- Risk overlay defaults: VIX, MOVE, high-yield credit stress, equity drawdown, and treasury flight-to-quality signals.
- Default scoring: rolling z-score or percentile normalization for market signals, because price returns, vol levels, spreads, and relative performance are not naturally comparable.
