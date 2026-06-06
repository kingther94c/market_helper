"""Phase 6 deliverable -- self-contained HTML research report.

Reads the committed JSON artifacts (experts / model / backtest / feature schema) and
renders data/research_artifacts/policy_expert_report.html: data & accounting, the 4
experts, labels, features + predictor skill, allocation + backtest vs baselines,
robustness, limitations, and the verdict. Inline CSS, no external dependencies.
"""
from __future__ import annotations

import json
import sys
from html import escape
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
ART = REPO_ROOT / "data/research_artifacts"
OUT_HTML = ART / "policy_expert_report.html"

CSS = """
body{font:15px/1.55 -apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1c2330;
 max-width:1040px;margin:0 auto;padding:28px 22px;background:#fafbfc}
h1{font-size:25px;margin:.2em 0}h2{font-size:19px;margin-top:1.7em;border-bottom:2px solid #e6e9ee;padding-bottom:5px}
h3{font-size:15px;margin-top:1.2em;color:#34405a}
.sub{color:#6b7488;margin-top:-.4em}
table{border-collapse:collapse;width:100%;margin:.6em 0;font-size:13.5px}
th,td{border:1px solid #e2e6ec;padding:5px 9px;text-align:right}
th{background:#f0f3f7;text-align:right}td:first-child,th:first-child{text-align:left}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:600}
.good{background:#e3f5ea;color:#1d7a44}.warn{background:#fdf3df;color:#9a6a12}.bad{background:#fde6e6;color:#b3322c}
.verdict{border-left:5px solid #d99a2b;background:#fffaf0;padding:14px 18px;margin:1em 0;border-radius:0 6px 6px 0}
.note{color:#6b7488;font-size:13px}.mono{font-family:ui-monospace,Menlo,Consolas,monospace}
.best{font-weight:700;background:#eef7f0}
ul{margin:.4em 0}li{margin:.2em 0}
"""


def load(name):
    return json.loads((ART / name).read_text(encoding="utf-8"))


def tbl(headers, rows, best_row=None):
    h = "".join(f"<th>{escape(str(x))}</th>" for x in headers)
    body = []
    for i, r in enumerate(rows):
        cls = ' class="best"' if best_row is not None and i == best_row else ""
        cells = "".join(f"<td>{escape(str(x))}</td>" for x in r)
        body.append(f"<tr{cls}>{cells}</tr>")
    return f"<table><thead><tr>{h}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def main() -> int:
    experts = load("policy_experts.json")
    model = load("policy_expert_model.json")
    bt = load("policy_expert_backtest.json")
    schema = load("policy_expert_feature_schema.json")
    m = model["oos_metrics"]

    P = []
    w = P.append
    w(f"<!doctype html><html><head><meta charset='utf-8'>"
      f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
      f"<title>Regime-Aware Policy-Expert Allocation</title><style>{CSS}</style></head><body>")
    w("<h1>Regime-Aware Policy-Expert Allocation &mdash; Research Report</h1>")
    w("<p class='sub'>Economically-interpretable policy experts from Growth&times;Inflation "
      "regimes, an ex-ante ML predictor of which expert outperforms, and a soft "
      "mixture-of-experts allocation. Walk-forward, vs investable baselines.</p>")

    # Verdict up top
    w("<div class='verdict'><b>Verdict: <span class='tag warn'>MONITOR</span></b><br>"
      "The ML mixture-of-experts improves risk-adjusted return over standard investable "
      f"baselines (Sharpe {bt['strategies']['MoE (this model)']['sharpe']} vs "
      f"{bt['strategies']['Best static (Goldilocks)']['sharpe']} for the best single static "
      f"expert; max-drawdown {bt['strategies']['MoE (this model)']['max_dd_pct']}% vs "
      f"{bt['strategies']['Best static (Goldilocks)']['max_dd_pct']}%), with the edge "
      "concentrated in crisis de-risking (2008, 2022). But a simple "
      "<i>cash-in-stagflation</i> heuristic achieves a comparable/better Sharpe "
      f"({bt['strategies']['Cash-in-stagflation']['sharpe']}), so the ML's marginal value "
      "over a well-chosen rule is modest. Deploy as an <b>advisory</b> signal, track live, "
      "reassess vs the simple rule. Read-only with respect to the broker.</div>")

    # 1 data
    w("<h2>1. Data &amp; accounting</h2>")
    w(f"<p>Monthly, {escape(experts['meta']['sample'])}. Sleeves: EQ = S&amp;P 500 TR "
      "(<span class='mono'>^SP500TR</span>), CM = S&amp;P GSCI (<span class='mono'>^SPGSCI</span>), "
      "FI = synthetic constant-maturity 10Y from FRED <span class='mono'>GS10</span> "
      "(par-bond duration/convexity), CASH = <span class='mono'>TB3MS</span>. FI is a "
      "futures excess-return overlay. Accounting: "
      "<span class='mono'>R = cash&middot;100% + &Sigma; exposure&middot;(sleeve&minus;cash)</span>. "
      "A MACRO (TSMOM trend) sleeve was analysed (positive crisis-alpha every regime, see "
      "&sect;2) but <b>removed from the final experts</b>: it was a uniform +10 overlay "
      "across all four, so it does not differentiate them and cancels in the "
      "cross-sectional allocation. Dropping it costs a small crisis-diversifying return "
      "(MoE Sharpe 0.69&rarr;0.65) but makes the experts directly implementable in EQ/CM/FI.</p>")

    # 2 experts
    w("<h2>2. The four policy experts (oracle teacher step)</h2>")
    w("<p class='note'>Consensus-dated regimes (the project regime engine's lagging growth "
      "score is deliberately not used). Robust selection = max mean s.t. p10 &ge; median p10 "
      "over 400 boundary-perturbed windows, the <b>same rule in every regime</b> &mdash; so "
      "stagflation lands on the attack template (short duration + commodities + trend), not "
      "cash-insurance. Smoothed to round, defensible exposures.</p>")
    rows = [[k, e["EQ"], e["CM"], e["MACRO"], e["FI"]] for k, e in experts["experts"].items()]
    w(tbl(["Expert (G&times;I)", "EQ", "CM", "MACRO", "FI (dur)"], rows))

    # 3 labels + 4 features/predictor
    w("<h2>3. Labels &amp; 4. Ex-ante predictor</h2>")
    w(f"<p>Forward expert returns at 3 / <b>6 (primary)</b> / 12 months &rarr; four label "
      "families (winner / winner-with-margin / softmax / direct cross-sectional excess). "
      f"Predictor: <b>{len(schema)} ex-ante features</b> (point-in-time; macro lagged +1 "
      "month) across inflation / growth / policy / rates / credit / risk / momentum / "
      "stress / trend. Multi-output Ridge predicting forward expert returns; alpha by an "
      "<b>embargoed time-series CV</b> (heavy shrinkage is essential &mdash; a naive "
      "low-alpha fit overfits the autocorrelated overlapping targets and goes negative).</p>")
    w("<h3>Out-of-sample skill (walk-forward, " + escape(str(m["oos_span"])) + ")</h3>")
    w(tbl(["metric", "value"], [
        ["months", m["n_oos_months"]],
        ["pooled rank IC", m["pooled_rank_ic"]],
        ["top-1 accuracy (4 classes)", m["top1_accuracy"]],
        ["predicted-best beats equal-weight", f"{m['predicted_best_beats_equalweight_rate']*100:.0f}%"],
        ["excess captured (predicted-best)", f"{m['mean_excess_captured_pct']}%"],
        ["baseline: always-Goldilocks", f"{m['baseline_always_goldilocks_pct']}%"],
        ["best possible (perfect foresight)", f"{m['mean_excess_best_possible_pct']}%"],
    ]))
    w("<p class='note'>Genuine positive cross-sectional skill (IC &approx;0.20), but "
      "always-Goldilocks is a strong sample baseline &mdash; the predictor's value is "
      "risk-adjusted, not raw capture.</p>")

    # 5 backtest
    w("<h2>5. Allocation &amp; backtest vs baselines</h2>")
    w(f"<p>Soft mixture-of-experts: W<sub>sleeve</sub> = &Sigma;<sub>k</sub> alloc<sub>k</sub> "
      "&middot; expert<sub>k</sub>, with turnover smoothing (EWMA), vol targeting "
      f"({int(bt['config']['target_vol']*100)}% target, {int(bt['config']['vol_cap']*100)}% cap), "
      f"and cash-on-low-confidence. Walk-forward {escape(str(bt['config']['oos_span']))}.</p>")
    order = sorted(bt["strategies"].items(), key=lambda kv: -(kv[1]["sharpe"] or -9))
    rows, best_i = [], None
    for i, (name, s) in enumerate(order):
        if name == "MoE (this model)":
            best_i = i
        rows.append([name, s["ann_return_pct"], s["ann_vol_pct"], s["sharpe"],
                     s["max_dd_pct"], s["calmar"], s["avg_monthly_turnover_pct"]])
    w(tbl(["strategy", "ret %", "vol %", "Sharpe", "maxDD %", "Calmar", "turnover %"], rows, best_i))
    w("<h3>Stress-episode attribution (MoE vs always-Goldilocks, total return)</h3>")
    er = [[k, f"{v['MoE_total_ret_pct']:+}%", f"{v['Goldilocks_total_ret_pct']:+}%"]
          for k, v in bt["stress_episode_attribution"].items()]
    w(tbl(["episode", "MoE", "Goldilocks"], er))
    w("<p class='note'>The MoE protects in 2008 and especially 2022 (stagflation tilt); it "
      "gives up upside in the 2020 V-recovery (de-risked into the vol spike) &mdash; the "
      "honest cost of risk management.</p>")

    # 6 robustness / limitations
    w("<h2>6. Robustness &amp; limitations</h2><ul>")
    w("<li><b>Experts are full-sample oracle templates</b> (the teacher step) &mdash; static "
      "vectors, but their regime dating is in-sample; only the predictor is walk-forward. "
      "Raw MoE return therefore inherits some in-sample optimism.</li>")
    w("<li><b>Heavy shrinkage required</b>: the predictor only has positive skill with strong "
      "regularization (embargoed-CV alpha &asymp;1000-3000); low alpha overfits.</li>")
    w("<li><b>Stagflation is data-thin</b> (2022 + 1990; the 1970s predate tradable data) &mdash; "
      "the most fragile conclusion; carries the heaviest caveat.</li>")
    w("<li><b>A simple cash-in-stagflation rule is competitive</b> &mdash; much of the ML's value "
      "is automating crisis de-risking a heuristic also captures.</li>")
    w("<li><b>Frictionless</b>: futures financing spread / transaction costs not yet charged "
      "(turnover is modest, ~6%/mo for the MoE).</li></ul>")

    # 7 separation
    w("<h2>7. What is robust vs tentative</h2><ul>")
    w("<li><span class='tag good'>robust directional</span> inflation-up shorts duration / "
      "favors commodities + trend; growth drives EQ. MACRO trend is crisis alpha.</li>")
    w("<li><span class='tag warn'>tentative template</span> the exact expert exposure sizes "
      "(in-sample ceilings shrunk to round numbers).</li>")
    w("<li><span class='tag warn'>statistically-supported signal</span> the predictor's "
      f"cross-sectional IC (&approx;{m['pooled_rank_ic']}) with heavy shrinkage.</li>")
    w("<li><span class='tag bad'>not yet implementation-ready</span> deploy advisory-only; "
      "add cost/financing audit and live tracking before any capital decision.</li></ul>")

    w("<p class='note'>Generated from committed artifacts: policy_experts.json, "
      "policy_expert_model.json, policy_expert_backtest.json. Reproduce via "
      "scripts/research/policy_expert_*.py. No execution; read-only re the broker.</p>")
    w("</body></html>")
    OUT_HTML.write_text("\n".join(P), encoding="utf-8")
    print(f"wrote {OUT_HTML}  ({OUT_HTML.stat().st_size//1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
