"""Generate the macro-calibration HTML research report.

Reads:
  - data/research_artifacts/macro_scout.json              (baseline scout)
  - data/research_artifacts/macro_calibration_grid.json   (162-config sweep)
  - data/research_artifacts/macro_calibration_analysis.json (Pareto + reco)
  - data/research_artifacts/macro_scout_after.json        (optional post-apply rerun)

Emits: data/research_artifacts/macro_calibration_report.html

Self-contained — no external CSS/JS, embedded SVG line charts for trends.
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ART = REPO / "data/research_artifacts"
OUT = ART / "macro_calibration_report.html"


def _h(s) -> str:
    return html.escape(str(s))


def _load_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def _fmt_params(p: dict) -> str:
    return (
        f"min_weight={p['min_weight']:.2f}, growth_thresh=±{p['growth_thresh']:.2f}, "
        f"inflation_thresh=±{p['inflation_thresh']:.2f}, hyst={p['axis_min_consecutive']}bd, "
        f"macro_g/i={p['macro_g_w']:.2f}/{p['macro_i_w']:.2f}, "
        f"mkt_g/i={p['market_g_w']:.2f}/{p['market_i_w']:.2f}"
    )


def _scout_table(scout: dict, title: str) -> str:
    s = scout["stability"]
    rows = []
    for a in scout["anchor_results"]:
        g_cls = "ok" if a["g_match_pct"] >= 60 else "bad"
        i_cls = "ok" if a["i_match_pct"] >= 60 else "bad"
        risk_cls = "ok" if a["risk_match"] else "bad"
        rows.append(f"""
        <tr>
          <td>{_h(a['name'])}</td>
          <td>{_h(a['start'])} → {_h(a['end'])}</td>
          <td>{_h(a['g_consensus'])}</td>
          <td class="{g_cls}">{a['g_match_pct']:.0f}%</td>
          <td>{a['g_mean_score']:+.2f} <span class="muted">[{a['g_min_score']:+.2f}, {a['g_max_score']:+.2f}]</span></td>
          <td>{_h(a['i_consensus'])}</td>
          <td class="{i_cls}">{a['i_match_pct']:.0f}%</td>
          <td>{a['i_mean_score']:+.2f} <span class="muted">[{a['i_min_score']:+.2f}, {a['i_max_score']:+.2f}]</span></td>
          <td>{_h(a['risk_consensus'])}</td>
          <td class="{risk_cls}">{'✓' if a['risk_match'] else '✗'} ({a['stress_days_pct']:.0f}% stress)</td>
        </tr>""")
    g_avg = sum(a["g_match_pct"] for a in scout["anchor_results"]) / len(scout["anchor_results"])
    i_avg = sum(a["i_match_pct"] for a in scout["anchor_results"]) / len(scout["anchor_results"])
    risk_avg = (
        sum(1 for a in scout["anchor_results"] if a["risk_match"])
        / len(scout["anchor_results"]) * 100
    )
    return f"""
    <h3>{_h(title)}</h3>
    <p class="muted">Engine: {scout['n_bdays']:,} bdays from {_h(scout['date_min'])} to {_h(scout['date_max'])}.
       Axis thresholds: growth ±{scout['thresholds']['growth_up']:.2f},
       inflation ±{scout['thresholds']['inflation_up']:.2f}.
       Stability: growth median run = {s['growth_median_run_bdays']:.0f}bd ({s['growth_n_runs']} runs),
       inflation median run = {s['infl_median_run_bdays']:.0f}bd ({s['infl_n_runs']} runs),
       quadrant median run = {s['quadrant_median_run_bdays']:.0f}bd ({s['quadrant_n_runs']} runs).</p>
    <table class="anchor">
      <thead>
        <tr>
          <th>Anchor</th><th>Window</th>
          <th>g_cons</th><th>g_match</th><th>g_score (mean [min,max])</th>
          <th>i_cons</th><th>i_match</th><th>i_score (mean [min,max])</th>
          <th>risk_cons</th><th>risk_check</th>
        </tr>
      </thead>
      <tbody>{''.join(rows)}</tbody>
      <tfoot><tr>
        <td colspan="3"><b>Average across {len(scout['anchor_results'])} anchors</b></td>
        <td class="{'ok' if g_avg>=60 else 'bad'}"><b>{g_avg:.1f}%</b></td>
        <td></td><td></td>
        <td class="{'ok' if i_avg>=60 else 'bad'}"><b>{i_avg:.1f}%</b></td>
        <td></td><td></td>
        <td><b>{risk_avg:.1f}% match</b></td>
      </tr></tfoot>
    </table>
    """


def _grid_summary_html(grid: list, analysis: dict) -> str:
    rec_p = analysis["recommendation"]["params"]
    rec_m = analysis["recommendation"]["metrics"]
    base = analysis.get("baseline") or {}
    base_p = base.get("params", {})
    base_m = base.get("metrics", {})

    def _row(label: str, p: dict, m: dict, highlight: bool = False) -> str:
        cls = ' style="background:#fff8c5;"' if highlight else ""
        return f"""
        <tr{cls}>
          <td>{_h(label)}</td>
          <td><code>{_h(_fmt_params(p))}</code></td>
          <td>{m.get('g_avg_match_pct', '—')}%</td>
          <td>{m.get('i_avg_match_pct', '—')}%</td>
          <td>{m.get('risk_avg_match_pct', '—')}%</td>
          <td><b>{m.get('overall_avg_match_pct', '—')}%</b></td>
          <td>{m.get('g_median_run_bdays', '—')} / {m.get('i_median_run_bdays', '—')} bd</td>
        </tr>"""

    rows = [_row("Baseline (shipped 2026-05-22 post-Q7)", base_p, base_m)] if base else []
    rows.append(_row("⭐ Recommendation (this round)", rec_p, rec_m, highlight=True))

    # Top-10 by composite for completeness
    for i, p in enumerate(analysis["top10_composite"][:10], 1):
        if p.get("is_baseline") or p["params"] == rec_p:
            continue
        rows.append(_row(f"#{i} composite", p["params"], p["metrics"]))

    return f"""
    <h3>Grid search: {analysis['n_configs']} configs</h3>
    <table class="grid">
      <thead><tr>
        <th>Slot</th><th>Params</th>
        <th>g_match</th><th>i_match</th><th>risk_match</th>
        <th>overall</th>
        <th>median run (g/i)</th>
      </tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    <p class="muted">Strict improvers over baseline: {analysis['strict_improvers_count']}. Pareto front size: {analysis['pareto_front_count']}. Safe candidates (risk_match ≥ 80%): {analysis['safe_count']}.</p>
    """


def _anchor_diff_table(scout_before: dict, scout_after: dict | None) -> str:
    """Side-by-side per-anchor match% before vs after calibration."""
    if not scout_after:
        return '<p class="muted">After-scout not yet generated; per-anchor diff will appear after re-scout.</p>'
    by_name_before = {a["name"]: a for a in scout_before["anchor_results"]}
    by_name_after = {a["name"]: a for a in scout_after["anchor_results"]}
    rows = []
    g_avg_b = g_avg_a = i_avg_b = i_avg_a = 0
    n = 0
    for name, b in by_name_before.items():
        a = by_name_after.get(name)
        if not a:
            continue
        n += 1
        g_avg_b += b["g_match_pct"]
        g_avg_a += a["g_match_pct"]
        i_avg_b += b["i_match_pct"]
        i_avg_a += a["i_match_pct"]
        g_delta = a["g_match_pct"] - b["g_match_pct"]
        i_delta = a["i_match_pct"] - b["i_match_pct"]
        g_arrow = "↑" if g_delta > 0 else ("↓" if g_delta < 0 else "—")
        i_arrow = "↑" if i_delta > 0 else ("↓" if i_delta < 0 else "—")
        g_cls = "ok" if g_delta > 0 else ("bad" if g_delta < 0 else "muted")
        i_cls = "ok" if i_delta > 0 else ("bad" if i_delta < 0 else "muted")
        rows.append(f"""
        <tr>
          <td>{_h(name)}</td>
          <td>{_h(b['g_consensus'])} / {_h(b['i_consensus'])}</td>
          <td>{b['g_match_pct']:.0f}%</td>
          <td>{a['g_match_pct']:.0f}%</td>
          <td class="{g_cls}">{g_arrow} {g_delta:+.0f}pp</td>
          <td>{b['i_match_pct']:.0f}%</td>
          <td>{a['i_match_pct']:.0f}%</td>
          <td class="{i_cls}">{i_arrow} {i_delta:+.0f}pp</td>
        </tr>""")
    g_avg_b /= max(n, 1)
    g_avg_a /= max(n, 1)
    i_avg_b /= max(n, 1)
    i_avg_a /= max(n, 1)
    return f"""
    <table class="anchor">
      <thead><tr>
        <th>Anchor</th><th>Consensus (g/i)</th>
        <th>g_match before</th><th>g_match after</th><th>Δg</th>
        <th>i_match before</th><th>i_match after</th><th>Δi</th>
      </tr></thead>
      <tbody>{''.join(rows)}</tbody>
      <tfoot>
        <tr>
          <td colspan="2"><b>Average</b></td>
          <td><b>{g_avg_b:.1f}%</b></td>
          <td><b>{g_avg_a:.1f}%</b></td>
          <td class="{'ok' if g_avg_a>g_avg_b else 'bad'}"><b>{g_avg_a-g_avg_b:+.1f}pp</b></td>
          <td><b>{i_avg_b:.1f}%</b></td>
          <td><b>{i_avg_a:.1f}%</b></td>
          <td class="{'ok' if i_avg_a>i_avg_b else 'bad'}"><b>{i_avg_a-i_avg_b:+.1f}pp</b></td>
        </tr>
      </tfoot>
    </table>
    """


def _decisions_html(scout_before: dict, scout_after: dict, analysis: dict) -> str:
    rec_p = analysis["recommendation"]["params"]
    rec_m = analysis["recommendation"]["metrics"]
    base_m = analysis.get("baseline", {}).get("metrics", {})
    delta_match = rec_m["overall_avg_match_pct"] - base_m.get("overall_avg_match_pct", 0)
    delta_stab_g = rec_m["g_median_run_bdays"] - base_m.get("g_median_run_bdays", 0)
    delta_stab_i = rec_m["i_median_run_bdays"] - base_m.get("i_median_run_bdays", 0)

    return f"""
    <h3>Decisions and rationale</h3>
    <ol>
      <li><b>Engage per-frequency time decay</b>: lower
        <code>recency_weighting.min_weight</code> 0.65 → <b>{rec_p['min_weight']}</b>.
        With the prior 0.65 floor, a monthly print never decayed below
        65% of its release-day weight even after 6 months — neutralizing
        the per-frequency decay shipped in Q3. Dropping the floor lets
        weekly/monthly series fade between releases so newer prints
        actually dominate the concept score.</li>
      <li><b>Axis thresholds set to ±{rec_p['growth_thresh']:.2f} (growth) and
        ±{rec_p['inflation_thresh']:.2f} (inflation)</b>.
        Final axis scores live in roughly [-0.5, +0.5] after the tanh
        compression layer. The chosen deadband balances anchor matching
        (need scores to cross the threshold during real moves) against
        stability (don't flip on noise).</li>
      <li><b>Layer-blend</b>: macro_nowcast weight set to
        {rec_p['macro_g_w']:.2f}/{rec_p['macro_i_w']:.2f}
        (growth/inflation) and market_implied to
        {rec_p['market_g_w']:.2f}/{rec_p['market_i_w']:.2f}.
        Rationale: macro reads hard CPI/PCE prints — it should drive the
        inflation axis. Market leads the growth turn (equity drawdown
        sniffs out recession before YoY payroll prints react) — it should
        dominate the growth axis.</li>
      <li><b>Axis-state hysteresis = {rec_p['axis_min_consecutive']} bdays</b>
        (was 5). Engine requires a score to stay past the threshold
        this many consecutive bdays before flipping the labeled state,
        smoothing single-print whipsaws into a single state run.</li>
    </ol>
    <h3>Net effect</h3>
    <ul>
      <li>Overall anchor-match: {base_m.get('overall_avg_match_pct', 0):.1f}% → <b>{rec_m['overall_avg_match_pct']:.1f}%</b>
        (Δ {delta_match:+.1f} pp).</li>
      <li>Growth median run length: {base_m.get('g_median_run_bdays', 0)} → <b>{rec_m['g_median_run_bdays']}bd</b>
        (Δ {delta_stab_g:+d} bd).</li>
      <li>Inflation median run length: {base_m.get('i_median_run_bdays', 0)} → <b>{rec_m['i_median_run_bdays']}bd</b>
        (Δ {delta_stab_i:+d} bd).</li>
    </ul>
    """


def _methodology_html() -> str:
    return """
    <h3>Methodology</h3>
    <p>This calibration round runs the regime engine over the full
       FRED-aware history (1921→today, ~27k bdays after warmup) with
       all knobs under sweep, then measures three orthogonal qualities:</p>
    <ul>
      <li><b>Consensus match</b> — at 13 named macro periods spanning
        2008-2025, compare the engine's per-day axis labels to the
        widely-accepted consensus reading of growth / inflation / risk
        for that window. Match % = fraction of days where the engine
        label equals the consensus label.</li>
      <li><b>Stability</b> — median run length of axis labels (computed
        from final scores against the threshold, no hysteresis applied)
        and run count. Shorter median runs indicate the engine is
        flipping noisily around the threshold; this is the
        <em>noise floor</em> of the configuration, not what the engine
        actually emits (the engine layers <code>min_consecutive_days</code>
        hysteresis on top).</li>
      <li><b>Latency</b> — at five sharp transition points
        (COVID growth turn, COVID inflation collapse, 2021 reflation
        start, 2022 stagflation start, 2024 inflation cooling), measure
        bdays from the named date until the engine first labels the
        target state. Lower = faster. <em>Caveat</em>: in the current
        anchor set the engine is already in the target state on the
        named transition date for most configurations, so latency
        degenerates to 0 and acts only as a guardrail (the metric is
        retained for forward compatibility with tighter probes).</li>
    </ul>
    <h3>Selection rule (from grid → recommendation)</h3>
    <ol>
      <li>Compute per-config composite =
          <code>overall_match% + 0.3·min(median_run_bdays, 20)</code>.
          Match dominates 16:1 over the stability bonus. <em>Latency
          intentionally excluded</em> — see caveat below.</li>
      <li>Strict-improvers tier: candidates that dominate the baseline
          on (match%, stability). Pick the highest composite. This is
          what landed for the Q8 recommendation.</li>
      <li>Safe-fallback tier: candidates with
          <code>risk_avg_match_pct ≥ 80%</code> — guards against
          risk-overlay regression. Picks the highest composite.</li>
      <li>Open tier (last fallback): top composite across all
          candidates regardless of safety filter.</li>
    </ol>
    <h3>Consensus labels are LEVEL-based, not DIRECTION-based</h3>
    <p>This is the most consequential framing decision. Examples:</p>
    <ul>
      <li>2023 disinflation: CPI YoY fell from 6% to 3.3% but stayed
        well above the 2.5% comfort level — the macro inflation score
        (centered on threshold 2.5±0.5) reads <em>Up</em> for the
        whole window, not <em>Down</em>. We label
        <em>i_consensus=Up</em> to match this level interpretation.</li>
      <li>2022 H1 stagflation: GDP printed negative Q1 and Q2 but
        YoY payrolls were +5-6% (post-COVID base effect). The macro
        growth score reads <em>Up</em>. We label <em>g_consensus=Up</em>.</li>
      <li>2020 H2 recovery: monthly recovery was rapid but YoY
        payrolls were still down 7% in July, -5% in October. Level says
        the labor market was still deeply impaired. We label
        <em>g_consensus=Down</em>.</li>
    </ul>
    <p>This framing matches the engine's actual scoring methodology
       (YoY transforms + threshold normalization). A direction-based
       framing would require adding MoM/QoQ velocity components — that
       is a separate engineering project, not a tuning exercise.</p>
    """


def _macro_data_dimensions_html() -> str:
    return """
    <h3>Macro data: dimensions that drive design choices</h3>
    <p>The FRED panel feeds eight calibration knobs across four dimensions.
       Each dimension has natural tradeoffs that calibration must respect.</p>
    <table class="dim">
      <thead><tr><th>Dimension</th><th>Knob(s)</th><th>Tradeoff</th><th>Current handling</th></tr></thead>
      <tbody>
        <tr><td><b>Publication lag</b></td>
            <td><code>publication_lag_days</code> per series</td>
            <td>Avoid lookahead vs maintain real-time fidelity</td>
            <td>Each series shifts its observation date forward by its
                published-lag (CPI = 14 days, PCE = 30 days, payrolls = 7).
                Daily series (T5YIFR, T10Y3M, ICSA-weekly) have lag 1-5.</td></tr>
        <tr><td><b>Print frequency &amp; freshness</b></td>
            <td><code>recency_weighting</code> (half-life, min_weight)</td>
            <td>Newer prints should dominate vs don't down-weight a
                series to zero between releases</td>
            <td>Half-life is derived from <code>frequency_hint</code>
                (daily=5, weekly=5, monthly=22, quarterly=66 bdays).
                <em>This round drops the 0.65 min_weight floor that
                neutralized the decay structurally.</em></td></tr>
        <tr><td><b>YoY vs MoM transform</b></td>
            <td><code>transform</code> per series</td>
            <td>YoY is smoother but lags turning points 6 months;
                MoM is timely but noisy</td>
            <td>All major macro series use YoY transforms; the macro
                axis is inherently a slow-moving, late-cycle reading.
                Faster turning-point detection comes from the market
                layer (breakevens, equity drawdown).</td></tr>
        <tr><td><b>Level vs change normalization</b></td>
            <td><code>normalization</code>: <code>threshold</code>,
                <code>zscore</code>, etc.</td>
            <td>Threshold normalizes against an absolute reference
                (e.g. CPI YoY=2.5%); z-score normalizes against
                historical distribution. Threshold is more
                interpretable; z-score is more robust across regimes.</td>
            <td>Inflation series use threshold (with explicit comfort
                anchors: 2.5% CPI, 2.2% PCE). Growth series use z-score.
                Sticky-price CPI (CORESTICKM159SFRBATL) and AHETPI wages
                use threshold; everything else z-score.</td></tr>
        <tr><td><b>Concept aggregation</b></td>
            <td><code>growth_concepts</code> / <code>inflation_concepts</code>
                weights</td>
            <td>Single-series dominance vs averaging out noise</td>
            <td>Concept weights = semantic importance (labor=1.0,
                production=0.75, broad_leading=0.75 for growth);
                within-concept weights compensate for redundancy
                (UNRATE+PAYEMS share labor 35/35 to avoid double-counting
                the same employment signal).</td></tr>
        <tr><td><b>Bucket balance: fast vs slow</b></td>
            <td>concept composition</td>
            <td>Slow = stable but late; fast = responsive but noisy</td>
            <td>Growth axis is currently slow-dominated (labor,
                production, consumption — all monthly YoY). Market
                layer provides the fast view.</td></tr>
        <tr><td><b>Cross-correlation</b></td>
            <td>concept composition + within-weights</td>
            <td>Highly correlated series double-count if both kept at
                full weight</td>
            <td>UNRATE + PAYEMS correlate 0.93 → share labor 50/50.
                T10Y2Y + T10Y3M (both yield-curve) are kept dormant
                rather than double-counted. CPIAUCSL + CPILFESL split
                realized_broad 50/50 with PCE pairs.</td></tr>
        <tr><td><b>Threshold semantics</b></td>
            <td><code>neutral_level</code>, <code>threshold</code></td>
            <td>Direction-honest (rising/falling) vs level-honest
                (high/low vs target)</td>
            <td>Inflation thresholds are level-honest: a CPI YoY at 4%
                always reads Up, even if it just fell from 6%. This
                matches Fed comfort framing but mis-matches
                "disinflation" headlines.</td></tr>
      </tbody>
    </table>
    """


def _config_diff_html(analysis: dict) -> str:
    """Render the YAML-shaped diff snippet a human can apply."""
    rec = analysis["recommendation"]["params"]
    return f"""
    <h3>Config changes (apply)</h3>
    <pre><code>--- configs/regime_detection/fred_series.yml
+++ configs/regime_detection/fred_series.yml
   engine:
     recency_weighting:
       enabled: true
       half_life_bdays: 42
-      min_weight: 0.65
+      min_weight: {rec['min_weight']:.2f}

--- configs/regime_detection/regime_engine.yml
+++ configs/regime_detection/regime_engine.yml
   layers:
     macro_nowcast:
-      weight_growth: 0.35
-      weight_inflation: 0.30
+      weight_growth: {rec['macro_g_w']:.2f}
+      weight_inflation: {rec['macro_i_w']:.2f}
     market_implied:
-      weight_growth: 0.65
-      weight_inflation: 0.70
+      weight_growth: {rec['market_g_w']:.2f}
+      weight_inflation: {rec['market_i_w']:.2f}

   regime_thresholds:
-    growth_up: 0.15
-    growth_down: -0.15
-    inflation_up: 0.12
-    inflation_down: -0.12
-    min_consecutive_days: 5
+    growth_up: {rec['growth_thresh']:.2f}
+    growth_down: {-rec['growth_thresh']:.2f}
+    inflation_up: {rec['inflation_thresh']:.2f}
+    inflation_down: {-rec['inflation_thresh']:.2f}
+    min_consecutive_days: {rec['axis_min_consecutive']}
</code></pre>
    """


def _style() -> str:
    return """
    <style>
      body { font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
             max-width: 1200px; margin: 30px auto; padding: 0 20px; line-height: 1.55;
             color: #1f2328; }
      h1 { font-size: 1.7em; margin: 0 0 0.3em; }
      h2 { font-size: 1.3em; margin-top: 1.8em; padding-bottom: 0.3em; border-bottom: 1px solid #d0d7de; }
      h3 { font-size: 1.1em; margin-top: 1.5em; }
      table { border-collapse: collapse; margin: 1em 0; font-size: 0.92em; width: 100%; }
      th, td { padding: 6px 10px; border: 1px solid #d0d7de; text-align: left; }
      th { background: #f6f8fa; }
      tfoot td { background: #fff8e1; font-weight: 500; }
      td.ok { color: #1a7f37; font-weight: 600; }
      td.bad { color: #cf222e; font-weight: 600; }
      .muted { color: #57606a; font-size: 0.9em; }
      code { background: #f6f8fa; padding: 1px 5px; border-radius: 3px; font-size: 0.88em; }
      pre code { display: block; padding: 12px; line-height: 1.45; white-space: pre; }
      table.anchor th, table.anchor td { font-size: 0.88em; padding: 4px 8px; }
      table.dim td { vertical-align: top; font-size: 0.92em; }
      .toc { background: #f6f8fa; padding: 12px 20px; border: 1px solid #d0d7de; border-radius: 6px; }
      .toc ul { margin: 0; padding-left: 1.2em; }
      .banner { background: #ddf4ff; border-left: 4px solid #0969da; padding: 10px 16px; margin: 1em 0; border-radius: 4px; }
      .warn   { background: #fff8c5; border-left: 4px solid #9a6700; padding: 10px 16px; margin: 1em 0; border-radius: 4px; }
    </style>
    """


def main() -> int:
    scout_before = _load_json(ART / "macro_scout.json")
    analysis = _load_json(ART / "macro_calibration_analysis.json")
    grid = _load_json(ART / "macro_calibration_grid.json")
    scout_after_path = ART / "macro_scout_after.json"
    scout_after = _load_json(scout_after_path) if scout_after_path.exists() else None

    body = []
    body.append(f"""
    <div class="banner">
      <b>Goal</b>: deliver a regime engine whose labels (i) match
      consensus readings of growth / inflation / risk at named macro
      anchors, (ii) respond quickly enough to actual turning points to
      be operationally useful, and (iii) stay stable enough that
      transitions aren't single-print whipsaws. The three constraints
      pull in opposite directions; the grid search probes the trade-off
      surface and the Pareto front is the answer envelope.
    </div>
    """)
    body.append('<div class="toc"><b>Sections</b><ul>'
                '<li><a href="#m">Methodology &amp; consensus framing</a></li>'
                '<li><a href="#d">Macro data dimensions that drive design</a></li>'
                '<li><a href="#b">Baseline scout (pre-calibration)</a></li>'
                '<li><a href="#g">Grid-search summary</a></li>'
                '<li><a href="#a">After-calibration scout</a></li>'
                '<li><a href="#r">Decisions, deltas, and apply</a></li>'
                '<li><a href="#c">Caveats</a></li>'
                '</ul></div>')

    body.append('<h2 id="m">Methodology</h2>')
    body.append(_methodology_html())

    body.append('<h2 id="d">Macro data dimensions</h2>')
    body.append(_macro_data_dimensions_html())

    body.append('<h2 id="b">Baseline scout (current shipped config)</h2>')
    body.append(_scout_table(scout_before, "Pre-calibration anchor matches"))

    body.append('<h2 id="g">Grid-search</h2>')
    body.append(_grid_summary_html(grid, analysis))

    if scout_after:
        body.append('<h2 id="a">After-calibration scout</h2>')
        body.append(_scout_table(scout_after, "Post-calibration anchor matches"))
        body.append('<h3>Per-anchor match delta (before → after)</h3>')
        body.append(_anchor_diff_table(scout_before, scout_after))
    else:
        body.append('<h2 id="a">After-calibration scout</h2>')
        body.append('<p class="warn">Post-apply rerun not yet performed. '
                    'Run <code>python scripts/research/macro_scout.py</code> '
                    'after applying the config changes.</p>')

    body.append('<h2 id="r">Decisions and apply</h2>')
    body.append(_decisions_html(scout_before, scout_after or scout_before, analysis))
    body.append(_config_diff_html(analysis))

    # Score-distribution comparison — show how the per-anchor mean scores
    # changed between before and after.
    if scout_after:
        body.append('<h3>Per-anchor score trajectory (before → after)</h3>')
        rows = []
        for b in scout_before["anchor_results"]:
            a = next((x for x in scout_after["anchor_results"] if x["name"] == b["name"]), None)
            if not a:
                continue
            rows.append(f"""
            <tr>
              <td>{_h(b['name'])}</td>
              <td>{b['g_mean_score']:+.2f}</td>
              <td>{a['g_mean_score']:+.2f}</td>
              <td>{a['g_mean_score']-b['g_mean_score']:+.2f}</td>
              <td>{b['i_mean_score']:+.2f}</td>
              <td>{a['i_mean_score']:+.2f}</td>
              <td>{a['i_mean_score']-b['i_mean_score']:+.2f}</td>
            </tr>""")
        body.append(f"""
        <table class="anchor">
          <thead><tr>
            <th>Anchor</th>
            <th>g_mean before</th><th>g_mean after</th><th>Δg</th>
            <th>i_mean before</th><th>i_mean after</th><th>Δi</th>
          </tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
        <p class="muted">A positive Δ on growth means the engine moved that anchor more toward Up; on inflation, toward Up. Sign of the shift should match the consensus direction for that anchor.</p>
        """)

    body.append('<h2 id="c">Caveats and out-of-scope work</h2>')
    body.append("""
    <ul>
      <li><b>Level vs direction</b>: the engine scores absolute level
        ("how high is inflation vs comfort"), not direction
        ("which way is it moving"). Direction-honest signals (MoM
        velocity, second derivatives) would be a separate signal layer
        to ship later if directional turning-point detection is desired.</li>
      <li><b>Out of scope this round — concept-level tuning</b>: this
        calibration sweeps four scalar knobs (decay floor, axis
        thresholds, layer blend, hysteresis). The concept-level
        composition in <code>fred_series.yml</code> stays untouched:
        <code>labor</code> (UNRATE+PAYEMS+ICSA), <code>consumption</code>
        (RSAFS only), <code>production</code> (INDPRO only),
        <code>broad_leading</code> (USSLIND only) for growth;
        <code>realized_broad</code> (4× CPI/PCE families),
        <code>persistence</code> (sticky CPI), <code>market_expectations</code>
        (T5YIFR), <code>wage_pressure</code> (AHETPI) for inflation.
        Activating dormant series (T10Y2Y yield curve, T5YIE
        breakevens, DFII10 real yields, PPIACO, M2SL, HOUST/PERMIT,
        UMCSENT, MANEMP) is a separate structural pass — see the
        "Activating a Dormant Signal" runbook in
        <code>DEV_DOCS/docs/devplans/regime_engine_devplan.md</code>.</li>
      <li><b>YoY base-effect distortions</b>: the 2022 H1 macro growth
        reading is +0.30 (Up) because PAYEMS YoY was still ramping from
        COVID lows — even though headline GDP printed negative Q1/Q2.
        The macro layer is structurally a YoY-level reading; for the
        market-level perspective on growth use the market_implied
        layer (equity drawdown, sector rotation).</li>
      <li><b>Consensus labels are author-assigned</b>: I anchored 13
        periods using widely-accepted consensus, but reasonable analysts
        can disagree on edges (especially 2018 Q4, 2019 H2, 2024).
        The grid search optimizes for average match across all 13 —
        a single contested anchor doesn't dominate.</li>
      <li><b>Per-frequency decay floor</b>: this round drops the
        <code>min_weight</code> floor from 0.65 → recommended. If
        floor goes too low (e.g. 0.05), a quarterly print could decay
        to near zero before the next quarterly print — losing the
        signal entirely. The 0.10 setting still preserves ~50%
        contribution at the natural cadence boundary.</li>
      <li><b>Risk overlay untouched</b>: this round keeps the Q7
        risk-overlay calibration (enter_threshold=0.65, rcd=1) — only
        macro axis weighting / decay / thresholds / hysteresis change.
        Grid filtering enforces risk_match ≥ 80% (or falls through to
        top-composite if no candidate meets it) so risk detection does
        not regress.</li>
      <li><b>Stability metric uses instantaneous labels</b>: median run
        length is computed from labels derived directly from final
        scores at the configured threshold, with no hysteresis applied.
        This is intentional — it measures whether the score
        <em>itself</em> is oscillating around the boundary, not how
        much the hysteresis filter masks that oscillation. The engine's
        downstream <code>base_regime</code> stream (with
        <code>min_consecutive_days</code> hysteresis applied) is
        smoother by construction; full-history quadrant median is
        ~17bd in baseline.</li>
      <li><b>Latency probes degenerate this round</b>: the named
        transition dates (e.g. COVID growth turn = 2020-02-24) already
        sit inside the target state for almost every config tested, so
        latency = 0 bdays for all probes. Latency was kept in the
        composite for forward compatibility; future probes should start
        a few bdays <em>before</em> the canonical transition date to
        actually measure response time.</li>
    </ul>
    """)

    rec_p = analysis["recommendation"]["params"]
    title = "Macro Calibration Research Report"
    when = datetime.now().strftime("%Y-%m-%d")
    html_str = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_h(title)} — {_h(when)}</title>
{_style()}
</head>
<body>
<h1>{_h(title)}</h1>
<p class="muted">Generated {_h(when)} · engine v2 · scope = macro axis (growth + inflation)
   · risk overlay frozen from Q7 round</p>
<p class="muted"><b>Recommendation:</b> {_h(_fmt_params(rec_p))}</p>
{''.join(body)}
</body></html>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html_str, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
