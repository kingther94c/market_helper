"""Runnable CLI for the option advisor.

Examples
--------
Scan SPY + QQQ against the live chain, with a held SPY lot::

    python -m market_helper.domain.option_advisor SPY QQQ \
        --aum 250000 --hold SPY:200 --regime Reflation --confidence Medium

Fallback when you have no live chain — override spot + IV (synthetic surface)::

    python -m market_helper.domain.option_advisor NVDA \
        --override NVDA:spot=120,iv=0.45 --hold NVDA:100 --no-realized

Write a JSON artifact for the report layer::

    python -m market_helper.domain.option_advisor SPY --json out/spy_ideas.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .service import idea_to_dict, run_advisor


def _reconfigure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def _parse_kv_list(items: list[str] | None, value_cast) -> dict:
    """Parse repeated ``SYM:VALUE`` flags into a dict."""
    out: dict = {}
    for item in items or []:
        if ":" not in item:
            raise SystemExit(f"bad --flag value {item!r}; expected SYM:VALUE")
        sym, val = item.split(":", 1)
        out[sym.upper()] = value_cast(val)
    return out


def _parse_overrides(items: list[str] | None) -> dict:
    """Parse ``SYM:spot=120,iv=0.45`` into {SYM: {"spot":120.0,"iv":0.45}}."""
    out: dict = {}
    for item in items or []:
        sym, _, rest = item.partition(":")
        fields: dict = {}
        for pair in rest.split(","):
            if not pair.strip():
                continue
            key, _, val = pair.partition("=")
            fields[key.strip()] = float(val)
        out[sym.upper()] = fields
    return out


def _fmt(x, nd=2, dash="-"):
    return dash if x is None else f"{x:,.{nd}f}"


def render_report(result) -> str:
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("OPTION ADVISOR — advisory only, not orders (read-only)")
    lines.append(
        f"as_of={result.as_of}  data_mode={result.data_mode}  "
        f"universe={','.join(result.universe_scanned) or '-'}  config v{result.config_version}"
    )
    counts = {k: 0 for k in ("PROCEED", "MONITOR", "REJECT")}
    for i in result.ideas:
        counts[i.label] = counts.get(i.label, 0) + 1
    lines.append(f"ideas: {len(result.ideas)}  "
                 f"PROCEED={counts['PROCEED']} MONITOR={counts['MONITOR']} REJECT={counts['REJECT']}")
    lines.append("=" * 78)

    for i in result.ideas:
        legs = "  ".join(
            f"{l.action.upper()} {l.right}{_fmt(l.resolved_strike, 0)}"
            f"@{_fmt(l.est_price)} (Δ{_fmt(l.est_delta)}, {l.resolved_dte}DTE)"
            for l in i.legs
        )
        g = i.net_greeks or {}
        sz = i.sizing
        liq = i.liquidity
        lines.append("")
        lines.append(f"[{i.label}] {i.category} · {i.structure_type} · {i.underlying_symbol}  "
                     f"(score {i.score:.3f}, {i.data_status})")
        lines.append(f"    thesis    : {i.thesis}")
        lines.append(f"    why now   : {i.why_now}")
        lines.append(f"    structure : {legs}")
        lines.append(f"    logic     : {i.expiry_strike_logic}")
        cf = i.est_net_debit_credit
        cf_word = "credit" if (cf or 0) >= 0 else "debit"
        lines.append(f"    economics : net {cf_word} {_fmt(abs(cf or 0))}/unit  "
                     f"maxloss {_fmt(i.est_max_loss)}  maxgain {_fmt(i.est_max_gain)}  "
                     f"breakeven {i.est_breakevens}")
        lines.append(f"    greeks    : Δ{_fmt(g.get('delta'),3)} Γ{_fmt(g.get('gamma'),4)} "
                     f"Θ{_fmt(g.get('theta'),1)} V{_fmt(g.get('vega'),1)}")
        if sz:
            lines.append(f"    sizing    : {sz.basis} max_contracts={sz.max_contracts} "
                         f"cap_at_risk={_fmt(sz.capital_at_risk_usd)} ({sz.notes})")
        if liq:
            lines.append(f"    liquidity : {liq.status}  worst_spread={_fmt(liq.worst_spread_pct,3)}  "
                         f"min_OI={liq.min_open_interest}")
        lines.append(f"    rationale : {i.rationale}")
    if result.warnings:
        lines.append("")
        lines.append("warnings:")
        for w in result.warnings[:20]:
            lines.append(f"  - {w}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout()
    p = argparse.ArgumentParser(prog="option-advisor", description="Read-only option idea advisor.")
    p.add_argument("symbols", nargs="+", help="underlying symbols, e.g. SPY QQQ AAPL")
    p.add_argument("--aum", type=float, default=None, help="funded AUM for sizing caps")
    p.add_argument("--hold", action="append", help="held shares, SYM:QTY (repeatable)")
    p.add_argument("--weight", action="append", help="portfolio weight, SYM:0.12 (repeatable)")
    p.add_argument("--override", action="append", help="SYM:spot=120,iv=0.45 (repeatable)")
    p.add_argument("--regime", default="", help="regime label, e.g. Reflation")
    p.add_argument("--confidence", default="", help="regime confidence: High|Medium|Low")
    p.add_argument("--crisis", action="store_true", help="set the crisis overlay flag")
    p.add_argument("--rules", default=None, help="path to advisor_rules.yaml override")
    p.add_argument("--prefer", default="cboe,yfinance", help="provider order (comma-sep)")
    p.add_argument("--no-realized", action="store_true", help="skip yfinance realized-vol fetch")
    p.add_argument("--json", default=None, help="write ideas as JSON to this path")
    args = p.parse_args(argv)

    result = run_advisor(
        [s.upper() for s in args.symbols],
        rules_path=args.rules,
        aum=args.aum,
        holdings=_parse_kv_list(args.hold, float),
        weights=_parse_kv_list(args.weight, float),
        regime_label=args.regime,
        regime_confidence=args.confidence,
        crisis_flag=args.crisis,
        overrides=_parse_overrides(args.override),
        prefer=tuple(x.strip() for x in args.prefer.split(",") if x.strip()),
        fetch_realized=not args.no_realized,
    )

    print(render_report(result))

    if args.json:
        out = {
            "as_of": result.as_of,
            "data_mode": result.data_mode,
            "universe_scanned": result.universe_scanned,
            "config_version": result.config_version,
            "warnings": result.warnings,
            "ideas": [idea_to_dict(i) for i in result.ideas],
        }
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
        print(f"wrote {len(result.ideas)} ideas -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
