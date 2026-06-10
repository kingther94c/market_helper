"""Cross-module advisor tools — the AI can finally see what the modules see.

v2.1's surfaces compute rich state (the live book, the FX target-vs-current gap,
held-roots roll yields, the persisted option scan) that the AI Plus panes
previously could not reach — the AI was asked to reason about "my holdings"
without being able to look at them. These four read-only tools close that gap
and are registered into **every** module's AI pane (the shared registry).

Invariants match the framework (``trade_advisor.ai.tools``): read-only, cached /
local data only — **no tool here triggers a network fetch** (the roll-yield tool
serves the cached artifact and says so when it's absent; quotes are fetched only
by the explicit dashboard button). Imports are lazy inside each tool so building
a registry stays cheap and layering stays clean.
"""

from __future__ import annotations

from typing import Any

from .tools import AiToolRegistry

_NO_PARAMS: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}


def register_advisor_tools(reg: AiToolRegistry) -> AiToolRegistry:
    """Register the cross-module read-only tools into ``reg`` (returns it)."""

    @reg.tool(
        "get_portfolio_book",
        "The live book: funded AUM (excl. options/futures), stock holdings (symbol → shares), held options "
        "(underlying/right/strike/expiry/qty) and held futures (root/contract/qty). The authoritative view of "
        "what is actually held — prefer it over any holdings list in the prompt.",
        _NO_PARAMS,
    )
    def get_portfolio_book() -> dict:
        from market_helper.application.trade_advisor import context_from_positions_csv

        c = context_from_positions_csv()
        return {
            "as_of": c.as_of,
            "funded_aum_usd": c.aum,
            "holdings_shares": dict(c.holdings),
            "held_options": [
                {k: o.get(k) for k in ("underlying", "right", "strike", "expiry", "qty")}
                for o in c.held_options
            ],
            "held_futures": [
                {k: f.get(k) for k in ("root", "contract", "exchange", "qty", "market_value")}
                for f in c.held_futures
            ],
            "note": "funded AUM excludes options/futures (sizing denominator); futures market_value = signed notional",
        }

    @reg.tool(
        "get_fx_decision",
        "FX hedge target-vs-current join: per-currency target hedge legs vs the FX futures the book actually "
        "holds — gap in contracts and USD (signed; long foreign = positive), plus the 'at target' currency mix "
        "and the book's per-currency exposure context. Cached hedge artifact; no network.",
        _NO_PARAMS,
    )
    def get_fx_decision() -> dict:
        from market_helper.application.trade_advisor.fx_decision import fx_decision_from_book

        out = fx_decision_from_book()
        if not out.get("available"):
            return {"available": False, "note": out.get("note", "unavailable")}
        return {
            "available": True,
            "data_mode": out.get("data_mode", ""),
            "rows": [
                {k: r[k] for k in ("ccy", "book_usd", "cur_qty", "cur_usd", "tgt_ct", "tgt_usd", "gap_ct", "gap_usd")}
                for r in out["rows"]
            ],
            "at_target_mix": [{"ccy": c, "weight": round(w, 4)} for c, _u, w in out["at_target"][:8]],
            "note": out["note"],
        }

    @reg.tool(
        "get_roll_yields",
        "Held-roots two-contract roll yield (held contract vs next liquid; annualized ln(F1/F2); positive = "
        "backwardation = long-friendly roll) from the CACHED quote artifact. If not fetched yet it says so — "
        "this tool never hits the network; the operator fetches quotes via the dashboard button.",
        _NO_PARAMS,
    )
    def get_roll_yields() -> dict:
        from market_helper.application.trade_advisor.roll_carry import load_roll_yields

        payload = load_roll_yields()
        if payload is None:
            return {"available": False,
                    "note": "no cached quotes — ask the operator to click 'Fetch quotes' on the Roll & Carry tab"}
        ok = [r for r in payload.get("rows", []) if r.get("status") == "ok"]
        skipped = [{"root": r.get("root"), "held": r.get("held_contract"), "why": r.get("note", r.get("status"))}
                   for r in payload.get("rows", []) if r.get("status") != "ok"]
        return {
            "available": True,
            "fetched_at": payload.get("fetched_at", ""),
            "age_hours": round(float(payload.get("age_hours", 0.0)), 1),
            "rows": ok,
            "skipped": skipped,
            "note": "two-contract slice for held roots only — not the full F1/F7 curve",
        }

    @reg.tool(
        "get_option_scan",
        "The latest persisted rule-based option scan: when it ran, its inputs, and each idea's screen "
        "(HEDGE collar / INCOME premium), label, score, yield, IV/RV and thesis. Use it to critique or build on "
        "the deterministic screen (e.g. before proposing premium-screen preset changes).",
        _NO_PARAMS,
    )
    def get_option_scan() -> dict:
        from market_helper.application.trade_advisor import load_option_scan

        saved = load_option_scan()
        if not saved or not saved["suggestions"]:
            return {"available": False, "note": "no scan cached — run the Option Strategy scan first"}
        ideas = [
            {
                "screen": s.category,
                "symbol": s.subject,
                "structure": s.title.split(" · ")[0] if " · " in s.title else s.title,
                "label": s.label,
                "score": s.score,
                "yield": (s.headline_metrics or {}).get("yield", ""),
                "iv_rv": (s.headline_metrics or {}).get("IV/RV", ""),
                "net": (s.headline_metrics or {}).get("net", ""),
                "thesis": (s.thesis or "")[:160],
            }
            for s in saved["suggestions"]
        ]
        return {
            "available": True,
            "saved_at": saved["saved_at"],
            "as_of": saved["as_of"],
            "data_mode": saved["data_mode"],
            "inputs": saved["inputs"],
            "n_ideas": len(ideas),
            "ideas": ideas,
            "warnings": saved["warnings"][:10],
        }

    return reg


def build_advisor_tool_registry() -> AiToolRegistry:
    """The full shared registry every AI Plus pane gets: the tactical research
    tools (regime / policy-expert / anchors / price-trend / tactical-edge) plus
    the cross-module book/FX/roll/scan tools above."""
    from market_helper.domain.tactical_ideas.ai_tools import build_tactical_tool_registry

    return register_advisor_tools(build_tactical_tool_registry())
