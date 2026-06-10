"""The FX target-vs-current decision join — application logic, one home.

``build_fx_decision`` is the pure join (devplan §9.1 V3): per-currency target
hedge leg vs the book's signed FX-futures overlay → gap (contracts + USD) and
the "at target" currency mix. It lives here so the dashboard FX panel, the
Today strip, and the AI tools all consume the *same* join — presentation keeps
only the formatting.

``fx_decision_from_book`` assembles the inputs (cached hedge artifact via the
fx_hedge adapter + the live positions CSV) and runs the join — the one-call
form the AI tool uses. Read-only, cached artifact only: no network.
"""

from __future__ import annotations

# The hedge instrument for CNY exposure is the offshore CNH future — join them as
# one bucket in the decision table (documented coarseness, not a hidden merge).
CCY_ALIAS = {"CNH": "CNY"}


def build_fx_decision(panel: dict, exposure: dict) -> dict:
    """The decision join: per-currency target hedge leg vs the held FX-futures overlay.

    Pure. ``panel`` needs ``{"available", "legs_raw": [{currency,
    target_contracts, target_notional_usd}, …]}``; ``exposure`` needs
    ``{"available", "by_currency": [(ccy, usd, weight), …],
    "fx_overlay_by_currency": {ccy: {"usd", "qty"}}}``. Returns ``{"available",
    "rows", "at_target", "note"}`` where each row is ``{ccy, book_usd, book_w,
    cur_qty, cur_usd, tgt_ct, tgt_usd, gap_ct, gap_usd}`` (signed notionals:
    long foreign = positive). ``at_target`` is the book's currency mix if the
    FX-futures overlay matched the target legs — same gross, single-assignment
    frame as the exposure table (no double counting of the implicit USD short).
    """
    if not panel.get("available") or not exposure.get("available"):
        return {"available": False, "rows": [], "at_target": [], "note": ""}

    book = {c: (usd, w) for c, usd, w in exposure["by_currency"]}
    overlay = {
        CCY_ALIAS.get(c, c): dict(v) for c, v in (exposure.get("fx_overlay_by_currency") or {}).items()
    }
    targets: dict[str, dict] = {}
    for leg in panel.get("legs_raw") or []:
        ccy = CCY_ALIAS.get(str(leg.get("currency", "")), str(leg.get("currency", "")))
        slot = targets.setdefault(ccy, {"usd": 0.0, "ct": 0})
        slot["usd"] += float(leg.get("target_notional_usd") or 0.0)
        slot["ct"] += int(leg.get("target_contracts") or 0)

    rows: list[dict] = []
    for ccy in sorted(set(targets) | set(overlay),
                      key=lambda c: (-abs(targets.get(c, {}).get("usd", 0.0)), c)):
        cur = overlay.get(ccy, {})
        tgt = targets.get(ccy, {})
        cur_usd = float(cur.get("usd") or 0.0)
        tgt_usd = float(tgt.get("usd") or 0.0)
        cur_qty = float(cur.get("qty") or 0.0)
        tgt_ct = int(tgt.get("ct") or 0)
        b_usd, b_w = book.get(ccy, (0.0, 0.0))
        rows.append({
            "ccy": ccy, "book_usd": b_usd, "book_w": b_w,
            "cur_qty": cur_qty, "cur_usd": cur_usd,
            "tgt_ct": tgt_ct, "tgt_usd": tgt_usd,
            "gap_ct": tgt_ct - cur_qty, "gap_usd": tgt_usd - cur_usd,
        })

    # "At target": replace the held overlay gross with the target gross per foreign
    # ccy, keep everything else, renormalize. Same gross frame as the exposure table.
    at: dict[str, float] = {c: usd for c, (usd, _w) in book.items()}
    for ccy in set(targets) | set(overlay):
        cur_abs = abs(float(overlay.get(ccy, {}).get("usd") or 0.0))
        tgt_abs = abs(float(targets.get(ccy, {}).get("usd") or 0.0))
        at[ccy] = max(at.get(ccy, 0.0) - cur_abs + tgt_abs, 0.0)
    total = sum(at.values())
    at_target = sorted(
        ((c, v, (v / total if total else 0.0)) for c, v in at.items() if v > 0.5),
        key=lambda x: -x[1],
    )

    note = (
        "Signed FX-futures notionals vs the cached target legs (CNH joins the CNY bucket). Book weights are "
        "gross-MV, single-assignment. A gap is information about distance-to-target, not an instruction — "
        "read-only, no orders."
    )
    return {"available": True, "rows": rows, "at_target": at_target, "note": note}


def fx_decision_from_book(*, provider=None, mode: str = "cached", positions_path=None) -> dict:
    """Assemble the join from the cached hedge artifact + the live book (read-only).

    Graceful: missing artifact or empty book → ``{"available": False, …}`` with a
    reason, never an exception. ``provider`` / ``positions_path`` are injectable
    for tests.
    """
    from market_helper.trade_advisor.adapters.fx_hedge import FxHedgeAdvisorPlugin
    from market_helper.trade_advisor.contracts import AdvisorContext

    from .portfolio import currency_exposure_from_positions_csv

    try:
        res = FxHedgeAdvisorPlugin().produce(AdvisorContext(), provider=provider, mode=mode)
        hedge = next((s for s in res.suggestions if s.body_kind == "fx_alloc"), None)
        available = hedge is not None and hedge.suggestion_id != "fx_hedge:missing"
        panel = {
            "available": available,
            "legs_raw": [dict(l) for l in (hedge.detail.get("fx_legs") or [])] if (available and hedge) else [],
        }
        data_mode = res.data_mode
    except Exception as exc:  # noqa: BLE001 — the join is best-effort, never raises
        return {"available": False, "rows": [], "at_target": [], "note": f"hedge target unreadable: {exc}"}

    exp = currency_exposure_from_positions_csv(positions_path)
    exposure = {
        "available": exp["n_positions"] > 0,
        "by_currency": exp["by_currency"],
        "fx_overlay_by_currency": exp.get("fx_overlay_by_currency") or {},
    }
    out = build_fx_decision(panel, exposure)
    out["data_mode"] = data_mode
    if not out["available"] and not out["note"]:
        out["note"] = ("no cached FX hedge target" if not panel["available"] else "no live positions found")
    return out
