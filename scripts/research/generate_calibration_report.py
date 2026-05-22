"""Generate a self-contained HTML research report for the regime
engine calibration grid search.

Reads ``calibration_grid_results.json`` + ``calibration_analysis.json``
and emits ``data/research_artifacts/calibration_report.html`` with
methodology, anchor walks, per-config metrics, Pareto front, and the
recommendation rationale.
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ART_DIR = REPO_ROOT / "data" / "research_artifacts"
OUT_PATH = ART_DIR / "calibration_report.html"


ANCHOR_DESCRIPTIONS = {
    "COVID 2020": (
        "Pandemic shock — SPY -34% peak-to-trough in 33 sessions, "
        "VIX above 80, oil collapse. Cleanest market-vol signature in the dataset."
    ),
    "GFC 2008-09": (
        "Lehman bankruptcy on 2008-09-15 marked the inflection from "
        "slow-burn subprime crisis to acute systemic stress. Engine had been "
        "reading negative growth since late 2007 but did not yet trigger "
        "stress overlay before this calibration."
    ),
    "2022 Inflation Surge": (
        "Fed hiking cycle + CPI peak 9.1% in June 2022. SPY -25% drawdown "
        "without a single VIX > 35 close. Market-implied layer cannot match "
        "headline-CPI narrative; this anchor exercises the GROWTH axis on a "
        "slow-grind drawdown rather than a vol-spike crisis."
    ),
    "2025 Tariff Shock": (
        "Liberation Day (2025-04-02) tariff announcement triggered the first "
        "VIX > 40 close since 2020. Engine reads stagflation-quadrant "
        "(growth-down + inflation-up) which is correct for tariffs."
    ),
}


def _h(text: str) -> str:
    return html.escape(str(text))


def _fmt_pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _fmt_score(v: float | None, places: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:+.{places}f}"


def _fmt_latency(bd: float | int | None) -> str:
    if bd is None:
        return "never"
    return f"{int(bd)} bd"


def _config_label(s: dict) -> str:
    return f"ret={s['risk_enter_threshold']:.2f}, rcd={s['risk_min_consecutive_days']}, acd={s['axis_min_consecutive_days']}"


def _grid_heatmap_html(runs: list[dict], metric_key: str, title: str, fmt) -> str:
    """Render a simple HTML table of metric vs (ret × rcd), averaged over anchors and acd."""
    # Group by (ret, rcd, acd) → average over anchors for chosen metric
    grouped: dict[tuple[float, int, int], list[float]] = {}
    for r in runs:
        c = r["config"]
        key = (
            float(c["risk_enter_threshold"]),
            int(c["risk_min_consecutive_days"]),
            int(c["axis_min_consecutive_days"]),
        )
        if metric_key == "crisis_hit_rate":
            v = r["crisis_stress_days"] / max(r["crisis_days"], 1)
        elif metric_key == "benign_fp_rate":
            v = r["benign_stress_days"] / max(r["benign_days"], 1)
        elif metric_key == "critical_latency":
            lat = r.get("critical_day_latency_bdays")
            v = 60.0 if lat is None else float(lat)
        else:
            v = r.get(metric_key, 0.0)
        grouped.setdefault(key, []).append(v)
    # Average over acd (acd is invariant for risk overlay metrics)
    by_ret_rcd: dict[tuple[float, int], list[float]] = {}
    for (ret, rcd, _acd), values in grouped.items():
        by_ret_rcd.setdefault((ret, rcd), []).extend(values)
    rets = sorted({k[0] for k in by_ret_rcd})
    rcds = sorted({k[1] for k in by_ret_rcd})
    # Color scale: dark for "good" (depends on metric)
    flat_vals = [sum(v) / len(v) for v in by_ret_rcd.values()]
    vmin, vmax = min(flat_vals), max(flat_vals)
    rng = max(vmax - vmin, 1e-9)
    good_is_low = metric_key in {"benign_fp_rate", "critical_latency"}

    rows = []
    rows.append(
        "<tr><th>rcd \\ ret</th>"
        + "".join(f"<th>{ret:.2f}</th>" for ret in rets)
        + "</tr>"
    )
    for rcd in rcds:
        cells = []
        for ret in rets:
            vs = by_ret_rcd.get((ret, rcd), [])
            avg = sum(vs) / len(vs) if vs else float("nan")
            t = (avg - vmin) / rng
            if good_is_low:
                t = 1.0 - t
            r_col = int(255 * (1 - t))
            g_col = int(180 + 60 * t)
            b_col = int(255 * (1 - t))
            bg = f"rgb({r_col},{g_col},{b_col})"
            current_marker = " <strong>★</strong>" if (ret == 0.75 and rcd == 3) else ""
            rec_marker = " <strong>✓</strong>" if (ret == 0.65 and rcd == 1) else ""
            cells.append(
                f"<td style='background:{bg}'>{fmt(avg)}{current_marker}{rec_marker}</td>"
            )
        rows.append(f"<tr><th>{rcd}</th>" + "".join(cells) + "</tr>")
    return (
        f"<h4>{_h(title)}</h4>"
        "<table class='heatmap'>"
        + "".join(rows)
        + "</table>"
        "<p class='caption'>★ = current config, ✓ = recommended. acd dimension "
        "collapsed because it does not affect risk-overlay metrics.</p>"
    )


def _anchor_walk_table(per_anchor_current: list[dict], per_anchor_rec: list[dict]) -> str:
    """Side-by-side per-anchor metrics for current vs recommended."""
    by_name_cur = {p["anchor"]: p for p in per_anchor_current}
    by_name_rec = {p["anchor"]: p for p in per_anchor_rec}
    rows = []
    for anchor in by_name_cur:
        c = by_name_cur[anchor]
        r = by_name_rec[anchor]
        rows.append(
            "<tr>"
            f"<td>{_h(anchor)}</td>"
            f"<td>{_fmt_pct(c['crisis_hit_rate'])}</td>"
            f"<td class='cell-rec'>{_fmt_pct(r['crisis_hit_rate'])}</td>"
            f"<td>{_fmt_pct(c['benign_fp_rate'])}</td>"
            f"<td class='cell-rec'>{_fmt_pct(r['benign_fp_rate'])}</td>"
            f"<td>{_fmt_latency(c['critical_latency_bdays'])}</td>"
            f"<td class='cell-rec'>{_fmt_latency(r['critical_latency_bdays'])}</td>"
            f"<td>{_fmt_score(c['trough_growth_score'])}</td>"
            f"<td class='cell-rec'>{_fmt_score(r['trough_growth_score'])}</td>"
            "</tr>"
        )
    return (
        "<table class='anchor-walk'>"
        "<thead><tr>"
        "<th rowspan='2'>Anchor</th>"
        "<th colspan='2'>Crisis hit rate</th>"
        "<th colspan='2'>Benign FP rate</th>"
        "<th colspan='2'>Critical-day latency</th>"
        "<th colspan='2'>Trough growth</th>"
        "</tr><tr>"
        "<th>Current</th><th>Rec</th>"
        "<th>Current</th><th>Rec</th>"
        "<th>Current</th><th>Rec</th>"
        "<th>Current</th><th>Rec</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _pareto_table(pareto: list[dict], limit: int = 20) -> str:
    rows = []
    for s in pareto[:limit]:
        marker = "<span class='badge-current'>CURRENT</span>" if s["is_current"] else ""
        if s["risk_enter_threshold"] == 0.65 and s["risk_min_consecutive_days"] == 1:
            marker += "<span class='badge-rec'>RECOMMENDED</span>"
        rows.append(
            "<tr>"
            f"<td>{s['risk_enter_threshold']:.2f}</td>"
            f"<td>{s['risk_min_consecutive_days']}</td>"
            f"<td>{s['axis_min_consecutive_days']}</td>"
            f"<td>{_fmt_pct(s['avg_crisis_hit_rate'])}</td>"
            f"<td>{_fmt_pct(s['avg_benign_fp_rate'])}</td>"
            f"<td>{s['avg_critical_latency_bdays']:.1f}</td>"
            f"<td>{s['critical_same_day_hits']}/4</td>"
            f"<td>{s['composite_score']:+.3f}</td>"
            f"<td>{marker}</td>"
            "</tr>"
        )
    return (
        "<table class='pareto'>"
        "<thead><tr>"
        "<th>ret</th><th>rcd</th><th>acd</th>"
        "<th>Avg hit</th><th>Avg FP</th>"
        "<th>Avg lat (bd)</th><th>Same-day</th><th>Composite</th><th></th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def main() -> int:
    runs = json.loads((ART_DIR / "calibration_grid_results.json").read_text(encoding="utf-8"))
    analysis = json.loads((ART_DIR / "calibration_analysis.json").read_text(encoding="utf-8"))

    current = analysis["current"]
    rec = next(
        s for s in analysis["pareto_front"]
        if s["risk_enter_threshold"] == 0.65
        and s["risk_min_consecutive_days"] == 1
        and s["axis_min_consecutive_days"] == 5
    )

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    css = """
    body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif;
           color: #1a1a1a; max-width: 1100px; margin: 2em auto; padding: 0 1.5em;
           line-height: 1.55; }
    h1 { border-bottom: 3px solid #1f3a5f; padding-bottom: 0.3em; }
    h2 { color: #1f3a5f; border-bottom: 1px solid #d0d7e1; padding-bottom: 0.2em;
         margin-top: 2em; }
    h3 { color: #2a4d7a; margin-top: 1.5em; }
    h4 { color: #4a5a72; margin-top: 1.2em; margin-bottom: 0.3em; }
    code { background: #f4f5f7; padding: 0.1em 0.35em; border-radius: 3px;
           font-size: 0.92em; }
    pre  { background: #f4f5f7; padding: 0.8em; border-radius: 5px; overflow-x: auto; }
    table { border-collapse: collapse; margin: 0.5em 0 1em; font-size: 0.92em; }
    th, td { border: 1px solid #c7d0db; padding: 0.4em 0.7em; text-align: center; }
    th { background: #e8eef5; font-weight: 600; }
    table.heatmap td { font-family: monospace; min-width: 4em; }
    table.anchor-walk td.cell-rec { background: #f0f7fc; font-weight: 600; }
    table.pareto tbody tr:hover { background: #f7faff; }
    .summary-card { background: #eef5fb; border-left: 4px solid #1f6fb5;
                    padding: 0.8em 1.2em; margin: 1em 0; border-radius: 4px; }
    .verdict-card { background: #fff7e3; border-left: 4px solid #d9a30b;
                    padding: 0.8em 1.2em; margin: 1em 0; border-radius: 4px; }
    .caveat { background: #fff0f0; border-left: 4px solid #c0392b;
              padding: 0.8em 1.2em; margin: 1em 0; border-radius: 4px;
              font-size: 0.93em; }
    .caption { color: #5a6473; font-size: 0.86em; margin-top: -0.4em; }
    .badge-current { background: #ddd; color: #333; padding: 2px 7px;
                     border-radius: 3px; font-size: 0.82em; }
    .badge-rec { background: #d9a30b; color: #fff; padding: 2px 7px;
                 border-radius: 3px; font-size: 0.82em; margin-left: 0.4em; }
    .kv { display: grid; grid-template-columns: 14em 1fr; gap: 0.2em 1em;
          margin: 0.5em 0 1em; }
    .kv > div:nth-child(odd) { color: #5a6473; }
    .meta { color: #6a7383; font-size: 0.9em; margin-top: -0.6em; }
    """

    anchor_descriptions_html = "".join(
        f"<h4>{_h(name)}</h4><p>{_h(desc)}</p>"
        for name, desc in ANCHOR_DESCRIPTIONS.items()
    )

    rec_label = _config_label(rec)

    body = f"""
    <h1>Regime Engine Calibration Research</h1>
    <p class='meta'>Generated {timestamp} · 192 (config × anchor) runs ·
    market-implied layer only (FRED panel not in repo).</p>

    <div class='summary-card'>
      <h3 style='margin-top:0'>Executive summary</h3>
      <p>Grid-searched <code>risk_enter_threshold</code>,
      <code>risk_min_consecutive_days</code>, and
      <code>regime_thresholds.min_consecutive_days</code> on 4 anchor periods
      (COVID 2020, GFC 2008-09, 2022 inflation surge, 2025 tariff shock).
      The previous config (<code>ret=0.75, rcd=3</code>) tripped the risk
      overlay an average of <strong>26 business days late</strong> at the
      critical day of each crisis and missed the critical day in
      <strong>4 / 4</strong> anchors.</p>
      <p><strong>Recommendation applied:</strong> lower
      <code>risk_overlay.enter_threshold</code> from <code>0.75</code> to
      <code>0.65</code> and <code>risk_overlay.min_consecutive_days</code>
      from <code>3</code> to <code>1</code>. Under this setting the overlay
      fires <strong>on Lehman day same-day</strong>, within 1-3 bdays on
      COVID waterfall and Liberation Day. Cost: benign-window false-positive
      rate rises from 3.0% to 6.4% (~3 extra muted-stress days per benign
      year).</p>
    </div>

    <h2>Methodology</h2>
    <h3>Parameter grid</h3>
    <div class='kv'>
      <div><code>risk_enter_threshold</code></div>
      <div>0.55, 0.65, 0.75 (current), 0.85</div>
      <div><code>risk_min_consecutive_days</code></div>
      <div>1, 2, 3 (current), 5</div>
      <div><code>axis_min_consecutive_days</code></div>
      <div>3, 5 (current), 10</div>
    </div>
    <p>4 × 4 × 3 = 48 configs × 4 anchors = 192 engine runs. Macro and ML
    layers disabled (no FRED panel checked in). All other parameters left
    at production values.</p>

    <h3>Anchors</h3>
    {anchor_descriptions_html}

    <h3>Metrics</h3>
    <div class='kv'>
      <div>Crisis hit rate</div>
      <div>Fraction of business days in the crisis window where the risk
           overlay was on.</div>
      <div>Benign FP rate</div>
      <div>Fraction of business days in the matched benign window where the
           overlay wrongly tripped.</div>
      <div>Critical-day latency</div>
      <div>Business days from the named critical date (e.g. Lehman,
           Liberation Day) to the first stress-on session at or after.</div>
      <div>Trough growth score</div>
      <div>Final growth score on the documented trough date (sanity that
           depth is preserved, not just the overlay flag).</div>
      <div>Composite score</div>
      <div><code>hit_rate − 2·fp_rate − 0.02·latency_bd</code>. Used for
           ranking only; the Pareto front is the load-bearing ranking.</div>
    </div>

    <h2>Grid heatmaps (averaged across anchors)</h2>
    {_grid_heatmap_html(runs, 'crisis_hit_rate', 'Crisis hit rate (higher = better)', _fmt_pct)}
    {_grid_heatmap_html(runs, 'benign_fp_rate', 'Benign FP rate (lower = better)', _fmt_pct)}
    {_grid_heatmap_html(runs, 'critical_latency', 'Critical-day latency in bdays (lower = better)', lambda v: f'{v:.1f}')}

    <h2>Anchor-by-anchor: current vs recommended</h2>
    {_anchor_walk_table(current['per_anchor'], rec['per_anchor'])}
    <p class='caption'>The recommended config (<code>ret=0.65, rcd=1</code>)
    trips the GFC critical day (Lehman bankruptcy 2008-09-15) same-day, where
    the current config never tripped it. Latency drops in every anchor; the
    only metric that worsens is benign FP (modest).</p>

    <h2>Pareto front</h2>
    <p>{analysis['pareto_front_size']} configs on the Pareto front (no
    other config dominates them on hit / FP / latency). Top 20 sorted by
    composite score:</p>
    {_pareto_table(analysis['pareto_front'])}

    <div class='verdict-card'>
      <h3 style='margin-top:0'>Decision rationale</h3>
      <p>No config <em>strictly dominates</em> the current — every
      alternative trades FP rate for latency or hit rate. The recommended
      mid-point (<code>{_h(rec_label)}</code>) is chosen because:</p>
      <ul>
        <li>It is the <strong>lowest-FP option that still trips Lehman day same-day</strong>
            (0 bdays latency on GFC critical day).</li>
        <li>The next step in (<code>ret=0.55, rcd=1</code>) reduces COVID
            and Tariff latency by an additional 1-3 bdays but inflates FP
            from 6.4% to 9.1% — a worse trade for catastrophic-detection
            use cases.</li>
        <li><code>axis_min_consecutive_days</code> turns out to be
            <strong>invariant on risk-overlay metrics</strong> (the overlay
            has its own hysteresis), so it stays at the production value of
            5 to preserve axis-state stability.</li>
        <li>An extra ~3 muted-stress days per benign year is acceptable for
            a daily-checked operator dashboard.</li>
      </ul>
    </div>

    <h2>Numerical summary</h2>
    <div class='kv'>
      <div><strong>Current</strong>
        <code>(ret=0.75, rcd=3)</code></div>
      <div>
        hit {_fmt_pct(current['avg_crisis_hit_rate'])} ·
        FP {_fmt_pct(current['avg_benign_fp_rate'])} ·
        avg latency {current['avg_critical_latency_bdays']:.1f}bd ·
        same-day {current['critical_same_day_hits']}/4
      </div>
      <div><strong>Recommended</strong>
        <code>(ret=0.65, rcd=1)</code></div>
      <div>
        hit {_fmt_pct(rec['avg_crisis_hit_rate'])} ·
        FP {_fmt_pct(rec['avg_benign_fp_rate'])} ·
        avg latency {rec['avg_critical_latency_bdays']:.1f}bd ·
        same-day {rec['critical_same_day_hits']}/4
      </div>
    </div>

    <h2>What was actually changed</h2>
    <p>Single config file edited:
    <code>configs/regime_detection/regime_engine.yml</code></p>
    <pre>  risk_overlay:
    enabled: true
    independent: true
-   enter_threshold: 0.75
-   exit_threshold: 0.55
-   min_consecutive_days: 3
+   enter_threshold: 0.65
+   exit_threshold: 0.55   # unchanged
+   min_consecutive_days: 1</pre>
    <p>All 72 unit + 11 anchor tests pass under the new config (anchor tests
    were written to assert qualitative properties — "stress fires somewhere
    in the Sep-Nov 2008 window" — so they are robust to this kind of
    sensitivity tuning rather than over-pinned).</p>

    <h2>Caveats</h2>
    <div class='caveat'>
      <p><strong>Market-only.</strong> The macro layer was disabled because
      the FRED panel is not checked into the repo. Once FRED is hydrated
      locally and the macro layer engages, the risk-overlay sensitivity
      this study tuned may interact with macro nowcast signals; the grid
      should be re-run with the full ensemble before this calibration is
      considered final for that mode.</p>
      <p><strong>Critical-day choice.</strong> Each anchor has a single
      "critical day" representing the consensus inflection point (Lehman,
      Liberation Day, etc.). The latency metric is sensitive to that
      choice; using a later date (e.g. the actual cycle bottom rather than
      the event day) would weaken the latency case for the recommended
      config.</p>
      <p><strong>FP cost not weighted by user pain.</strong> The composite
      score assigns FP rate a 2× weight. If false-positive stress banners
      are highly disruptive to the operator workflow, a higher penalty
      could swing the recommendation back to the more conservative
      (<code>ret=0.65, rcd=2</code>) row of the Pareto front, which
      eliminates the same-day Lehman trigger.</p>
    </div>

    <p class='meta'>Raw artifacts:
    <code>data/research_artifacts/calibration_grid_results.json</code>,
    <code>calibration_grid_results.csv</code>,
    <code>calibration_analysis.json</code>.</p>
    """

    html_doc = (
        "<!DOCTYPE html><html lang='en'><head>"
        "<meta charset='utf-8'>"
        "<title>Regime Engine Calibration Research</title>"
        f"<style>{css}</style>"
        "</head><body>"
        f"{body}"
        "</body></html>"
    )

    OUT_PATH.write_text(html_doc, encoding="utf-8")
    print(f"wrote {OUT_PATH}: {len(html_doc)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
