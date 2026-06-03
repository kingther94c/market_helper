"""Orchestrator: scan symbols → ranked, labelled, audited option ideas.

Ties the layers together: ``get_chain`` (live → fallback → synthetic) →
:mod:`.signals` → :mod:`.candidates` → :mod:`.filters` → :mod:`.ranking`,
returning one :class:`~.contracts.OptionAdvisoryResult`.

Read-only: only fetches public market data; emits ideas, never orders.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any

from . import candidates, filters, providers, ranking, signals
from .config import CONFIG_VERSION, load_rules
from .contracts import OptionAdvisoryResult, OptionIdea


def advise_symbol(
    symbol: str,
    *,
    rules: dict,
    aum: float | None = None,
    held_qty: float = 0.0,
    weight: float = 0.0,
    sector: str = "",
    regime_label: str = "",
    regime_confidence: str = "",
    crisis_flag: bool = False,
    spot_override: float | None = None,
    iv_override: float | None = None,
    prefer: tuple[str, ...] = ("cboe", "yfinance"),
    fetch_realized: bool = True,
) -> tuple[list[OptionIdea], str, list[str]]:
    """Return ``(ideas, data_mode, warnings)`` for a single underlying."""
    chain = providers.get_chain(
        symbol, prefer=prefer, spot_override=spot_override, iv_override=iv_override,
    )
    ctx = signals.build_context(
        symbol, chain, held_qty=held_qty, weight=weight, sector=sector,
        regime_label=regime_label, regime_confidence=regime_confidence,
        crisis_flag=crisis_flag, fetch_realized=fetch_realized,
    )

    # Inject AUM into the rules' filter block so sizing can read it (kept out of
    # the public signature to avoid threading it through every layer).
    rules = {**rules, "filters": {**rules.get("filters", {}), "_aum": aum}}

    raw = candidates.generate(chain, ctx, rules)
    enriched: list[OptionIdea] = []
    for idea in raw:
        fos, sizing = filters.evaluate(idea, ctx, rules)
        enriched.append(replace(idea, filters_applied=fos, sizing=sizing))
    labelled = ranking.rank_and_label(enriched, rules)
    return labelled, chain.data_mode, list(chain.warnings)


def run_advisor(
    symbols: list[str],
    *,
    rules_path: str | None = None,
    aum: float | None = None,
    holdings: dict[str, float] | None = None,
    weights: dict[str, float] | None = None,
    sectors: dict[str, str] | None = None,
    regime_label: str = "",
    regime_confidence: str = "",
    crisis_flag: bool = False,
    overrides: dict[str, dict[str, float]] | None = None,
    prefer: tuple[str, ...] = ("cboe", "yfinance"),
    fetch_realized: bool = True,
    as_of: str | None = None,
) -> OptionAdvisoryResult:
    """Scan ``symbols`` and return one combined advisory result.

    ``holdings`` maps symbol → shares held (enables covered-call/hedge ideas).
    ``overrides`` maps symbol → ``{"spot": ..., "iv": ...}`` user overrides.
    """
    rules = load_rules(rules_path)
    holdings = holdings or {}
    weights = weights or {}
    sectors = sectors or {}
    overrides = overrides or {}

    all_ideas: list[OptionIdea] = []
    scanned: list[str] = []
    warnings: list[str] = []
    modes: set[str] = set()

    for sym in symbols:
        ov = overrides.get(sym, {})
        try:
            ideas, mode, warns = advise_symbol(
                sym, rules=rules, aum=aum,
                held_qty=holdings.get(sym, 0.0), weight=weights.get(sym, 0.0),
                sector=sectors.get(sym, ""),
                regime_label=regime_label, regime_confidence=regime_confidence, crisis_flag=crisis_flag,
                spot_override=ov.get("spot"), iv_override=ov.get("iv"),
                prefer=prefer, fetch_realized=fetch_realized,
            )
        except Exception as exc:  # noqa: BLE001 — one bad symbol must not sink the scan
            warnings.append(f"{sym}: {type(exc).__name__}: {str(exc)[:160]}")
            continue
        all_ideas.extend(ideas)
        scanned.append(sym)
        modes.add(mode)
        warnings.extend(f"{sym}: {w}" for w in warns)

    # Overall data mode: worst-honesty wins for the headline.
    order = ["synthetic", "user_override", "live_anchored_synthetic", "live_chain"]
    overall = next((m for m in order if m in modes), "synthetic") if modes else "synthetic"

    as_of_val = as_of or (all_ideas[0].as_of if all_ideas else "")
    return OptionAdvisoryResult(
        as_of=as_of_val,
        ideas=all_ideas,
        universe_scanned=scanned,
        data_mode=overall,
        config_version=str(rules.get("version", CONFIG_VERSION)),
        warnings=warnings,
    )


def idea_to_dict(idea: OptionIdea) -> dict[str, Any]:
    """JSON-serializable view of an idea (for CLI / artifact output)."""
    return asdict(idea)
