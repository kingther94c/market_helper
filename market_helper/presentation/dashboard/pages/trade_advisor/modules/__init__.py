"""Per-module surfaces for the v2 Advisor cockpit.

Each module owns its own inputs and presentation (no shared global-input panel,
no single Run). The four peer modules:

- ``option``    — Option Strategy: Rule-based (collar over holdings + premium
  shorts over the security universe) | AI Plus dialog.
- ``fx_hedge``  — FX Hedge: a decision panel (baseline mix + exposure + carry →
  tilt), not idea-cards. | AI Plus dialog.
- ``tactical``  — Tactical Trade Ideas: the external Tactical Edge brief as a
  baseline, then AI accumulation.
- ``roll``      — Roll & Carry Calendar: holdings-derived, no run.

See ``docs/architecture/devplans/trade_advisor.md`` §5.
"""
