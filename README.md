# Market Helper (Rulebook-First Regime Detection)

This project builds a **transparent, non-black-box rulebook** to classify market regime from two lenses:

1. **Macro lens** (growth + inflation fundamentals)
2. **Market lens** (1-week cross-asset price action)

It then combines both to identify the most likely current regime.

## Regime framework

We use the classic growth/inflation quadrant, with a risk-on/risk-off overlay:

- **Goldilocks**: Growth Up, Inflation Down, Risk On
- **Overheating**: Growth Up, Inflation Up, Risk On
- **Stagflation**: Growth Down, Inflation Up, Risk Off
- **Disinflation Slowdown**: Growth Down, Inflation Down, Risk Off

If risk signals disagree with the quadrant, the engine keeps the macro quadrant but adds a risk-tag in the explanation.

## Rulebook design principles

- Deterministic rules only (no model fitting).
- Economically intuitive sign expectations.
- Explicit weights and thresholds.
- Robust to missing data (scores rescaled to available signals).

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

### 1) Run from market data only (recent 1W move)

```bash
python -m market_helper.main --use-live-market
```

### 2) Add macro inputs from JSON

Create `macro_input.json`:

```json
{
  "gdp_nowcast_delta": 0.3,
  "payrolls_3m_avg_delta": 40000,
  "unemployment_rate_delta": -0.1,
  "ism_mfg_level": 51.2,
  "cpi_yoy_minus_target": 0.8,
  "core_cpi_3m_annualized_delta": 0.2,
  "wage_growth_3m_delta": 0.1,
  "5y5y_infl_exp_delta": 0.05
}
```

Run:

```bash
python -m market_helper.main --use-live-market --macro-json macro_input.json
```

## What gets scored

### Macro growth signals

- GDP nowcast change
- 3m average payroll momentum
- Unemployment rate change
- ISM manufacturing level (>50 expansion)

### Macro inflation signals

- CPI YoY minus target
- Core CPI 3m annualized momentum
- Wage growth momentum
- Long-term inflation expectations (5y5y) momentum

### Market growth/risk/inflation signals (1W)

- `SPY` (equities)
- `IWM/SPY` (small vs large caps)
- `VWO/VEA` (EM vs DM equities)
- `HYG/LQD` (credit risk appetite)
- `XLY/XLP` (cyclical vs defensive)
- `COPX` (copper miners proxy)
- `USO` (oil)
- `TLT` (duration / disinflation proxy, inverse sign for reflation)
- `TIP/IEF` (inflation breakeven proxy)

## Notes

- This is designed as a **decision aid**, not investment advice.
- You can tune thresholds/weights in `market_helper/regime_rulebook.py`.
