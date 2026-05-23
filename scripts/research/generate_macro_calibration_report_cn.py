"""生成中文版的宏观校准研究报告。

读取的 JSON 数据与英文版相同 (macro_scout.json / macro_scout_after.json /
macro_calibration_grid.json / macro_calibration_analysis.json), 输出到
data/research_artifacts/macro_calibration_report_cn.html。
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ART = REPO / "data/research_artifacts"
OUT = ART / "macro_calibration_report_cn.html"


def _h(s) -> str:
    return html.escape(str(s))


def _load_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def _fmt_params(p: dict) -> str:
    return (
        f"min_weight={p['min_weight']:.2f}, growth_thresh=±{p['growth_thresh']:.2f}, "
        f"inflation_thresh=±{p['inflation_thresh']:.2f}, hyst={p['axis_min_consecutive']}日, "
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
          <td class="{risk_cls}">{'✓' if a['risk_match'] else '✗'} ({a['stress_days_pct']:.0f}% 压力日)</td>
        </tr>""")
    g_avg = sum(a["g_match_pct"] for a in scout["anchor_results"]) / len(scout["anchor_results"])
    i_avg = sum(a["i_match_pct"] for a in scout["anchor_results"]) / len(scout["anchor_results"])
    risk_avg = (
        sum(1 for a in scout["anchor_results"] if a["risk_match"])
        / len(scout["anchor_results"]) * 100
    )
    return f"""
    <h3>{_h(title)}</h3>
    <p class="muted">引擎运行: {scout['n_bdays']:,} 个交易日，{_h(scout['date_min'])} 至 {_h(scout['date_max'])}。
       Axis 阈值: 增长 ±{scout['thresholds']['growth_up']:.2f}，
       通胀 ±{scout['thresholds']['inflation_up']:.2f}。
       稳定性: 增长 label 中位数游程 {s['growth_median_run_bdays']:.0f}日 ({s['growth_n_runs']} 段)，
       通胀 label 中位数游程 {s['infl_median_run_bdays']:.0f}日 ({s['infl_n_runs']} 段)，
       quadrant 中位数游程 {s['quadrant_median_run_bdays']:.0f}日 ({s['quadrant_n_runs']} 段)。</p>
    <table class="anchor">
      <thead>
        <tr>
          <th>锚定时期</th><th>窗口</th>
          <th>增长共识</th><th>g_匹配</th><th>g_分数 (均值 [低,高])</th>
          <th>通胀共识</th><th>i_匹配</th><th>i_分数 (均值 [低,高])</th>
          <th>风险共识</th><th>风险检查</th>
        </tr>
      </thead>
      <tbody>{''.join(rows)}</tbody>
      <tfoot><tr>
        <td colspan="3"><b>{len(scout['anchor_results'])} 个锚定平均</b></td>
        <td class="{'ok' if g_avg>=60 else 'bad'}"><b>{g_avg:.1f}%</b></td>
        <td></td><td></td>
        <td class="{'ok' if i_avg>=60 else 'bad'}"><b>{i_avg:.1f}%</b></td>
        <td></td><td></td>
        <td><b>{risk_avg:.1f}% 匹配</b></td>
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
          <td>{m.get('g_median_run_bdays', '—')} / {m.get('i_median_run_bdays', '—')} 日</td>
        </tr>"""

    rows = [_row("Baseline (Q7 之后基线, 2026-05-22)", base_p, base_m)] if base else []
    rows.append(_row("⭐ 推荐 (本轮 Q8)", rec_p, rec_m, highlight=True))

    for i, p in enumerate(analysis["top10_composite"][:10], 1):
        if p.get("is_baseline") or p["params"] == rec_p:
            continue
        rows.append(_row(f"#{i} (按 composite 排)", p["params"], p["metrics"]))

    return f"""
    <h3>网格搜索: 共 {analysis['n_configs']} 个配置</h3>
    <table class="grid">
      <thead><tr>
        <th>位次</th><th>参数</th>
        <th>g_匹配</th><th>i_匹配</th><th>风险匹配</th>
        <th>总体</th>
        <th>中位数游程 (g/i)</th>
      </tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    <p class="muted">严格优于 baseline 的候选: {analysis['strict_improvers_count']} 个。Pareto 前沿大小: {analysis['pareto_front_count']} 个。安全候选 (risk_match ≥ 80%): {analysis['safe_count']} 个。</p>
    """


def _anchor_diff_table(scout_before: dict, scout_after: dict | None) -> str:
    if not scout_after:
        return '<p class="muted">尚未生成 after-scout，应用配置后将出现 per-anchor 对比表。</p>'
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
        <th>锚定时期</th><th>共识 (g/i)</th>
        <th>g_匹配 (前)</th><th>g_匹配 (后)</th><th>Δg</th>
        <th>i_匹配 (前)</th><th>i_匹配 (后)</th><th>Δi</th>
      </tr></thead>
      <tbody>{''.join(rows)}</tbody>
      <tfoot>
        <tr>
          <td colspan="2"><b>平均</b></td>
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
    <h3>关键决策与依据</h3>
    <ol>
      <li><b>层间权重: macro 与 market 改为 balanced (各 0.50)</b>
        (原 macro 0.35/0.30 + market 0.65/0.70)。
        本轮宏观层首次接入完整 FRED 面板，硬数据 (CPI/PCE/payrolls) 真正
        进入打分。Grid 表明 balanced 在 13 个共识锚定的总体匹配率上
        全面占优 — 因为 macro 在 expansion / reflation 周期上的判断
        (yoy 视角下增长稳/通胀升) 是对的，而原来 market-heavy 的 blend
        让这些周期被股市噪音拖到 Neutral。</li>
      <li><b>增长 axis 阈值: ±0.15 → ±0.10</b>。
        在新的 50/50 blend 下，增长分数典型范围更靠近零附近。
        把 deadband 收窄使
        2017 Goldilocks (+45pp)、2010-12 expansion (+24pp)、2021 reflation
        (+28pp)、2022 H1 (+30pp) 这些"轻度但持续 Up"的窗口正确显示为
        Up，而不是被打成 Neutral。</li>
      <li><b>通胀 axis 阈值 (±0.12) 与 hysteresis (5 日) 不变</b>。
        Grid 显示这两个已经位于最优区间。通胀 deadband 进一步收窄
        (例如 ±0.08) 反而在 2017、2020H2 等阶段错报为 Up，得不偿失。
        Hysteresis 改大到 10 日对 measurement 无差异 (我们的 stability
        指标用 raw label 计算)，且会延迟实盘里的 turning point 检测。</li>
      <li><b>Recency decay 的下限 (min_weight = 0.65) 保持</b>。
        本来 Q3 文档建议作为 next step 把这个降到 ~0.10 来"激活
        per-frequency decay"。但 grid 显示 0.10 / 0.30 / 0.65 三档
        在 match 上几乎没有差异 — 因为高频 series (周度 ICSA、日度
        T5YIFR) 在各自 concept 内的 within-weight 都很小 (ICSA 在
        labor 是 0.30，T5YIFR 在 market_expectations 是 1.0 但该
        concept 只占 inflation 1.25/3.75 ≈ 33%)，光让它们 fade 不
        能撼动 axis 分数。要真正让 decay 起作用需要重构 concept
        composition，本轮不做。</li>
    </ol>
    <h3>净效果</h3>
    <ul>
      <li>总体共识匹配: {base_m.get('overall_avg_match_pct', 0):.1f}% → <b>{rec_m['overall_avg_match_pct']:.1f}%</b>
        (Δ {delta_match:+.1f} pp)</li>
      <li>增长 label 中位数游程: {base_m.get('g_median_run_bdays', 0)} → <b>{rec_m['g_median_run_bdays']} 日</b>
        (Δ {delta_stab_g:+d} 日)</li>
      <li>通胀 label 中位数游程: {base_m.get('i_median_run_bdays', 0)} → <b>{rec_m['i_median_run_bdays']} 日</b>
        (Δ {delta_stab_i:+d} 日)</li>
      <li>风险 overlay 匹配率: 77% (Q7 已经最优，未动)</li>
    </ul>
    """


def _methodology_html() -> str:
    return """
    <h3>方法学</h3>
    <p>本轮校准把 regime 引擎跑过完整的 FRED-aware 历史
       (1921 → 今天，约 27,000 个交易日，warmup 后)，所有调节旋钮都
       在网格里扫，然后衡量三个正交质量:</p>
    <ul>
      <li><b>共识匹配 (consensus match)</b> — 在 13 个跨 2008-2025 的
        命名宏观周期上，把引擎逐日的 axis label 和该窗口的广泛接受
        consensus 读数 (增长/通胀/风险) 对比。匹配率 = 引擎 label 与
        consensus label 一致的天数比例。</li>
      <li><b>稳定性 (stability)</b> — axis label 的中位数游程长度
        (用 final score 对照阈值即时计算，<em>不</em>应用
        hysteresis)，以及游程数量。中位数游程越短说明引擎在阈值附近
        反复抖。这是配置的 <em>噪声底</em>，不是引擎实际 emit 的 label
        流 — 引擎下游会再叠一层 <code>min_consecutive_days</code>
        hysteresis 把它平滑。</li>
      <li><b>响应速度 (latency)</b> — 在 5 个 sharp transition 点
        (COVID 增长转折、COVID 通胀塌陷、2021 reflation 起点、
        2022 stagflation 起点、2024 通胀降温)，测量从命名日期起到
        引擎首次 label 目标状态的交易日数。越低越快。<em>注意</em>:
        本轮的 anchor 集里，命名 transition 日期对绝大多数配置而言
        引擎已经在目标状态，latency 退化为 0，只作为护栏 (保留为
        未来更精细 probe 的接口)。</li>
    </ul>
    <h3>选择规则 (网格 → 推荐)</h3>
    <ol>
      <li>每个配置算 composite =
          <code>overall_match% + 0.3·min(median_run_bdays, 20)</code>。
          匹配率与稳定性的相对权重是 16:1，匹配率主导。
          <em>Latency 故意不入选择规则</em> — 见上述退化原因。</li>
      <li>严格优于 baseline (strict-improvers) 层: 在 (匹配率, 稳定性)
          两个维度都不弱于 baseline 且至少一个严格更优的候选。按
          composite 取最高 — 本轮 Q8 推荐就是从这层选出。</li>
      <li>Safe-fallback 层: <code>risk_avg_match_pct ≥ 80%</code> 的
          候选，防止 risk overlay 倒退。按 composite 取最高。</li>
      <li>Open 层 (兜底): 无视 safety filter 的 composite 最高。</li>
    </ol>
    <h3>共识标签是 LEVEL-based，不是 DIRECTION-based</h3>
    <p>这是最重要的 framing 决定。例子:</p>
    <ul>
      <li>2023 disinflation: CPI YoY 从 6% 降到 3.3%，但仍远高于
        2.5% 的舒适水平 — 宏观通胀分数 (以 2.5±0.5 为阈值的
        threshold 归一化) 整个窗口都读 <em>Up</em>，不是
        <em>Down</em>。所以 i_consensus 标 Up 以匹配 level 解读。</li>
      <li>2022 H1 stagflation: GDP Q1 / Q2 都打负，但 YoY payrolls
        是 +5-6% (post-COVID 基数效应)。宏观增长分数读
        <em>Up</em>。所以 g_consensus 标 Up。</li>
      <li>2020 H2 recovery: 月度恢复很快，但 YoY payrolls 7 月还差
        -7%，10 月 -5%。Level 上看劳动力市场还是深度受损。所以
        g_consensus 标 Down。</li>
    </ul>
    <p>这个 framing 匹配引擎的实际打分方式 (YoY transform + threshold
       归一化)。direction-based framing 需要加 MoM/QoQ velocity 类
       signal — 那是另一个工程任务，不是 calibration tuning。</p>
    """


def _macro_data_dimensions_html() -> str:
    return """
    <h3>宏观数据: 决定设计的几个维度</h3>
    <p>FRED 面板为 8 个 calibration 旋钮提供输入，跨 4 个维度。
       每个维度都有天然的 tradeoff，calibration 必须尊重。</p>
    <table class="dim">
      <thead><tr><th>维度</th><th>旋钮</th><th>Tradeoff</th><th>当前处理</th></tr></thead>
      <tbody>
        <tr><td><b>发布滞后</b></td>
            <td><code>publication_lag_days</code> per series</td>
            <td>避免 lookahead vs 实时保真</td>
            <td>每个 series 把观测日期按其发布滞后向前 shift (CPI 14 日，
                PCE 30 日，payrolls 7 日)。日度 series (T5YIFR、T10Y3M、
                ICSA 周度) 滞后 1-5 日。</td></tr>
        <tr><td><b>发布频率与新鲜度</b></td>
            <td><code>recency_weighting</code> (half_life、min_weight)</td>
            <td>新 print 应该 dominate vs 不把 series 在发布间隔内
                降权到零</td>
            <td>Half-life 由 <code>frequency_hint</code> 派生
                (daily=5、weekly=5、monthly=22、quarterly=66 日)。
                <em>本轮 grid 显示降低 0.65 的下限并不显著改善 match —
                高频 series 在 concept 内 within-weight 太小。</em></td></tr>
        <tr><td><b>YoY vs MoM transform</b></td>
            <td><code>transform</code> per series</td>
            <td>YoY 平滑但滞后转折 6 个月;
                MoM 及时但噪声大</td>
            <td>所有主要宏观 series 都用 YoY transform — 宏观 axis 本质
                是慢速、晚周期读数。更快的 turning-point 检测来自 market
                layer (breakevens、equity drawdown)。</td></tr>
        <tr><td><b>Level vs change 归一化</b></td>
            <td><code>normalization</code>:
                <code>threshold</code>、<code>zscore</code> 等</td>
            <td>Threshold 对照绝对参考值 (例 CPI YoY=2.5%);
                z-score 对照历史分布。Threshold 更可解释;
                z-score 跨 regime 更稳健。</td>
            <td>通胀 series 用 threshold (显式锚: CPI 2.5%、PCE 2.2%)。
                增长 series 用 z-score。Sticky-price CPI 和 AHETPI 工资
                也用 threshold; 其它都 z-score。</td></tr>
        <tr><td><b>Concept 聚合</b></td>
            <td><code>growth_concepts</code> /
                <code>inflation_concepts</code> 权重</td>
            <td>单 series 主导 vs 平均掉噪</td>
            <td>Concept 权重 = 语义重要性 (labor=1.0, production=0.75,
                broad_leading=0.75 for 增长); concept 内 within-weight
                补偿冗余 (UNRATE+PAYEMS 在 labor 共占 35/35 防止 employment
                信号被双计)。</td></tr>
        <tr><td><b>Bucket 平衡: fast vs slow</b></td>
            <td>concept composition</td>
            <td>Slow = 稳定但晚; fast = 响应但抖</td>
            <td>增长 axis 当前 slow-dominated (labor、production、
                consumption 全部 monthly YoY)。Market layer 补 fast 视角。</td></tr>
        <tr><td><b>交叉相关</b></td>
            <td>concept composition + within-weights</td>
            <td>高相关 series 双计会放大错觉</td>
            <td>UNRATE + PAYEMS 相关 0.93 → labor 内 50/50 split。
                T10Y2Y + T10Y3M (都是 yield curve) 当前不入 concept
                (dormant) 避免双计。CPIAUCSL + CPILFESL 与 PCE 配对在
                realized_broad 内各 25%。</td></tr>
        <tr><td><b>Threshold 语义</b></td>
            <td><code>neutral_level</code>、<code>threshold</code></td>
            <td>Direction-honest (升/降) vs
                level-honest (相对目标高/低)</td>
            <td>通胀阈值是 level-honest: CPI YoY 在 4% 永远读 Up，
                即使刚从 6% 跌下来。匹配 Fed 舒适框架但和"disinflation"
                的口语表达不符 (见 Methodology 节)。</td></tr>
      </tbody>
    </table>
    """


def _config_diff_html(analysis: dict) -> str:
    rec = analysis["recommendation"]["params"]
    return f"""
    <h3>配置变更 (已应用)</h3>
    <pre><code>--- configs/regime_detection/regime_engine.yml
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
+    growth_up: {rec['growth_thresh']:.2f}
+    growth_down: {-rec['growth_thresh']:.2f}
     inflation_up: 0.12     # 不变
     inflation_down: -0.12  # 不变
     min_consecutive_days: 5  # 不变

# fred_series.yml 不动
# (recency_weighting.min_weight 保持 {rec['min_weight']:.2f} —
#  grid 显示降低对 match 无显著贡献)
</code></pre>
    """


def _style() -> str:
    return """
    <style>
      body { font-family: ui-sans-serif, system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", "Segoe UI", Roboto, sans-serif;
             max-width: 1200px; margin: 30px auto; padding: 0 20px; line-height: 1.65;
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
    body.append("""
    <div class="banner">
      <b>目标</b>: 交付一个 regime 引擎，做到 (i) 命名宏观锚定时期的
      label 符合广泛接受的共识读数，(ii) 对实际 turning point 响应足够
      快可作为日级操作信号，(iii) 转换稳定到不会因单一 print 反复跳。
      这三个约束方向相反; grid 搜索探测了 tradeoff 平面，Pareto 前沿
      就是答案区间。
    </div>
    """)
    body.append('<div class="toc"><b>章节</b><ul>'
                '<li><a href="#m">方法学与共识 framing</a></li>'
                '<li><a href="#d">宏观数据维度</a></li>'
                '<li><a href="#b">基线扫描 (校准前)</a></li>'
                '<li><a href="#g">网格搜索汇总</a></li>'
                '<li><a href="#a">校准后扫描</a></li>'
                '<li><a href="#r">决策、净效果、配置变更</a></li>'
                '<li><a href="#c">注意事项与未覆盖工作</a></li>'
                '</ul></div>')

    body.append('<h2 id="m">方法学</h2>')
    body.append(_methodology_html())

    body.append('<h2 id="d">宏观数据维度</h2>')
    body.append(_macro_data_dimensions_html())

    body.append('<h2 id="b">基线扫描 (当前 shipped 配置)</h2>')
    body.append(_scout_table(scout_before, "校准前: 各锚定时期匹配率"))

    body.append('<h2 id="g">网格搜索</h2>')
    body.append(_grid_summary_html(grid, analysis))

    if scout_after:
        body.append('<h2 id="a">校准后扫描</h2>')
        body.append(_scout_table(scout_after, "校准后: 各锚定时期匹配率"))
        body.append('<h3>逐锚定匹配率变化 (前 → 后)</h3>')
        body.append(_anchor_diff_table(scout_before, scout_after))
    else:
        body.append('<h2 id="a">校准后扫描</h2>')
        body.append('<p class="warn">尚未做 post-apply 复跑。应用配置后运行 '
                    '<code>python scripts/research/macro_scout.py</code> 即可。</p>')

    body.append('<h2 id="r">决策与应用</h2>')
    body.append(_decisions_html(scout_before, scout_after or scout_before, analysis))
    body.append(_config_diff_html(analysis))

    if scout_after:
        body.append('<h3>逐锚定平均分数轨迹 (前 → 后)</h3>')
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
            <th>锚定时期</th>
            <th>g_均值 (前)</th><th>g_均值 (后)</th><th>Δg</th>
            <th>i_均值 (前)</th><th>i_均值 (后)</th><th>Δi</th>
          </tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
        <p class="muted">增长 Δ 为正表示引擎把该窗口推向更明显的 Up; 通胀同理。
           变化方向应与该锚定的 consensus 方向一致。</p>
        """)

    body.append('<h2 id="c">注意事项与未覆盖工作</h2>')
    body.append("""
    <ul>
      <li><b>Level vs direction</b>: 引擎打的是绝对 level (
        "通胀离舒适水平有多高")，不是方向 ("正在朝哪边走")。
        如果想要 direction-honest 信号 (MoM velocity, 二阶导数)，
        需要单独加一层 signal，不是本轮 tuning 能解决的。</li>
      <li><b>本轮不动 concept-level tuning</b>: 本次 calibration 只扫
        4 个标量旋钮 (decay floor、axis 阈值、layer blend、hysteresis)。
        <code>fred_series.yml</code> 里的 concept composition 不动:
        增长用 <code>labor</code> (UNRATE+PAYEMS+ICSA)、
        <code>consumption</code> (RSAFS)、
        <code>production</code> (INDPRO)、
        <code>broad_leading</code> (USSLIND);
        通胀用 <code>realized_broad</code> (CPI/CPILFE/PCE/PCEPILFE 各 25%)、
        <code>persistence</code> (sticky CPI)、
        <code>market_expectations</code> (T5YIFR)、
        <code>wage_pressure</code> (AHETPI)。
        激活 dormant series (T10Y2Y yield curve、T5YIE breakevens、
        DFII10 real yield、PPIACO、M2SL、HOUST/PERMIT、UMCSENT、MANEMP)
        是单独的结构性 pass — 参见
        <code>docs/architecture/devplans/regime_engine.md</code>
        的 "Activating a Dormant Signal" runbook。</li>
      <li><b>共识 label 是作者指定</b>: 我把 13 个锚定按广泛接受的
        consensus 打了标，但 reasonable analysts 在边缘会有分歧
        (尤其 2018 Q4、2019 H2、2024)。Grid 优化的是 13 个的平均
        匹配率 — 单个有争议的锚定不会主导结果。</li>
      <li><b>风险 overlay 不动</b>: 本轮保留 Q7 的风险 overlay
        校准 (enter_threshold=0.65, rcd=1) — 只动宏观 axis 的
        权重 / decay / 阈值 / hysteresis。Grid 过滤 risk_match ≥ 80%
        (或 fall through 到 top composite) 防止风险检测倒退。</li>
      <li><b>稳定性指标用的是 instantaneous label</b>: 中位数游程
        长度直接从 final 分数对照阈值算，<em>没有</em>叠 hysteresis。
        这是有意为之 — 测的是 <em>分数本身</em> 在边界附近的振荡，
        不是 hysteresis 滤波器掩盖了多少抖动。引擎下游的
        <code>base_regime</code> 流 (叠了 <code>min_consecutive_days</code>
        hysteresis) 比这平滑得多; baseline 的 quadrant 中位数游程是
        17 日。</li>
      <li><b>本轮 latency probe 退化</b>: 命名 transition 日期 (例
        COVID 增长转折 = 2020-02-24) 对大多数配置都已经处于目标
        状态，所以 latency = 0 对所有 probe 成立。Latency 保留在
        composite 是 forward-compat; 未来 probe 应该从规范 transition
        日期 <em>之前</em> 几日起算才能真正测出响应速度。</li>
    </ul>
    """)

    rec_p = analysis["recommendation"]["params"]
    title = "宏观校准研究报告 (Q8)"
    when = datetime.now().strftime("%Y-%m-%d")
    html_str = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{_h(title)} — {_h(when)}</title>
{_style()}
</head>
<body>
<h1>{_h(title)}</h1>
<p class="muted">生成日期 {_h(when)} · regime engine v2 · 范围 = 宏观 axis (增长 + 通胀)
   · 风险 overlay 已冻结自 Q7</p>
<p class="muted"><b>推荐参数:</b> {_h(_fmt_params(rec_p))}</p>
{''.join(body)}
</body></html>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html_str, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
