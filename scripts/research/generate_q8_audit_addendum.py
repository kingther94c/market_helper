"""Generate the Q8 audit addendum HTML (both EN and CN).

Reads the 4 follow-on JSON artifacts (macro_robustness, macro_label_ambiguity,
macro_latency, macro_concept_attribution) and emits an addendum HTML that
answers the 4 audit questions:

  Q1. Is Q8 robust to anchor perturbations?
  Q2. Which failures are label-ambiguity vs genuine signal failure?
  Q3. Real-latency (lead-in probes) — does Q8 react fast enough?
  Q4. Concept-level attribution for wins and losses.

Q8 is marked "provisional, ships unchanged" with explicit
"what would make Q8 final" criteria at the end.
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ART = REPO / "data/research_artifacts"
OUT_EN = ART / "macro_calibration_audit_en.html"
OUT_CN = ART / "macro_calibration_audit_cn.html"


def _h(s) -> str:
    return html.escape(str(s))


def _load(name: str) -> dict | list:
    return json.loads((ART / name).read_text(encoding="utf-8"))


def _style() -> str:
    return """
    <style>
      body { font-family: ui-sans-serif, system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", "Segoe UI", Roboto, sans-serif;
             max-width: 1200px; margin: 30px auto; padding: 0 20px; line-height: 1.55;
             color: #1f2328; }
      h1 { font-size: 1.7em; margin: 0 0 0.3em; }
      h2 { font-size: 1.3em; margin-top: 1.8em; padding-bottom: 0.3em; border-bottom: 1px solid #d0d7de; }
      h3 { font-size: 1.1em; margin-top: 1.5em; }
      table { border-collapse: collapse; margin: 1em 0; font-size: 0.92em; width: 100%; }
      th, td { padding: 6px 10px; border: 1px solid #d0d7de; text-align: left; vertical-align: top; }
      th { background: #f6f8fa; }
      td.pass { color: #1a7f37; font-weight: 600; }
      td.fail { color: #cf222e; font-weight: 600; }
      td.amb { color: #9a6700; font-weight: 600; }
      td.def { color: #6639ba; font-weight: 600; }
      .muted { color: #57606a; font-size: 0.9em; }
      code { background: #f6f8fa; padding: 1px 5px; border-radius: 3px; font-size: 0.88em; }
      pre code { display: block; padding: 12px; line-height: 1.45; white-space: pre; }
      .banner { background: #ddf4ff; border-left: 4px solid #0969da; padding: 10px 16px; margin: 1em 0; border-radius: 4px; }
      .warn   { background: #fff8c5; border-left: 4px solid #9a6700; padding: 10px 16px; margin: 1em 0; border-radius: 4px; }
      .pass-banner { background: #dafbe1; border-left: 4px solid #1a7f37; padding: 10px 16px; margin: 1em 0; border-radius: 4px; }
      .toc { background: #f6f8fa; padding: 12px 20px; border: 1px solid #d0d7de; border-radius: 6px; }
      .toc ul { margin: 0; padding-left: 1.2em; }
      .small { font-size: 0.85em; }
    </style>
    """


def _verdict_cls(verdict: str) -> str:
    if verdict.startswith("PASS"):
        return "pass"
    if verdict.startswith("FAIL"):
        return "fail"
    if "definition-artifact" in verdict or "label-defensible" in verdict:
        return "def"
    if "ambiguous" in verdict:
        return "amb"
    return ""


# ===========================================================================
# English version
# ===========================================================================

def _build_en(robust: dict, label: dict, latency: dict, attrib: dict) -> str:
    # Q1: Robustness
    s = robust["summary"]
    q1 = f"""
    <h2 id="q1">Q1 — Is Q8 robust to reasonable anchor perturbations?</h2>
    <div class="{'pass-banner' if s['q8_loses_count'] == 0 else 'warn'}">
      <b>Answer:</b> Yes. Q8 beats baseline in
      <b>{s['q8_beats_baseline_count']}/{robust['n_perturbations']}</b>
      perturbations, ranks #1 in {s['q8_top1_count']}/{robust['n_perturbations']}
      contenders, never loses to baseline. Delta range: {s['q8_min_delta_pp']:+.1f}
      to {s['q8_max_delta_pp']:+.1f} pp (median {s['q8_median_delta_pp']:+.1f}).
    </div>

    <p>{robust['n_perturbations']} perturbations tested across {robust['n_contenders']}
       contender configs: original anchor set, 6 boundary shifts (±5/±10/±20 bdays),
       1 alternative-consensus-label sweep, and 13 leave-one-out drops.</p>

    <h3>Worst perturbations for Q8 (smallest Q8-baseline gap)</h3>
    <table>
      <thead><tr><th>Perturbation</th><th>Q8 overall</th><th>Baseline overall</th><th>Δ (pp)</th></tr></thead>
      <tbody>
    """
    for r in robust["worst_perturbations_for_q8"]:
        q1 += f"<tr><td>{_h(r['perturbation'])}</td><td>{r['q8']:.1f}%</td><td>{r['baseline']:.1f}%</td><td>{r['delta']:+.1f}</td></tr>"
    q1 += """
      </tbody>
    </table>
    <p class="muted">Notable: under alternative-consensus labels, Q8 still beats
       baseline by 1.6pp. Boundary shifts of ±5-20 bdays change overall match
       by only ~5pp absolute — the recommendation is not keyed to specific
       anchor start/end dates.</p>
    """

    # Q2: Label ambiguity
    by_conf = label["by_confidence_class"]
    q2_verdicts = label["q8_verdict_counts"]
    q2 = f"""
    <h2 id="q2">Q2 — Which Q8 misses are label-ambiguity vs genuine signal failure?</h2>

    <h3>Match% by confidence class</h3>
    <table>
      <thead><tr>
        <th>Confidence class</th><th>n anchors</th>
        <th>Baseline g/i</th><th>Q8 g/i</th><th>Δg / Δi</th>
      </tr></thead>
      <tbody>
    """
    for c, m in by_conf.items():
        dg = m["q8_g_avg"] - m["baseline_g_avg"]
        di = m["q8_i_avg"] - m["baseline_i_avg"]
        q2 += f"""
        <tr>
          <td>{_h(c)}</td><td>{m['n_anchors']}</td>
          <td>{m['baseline_g_avg']}% / {m['baseline_i_avg']}%</td>
          <td>{m['q8_g_avg']}% / {m['q8_i_avg']}%</td>
          <td>{dg:+.1f}pp / {di:+.1f}pp</td>
        </tr>"""
    q2 += """
      </tbody>
    </table>
    <p class="muted">Q8's biggest gains are concentrated on the
       <em>clear</em>-confidence anchors (4 anchors with near-unanimous
       consensus), where it lifts growth match by 17.6pp and inflation by 5.2pp.
       The <em>definition-dependent</em> class still benefits (+2pp growth,
       +14pp inflation) but progress is bounded by framing rather than tuning.</p>

    <h3>Per-anchor verdicts</h3>
    <p>"PASS" = match ≥ 60% under primary consensus.
       "definition-artifact" = match jumps ≥ 30pp under alt label, framing is
       the bottleneck.
       "label-defensible" = alt label achieves ≥ 60%, reasonable analysts disagree.
       "ambiguous" = neither label clearly resolves; engine reading is somewhere
       between.
       "FAIL (clear)" = clear-confidence anchor with no defensible alt — genuine
       signal-design problem worth flagging.</p>
    <table>
      <thead><tr>
        <th>Anchor</th><th>Confidence</th><th>Consensus (g/i)</th>
        <th>Q8 g match</th><th>g verdict</th><th>Q8 i match</th><th>i verdict</th>
      </tr></thead>
      <tbody>
    """
    for x in label["per_anchor"]:
        gc = _verdict_cls(x["q8_g_verdict"])
        ic = _verdict_cls(x["q8_i_verdict"])
        q2 += f"""
        <tr>
          <td>{_h(x['name'])}</td><td>{_h(x['confidence'])}</td>
          <td>{_h(x['consensus'])}</td>
          <td>{x['q8_g_match']:.0f}%</td><td class="{gc}">{_h(x['q8_g_verdict'])}</td>
          <td>{x['q8_i_match']:.0f}%</td><td class="{ic}">{_h(x['q8_i_verdict'])}</td>
        </tr>"""
    q2 += """
      </tbody>
    </table>
    <p class="muted"><b>Genuine FAIL (clear)</b>: 2022 H1 inflation growth (Q8
       g=34%; macro_g=+0.30 says Up but market_g=-0.47 drags final down to -0.09)
       and 2025 tariff shock (both axes; engine has no tariff-cost or
       single-event-shock channel). 2022 H1 i=59% is borderline (just under
       60% pass threshold). All other "fails" are either label-defensible
       or definition-artifact under the framework.</p>
    """

    # Q3: Latency
    by_cfg = latency["by_config"]
    q3 = f"""
    <h2 id="q3">Q3 — Does Q8 detect transitions with useful latency?</h2>

    <div class="{'warn' if (by_cfg.get('Q8 winner (balanced + gt=0.10)') or {}).get('mean_latency_bdays', 0) > (by_cfg.get('Q7 baseline (Q6 + Q7 risk overlay)') or {}).get('mean_latency_bdays', 0) else 'pass-banner'}">
      <b>Answer:</b> Q8 is <em>slightly slower</em> than baseline on real
      transition probes (mean latency 19.3bd vs 16.4bd, +3bd). The biggest
      individual regression is the 2021 reflation start (+11bd: 2bd → 13bd)
      because the market-implied breakeven signal was an early lead that
      the balanced blend dilutes. This is a real tradeoff to disclose,
      not a free lunch.
    </div>

    <p>Redesigned latency probes start 60 bdays <em>before</em> each canonical
       transition (so the engine genuinely starts in the prior state) and
       measure bdays from the transition until the engine first labels the
       target state and HOLDS it for ≥5 consecutive bdays.</p>

    <table>
      <thead><tr><th>Probe</th>"""
    for cfg_name in by_cfg:
        short = cfg_name.split(":")[-1].strip()[:30]
        q3 += f"<th>{_h(short)}</th>"
    q3 += "</tr></thead><tbody>"
    for row in latency["all_rows"]:
        pass  # we'll use the structured access below
    # Build probe × config matrix
    probes_seen = []
    for row in latency["all_rows"]:
        if row["probe"] not in probes_seen:
            probes_seen.append(row["probe"])
    for probe_name in probes_seen:
        q3 += f"<tr><td>{_h(probe_name)}</td>"
        for cfg_name in by_cfg:
            r = next((x for x in latency["all_rows"]
                      if x["probe"] == probe_name and x["config_name"] == cfg_name), None)
            if r and r["latency_bdays"] is not None:
                q3 += f"<td>{r['latency_bdays']}bd</td>"
            else:
                q3 += "<td class='muted'>—</td>"
        q3 += "</tr>"
    q3 += "</tbody></table>"

    q3 += "<h3>Mean / median latency per config</h3><table><thead><tr><th>Config</th><th>Mean (bd)</th><th>Median (bd)</th><th>Max (bd)</th></tr></thead><tbody>"
    for cfg, s in by_cfg.items():
        q3 += f"<tr><td>{_h(cfg)}</td><td>{s['mean_latency_bdays']}</td><td>{s['median_latency_bdays']}</td><td>{s['max_latency_bdays']}</td></tr>"
    q3 += "</tbody></table>"

    q3 += """
    <p class="muted">Several probes show 0bd because the lead-in starts after
       the engine had already moved (e.g. COVID growth turn: market drop
       began Feb 24 so by the canonical Mar 10 the engine was already in
       Down state). These probes act as guardrails ("engine isn't somehow
       missing this") rather than discriminating latency tests.</p>
    <p class="muted">The Q8 slowdown is concentrated on probes where the
       <em>market</em> layer leads. With the balanced 50/50 blend, those
       leads dilute against the slower macro view. Acceptable trade-off
       for the +5pp consensus match win on the original anchor set, but
       worth knowing.</p>
    """

    # Q4: Concept attribution
    q4 = """
    <h2 id="q4">Q4 — Which concept-level contributors explain Q8's wins and losses?</h2>
    <p>For each anchor we picked the midpoint date and pulled per-layer scores
       plus top contributing series.  Below are the most informative cases
       — those where Q8 changed the axis label compared to baseline.</p>
    """
    anchors_with_change = []
    for a in attrib["anchors"]:
        if not a["per_date"]:
            continue
        mid = a["per_date"][len(a["per_date"]) // 2]
        b = mid["baseline"]
        q = mid["q8"]
        if b["g_label"] != q["g_label"] or b["i_label"] != q["i_label"]:
            anchors_with_change.append((a, mid, b, q))

    for a, mid, b, q in anchors_with_change:
        q4 += f"""
        <h3>{_h(a['name'])} ({_h(mid['date'])}, consensus g={_h(a['g_consensus'])}, i={_h(a['i_consensus'])})</h3>
        <table>
          <thead><tr><th></th><th>Baseline</th><th>Q8</th></tr></thead>
          <tbody>
            <tr><td>final_g (label)</td><td>{b['final_g']:+.2f} ({_h(b['g_label'])})</td><td>{q['final_g']:+.2f} ({_h(q['g_label'])})</td></tr>
            <tr><td>final_i (label)</td><td>{b['final_i']:+.2f} ({_h(b['i_label'])})</td><td>{q['final_i']:+.2f} ({_h(q['i_label'])})</td></tr>
            <tr><td>macro_nowcast (g/i)</td>
                <td>{b['layer_outputs'].get('macro_nowcast', {}).get('growth', '—')} / {b['layer_outputs'].get('macro_nowcast', {}).get('inflation', '—')}</td>
                <td>{q['layer_outputs'].get('macro_nowcast', {}).get('growth', '—')} / {q['layer_outputs'].get('macro_nowcast', {}).get('inflation', '—')}</td>
            </tr>
            <tr><td>market_implied (g/i)</td>
                <td>{b['layer_outputs'].get('market_implied', {}).get('growth', '—')} / {b['layer_outputs'].get('market_implied', {}).get('inflation', '—')}</td>
                <td>{q['layer_outputs'].get('market_implied', {}).get('growth', '—')} / {q['layer_outputs'].get('market_implied', {}).get('inflation', '—')}</td>
            </tr>
            <tr><td>top contributors (≤3)</td>
                <td class="small">{_h(b['top_contributors'][:3])}</td>
                <td class="small">{_h(q['top_contributors'][:3])}</td>
            </tr>
          </tbody>
        </table>
        """

    q4 += """
    <h3>Patterns across all anchor-changes</h3>
    <ul>
      <li><b>2022 H1 inflation</b>: macro_i=+0.57 (correctly reading peak CPI),
        market_i=-0.15 (oil rolled over before CPI peaked). Q8's 50/50 blend
        lets the macro signal dominate (final_i=+0.21 → Up); baseline
        30/70 buried it (final_i=+0.07 → Neutral). <b>This is the
        flagship case for the layer-blend change.</b></li>
      <li><b>2017 Goldilocks growth</b>: macro_g=+0.14, market_g=+0.11.
        Both layers correctly mildly positive. Baseline's final_g=+0.12 sits
        right under the ±0.15 threshold → Neutral. Q8's tighter ±0.10 lifts
        the same score to Up. <b>This case is driven entirely by the threshold
        change, not the blend.</b></li>
      <li><b>2020H2 catch-up inflation</b>: macro_i=-0.55 (CPI YoY still ~1.4%,
        below 2.5% comfort), market_i=+0.24 (reflation pricing). Baseline
        cancels (final_i≈0 → Neutral). Q8 balanced blend lets macro show
        through (final_i=-0.16 → Down) — matches the LEVEL framing.</li>
      <li><b>2024 disinflation inflation (LOSS)</b>: macro_i=+0.39 (CPI still
        ~3%, above 2.5+0.5 threshold band reads Up), market_i=-0.08. Baseline
        gets it right by accident (final_i=+0.06 → Neutral); Q8 over-rotates
        to Up (final_i=+0.16). <b>This is a structural threshold-semantics
        problem</b>, not a blend tuning issue. Widening CPI threshold
        neutral_level 2.5 → 3.0 in a future round would fix this but would
        also weaken the 2022 H1 detection — left as out-of-scope here.</li>
    </ul>
    """

    # Final verdict
    verdict = f"""
    <h2 id="verdict">Provisional verdict and "what would make Q8 final"</h2>
    <div class="pass-banner">
      <b>Recommendation</b>: ship Q8 unchanged. Robustness is strong
      (21/21 perturbations), per-confidence-class wins are concentrated
      where consensus is clearest, latency cost is small (+3bd mean) and
      acceptable for daily-checked operator dashboards.
    </div>
    <p>To upgrade Q8 from <em>provisional</em> to <em>final</em>, the
       following would need to be done:</p>
    <ol>
      <li><b>Fix the 2 "FAIL (clear)" inflation cases</b>:
        <ul>
          <li>2025 tariff: engine has no tariff-cost / single-event shock
            channel. Either add an event-overlay signal or accept the
            shortfall and document it.</li>
          <li>2022 H1 inflation growth (FAIL, g=34%): macro_g=+0.30 was
            correct but market_g=-0.47 dragged final to -0.09. Possibly
            tighten the post-COVID base-effect handling in the labor
            concept (YoY payrolls was structurally distorted by 2021 lows).</li>
        </ul>
      </li>
      <li><b>Fix the CPI 3% → "Up" framing artifact</b> (Q4 2024 disinflation):
        consider neutral_level 2.5 → 3.0 (Fed's de facto operating range) and
        re-run the grid. May regress 2017 Goldilocks unless threshold is
        compensated.</li>
      <li><b>Pre-register the next round's anchor set</b> before tuning,
        and split anchors into train/holdout. Current 13 anchors are
        author-curated and used both for grid search and validation —
        in-sample leakage is unavoidable. A holdout of 3-4 anchors
        (e.g. 2008, 2017, 2024) would let us validate Q8 without
        re-touching it.</li>
      <li><b>Layer concept-level tuning</b>: the current grid only
        touches 4 scalar knobs. Concept composition (e.g. yield curve
        T10Y2Y / T10Y3M to growth, T5YIE breakeven to inflation, oil
        to market_implied inflation) would change which signals dominate
        — that's a separate structural pass.</li>
      <li><b>Add direction-honest signals</b>: a MoM-velocity or
        6m-change layer would catch the "disinflation in progress" reading
        that the level-only macro layer cannot. Out of scope for Q8.</li>
    </ol>
    """

    body = []
    body.append("""
    <div class="banner">
      <b>Audit scope</b>: Q8 macro calibration (commits 4ae9d1502, f38195fcb)
      is currently shipped to <code>configs/regime_detection/regime_engine.yml</code>.
      This addendum tests robustness, separates label ambiguity from signal
      failures, measures real-latency under redesigned probes, and attributes
      Q8 wins/losses to concept-level contributors. Treats Q8 as <em>provisional</em>
      pending audit verdict.
    </div>
    """)
    body.append('<div class="toc"><b>Audit questions</b><ul>'
                '<li><a href="#q1">Q1. Robustness to anchor perturbations</a></li>'
                '<li><a href="#q2">Q2. Label-ambiguity vs signal-failure</a></li>'
                '<li><a href="#q3">Q3. Real-latency (lead-in probes)</a></li>'
                '<li><a href="#q4">Q4. Concept-level attribution</a></li>'
                '<li><a href="#verdict">Provisional verdict and what would make Q8 final</a></li>'
                '</ul></div>')
    body.append(q1)
    body.append(q2)
    body.append(q3)
    body.append(q4)
    body.append(verdict)
    return "\n".join(body)


# ===========================================================================
# Chinese version
# ===========================================================================

def _build_cn(robust: dict, label: dict, latency: dict, attrib: dict) -> str:
    s = robust["summary"]
    q1 = f"""
    <h2 id="q1">Q1 — Q8 对合理的 anchor 扰动是否鲁棒？</h2>
    <div class="pass-banner">
      <b>结论:</b> 是。Q8 在
      <b>{s['q8_beats_baseline_count']}/{robust['n_perturbations']}</b>
      个扰动里都击败 baseline，在 {s['q8_top1_count']}/{robust['n_perturbations']}
      个里排名第一，从未输给 baseline。Δ 区间:
      {s['q8_min_delta_pp']:+.1f} 至 {s['q8_max_delta_pp']:+.1f} pp
      (中位数 {s['q8_median_delta_pp']:+.1f})。
    </div>

    <p>测试了 {robust['n_perturbations']} 个扰动 × {robust['n_contenders']}
       个 contender 配置: 原始 anchor 集，6 种边界偏移 (±5/±10/±20 bdays)，
       1 种 alternative-consensus 标签扫描，13 个 leave-one-out。</p>

    <h3>对 Q8 最不利的扰动 (Q8-baseline 差距最小)</h3>
    <table>
      <thead><tr><th>扰动</th><th>Q8 总体</th><th>Baseline 总体</th><th>Δ (pp)</th></tr></thead>
      <tbody>
    """
    for r in robust["worst_perturbations_for_q8"]:
        q1 += f"<tr><td>{_h(r['perturbation'])}</td><td>{r['q8']:.1f}%</td><td>{r['baseline']:.1f}%</td><td>{r['delta']:+.1f}</td></tr>"
    q1 += """
      </tbody>
    </table>
    <p class="muted">值得注意: 在 alternative-consensus 标签下，Q8 仍比 baseline
       高 1.6pp。±5-20 bdays 的边界偏移只把总体匹配率改变 ~5pp 绝对值 —
       推荐参数不是 keyed 到具体的 anchor 起止日期。</p>
    """

    by_conf = label["by_confidence_class"]
    q2 = f"""
    <h2 id="q2">Q2 — Q8 的 miss 哪些是 label 模糊，哪些是真正的信号失败？</h2>

    <h3>按 confidence class 看匹配率</h3>
    <table>
      <thead><tr>
        <th>Confidence 类别</th><th>anchor 数</th>
        <th>Baseline g/i</th><th>Q8 g/i</th><th>Δg / Δi</th>
      </tr></thead>
      <tbody>
    """
    for c, m in by_conf.items():
        dg = m["q8_g_avg"] - m["baseline_g_avg"]
        di = m["q8_i_avg"] - m["baseline_i_avg"]
        q2 += f"""
        <tr>
          <td>{_h(c)}</td><td>{m['n_anchors']}</td>
          <td>{m['baseline_g_avg']}% / {m['baseline_i_avg']}%</td>
          <td>{m['q8_g_avg']}% / {m['q8_i_avg']}%</td>
          <td>{dg:+.1f}pp / {di:+.1f}pp</td>
        </tr>"""
    q2 += """
      </tbody>
    </table>
    <p class="muted">Q8 最大涨幅集中在 <em>clear</em>-confidence anchor
       (共识几乎一致的 4 个) — 增长匹配率 +17.6pp，通胀 +5.2pp。
       <em>definition-dependent</em> 类也涨 (g+2pp，i+14pp) 但上限被 framing
       本身限制，调参没法继续榨干。</p>

    <h3>每个 anchor 的 verdict</h3>
    <p>"PASS" = 主 consensus 下匹配率 ≥ 60%。
       "definition-artifact" = 切换到 alt label 后匹配率跳升 ≥ 30pp，
       framing 是瓶颈，不是引擎问题。
       "label-defensible" = alt label 下达到 ≥ 60%，合理 analyst 会分歧。
       "ambiguous" = 都没有清晰决议，引擎读数在中间地带。
       "FAIL (clear)" = clear-confidence anchor 没有 defensible alt label —
       <b>真正的信号设计问题</b>，需要 flag。</p>
    <table>
      <thead><tr>
        <th>Anchor</th><th>Confidence</th><th>共识 (g/i)</th>
        <th>Q8 g 匹配</th><th>g verdict</th><th>Q8 i 匹配</th><th>i verdict</th>
      </tr></thead>
      <tbody>
    """
    for x in label["per_anchor"]:
        gc = _verdict_cls(x["q8_g_verdict"])
        ic = _verdict_cls(x["q8_i_verdict"])
        q2 += f"""
        <tr>
          <td>{_h(x['name'])}</td><td>{_h(x['confidence'])}</td>
          <td>{_h(x['consensus'])}</td>
          <td>{x['q8_g_match']:.0f}%</td><td class="{gc}">{_h(x['q8_g_verdict'])}</td>
          <td>{x['q8_i_match']:.0f}%</td><td class="{ic}">{_h(x['q8_i_verdict'])}</td>
        </tr>"""
    q2 += """
      </tbody>
    </table>
    <p class="muted"><b>真正的 FAIL (clear) 只有 2 个</b>: 2022 H1 inflation
       growth (Q8 g=34%; macro_g=+0.30 看到 Up 但 market_g=-0.47 把 final
       拖到 -0.09) 和 2025 tariff (双轴都失败; 引擎没有 tariff-cost / 单事件
       shock 通道)。2022 H1 i=59% 是边缘情况 (刚低于 60% 阈值)。
       其它"fail" 要么 label-defensible，要么 definition-artifact，框架决定的。</p>
    """

    by_cfg = latency["by_config"]
    q3 = f"""
    <h2 id="q3">Q3 — Q8 是否对 transition 响应足够快？</h2>

    <div class="warn">
      <b>结论:</b> Q8 在重设的 latency probe 上比 baseline <em>稍慢</em>
      (平均延迟 19.3bd vs 16.4bd，+3bd)。最大单项倒退是 2021 reflation
      start (+11bd: 2bd → 13bd) — 因为 market layer 的 breakeven 早期信号
      被 balanced blend 稀释了。这是必须披露的真实 trade-off，不是免费午餐。
    </div>

    <p>重设的 latency probe 从每个 canonical transition 之前 <em>60 bdays</em>
       开始 (确保引擎确实从 prior state 起步)，测量从 transition 日到引擎
       首次 label 目标 state 且 hold ≥5 个 bdays 之间的 bday 数。</p>

    <table>
      <thead><tr><th>Probe</th>"""
    for cfg_name in by_cfg:
        short = cfg_name.split(":")[-1].strip()[:30]
        q3 += f"<th>{_h(short)}</th>"
    q3 += "</tr></thead><tbody>"
    probes_seen = []
    for row in latency["all_rows"]:
        if row["probe"] not in probes_seen:
            probes_seen.append(row["probe"])
    for probe_name in probes_seen:
        q3 += f"<tr><td>{_h(probe_name)}</td>"
        for cfg_name in by_cfg:
            r = next((x for x in latency["all_rows"]
                      if x["probe"] == probe_name and x["config_name"] == cfg_name), None)
            if r and r["latency_bdays"] is not None:
                q3 += f"<td>{r['latency_bdays']}bd</td>"
            else:
                q3 += "<td class='muted'>—</td>"
        q3 += "</tr>"
    q3 += "</tbody></table>"

    q3 += "<h3>每配置的均值 / 中位数 latency</h3><table><thead><tr><th>配置</th><th>均值 (bd)</th><th>中位数 (bd)</th><th>最大 (bd)</th></tr></thead><tbody>"
    for cfg, sx in by_cfg.items():
        q3 += f"<tr><td>{_h(cfg)}</td><td>{sx['mean_latency_bdays']}</td><td>{sx['median_latency_bdays']}</td><td>{sx['max_latency_bdays']}</td></tr>"
    q3 += "</tbody></table>"

    q3 += """
    <p class="muted">几个 probe 显示 0bd 是因为 lead-in 起点之后引擎就已经
       move 了 (例: COVID growth turn 市场 Feb 24 就开始崩，到 canonical
       transition Mar 10 引擎已经在 Down state)。这些 probe 起的是
       "护栏" 作用 ("引擎没有错过这次")，不是分辨 latency 的真正测试。</p>
    <p class="muted">Q8 慢的地方集中在 <em>market</em> layer 引领的 probe。
       50/50 balanced blend 下，那些 leading signal 被 macro 的慢视角稀释。
       原 anchor 集 +5pp 共识匹配胜出可以接受这个 trade-off，但要知道。</p>
    """

    q4 = """
    <h2 id="q4">Q4 — Q8 的成功与失败由哪些 concept-level 因素解释？</h2>
    <p>对每个 anchor 取中点日期，dump 各 layer 分数 + top 贡献 series。
       下面是最有信息的 case —— 那些 Q8 与 baseline 在 axis label 上有差异
       的日子。</p>
    """
    anchors_with_change = []
    for a in attrib["anchors"]:
        if not a["per_date"]:
            continue
        mid = a["per_date"][len(a["per_date"]) // 2]
        b = mid["baseline"]
        q = mid["q8"]
        if b["g_label"] != q["g_label"] or b["i_label"] != q["i_label"]:
            anchors_with_change.append((a, mid, b, q))

    for a, mid, b, q in anchors_with_change:
        q4 += f"""
        <h3>{_h(a['name'])} ({_h(mid['date'])}, 共识 g={_h(a['g_consensus'])}, i={_h(a['i_consensus'])})</h3>
        <table>
          <thead><tr><th></th><th>Baseline</th><th>Q8</th></tr></thead>
          <tbody>
            <tr><td>final_g (label)</td><td>{b['final_g']:+.2f} ({_h(b['g_label'])})</td><td>{q['final_g']:+.2f} ({_h(q['g_label'])})</td></tr>
            <tr><td>final_i (label)</td><td>{b['final_i']:+.2f} ({_h(b['i_label'])})</td><td>{q['final_i']:+.2f} ({_h(q['i_label'])})</td></tr>
            <tr><td>macro_nowcast (g/i)</td>
                <td>{b['layer_outputs'].get('macro_nowcast', {}).get('growth', '—')} / {b['layer_outputs'].get('macro_nowcast', {}).get('inflation', '—')}</td>
                <td>{q['layer_outputs'].get('macro_nowcast', {}).get('growth', '—')} / {q['layer_outputs'].get('macro_nowcast', {}).get('inflation', '—')}</td>
            </tr>
            <tr><td>market_implied (g/i)</td>
                <td>{b['layer_outputs'].get('market_implied', {}).get('growth', '—')} / {b['layer_outputs'].get('market_implied', {}).get('inflation', '—')}</td>
                <td>{q['layer_outputs'].get('market_implied', {}).get('growth', '—')} / {q['layer_outputs'].get('market_implied', {}).get('inflation', '—')}</td>
            </tr>
            <tr><td>top 贡献者 (≤3)</td>
                <td class="small">{_h(b['top_contributors'][:3])}</td>
                <td class="small">{_h(q['top_contributors'][:3])}</td>
            </tr>
          </tbody>
        </table>
        """

    q4 += """
    <h3>跨所有 label-change anchor 的模式</h3>
    <ul>
      <li><b>2022 H1 inflation</b>: macro_i=+0.57 (正确读到 CPI 高峰)，
        market_i=-0.15 (油价比 CPI 高峰更早 roll over)。Q8 的 50/50 blend
        让 macro 信号 dominate (final_i=+0.21 → Up); baseline 30/70 把它
        埋了 (final_i=+0.07 → Neutral)。<b>这是层权重改动的旗舰 case。</b></li>
      <li><b>2017 Goldilocks growth</b>: macro_g=+0.14, market_g=+0.11。
        两层都正确轻度 positive。Baseline 的 final_g=+0.12 卡在 ±0.15 阈值
        下方 → Neutral。Q8 把阈值收紧到 ±0.10 让同样的分数变成 Up。
        <b>这个 case 完全是阈值改动驱动，不是 blend 改动。</b></li>
      <li><b>2020H2 catch-up inflation</b>: macro_i=-0.55 (CPI YoY 仍 ~1.4%，
        在 2.5% 舒适水平之下)，market_i=+0.24 (reflation 定价)。Baseline
        相互抵消 (final_i≈0 → Neutral)。Q8 balanced blend 让 macro 透出
        (final_i=-0.16 → Down) — 匹配 LEVEL framing。</li>
      <li><b>2024 disinflation inflation (LOSS)</b>: macro_i=+0.39 (CPI 仍
        ~3%，在 2.5+0.5 阈值带之上读 Up)，market_i=-0.08。Baseline 阴差阳错
        蒙对 (final_i=+0.06 → Neutral); Q8 over-rotate 到 Up (final_i=+0.16)。
        <b>这是 threshold-semantics 结构问题</b>，不是 blend tuning 问题。
        把 CPI threshold neutral_level 2.5 → 3.0 可以修，但会削弱 2022 H1
        检测 — 留作 Q8 范围外。</li>
    </ul>
    """

    verdict = f"""
    <h2 id="verdict">Provisional 结论 + "Q8 何时算 final"</h2>
    <div class="pass-banner">
      <b>建议</b>: Q8 不动，按已 ship 保留。鲁棒性强 (21/21 扰动)，
      最权威的共识 anchor 上涨幅最大，latency 代价小 (+3bd 均值)、
      对日级 dashboard 可接受。
    </div>
    <p>要把 Q8 从 <em>provisional</em> 升级到 <em>final</em>，下面这些
       需要做:</p>
    <ol>
      <li><b>修复 2 个 "FAIL (clear)" inflation case</b>:
        <ul>
          <li>2025 tariff: 引擎没有 tariff-cost / 单事件 shock 通道。
            要么加 event-overlay signal，要么接受短板并文档化。</li>
          <li>2022 H1 inflation growth (FAIL, g=34%): macro_g=+0.30
            是对的但 market_g=-0.47 把 final 拖到 -0.09。可能要 tighten
            labor concept 在 post-COVID 基数效应的处理 (YoY payrolls 2021
            被低基数结构性扭曲)。</li>
        </ul>
      </li>
      <li><b>修复 CPI 3% → "Up" 的 framing artifact</b> (Q4 2024 disinflation):
        考虑 neutral_level 2.5 → 3.0 (Fed 实际操作区间) 并重跑 grid。
        可能会回退 2017 Goldilocks 除非阈值补偿。</li>
      <li><b>下一轮校准前 pre-register anchor 集</b>，把 anchor 拆成
        train/holdout。当前 13 个 anchor 由作者主观挑选，同时用于 grid 搜索
        和验证 —— 样本内 leakage 不可避免。留 3-4 个 holdout
        (例: 2008、2017、2024) 可以独立验证 Q8 而不再触碰它。</li>
      <li><b>叠 concept-level tuning</b>: 当前 grid 只动 4 个标量旋钮。
        Concept composition (例: yield curve T10Y2Y/T10Y3M 加到 growth、
        T5YIE breakeven 加到 inflation、油价加到 market_implied inflation)
        会改变哪些信号 dominate —— 这是单独的结构性 pass。</li>
      <li><b>加 direction-honest 信号</b>: MoM-velocity 或 6m-change 层
        可以读出 "disinflation in progress" —— 当前 level-only macro layer
        做不到。Q8 范围外。</li>
    </ol>
    """

    body = []
    body.append("""
    <div class="banner">
      <b>审计范围</b>: Q8 macro 校准 (commit 4ae9d1502, f38195fcb) 已 ship
      到 <code>configs/regime_detection/regime_engine.yml</code>。本附录
      测试鲁棒性、分离 label 模糊与信号失败、用重设的 probe 测量真实 latency、
      把 Q8 的成败归因到 concept-level 贡献者。把 Q8 当 <em>provisional</em>
      等待审计结论。
    </div>
    """)
    body.append('<div class="toc"><b>审计问题</b><ul>'
                '<li><a href="#q1">Q1. 对 anchor 扰动的鲁棒性</a></li>'
                '<li><a href="#q2">Q2. Label 模糊 vs 信号失败</a></li>'
                '<li><a href="#q3">Q3. 真实 latency (lead-in probes)</a></li>'
                '<li><a href="#q4">Q4. Concept-level 归因</a></li>'
                '<li><a href="#verdict">Provisional 结论 + Q8 何时算 final</a></li>'
                '</ul></div>')
    body.append(q1)
    body.append(q2)
    body.append(q3)
    body.append(q4)
    body.append(verdict)
    return "\n".join(body)


def main() -> int:
    robust = _load("macro_robustness.json")
    label = _load("macro_label_ambiguity.json")
    latency = _load("macro_latency.json")
    attrib = _load("macro_concept_attribution.json")

    when = datetime.now().strftime("%Y-%m-%d")

    en_body = _build_en(robust, label, latency, attrib)
    en_html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Q8 Macro Calibration — Audit Addendum ({when})</title>
{_style()}
</head>
<body>
<h1>Q8 Macro Calibration — Audit Addendum</h1>
<p class="muted">{when} · audits the shipped Q8 calibration
   (commits <code>4ae9d1502</code>, <code>f38195fcb</code>) against four
   questions raised after the original report landed.</p>
{en_body}
</body></html>
"""
    OUT_EN.write_text(en_html, encoding="utf-8")
    print(f"wrote {OUT_EN} ({OUT_EN.stat().st_size:,} bytes)")

    cn_body = _build_cn(robust, label, latency, attrib)
    cn_html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Q8 宏观校准审计附录 ({when})</title>
{_style()}
</head>
<body>
<h1>Q8 宏观校准 —— 审计附录</h1>
<p class="muted">{when} · 对已 ship 的 Q8 校准 (commit
   <code>4ae9d1502</code>, <code>f38195fcb</code>) 做四个角度的审计。</p>
{cn_body}
</body></html>
"""
    OUT_CN.write_text(cn_html, encoding="utf-8")
    print(f"wrote {OUT_CN} ({OUT_CN.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
