"""Read-only, advisory-only option-idea research layer.

Scans selected underlyings (holdings + watchlist) and surfaces ranked option
trade *ideas* — never orders. See ``docs/architecture/devplans/option_advisor.md``
and ADR 0006 for scope. Pricing is pure-stdlib Black–Scholes (no new deps).
"""
