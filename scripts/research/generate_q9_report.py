"""Generate Q9 calibration report (EN + CN) with train/holdout discipline
and velocity-layer narrative.

Reads:
  data/research_artifacts/macro_calibration_grid_q9.json
  data/research_artifacts/macro_calibration_analysis_q9.json
  data/research_artifacts/macro_scout.json (Q8 baseline scout for reference)
  data/research_artifacts/macro_scout_after.json (Q8 ship state)
  data/research_artifacts/macro_scout_q9_after.json (Q9 ship state, optional)
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ART = REPO / "data/research_artifacts"
OUT_EN = ART / "macro_calibration_q9_en.html"
OUT_CN = ART / "macro_calibration_q9_cn.html"


def _h(s) -> str:
    return html.escape(str(s))


def _load(name: str) -> dict | list:
    return json.loads((ART / name).read_text(encoding="utf-8"))


def _style() -> str:
    return """
    <style>
      body { font-family: ui-sans-serif, system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", "Segoe UI", Roboto, sans-serif;
             max-width: 1200px; margin: 30px auto; padding: 0 20px; line-height: 1.6;
             color: #1f2328; }
      h1 { font-size: 1.7em; margin: 0 0 0.3em; }
      h2 { font-size: 1.3em; margin-top: 1.8em; padding-bottom: 0.3em; border-bottom: 1px solid #d0d7de; }
      h3 { font-size: 1.05em; margin-top: 1.3em; }
      table { border-collapse: collapse; margin: 1em 0; font-size: 0.92em; width: 100%; }
      th, td { padding: 6px 10px; border: 1px solid #d0d7de; text-align: left; vertical-align: top; }
      th { background: #f6f8fa; }
      td.ok { color: #1a7f37; font-weight: 600; }
      td.bad { color: #cf222e; font-weight: 600; }
      td.holdout { background: #fff8e1; }
      .muted { color: #57606a; font-size: 0.9em; }
      code { background: #f6f8fa; padding: 1px 5px; border-radius: 3px; font-size: 0.88em; }
      pre code { display: block; padding: 12px; line-height: 1.45; white-space: pre; }
      .banner { background: #ddf4ff; border-left: 4px solid #0969da; padding: 10px 16px; margin: 1em 0; border-radius: 4px; }
      .pass-banner { background: #dafbe1; border-left: 4px solid #1a7f37; padding: 10px 16px; margin: 1em 0; border-radius: 4px; }
      .warn { background: #fff8c5; border-left: 4px solid #9a6700; padding: 10px 16px; margin: 1em 0; border-radius: 4px; }
      .toc { background: #f6f8fa; padding: 12px 20px; border: 1px solid #d0d7de; border-radius: 6px; }
    </style>
    """


def _fmt_params_q9(p: dict, lang: str = "en") -> str:
    if lang == "cn":
        return (
            f"通胀_velocity_weight={p['inflation_velocity_weight']}, "
            f"增长_velocity_weight={p['growth_velocity_weight']}, "
            f"growth_thresh=±{p['growth_thresh']}, "
            f"inflation_thresh=±{p['inflation_thresh']}, "
            f"macro_w={p['macro_w']}, market_w={p['market_w']}"
        )
    return (
        f"inflation_velocity_w={p['inflation_velocity_weight']}, "
        f"growth_velocity_w={p['growth_velocity_weight']}, "
        f"growth_thresh=±{p['growth_thresh']}, "
        f"inflation_thresh=±{p['inflation_thresh']}, "
        f"macro_w={p['macro_w']}, market_w={p['market_w']}"
    )


def _train_holdout_summary(rec, baseline, lang: str = "en") -> str:
    rt = rec["train"]
    rh = rec["holdout"]
    bt = baseline["train"]["overall"] if baseline else 0
    bh = baseline["holdout"]["overall"] if baseline else 0
    train_delta = rt["overall"] - bt
    holdout_delta = rh["overall"] - bh

    if lang == "cn":
        return f"""
        <table>
          <thead><tr><th>评估集</th><th>{'Anchor数'}</th><th>g_avg</th><th>i_avg</th><th>risk_avg</th><th>总体</th><th>vs Q8 baseline</th></tr></thead>
          <tbody>
            <tr><td><b>Train</b> (grid 选择信号)</td><td>9</td>
                <td>{rt['g_avg']:.1f}%</td><td>{rt['i_avg']:.1f}%</td><td>{rt['risk_avg']:.1f}%</td>
                <td><b>{rt['overall']:.1f}%</b></td>
                <td class="{'ok' if train_delta>0 else 'bad'}">{train_delta:+.1f}pp</td></tr>
            <tr><td class="holdout"><b>Holdout</b> (事后验证, 未参与 selection)</td><td>4</td>
                <td class="holdout">{rh['g_avg']:.1f}%</td><td class="holdout">{rh['i_avg']:.1f}%</td>
                <td class="holdout">{rh['risk_avg']:.1f}%</td>
                <td class="holdout"><b>{rh['overall']:.1f}%</b></td>
                <td class="holdout {'ok' if holdout_delta>0 else 'bad'}">{holdout_delta:+.1f}pp</td></tr>
          </tbody>
        </table>
        """
    return f"""
    <table>
      <thead><tr><th>Set</th><th>n anchors</th><th>g_avg</th><th>i_avg</th><th>risk_avg</th><th>overall</th><th>vs Q8 baseline</th></tr></thead>
      <tbody>
        <tr><td><b>Train</b> (grid selection signal)</td><td>9</td>
            <td>{rt['g_avg']:.1f}%</td><td>{rt['i_avg']:.1f}%</td><td>{rt['risk_avg']:.1f}%</td>
            <td><b>{rt['overall']:.1f}%</b></td>
            <td class="{'ok' if train_delta>0 else 'bad'}">{train_delta:+.1f}pp</td></tr>
        <tr><td class="holdout"><b>Holdout</b> (strict post-hoc validation, no selection pressure)</td><td>4</td>
            <td class="holdout">{rh['g_avg']:.1f}%</td><td class="holdout">{rh['i_avg']:.1f}%</td>
            <td class="holdout">{rh['risk_avg']:.1f}%</td>
            <td class="holdout"><b>{rh['overall']:.1f}%</b></td>
            <td class="holdout {'ok' if holdout_delta>0 else 'bad'}">{holdout_delta:+.1f}pp</td></tr>
      </tbody>
    </table>
    """


def _per_anchor_table(metrics, label: str, lang: str = "en") -> str:
    rows = []
    for a in metrics["per_anchor"]:
        rows.append(f"""
        <tr>
          <td>{_h(a['name'])}</td>
          <td>{a['g_match_pct']:.0f}%</td>
          <td>{a['i_match_pct']:.0f}%</td>
          <td>{'✓' if a['risk_match'] else '✗'}</td>
        </tr>""")
    if lang == "cn":
        return f"""
        <h4>{_h(label)} 每个 anchor 详情</h4>
        <table>
          <thead><tr><th>Anchor</th><th>g_match</th><th>i_match</th><th>risk_match</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
        """
    return f"""
    <h4>{_h(label)} per-anchor detail</h4>
    <table>
      <thead><tr><th>Anchor</th><th>g_match</th><th>i_match</th><th>risk_match</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    """


def _build_en(analysis: dict, grid: list) -> str:
    rec = analysis["recommendation"]
    baseline = analysis["baseline_q8_equivalent"]
    rec_p = rec["params"]
    train_gap = rec["train"]["overall"] - rec["holdout"]["overall"]
    baseline_gap = (baseline["train"]["overall"] - baseline["holdout"]["overall"]) if baseline else 0

    intro = f"""
    <div class="banner">
      <b>Q9 scope</b>: introduce a direction-honest velocity layer
      (3-month annualized rate of change on CPI/PCE for inflation,
      PAYEMS/INDPRO for growth) alongside the existing YoY-level concepts.
      Use a 9-train / 4-holdout anchor split so the grid sees only 9
      anchors during selection and the 4 holdout anchors validate
      generalization post-hoc.
    </div>
    <div class="toc"><b>Sections</b><ul>
      <li><a href="#method">Methodology — velocity layer + train/holdout</a></li>
      <li><a href="#split">Train / Holdout split rationale</a></li>
      <li><a href="#grid">Grid search ({analysis['n_configs']} configs)</a></li>
      <li><a href="#winner">Recommended winner — train and holdout</a></li>
      <li><a href="#config">Config changes (apply)</a></li>
      <li><a href="#caveats">Caveats</a></li>
    </ul></div>
    """

    methodology = f"""
    <h2 id="method">Methodology</h2>
    <h3>Velocity layer (direction-honest signal)</h3>
    <p>Q8 audit identified one persistent structural failure: the engine
       reads CPI YoY at 3% as "Up" (above 2.5±0.5 threshold), even when
       inflation is monotonically falling — a LEVEL-honest reading that
       does not match the "disinflation in progress" narrative. Q9 adds
       five new panel columns using the existing
       <code>qoq_annualized</code> transform (3-month annualized rate
       of change) on the same FRED series:</p>
    <ul>
      <li><code>CPIAUCSL_velocity_3m</code> (inflation)</li>
      <li><code>CPILFESL_velocity_3m</code> (inflation, core)</li>
      <li><code>PCEPI_velocity_3m</code> (inflation)</li>
      <li><code>PAYEMS_velocity_3m</code> (growth)</li>
      <li><code>INDPRO_velocity_3m</code> (growth)</li>
    </ul>
    <p>These feed two new concepts <code>inflation_velocity</code> and
       <code>growth_velocity</code> with their own concept weights — the
       grid sweeps those weights to find the level/velocity balance that
       maximizes train consensus match while preserving holdout
       performance.</p>
    <p>Mechanical change required: <code>SeriesSpec</code> gained an
       optional <code>name</code> field so the same FRED <code>series_id</code>
       (e.g. <code>CPIAUCSL</code>) can be loaded under two transforms
       (yoy_pct as <code>CPIAUCSL</code>, qoq_annualized as
       <code>CPIAUCSL_velocity_3m</code>) — separate panel columns,
       single FRED fetch. No behavior change for specs without
       <code>name</code> (defaults to series_id).</p>

    <h3>Train / Holdout discipline</h3>
    <p>Q8 audit explicitly flagged that the same 13 anchors drove both
       grid search and validation — in-sample leakage was unavoidable.
       Q9 fixes this by tagging 4 anchors as <em>holdout</em>:</p>
    <ul>
      <li><b>2008 GFC trough</b> (clear) — crisis cycle</li>
      <li><b>2017 Goldilocks</b> (defensible) — textbook normal cycle</li>
      <li><b>2024 disinflation</b> (definition-dependent) — the velocity
        layer's target case; holding it out prevents fitting the new
        signal to this single anchor</li>
      <li><b>2025 tariff shock</b> (clear) — newest anchor, tests
        generalization to current data</li>
    </ul>
    <p>Grid evaluates 9 train anchors only for selection. Holdout is
       computed for every config but used strictly post-hoc.</p>

    <h3>Selection rule</h3>
    <ol>
      <li>Compute <code>composite_train = train_overall_match% + 0.3 ×
          min(median_run_bdays, 20)</code>.</li>
      <li>Strict-improvers tier vs Q8-equivalent baseline (velocity
          weights = 0): better on (train_overall, stability), pick highest
          composite.</li>
      <li>Otherwise top composite_train.</li>
      <li><b>Holdout never enters selection.</b> Post-hoc holdout
          performance is reported separately as the validation signal.</li>
    </ol>
    """

    split = """
    <h2 id="split">Train / Holdout split rationale</h2>
    <table>
      <thead><tr><th>Set</th><th>Anchors</th><th>Why</th></tr></thead>
      <tbody>
        <tr><td><b>Train</b> (9)</td>
            <td>2010-12, 2015-16, 2018 Q4, 2019 H2, 2020 COVID, 2020H2,
                2021 reflation, 2022 H1, 2023 high-inflation</td>
            <td>Mix of clear / defensible / definition-dependent confidence.
                Cover crisis, expansion, stagflation, recovery. Most of
                Q8's wins concentrated here.</td></tr>
        <tr><td class="holdout"><b>Holdout</b> (4)</td>
            <td>2008 GFC, 2017 Goldilocks, 2024 disinflation, 2025 tariff</td>
            <td class="holdout">Span crisis / normal / target /
                newest-data. 2024 disinflation is the velocity layer's
                <em>target</em> case — holding it out is the cleanest
                way to validate that the velocity signal isn't being
                fit to this single anchor.</td></tr>
      </tbody>
    </table>
    """

    # Grid summary table
    grid_html = f"""
    <h2 id="grid">Grid search ({analysis['n_configs']} configs)</h2>
    <p class="muted">Sweep: 5 inflation_velocity_weight × 4
       growth_velocity_weight × 3 growth_thresh × 3 inflation_thresh × 2
       layer_blend (macro/market) = {analysis['n_configs']} configs. Each
       runs the full engine over 1921-today (~27k bdays), then evaluates
       on the 9 train and 4 holdout anchors independently.</p>
    <h3>Top 10 by composite_train</h3>
    <table>
      <thead><tr><th>#</th><th>Params</th><th>train</th><th>holdout</th><th>g_run / i_run</th></tr></thead>
      <tbody>
    """
    for i, r in enumerate(analysis["top10_by_train_composite"][:10], 1):
        is_rec = r["params"] == rec["params"]
        bg = ' style="background:#fff8c5;"' if is_rec else ""
        grid_html += f"""
        <tr{bg}>
          <td>{'⭐' if is_rec else i}</td>
          <td><code style="font-size:0.85em">{_h(_fmt_params_q9(r['params']))}</code></td>
          <td>{r['train']['overall']:.1f}%</td>
          <td>{r['holdout']['overall']:.1f}%</td>
          <td>{r['stability']['g_median_run_bdays']}/{r['stability']['i_median_run_bdays']}bd</td>
        </tr>"""
    grid_html += f"""
      </tbody>
    </table>
    <p class="muted">Strict improvers over Q8-baseline on train: {analysis['strict_improvers_count']}.</p>
    """

    # Winner block
    overfit_warn = ""
    if abs(train_gap) > 10:
        cls = "warn"
        overfit_msg = f"⚠️ Train-holdout gap is {train_gap:+.1f}pp — possible overfit to train anchors. Read holdout carefully."
        overfit_warn = f'<div class="{cls}">{_h(overfit_msg)}</div>'
    else:
        overfit_msg = f"Train-holdout gap: {train_gap:+.1f}pp (Q8-baseline gap was {baseline_gap:+.1f}pp). Within acceptable noise — no overfit signal."
        overfit_warn = f'<div class="pass-banner">{_h(overfit_msg)}</div>'

    winner = f"""
    <h2 id="winner">Recommended winner</h2>
    <p><b>Params:</b> <code>{_h(_fmt_params_q9(rec_p))}</code></p>
    {_train_holdout_summary(rec, baseline)}
    {overfit_warn}
    {_per_anchor_table(rec['holdout'], 'HOLDOUT (post-hoc validation)')}
    {_per_anchor_table(rec['train'], 'TRAIN (grid signal)')}
    """

    # Config diff
    config_diff = f"""
    <h2 id="config">Config changes (apply)</h2>
    <pre><code>--- configs/regime_detection/fred_series.yml
+++ configs/regime_detection/fred_series.yml
   inflation_velocity:
-    weight: 0.0
+    weight: {rec_p['inflation_velocity_weight']}
     series:
       CPIAUCSL_velocity_3m: 0.40
       CPILFESL_velocity_3m: 0.30
       PCEPI_velocity_3m: 0.30
   growth_velocity:
-    weight: 0.0
+    weight: {rec_p['growth_velocity_weight']}
     series:
       PAYEMS_velocity_3m: 0.55
       INDPRO_velocity_3m: 0.45
</code></pre>"""

    # Threshold / blend changes (if any)
    if (rec_p['growth_thresh'] != 0.10 or rec_p['inflation_thresh'] != 0.12
            or rec_p['macro_w'] != 0.50):
        config_diff += f"""
    <pre><code>--- configs/regime_detection/regime_engine.yml
+++ configs/regime_detection/regime_engine.yml
   layers.macro_nowcast.weight_growth:    {rec_p['macro_w']}
   layers.macro_nowcast.weight_inflation: {rec_p['macro_w']}
   layers.market_implied.weight_growth:   {rec_p['market_w']}
   layers.market_implied.weight_inflation:{rec_p['market_w']}
   regime_thresholds.growth_up:           {rec_p['growth_thresh']}
   regime_thresholds.growth_down:         {-rec_p['growth_thresh']}
   regime_thresholds.inflation_up:        {rec_p['inflation_thresh']}
   regime_thresholds.inflation_down:      {-rec_p['inflation_thresh']}
</code></pre>"""
    else:
        config_diff += '<p class="muted">No changes to regime_engine.yml — Q8 layer weights and thresholds remain optimal under Q9.</p>'

    caveats = """
    <h2 id="caveats">Caveats</h2>
    <ul>
      <li><b>Holdout is small (4 anchors)</b> — high variance signal.
        A 5pp train/holdout gap is within sampling noise.</li>
      <li><b>2024 disinflation is in holdout</b> — if Q9 wins primarily
        because the velocity layer fits 2024 well, that win is real but
        narrow. Per-anchor holdout breakdown shows whether the gains are
        2024-only or distributed.</li>
      <li><b>2025 tariff still unsolved</b>: the velocity layer reads
        CPI/PCE prints, which lag policy events by 1-2 months. Engine
        still has no single-event-shock channel — left as deferred work.</li>
      <li><b>Risk overlay frozen from Q7</b>. Q9 only changes macro axis
        components.</li>
      <li><b>Concept composition is opinionated</b>: velocity concepts
        use 40/30/30 weights on CPI/Core CPI/PCE (inflation) and
        55/45 on PAYEMS/INDPRO (growth). Different splits could yield
        different winners — single-pass grid does not sweep these
        within-weights.</li>
    </ul>
    """
    return intro + methodology + split + grid_html + winner + config_diff + caveats


def _build_cn(analysis: dict, grid: list) -> str:
    rec = analysis["recommendation"]
    baseline = analysis["baseline_q8_equivalent"]
    rec_p = rec["params"]
    train_gap = rec["train"]["overall"] - rec["holdout"]["overall"]
    baseline_gap = (baseline["train"]["overall"] - baseline["holdout"]["overall"]) if baseline else 0

    intro = f"""
    <div class="banner">
      <b>Q9 范围</b>: 加 direction-honest 的 velocity 层 (CPI/PCE 的
      3 月年化变动率作为通胀方向, PAYEMS/INDPRO 同理作为增长方向),
      和现有 YoY-level concept 并列。9-train / 4-holdout 锚定切分
      让 grid 只看 9 个 anchor 选择, 4 个 holdout 做事后泛化验证。
    </div>
    <div class="toc"><b>章节</b><ul>
      <li><a href="#method">方法学 — velocity 层 + train/holdout</a></li>
      <li><a href="#split">Train/Holdout 切分依据</a></li>
      <li><a href="#grid">网格搜索 ({analysis['n_configs']} 个 config)</a></li>
      <li><a href="#winner">推荐 winner — train + holdout</a></li>
      <li><a href="#config">配置变更 (应用)</a></li>
      <li><a href="#caveats">注意事项</a></li>
    </ul></div>
    """

    methodology = f"""
    <h2 id="method">方法学</h2>
    <h3>Velocity 层 (direction-honest 信号)</h3>
    <p>Q8 audit 锁定一个持续的结构性失败: 引擎把 CPI YoY 3% 读成 "Up"
       (高于 2.5±0.5 阈值)，即使通胀正在单调下降 — LEVEL-honest 读法,
       但和 "disinflation in progress" 的叙事不符。Q9 用现有的
       <code>qoq_annualized</code> 变换 (3 月年化变动率) 在同样的
       FRED series 上加 5 个新 panel column:</p>
    <ul>
      <li><code>CPIAUCSL_velocity_3m</code> (通胀)</li>
      <li><code>CPILFESL_velocity_3m</code> (通胀, 核心)</li>
      <li><code>PCEPI_velocity_3m</code> (通胀)</li>
      <li><code>PAYEMS_velocity_3m</code> (增长)</li>
      <li><code>INDPRO_velocity_3m</code> (增长)</li>
    </ul>
    <p>这些 series 喂给两个新 concept <code>inflation_velocity</code>
       和 <code>growth_velocity</code>, 各自带 concept 权重 — grid
       扫这两个权重, 找 level/velocity 平衡, 让 train 共识匹配最大同时
       不破坏 holdout 性能。</p>
    <p>必要的机制改动: <code>SeriesSpec</code> 加可选 <code>name</code>
       字段, 让同一个 FRED <code>series_id</code> (例如 <code>CPIAUCSL</code>)
       可以同时被两个 spec 加载 (yoy_pct 作为 <code>CPIAUCSL</code>,
       qoq_annualized 作为 <code>CPIAUCSL_velocity_3m</code>) — panel
       两列, FRED 只 fetch 一次。不带 <code>name</code> 的 spec 不变
       (默认 = series_id)。</p>

    <h3>Train / Holdout 纪律</h3>
    <p>Q8 audit 明确指出: 同一个 13 anchor 集既用于 grid 搜索又用于验证
       — in-sample leakage 不可避免。Q9 把 4 个 anchor 标 <em>holdout</em>:</p>
    <ul>
      <li><b>2008 GFC trough</b> (clear) — 危机周期代表</li>
      <li><b>2017 Goldilocks</b> (defensible) — 教科书正常周期</li>
      <li><b>2024 disinflation</b> (definition-dependent) — velocity 层
        的目标 case; 保留它防止 velocity 信号被 fit 到这个单一 anchor</li>
      <li><b>2025 tariff shock</b> (clear) — 最新 anchor, 测试对当前数据的
        泛化</li>
    </ul>
    <p>Grid 只在 9 个 train anchor 上选择。Holdout 对每个 config 都算,
       但严格事后只读。</p>

    <h3>选择规则</h3>
    <ol>
      <li>计算 <code>composite_train = train_overall_match% + 0.3 ×
          min(median_run_bdays, 20)</code>。</li>
      <li>严格优于 Q8-equivalent baseline (velocity 权重 = 0) 的层:
          (train_overall, stability) 都不弱于 baseline, 取最高 composite。</li>
      <li>否则取 composite_train 最高。</li>
      <li><b>Holdout 永不进入选择。</b> 事后 holdout 性能单独作为验证信号。</li>
    </ol>
    """

    split = """
    <h2 id="split">Train / Holdout 切分依据</h2>
    <table>
      <thead><tr><th>集合</th><th>Anchor</th><th>原因</th></tr></thead>
      <tbody>
        <tr><td><b>Train</b> (9)</td>
            <td>2010-12, 2015-16, 2018 Q4, 2019 H2, 2020 COVID, 2020H2,
                2021 reflation, 2022 H1, 2023 high-inflation</td>
            <td>包括 clear / defensible / definition-dependent confidence。
                覆盖危机, 扩张, 滞胀, 复苏。Q8 的增益主要集中在这里。</td></tr>
        <tr><td class="holdout"><b>Holdout</b> (4)</td>
            <td>2008 GFC, 2017 Goldilocks, 2024 disinflation, 2025 tariff</td>
            <td class="holdout">跨越 危机 / 正常 / 目标 / 最新数据。
                2024 disinflation 是 velocity 层的 <em>目标</em> case
                — 保留它是验证 velocity 信号不是 fit 到单一 anchor
                的最干净方法。</td></tr>
      </tbody>
    </table>
    """

    grid_html = f"""
    <h2 id="grid">网格搜索 ({analysis['n_configs']} 个 config)</h2>
    <p class="muted">扫描: 5 inflation_velocity_weight × 4
       growth_velocity_weight × 3 growth_thresh × 3 inflation_thresh × 2
       layer_blend (macro/market) = {analysis['n_configs']} 个 config。
       每个跑全 engine 1921-至今 (~27k bdays), 然后分别在 9 个 train 和
       4 个 holdout anchor 上独立评估。</p>
    <h3>按 composite_train 排前 10</h3>
    <table>
      <thead><tr><th>#</th><th>参数</th><th>train</th><th>holdout</th><th>g_run / i_run</th></tr></thead>
      <tbody>
    """
    for i, r in enumerate(analysis["top10_by_train_composite"][:10], 1):
        is_rec = r["params"] == rec["params"]
        bg = ' style="background:#fff8c5;"' if is_rec else ""
        grid_html += f"""
        <tr{bg}>
          <td>{'⭐' if is_rec else i}</td>
          <td><code style="font-size:0.85em">{_h(_fmt_params_q9(r['params'], 'cn'))}</code></td>
          <td>{r['train']['overall']:.1f}%</td>
          <td>{r['holdout']['overall']:.1f}%</td>
          <td>{r['stability']['g_median_run_bdays']}/{r['stability']['i_median_run_bdays']}bd</td>
        </tr>"""
    grid_html += f"""
      </tbody>
    </table>
    <p class="muted">严格优于 Q8-baseline 的候选 (在 train 上): {analysis['strict_improvers_count']} 个。</p>
    """

    overfit_warn = ""
    if abs(train_gap) > 10:
        cls = "warn"
        overfit_msg = f"⚠️ Train-holdout gap 为 {train_gap:+.1f}pp — 可能过拟合 train。仔细看 holdout。"
        overfit_warn = f'<div class="{cls}">{_h(overfit_msg)}</div>'
    else:
        overfit_msg = f"Train-holdout gap: {train_gap:+.1f}pp (Q8-baseline gap 是 {baseline_gap:+.1f}pp)。在可接受噪音内 — 无过拟合信号。"
        overfit_warn = f'<div class="pass-banner">{_h(overfit_msg)}</div>'

    winner = f"""
    <h2 id="winner">推荐 winner</h2>
    <p><b>参数:</b> <code>{_h(_fmt_params_q9(rec_p, 'cn'))}</code></p>
    {_train_holdout_summary(rec, baseline, 'cn')}
    {overfit_warn}
    {_per_anchor_table(rec['holdout'], 'HOLDOUT (事后验证)', 'cn')}
    {_per_anchor_table(rec['train'], 'TRAIN (grid 信号)', 'cn')}
    """

    config_diff = f"""
    <h2 id="config">配置变更 (应用)</h2>
    <pre><code>--- configs/regime_detection/fred_series.yml
+++ configs/regime_detection/fred_series.yml
   inflation_velocity:
-    weight: 0.0
+    weight: {rec_p['inflation_velocity_weight']}
     series:
       CPIAUCSL_velocity_3m: 0.40
       CPILFESL_velocity_3m: 0.30
       PCEPI_velocity_3m: 0.30
   growth_velocity:
-    weight: 0.0
+    weight: {rec_p['growth_velocity_weight']}
     series:
       PAYEMS_velocity_3m: 0.55
       INDPRO_velocity_3m: 0.45
</code></pre>"""

    if (rec_p['growth_thresh'] != 0.10 or rec_p['inflation_thresh'] != 0.12
            or rec_p['macro_w'] != 0.50):
        config_diff += f"""
    <pre><code>--- configs/regime_detection/regime_engine.yml
+++ configs/regime_detection/regime_engine.yml
   layers.macro_nowcast.weight_growth:    {rec_p['macro_w']}
   layers.macro_nowcast.weight_inflation: {rec_p['macro_w']}
   layers.market_implied.weight_growth:   {rec_p['market_w']}
   layers.market_implied.weight_inflation:{rec_p['market_w']}
   regime_thresholds.growth_up:           {rec_p['growth_thresh']}
   regime_thresholds.growth_down:         {-rec_p['growth_thresh']}
   regime_thresholds.inflation_up:        {rec_p['inflation_thresh']}
   regime_thresholds.inflation_down:      {-rec_p['inflation_thresh']}
</code></pre>"""
    else:
        config_diff += '<p class="muted">regime_engine.yml 不动 — Q8 的 layer 权重和阈值在 Q9 下仍最优。</p>'

    caveats = """
    <h2 id="caveats">注意事项</h2>
    <ul>
      <li><b>Holdout 样本小 (4 anchor)</b> — 高方差信号。Train/holdout 5pp 差距在采样噪音内。</li>
      <li><b>2024 disinflation 在 holdout</b> — 如果 Q9 主要因 velocity
        层 fit 到 2024 而赢, 那个胜利是真的但范围窄。Per-anchor
        holdout breakdown 显示收益是 2024 独占还是分散。</li>
      <li><b>2025 tariff 仍未解</b>: velocity 层读 CPI/PCE prints, 它们
        比政策事件滞后 1-2 个月。引擎仍缺单事件 shock 通道 — 留作 deferred。</li>
      <li><b>Risk overlay 自 Q7 冻结</b>。Q9 只动宏观 axis 部分。</li>
      <li><b>Concept composition 是 opinionated 的</b>: velocity concept
        用 40/30/30 权重 (CPI/Core CPI/PCE 通胀) 和 55/45 (PAYEMS/INDPRO 增长)。
        不同 split 可能给不同 winner — 单遍 grid 不扫这些 within-weight。</li>
    </ul>
    """
    return intro + methodology + split + grid_html + winner + config_diff + caveats


def main() -> int:
    analysis = _load("macro_calibration_analysis_q9.json")
    grid = _load("macro_calibration_grid_q9.json")
    when = datetime.now().strftime("%Y-%m-%d")
    en_body = _build_en(analysis, grid)
    cn_body = _build_cn(analysis, grid)

    OUT_EN.write_text(f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Q9 Macro Calibration — Velocity Layer ({when})</title>
{_style()}
</head>
<body>
<h1>Q9 Macro Calibration — Velocity Layer + Train/Holdout Discipline</h1>
<p class="muted">{when} · regime engine v2 · scope = macro axis only (risk overlay frozen at Q7)</p>
{en_body}
</body></html>
""", encoding="utf-8")
    print(f"wrote {OUT_EN} ({OUT_EN.stat().st_size:,} bytes)")

    OUT_CN.write_text(f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Q9 宏观校准 — Velocity 层 ({when})</title>
{_style()}
</head>
<body>
<h1>Q9 宏观校准 — Velocity 层 + Train/Holdout 纪律</h1>
<p class="muted">{when} · regime engine v2 · 范围 = 仅宏观 axis (风险 overlay 冻结自 Q7)</p>
{cn_body}
</body></html>
""", encoding="utf-8")
    print(f"wrote {OUT_CN} ({OUT_CN.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
