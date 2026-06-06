# Regime-Aware Policy Experts (clean-room rebuild)

> Perfect-foresight, in-sample CEILING -- a teacher / expert-discovery step, NOT a tradable strategy. Experts are STATIC exposure vectors (no future info when applied month-by-month). Consensus-dated regimes; the project regime engine's labels are deliberately NOT used. No execution.

Sample 1989-02 .. 2026-05 (448 months). Sleeves EQ=^SP500TR, CM=^SPGSCI, FI=synthetic 10Y (FRED GS10, futures->excess), CASH=TB3MS, MACRO=TSMOM trend proxy (vol-scaled ~10%). Accounting `R = cash*100% + sum exposure*(sleeve-cash)`. Robust selection: 400 draws (+/-6mo + subsets), **max mean s.t. p10 >= median p10**, the SAME rule in every regime.


## In-regime sleeve EXCESS returns (oracle sanity, ann %)

| regime (G x I) | n | EQ | CM | FI | MACRO | corr(EQ,FI) | corr(EQ,CM) |
|---|--:|--:|--:|--:|--:|--:|--:|
| **Goldilocks** (G↑ I↓) | 141 | +16.9% | -5.8% | +2.3% | +7.2% | +0.05 | +0.27 |
| **Reflation** (G↑ I↑) | 70 | +23.5% | +32.0% | -2.8% | +3.3% | -0.0 | +0.2 |
| **Stagflation** (G↓ I↑) | 14 | -28.2% | +40.1% | -17.5% | +20.5% | +0.44 | -0.02 |
| **Recession** (G↓ I↓) | 34 | -16.4% | -54.7% | +14.8% | +9.8% | -0.04 | +0.56 |

*Inflation axis -> duration sign; growth axis -> EQ/CM. MACRO/trend is crisis alpha (positive everywhere; EQ-diversifying in stress).*


## Robust corner vs smoothed expert template

| regime | robust corner (EQ/CM/MACRO/FI) | mean / p10 / min | vol | **smoothed template** | full-sample ret / vol / maxDD |
|---|---|--:|--:|---|--:|
| **Goldilocks** (G↑ I↓) | 100/0/0/+200 | +23.22/+20.29/+15.46% | 17% | **EQ100/CM0/MACRO0/FI+150** | +15.09% / 17% / -42.92% |
| **Reflation** (G↑ I↑) | 100/15/0/+50 | +24.59/+19.47/+12.89% | 14% | **EQ100/CM15/MACRO0/FI+50** | +13.01% / 16% / -51.07% |
| **Stagflation** (G↓ I↑) | 0/15/0/-100 | +20.07/+7.05/-6.1% | 9% | **EQ0/CM15/MACRO0/FI-100** | +0.51% / 8% / -48.83% |
| **Recession** (G↓ I↓) | 60/0/0/+200 | +15.44/+6.75/-0.16% | 20% | **EQ60/CM0/MACRO0/FI+150** | +11.82% / 13% / -38.0% |

*Smoothing: EQ/CM/MACRO -> nearest 5; |FI| capped at 150 then -> nearest 25 (defensible duration leverage). Full-sample = the static template applied to EVERY month 1989+ (context; not the in-regime ceiling).*


## The four policy experts

- **Goldilocks** (G↑ I↓): EQ 100 / CM 0 / MACRO 0 / FI +150 (duration via futures, excess)
- **Reflation** (G↑ I↑): EQ 100 / CM 15 / MACRO 0 / FI +50 (duration via futures, excess)
- **Stagflation** (G↓ I↑): EQ 0 / CM 15 / MACRO 0 / FI -100 (duration via futures, excess)
- **Recession** (G↓ I↓): EQ 60 / CM 0 / MACRO 0 / FI +150 (duration via futures, excess)


## Robust directional insight vs tentative template

- **Robust (directional, high confidence):** inflation-up shorts duration / inflation-down lengthens it; growth drives EQ (and CM in reflation); MACRO trend is additive crisis alpha. These signs were stable across the perturbed draws.

- **Tentative (magnitudes / templates):** the exact exposure sizes are an in-sample ceiling shrunk to round numbers -- treat as starting templates, not optima.

- **Stagflation is the fragile conclusion:** only ~14 months (2022 + 1990; the 1970s are pre-sample). Its attack template (short duration + long commodities + long trend) carries the heaviest caveat and the most shrinkage; its min-return draw is the worst of the four.


## Handoff

- `policy_expert_returns.csv` -- each expert's full-sample monthly return series (1989+), the input for the Phase-3 forward-label step.

