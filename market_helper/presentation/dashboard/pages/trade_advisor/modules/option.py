"""Option Strategy module — Rule-based | AI Plus (the canonical two-pane).

- **Rule-based** (left): scans current holdings + the security universe with the
  preset option engine. Two screens (devplan §5.1): a **zero-cost collar** over
  *holdings* (hedge) and **premium shorts** (sell call/put) over the *universe*
  (income). Inputs are scoped to options — no global panel. Ideas flow to the
  journal/Inbox (this module is idea-shaped).
- **AI Plus** (right): given holdings + the interest universe, the AI opens the
  search, calls read-only tools to judge whether an opportunity is good enough,
  and refines on feedback. Read-only, never orders.

v2.1: the latest scan **persists** (`option_scan_latest.json`) and is restored on
open with a saved-at badge — the tab opens with answers, not buttons — and a
ranked **summary table** sits above the cards so 10+ ideas compare at a glance.

The scan universe comes from ``configs/security_universe.csv`` (EQ rows), not the
old hardcoded 14-name list.
"""
from __future__ import annotations

import asyncio

from nicegui import ui

from market_helper.application.trade_advisor import (
    current_regime_seed,
    load_option_scan,
    save_option_scan,
)
from market_helper.trade_advisor.contracts import LABEL_ORDER

from ..ai_pane import module_ai_initial, render_ai_pane
from ..cards import _render_module, _ui_table
from ..inputs import (
    CONFIDENCE_OPTIONS,
    REGIME_OPTIONS,
    AdvisorInputs,
    build_run_context,
    load_option_universe,
)


def partition_option_ideas(suggestions):
    """Split option suggestions into the user's two screens + the remainder.

    Returns ``[(title, items, empty_note), …]``: Hedge (collar/protective over
    holdings), Income (sell premium over the universe), then any other structures.
    """
    hedge = [s for s in suggestions if s.category == "HEDGE"]
    income = [s for s in suggestions if s.category == "INCOME"]
    other = [s for s in suggestions if s.category not in ("HEDGE", "INCOME")]
    return [
        ("Hedge · zero-cost / protective collar (your holdings)", hedge,
         "No collar / hedge structures for your holdings."),
        ("Income · sell premium (security universe)", income,
         "No premium-selling opportunities for these inputs."),
        ("Other structures", other, ""),  # empty note "" → section hidden when empty
    ]


_SCREEN_NAME = {"HEDGE": "Hedge", "INCOME": "Income"}


def option_summary_rows(suggestions) -> tuple[list[str], list[list[str]]]:
    """Ranked one-line-per-idea summary (the compare-at-a-glance view above the cards).

    Sorted like the cards (label rank, then score desc). Pulls the value-screen
    signals (yield · IV/RV) and the risk one-liners straight from the headline
    metrics so the table and the cards can never disagree.
    """
    headers = ["Screen", "Symbol", "Structure", "Label", "Yield", "IV/RV", "Net", "@-10%", "Liq"]
    ordered = sorted(suggestions, key=lambda s: (LABEL_ORDER.get(s.label, 9), -s.score))
    rows: list[list[str]] = []
    for s in ordered:
        m = s.headline_metrics or {}
        structure = s.title.split(" · ")[0] if " · " in s.title else s.title
        rows.append([
            _SCREEN_NAME.get(s.category, "Other"),
            s.subject,
            structure,
            s.label,
            m.get("yield", "—"),
            m.get("IV/RV", "—"),
            m.get("net", "—"),
            m.get("@-10%", "—"),
            m.get("liq", "—"),
        ])
    return headers, rows


def _render_option_results(results, suggestions, journal, on_decision) -> None:
    """Render the summary table + the ideas grouped into the two screens (+ other)."""
    results.clear()
    with results:
        if len(suggestions) > 1:
            with ui.expansion(f"Summary · {len(suggestions)} ideas ranked", value=True).classes("w-full"):
                headers, rows = option_summary_rows(suggestions)
                _ui_table(headers, rows)
        for title, items, empty in partition_option_ideas(suggestions):
            if not items and not empty:
                continue
            ui.label(title).classes("text-subtitle2")
            box = ui.column().classes("w-full gap-3")
            _render_module(box, items, journal, on_decision, empty_note=empty)


def _make_option_ai_builder(sym_sel, held_sel, port_sw):
    """Factory: an AI-pane initial_builder that reads the live universe/held inputs.

    With "use my portfolio" on, the AI is pointed at the ``get_portfolio_book``
    tool (authoritative) instead of the greyed-out manual held list; it can also
    pull the persisted rule-based scan (``get_option_scan``) to critique it.
    """

    def _builder():
        syms = list(sym_sel.value or [])
        held = list(held_sel.value or [])
        framing = (
            "You are an options RESEARCH partner. Given my holdings and a scan universe, evaluate which names "
            "are worth an option structure under two screens: (a) a zero-cost / protective COLLAR over names I "
            "HOLD (hedge the downside), and (b) SELLING premium (covered call / cash-secured put / defined-risk "
            "spread) across the universe where it's worth it. Judge whether each opportunity is good enough on "
            "IV level, liquidity, and event risk. You may call read-only tools (portfolio book, the last "
            "rule-based scan, price-trend, regime) to support the read. Frame premium sales by their "
            "tail/assignment risk, never as a 'yield'. Never output an order, contract count to execute, or size."
        )
        holdings_line = (
            "Holdings: call get_portfolio_book — it is authoritative (the live book drives the scan)."
            if port_sw.value
            else f"Holdings: {', '.join(held) or '(none specified)'}."
        )
        ask = (
            f"{holdings_line} Scan universe: {', '.join(syms) or '(none)'}. "
            "If a rule-based scan is cached (get_option_scan), compare your read against it — what it missed or "
            "over-ranked. For the most attractive few names, say: the structure, the one-line reason, the main "
            "risk, and your confidence. Separate hedge (collar) ideas from premium-income ideas. No orders, no sizes."
        )
        return module_ai_initial(framing, ask)

    return _builder


def render_option_module(journal, refresh_inbox) -> None:
    """Render the Option Strategy two-pane surface."""
    ui.label("Option Strategy").classes("text-subtitle1")
    ui.label(
        "Rule-based scan (collar over holdings · premium shorts over the security universe) on the left; "
        "AI Plus opens the search on the right. Read-only ideas, never orders."
    ).classes("text-caption pm-muted")

    seed = current_regime_seed()
    universe = load_option_universe()
    default_syms = [s for s in ("SPY", "QQQ", "NVDA", "AAPL") if s in universe] or universe[:4]
    default_held = [s for s in ("SPY",) if s in universe]

    with ui.row().classes("w-full gap-4 items-start wrap"):
        # ---- Rule-based pane ----
        with ui.column().classes("grow gap-2").style("min-width: 440px"):
            with ui.card().classes("w-full pm-card"):
                ui.label("Rule-based · scan holdings + security universe").classes("text-subtitle2")
                sym_sel = ui.select(universe, value=default_syms, multiple=True, label="Scan universe").props(
                    "use-chips"
                ).classes("w-full")
                held_sel = ui.select(universe, value=default_held, multiple=True, label="Treat as held (100 sh)").props(
                    "use-chips"
                ).classes("w-full")
                aum_in = ui.number("AUM (USD)", value=250_000, min=0, step=10_000, format="%.0f").classes("w-full")
                regime_sel = ui.select(REGIME_OPTIONS, value=seed.regime, label="Regime").classes("w-full")
                conf_sel = ui.select(CONFIDENCE_OPTIONS, value=seed.confidence, label="Confidence").classes("w-full")
                crisis_sw = ui.switch("Crisis overlay", value=seed.crisis)
                if seed.is_seeded:
                    ui.label(
                        f"Regime auto-seeded: {seed.regime}"
                        f"{' · ' + seed.confidence if seed.confidence else ''}"
                        f"{' · stress overlay' if seed.crisis else ''} (override above)"
                    ).classes("text-caption pm-muted")
                rv_sw = ui.switch("Fetch realized vol (slower)", value=False)
                earn_sw = ui.switch("Check earnings (slower)", value=False)
                port_sw = ui.switch("Use my portfolio (live positions)", value=True)
                port_note = ui.label(
                    "Held names + AUM come from the live book — “Treat as held” and AUM above are ignored "
                    "(universe / regime still apply)."
                ).classes("text-caption pm-muted")
                run_btn = ui.button("Scan options")
                status = ui.label("").classes("text-caption pm-muted")

                def _sync_manual_inputs() -> None:
                    """Grey out the manual book controls while the live book drives the scan."""
                    if port_sw.value:
                        held_sel.disable()
                        aum_in.disable()
                        port_note.set_visibility(True)
                    else:
                        held_sel.enable()
                        aum_in.enable()
                        port_note.set_visibility(False)

                _sync_manual_inputs()
                port_sw.on_value_change(_sync_manual_inputs)

                # Crystallize (devplan §2 closed loop): what AI Plus discovers
                # lands here as a bounded preset edit — config, not code. The
                # next scan reads the YAML, so the deterministic pane improves.
                with ui.expansion("Premium screen preset · crystallize").classes("w-full"):
                    from market_helper.application.trade_advisor.option_rules import (
                        load_premium_screen,
                        save_premium_screen,
                    )

                    ps = load_premium_screen()
                    ui.label(
                        "The INCOME value screen's knobs (bounded). Saving edits only these values in "
                        "advisor_rules.yaml — the research comments survive."
                    ).classes("text-caption pm-muted")
                    y_in = ui.number("Target yield (ann., 1.0 = 100%)",
                                     value=ps.get("target_yield_annualized", 0.40),
                                     min=0.05, max=2.0, step=0.05).classes("w-full")
                    span_in = ui.number("VRP richness span (IV/RV − 1 scoring 1.0)",
                                        value=ps.get("vrp_ratio_span", 0.5),
                                        min=0.05, max=2.0, step=0.05).classes("w-full")
                    minv_in = ui.number("Min IV/RV (≤1 = selling cheap vol)",
                                        value=ps.get("min_vrp_ratio", 1.0),
                                        min=0.5, max=2.0, step=0.05).classes("w-full")
                    dte_in = ui.number("Manage DTE", value=ps.get("manage_dte", 21),
                                       min=7, max=45, step=1).classes("w-full")
                    with ui.row().classes("items-center gap-2"):
                        save_btn = ui.button("Save preset").props("dense")
                        saved_note = ui.label("").classes("text-caption pm-muted")

                    async def _save_preset() -> None:
                        save_btn.disable()
                        try:
                            written = await asyncio.to_thread(
                                lambda: save_premium_screen({
                                    "target_yield_annualized": y_in.value,
                                    "vrp_ratio_span": span_in.value,
                                    "min_vrp_ratio": minv_in.value,
                                    "manage_dte": dte_in.value,
                                })
                            )
                            saved_note.text = (
                                "Saved ✓ — the next scan uses it." if written else "Nothing to save."
                            )
                        except Exception as exc:  # noqa: BLE001 — surface, never crash
                            saved_note.text = f"Save failed: {type(exc).__name__}: {str(exc)[:120]}"
                        finally:
                            save_btn.enable()

                    save_btn.on_click(_save_preset)
            results = ui.column().classes("w-full gap-3")
            with results:
                ui.label("Scan to populate collar (holdings) + premium-short (universe) ideas.").classes(
                    "text-caption pm-muted"
                )

        # ---- AI Plus pane ----
        with ui.column().classes("grow gap-2").style("min-width: 360px"):
            render_ai_pane(
                _make_option_ai_builder(sym_sel, held_sel, port_sw),
                intro="Opt-in: given your holdings + universe, the AI evaluates which names are worth a collar or "
                      "a premium sale (calling read-only tools to judge IV / trend / regime). After a brief, type "
                      "feedback to refine — analysis only, never orders.",
                generate_label="Find opportunities (AI)",
            )

    def _scan_inputs() -> dict:
        return {
            "symbols": list(sym_sel.value or []),
            "held": list(held_sel.value or []),
            "aum": float(aum_in.value or 0),
            "regime": regime_sel.value or "",
            "use_portfolio": bool(port_sw.value),
        }

    async def _restore_last_scan() -> None:
        """Open with the persisted scan (as-of badged) instead of an empty pane."""
        try:
            saved = await asyncio.to_thread(load_option_scan)
        except Exception:  # noqa: BLE001 — restore is best-effort, never break the page
            saved = None
        if not saved or not saved["suggestions"]:
            return
        _render_option_results(results, saved["suggestions"], journal, refresh_inbox)
        scanned = saved["inputs"].get("symbols") or []
        status.text = (
            f"Restored scan from {saved['saved_at'][:16]} · {len(saved['suggestions'])} ideas · "
            f"data: {saved['data_mode'] or 'n/a'}"
            + (f" · universe {len(scanned)}" if scanned else "")
            + " — re-scan to refresh."
        )

    ui.timer(0.1, _restore_last_scan, once=True)

    async def run() -> None:
        run_btn.disable()
        status.text = "Scanning…"
        inp = AdvisorInputs(
            symbols=list(sym_sel.value or []),
            held=list(held_sel.value or []),
            aum=float(aum_in.value or 0),
            regime=regime_sel.value or "",
            confidence=conf_sel.value or "",
            crisis=bool(crisis_sw.value),
            fetch_realized=bool(rv_sw.value),
            check_earnings=bool(earn_sw.value),
        )
        if not inp.symbols and not port_sw.value:
            status.text = "Pick at least one symbol (or enable “use my portfolio”)."
            run_btn.enable()
            return
        context, book_note = build_run_context(inp, use_portfolio=bool(port_sw.value))
        try:
            from market_helper.application.trade_advisor.option_rules import advisor_rules_path
            from market_helper.trade_advisor.adapters.option import OptionAdvisorPlugin

            # Honor the YAML preset (the crystallize loop) when it exists.
            rules = advisor_rules_path()
            rules_path = str(rules) if rules.exists() else None
            res = await asyncio.to_thread(
                lambda: OptionAdvisorPlugin().produce(
                    context, rules_path=rules_path,
                    fetch_realized=inp.fetch_realized, fetch_events=inp.check_earnings,
                )
            )
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the page
            status.text = f"Failed: {type(exc).__name__}: {exc}"
            run_btn.enable()
            return
        _render_option_results(results, res.suggestions, journal, refresh_inbox)
        status.text = f"Done · {len(res.suggestions)} ideas · data: {res.data_mode or 'n/a'}{book_note}"
        run_btn.enable()
        try:  # persist so the next open (and the Today strip) sees this scan
            await asyncio.to_thread(
                lambda: save_option_scan(
                    res.suggestions, as_of=res.as_of, data_mode=res.data_mode,
                    inputs=_scan_inputs(), warnings=list(res.warnings),
                )
            )
        except Exception:  # noqa: BLE001 — persistence is best-effort
            pass

    run_btn.on_click(run)
