"""Generate the Phase 1 + Phase 2 neighborhood-stability addendum
report (EN + CN) for the Q9 macro calibration.

Reads:
  data/research_artifacts/macro_neighborhood_q9_original.json
    — Phase 1 analysis on the original 360-config grid
  data/research_artifacts/macro_neighborhood_q9_v2.json
    — Phase 1+2 unified analysis on the augmented 522-config grid

Synthesizes a single addendum that answers the user critique:
  "The grid winner is the argmax of a noisy surface. The optimum should
   be a point whose small-neighborhood median is top-tier AND has no
   particularly bad point in the neighborhood."

Emits:
  data/research_artifacts/macro_q9_neighborhood_addendum_en.html
  data/research_artifacts/macro_q9_neighborhood_addendum_cn.html
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ART = REPO / "data/research_artifacts"
OUT_EN = ART / "macro_q9_neighborhood_addendum_en.html"
OUT_CN = ART / "macro_q9_neighborhood_addendum_cn.html"


def _h(s) -> str:
    return html.escape(str(s))


def _load(name: str) -> dict | list:
    return json.loads((ART / name).read_text(encoding="utf-8"))


def _fmt_params(p: dict) -> str:
    return (
        f"ivw={p['inflation_velocity_weight']}, "
        f"gvw={p['growth_velocity_weight']}, "
        f"gt=±{p['growth_thresh']}, "
        f"it=±{p['inflation_thresh']}, "
        f"macro/market={p['macro_w']}/{p['market_w']}"
    )


def _verdict_decision(orig: dict, ref: dict, lang: str = "en"):
    """Return (decision, details, recommendation_params)."""
    q9 = ref["q9_winner_annot"]
    top_orig = orig["top10_robust"][0] if orig["top10_robust"] else None
    top_ref = ref["top10_robust"][0] if ref["top10_robust"] else None

    if not top_ref:
        return ("inconclusive", "No candidate passes all filters on augmented grid.", None)

    q9_is_top = top_ref.get("is_q9_winner", False)
    if q9_is_top:
        return ("keep_q9", "Q9 winner IS the neighborhood-robust top on the augmented grid.", q9["params"])

    # Different top — compare on holdout
    h_delta = top_ref["self_holdout"] - q9["self_holdout"] if q9 else 0
    t_delta = top_ref["self_train"] - q9["self_train"] if q9 else 0
    robust_delta = top_ref["robust_train"] - q9["robust_train"] if q9 else 0

    if h_delta >= -0.5 and robust_delta > 0:
        # Top robust is also non-regressing on holdout AND has better robust train
        return ("switch", f"Top robust beats Q9 on train (+{t_delta:.1f}pp) without losing meaningful holdout ({h_delta:+.1f}pp).", top_ref["params"])
    elif h_delta < -0.5:
        return ("keep_q9", f"Top robust gains train-robustness ({robust_delta:+.1f}pp) but loses holdout ({h_delta:+.1f}pp). Q9 winner sits at a different point on the train/holdout curve.", q9["params"])
    else:
        return ("close_call", "Multiple candidates are nearly equivalent; defer to operator preference.", q9["params"])


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
      td.q9 { background: #fff8c5; }
      .muted { color: #57606a; font-size: 0.9em; }
      code { background: #f6f8fa; padding: 1px 5px; border-radius: 3px; font-size: 0.88em; }
      pre code { display: block; padding: 12px; line-height: 1.45; white-space: pre; }
      .banner { background: #ddf4ff; border-left: 4px solid #0969da; padding: 10px 16px; margin: 1em 0; border-radius: 4px; }
      .pass-banner { background: #dafbe1; border-left: 4px solid #1a7f37; padding: 10px 16px; margin: 1em 0; border-radius: 4px; }
      .warn { background: #fff8c5; border-left: 4px solid #9a6700; padding: 10px 16px; margin: 1em 0; border-radius: 4px; }
      .toc { background: #f6f8fa; padding: 12px 20px; border: 1px solid #d0d7de; border-radius: 6px; }
    </style>
    """


def _top_table(top_list, q9_params, lang="en"):
    if lang == "cn":
        headers = ["#", "参数", "self_T", "nbr_med_T", "nbr_min_T", "self_H", "nbr_min_H", "robust_T", "标记"]
    else:
        headers = ["#", "Params", "self_T", "nbr_med_T", "nbr_min_T", "self_H", "nbr_min_H", "robust_T", "Mark"]

    rows = []
    for i, a in enumerate(top_list[:10], 1):
        p = a["params"]
        is_q9 = q9_params and all(abs(float(p[k]) - float(v)) < 1e-6 for k, v in q9_params.items())
        is_baseline = a.get("is_q8_baseline", False)
        mark = "Q9*" if is_q9 else ("Q8 base" if is_baseline else "")
        cls = ' class="q9"' if is_q9 else ""
        rows.append(f"""
        <tr{cls}>
          <td>{i}</td>
          <td><code style="font-size:0.85em">{_h(_fmt_params(p))}</code></td>
          <td>{a['self_train']:.1f}%</td>
          <td>{a['nbr_train_median']:.1f}%</td>
          <td>{a['nbr_train_min']:.1f}%</td>
          <td>{a['self_holdout']:.1f}%</td>
          <td>{a['nbr_holdout_min']:.1f}%</td>
          <td><b>{a['robust_train']:.1f}</b></td>
          <td>{mark}</td>
        </tr>""")

    return f"""<table>
      <thead><tr>{''.join(f'<th>{h}</th>' for h in headers)}</tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>"""


def _filter_cascade_table(filters, total, lang="en"):
    if lang == "cn":
        rows = "".join(f"<tr><td>{_h(k)}</td><td>{v}/{total}</td></tr>" for k, v in filters.items() if k != "total")
        return f"""<table><thead><tr><th>过滤器</th><th>通过 / 总数</th></tr></thead><tbody>{rows}</tbody></table>"""
    rows = "".join(f"<tr><td>{_h(k)}</td><td>{v}/{total}</td></tr>" for k, v in filters.items() if k != "total")
    return f"""<table><thead><tr><th>Filter</th><th>Pass / total</th></tr></thead><tbody>{rows}</tbody></table>"""


def _build_en(orig: dict, ref: dict, decision: str, details: str, rec_params: dict | None) -> str:
    q9 = ref["q9_winner_annot"]
    top_ref = ref["top10_robust"][0] if ref["top10_robust"] else None
    n_orig = orig["n_configs"]
    n_ref = ref["n_configs"]

    decision_class = {
        "keep_q9": "pass-banner",
        "switch": "warn",
        "close_call": "warn",
        "inconclusive": "warn",
    }.get(decision, "warn")

    decision_label = {
        "keep_q9": "KEEP Q9 winner",
        "switch": "SWITCH to neighborhood-robust top",
        "close_call": "CLOSE CALL — operator preference",
        "inconclusive": "INCONCLUSIVE",
    }.get(decision, decision)

    return f"""
    <div class="banner">
      <b>Motivation</b>: the Q9 winner was selected as the argmax of
      <code>train_overall + 0.3·stability</code> among configs that did not
      regress on holdout. Argmax of a noisy surface can sit on a single
      grid-point spike. A robust optimum is one whose <em>neighborhood</em>
      is also top-tier and has no particularly bad neighbor. This addendum
      checks Q9 against that criterion in two phases:
      <ol>
        <li><b>Phase 1</b>: re-analyze the existing 360-config grid with
          L1 neighborhood statistics (zero new computation).</li>
        <li><b>Phase 2</b>: half-step refinement around the contenders
          (162 new configs, augmented grid = 522 configs), repeat the
          neighborhood analysis.</li>
      </ol>
    </div>

    <div class="toc"><b>Sections</b><ul>
      <li><a href="#rules">Selection rules (user-confirmed)</a></li>
      <li><a href="#p1">Phase 1 — neighborhood analysis, original grid</a></li>
      <li><a href="#p2">Phase 2 — augmented grid + re-analysis</a></li>
      <li><a href="#cmp">Q9 winner vs top robust (side-by-side)</a></li>
      <li><a href="#decision">Decision</a></li>
      <li><a href="#caveats">Caveats</a></li>
    </ul></div>

    <h2 id="rules">Selection rules (user-confirmed before execution)</h2>
    <ul>
      <li><b>Neighborhood</b>: L1 grid-index, same <code>layer_blend</code>
        (categorical, not crossed), ±1 step on exactly one of the 4
        continuous dims (ivw, gvw, gt, it). Max 8 neighbors per config.</li>
      <li><b>Top metric</b>: <code>median(neighbor train_overall)</code>
        — robust to a single outlier neighbor.</li>
      <li><b>No bad neighbor</b>:
        <code>min(neighbor train) ≥ max(baseline_train, self − 5pp)</code>
        — worst neighbor must beat baseline AND stay within 5pp of self.</li>
      <li><b>Eligibility filters</b>: <code>n_neighbors ≥ 4</code> AND
        <code>holdout ≥ baseline_holdout</code> AND
        <code>self_train > baseline_train</code> AND no_bad_neighbor.</li>
      <li><b>Ranking</b>:
        <code>robust_train = mean(self_train, neighbor_median_train)</code>;
        tiebreaker: <code>self_train</code>.</li>
      <li><b>Train/holdout discipline preserved</b>: all stats split by
        train and holdout; holdout never enters the optimization objective.</li>
    </ul>

    <h2 id="p1">Phase 1 — neighborhood analysis on original grid ({n_orig} configs)</h2>
    {_filter_cascade_table(orig["filter_cascade"], orig["filter_cascade"]["total"])}
    <p class="muted">Eligibility cascade reduces {orig["filter_cascade"]["total"]} → {orig["filter_cascade"]["all_combined"]} candidates. Q9 winner rank by robust_train among eligible: <b>{orig["q9_winner_rank_among_eligible"]}</b>.</p>

    <h3>Phase-1 top 10 by robust_train</h3>
    {_top_table(orig["top10_robust"], q9["params"])}

    <h2 id="p2">Phase 2 — augmented grid ({n_ref} configs)</h2>
    <p>Refined zone added half-step values on the dims that dominate
       the top-15: <code>ivw</code> ∈ {{0.5, 0.6, 0.7, 0.85, 1.0}},
       <code>gvw</code> ∈ {{0.0, 0.15, 0.3}}, <code>it</code> ∈ {{0.10,
       0.11, 0.12, 0.13, 0.14, 0.15}}, layer-blend ∈ {{0.55/0.45,
       0.60/0.40}}. Plus the original coarse grid, deduped: 162 new
       runs.</p>

    {_filter_cascade_table(ref["filter_cascade"], ref["filter_cascade"]["total"])}
    <p class="muted">Q9 winner rank by robust_train on augmented grid: <b>{ref["q9_winner_rank_among_eligible"]}</b> (was {orig["q9_winner_rank_among_eligible"]} on original).</p>

    <h3>Phase-2 top 10 by robust_train</h3>
    {_top_table(ref["top10_robust"], q9["params"])}

    <h2 id="cmp">Q9 winner vs Phase-2 top robust (side-by-side)</h2>
    <table>
      <thead><tr><th></th><th>Q9 winner</th><th>Phase-2 top robust</th><th>Δ</th></tr></thead>
      <tbody>
        <tr><td>Params</td><td><code style="font-size:0.85em">{_h(_fmt_params(q9['params']))}</code></td>
            <td><code style="font-size:0.85em">{_h(_fmt_params(top_ref['params']))}</code></td><td></td></tr>
        <tr><td>self_train</td><td>{q9['self_train']:.1f}%</td><td>{top_ref['self_train']:.1f}%</td>
            <td>{top_ref['self_train']-q9['self_train']:+.1f}pp</td></tr>
        <tr><td>self_holdout</td><td>{q9['self_holdout']:.1f}%</td><td>{top_ref['self_holdout']:.1f}%</td>
            <td>{top_ref['self_holdout']-q9['self_holdout']:+.1f}pp</td></tr>
        <tr><td>nbr_train_median</td><td>{q9['nbr_train_median']:.1f}%</td><td>{top_ref['nbr_train_median']:.1f}%</td>
            <td>{top_ref['nbr_train_median']-q9['nbr_train_median']:+.1f}pp</td></tr>
        <tr><td>nbr_train_min</td><td>{q9['nbr_train_min']:.1f}%</td><td>{top_ref['nbr_train_min']:.1f}%</td>
            <td>{top_ref['nbr_train_min']-q9['nbr_train_min']:+.1f}pp</td></tr>
        <tr><td>nbr_holdout_min</td><td>{q9['nbr_holdout_min']:.1f}%</td><td>{top_ref['nbr_holdout_min']:.1f}%</td>
            <td>{top_ref['nbr_holdout_min']-q9['nbr_holdout_min']:+.1f}pp</td></tr>
        <tr><td>robust_train</td><td>{q9['robust_train']:.1f}</td><td>{top_ref['robust_train']:.1f}</td>
            <td>{top_ref['robust_train']-q9['robust_train']:+.1f}</td></tr>
        <tr><td>n_neighbors</td><td>{q9['n_neighbors']}</td><td>{top_ref['n_neighbors']}</td><td></td></tr>
      </tbody>
    </table>

    <h2 id="decision">Decision</h2>
    <div class="{decision_class}">
      <b>{_h(decision_label)}</b><br>
      {_h(details)}
    </div>

    {f'<h3>Recommended params (apply)</h3><pre><code>{_h(_fmt_params(rec_params))}</code></pre>' if rec_params else ''}

    <h2 id="caveats">Caveats</h2>
    <ul>
      <li><b>Grid is still discrete</b>: even at half-step, the response
        surface is sampled, not analytical. A truly continuous optimum
        could sit between Phase-2 grid points.</li>
      <li><b>Small holdout (4 anchors)</b>: holdout delta of ±1-2pp is
        within sampling noise. Don't read holdout regressions of less
        than ~2pp as strong evidence.</li>
      <li><b>Neighborhood definition is L1, not L2</b>: configs that
        differ on 2+ dims are not considered neighbors. This is
        deliberate (each dim has different scale and meaning) but it
        means stability w.r.t. simultaneous multi-dim drift is not
        tested.</li>
      <li><b>Layer blend is treated as categorical</b>: we never compare
        across blends in a neighborhood. A robust optimum within
        m/m=0.6/0.4 may still be brittle if the operator changes blend
        for other reasons.</li>
      <li><b>"5pp drop" floor is arbitrary</b>: a tighter or looser
        threshold would change which configs pass the "no bad neighbor"
        rule. 5pp was chosen because it's roughly the Q8→Q9 train
        improvement scale.</li>
    </ul>
    """


def _build_cn(orig: dict, ref: dict, decision: str, details: str, rec_params: dict | None) -> str:
    q9 = ref["q9_winner_annot"]
    top_ref = ref["top10_robust"][0] if ref["top10_robust"] else None
    n_orig = orig["n_configs"]
    n_ref = ref["n_configs"]

    decision_class = {
        "keep_q9": "pass-banner",
        "switch": "warn",
        "close_call": "warn",
        "inconclusive": "warn",
    }.get(decision, "warn")

    decision_label = {
        "keep_q9": "保留 Q9 winner",
        "switch": "切换到邻域鲁棒 top",
        "close_call": "差距很小 — 由操作员决定",
        "inconclusive": "未定论",
    }.get(decision, decision)

    return f"""
    <div class="banner">
      <b>动机</b>: Q9 winner 是在 holdout 不 regression 的前提下, 按
      <code>train_overall + 0.3·stability</code> 取 argmax 选出的。
      但 argmax 在带噪面上可能停在单格尖刺。鲁棒最优应该是
      <em>邻域</em> 也 top-tier 且没有特别差邻居的点。本附录两阶段验证:
      <ol>
        <li><b>Phase 1</b>: 在现有 360 配置上重做 L1 邻域统计 (零额外计算)。</li>
        <li><b>Phase 2</b>: 在 contender 周围半步细化 (162 新 config,
          扩展网格 = 522 config), 重做邻域分析。</li>
      </ol>
    </div>

    <div class="toc"><b>章节</b><ul>
      <li><a href="#rules">选择规则 (用户预先确认)</a></li>
      <li><a href="#p1">Phase 1 — 原始网格邻域分析</a></li>
      <li><a href="#p2">Phase 2 — 扩展网格 + 再分析</a></li>
      <li><a href="#cmp">Q9 winner vs 鲁棒 top (并排)</a></li>
      <li><a href="#decision">决策</a></li>
      <li><a href="#caveats">注意事项</a></li>
    </ul></div>

    <h2 id="rules">选择规则 (执行前已和用户确认)</h2>
    <ul>
      <li><b>邻域</b>: L1 网格索引, 同 <code>layer_blend</code> (分类变量,
        不跨), 在 4 个连续维 (ivw, gvw, gt, it) 中只动 1 个 ±1 步。
        每个 config 最多 8 个邻居。</li>
      <li><b>Top 指标</b>: <code>median(邻居 train_overall)</code> —
        对单个异常邻居稳健。</li>
      <li><b>无差点规则</b>:
        <code>min(邻居 train) ≥ max(baseline_train, 自身 − 5pp)</code>
        — 最差邻居必须高于 baseline 且距自身不超过 5pp。</li>
      <li><b>资格过滤器</b>: <code>n_neighbors ≥ 4</code> AND
        <code>holdout ≥ baseline_holdout</code> AND
        <code>self_train > baseline_train</code> AND no_bad_neighbor。</li>
      <li><b>排序</b>:
        <code>robust_train = mean(self_train, 邻居中位数 train)</code>;
        次序: <code>self_train</code>。</li>
      <li><b>Train/holdout 纪律保持</b>: 所有统计分别在 train 和 holdout
        上算; holdout 永不进入优化目标。</li>
    </ul>

    <h2 id="p1">Phase 1 — 原始网格邻域分析 ({n_orig} configs)</h2>
    {_filter_cascade_table(orig["filter_cascade"], orig["filter_cascade"]["total"], "cn")}
    <p class="muted">资格级联 {orig["filter_cascade"]["total"]} → {orig["filter_cascade"]["all_combined"]} 候选。Q9 winner 在合格者中按 robust_train 排名: <b>{orig["q9_winner_rank_among_eligible"]}</b>。</p>

    <h3>Phase-1 robust_train 前 10</h3>
    {_top_table(orig["top10_robust"], q9["params"], "cn")}

    <h2 id="p2">Phase 2 — 扩展网格 ({n_ref} configs)</h2>
    <p>细化区在主导前 15 的维度上加半步: <code>ivw</code> ∈
       {{0.5, 0.6, 0.7, 0.85, 1.0}}, <code>gvw</code> ∈ {{0.0, 0.15, 0.3}},
       <code>it</code> ∈ {{0.10, 0.11, 0.12, 0.13, 0.14, 0.15}},
       layer-blend ∈ {{0.55/0.45, 0.60/0.40}}。加上原粗格, 去重: 162 个
       新 config。</p>

    {_filter_cascade_table(ref["filter_cascade"], ref["filter_cascade"]["total"], "cn")}
    <p class="muted">Q9 winner 在扩展网格上按 robust_train 排名: <b>{ref["q9_winner_rank_among_eligible"]}</b> (原始网格上是 {orig["q9_winner_rank_among_eligible"]})。</p>

    <h3>Phase-2 robust_train 前 10</h3>
    {_top_table(ref["top10_robust"], q9["params"], "cn")}

    <h2 id="cmp">Q9 winner vs Phase-2 鲁棒 top (并排)</h2>
    <table>
      <thead><tr><th></th><th>Q9 winner</th><th>Phase-2 鲁棒 top</th><th>Δ</th></tr></thead>
      <tbody>
        <tr><td>参数</td><td><code style="font-size:0.85em">{_h(_fmt_params(q9['params']))}</code></td>
            <td><code style="font-size:0.85em">{_h(_fmt_params(top_ref['params']))}</code></td><td></td></tr>
        <tr><td>self_train</td><td>{q9['self_train']:.1f}%</td><td>{top_ref['self_train']:.1f}%</td>
            <td>{top_ref['self_train']-q9['self_train']:+.1f}pp</td></tr>
        <tr><td>self_holdout</td><td>{q9['self_holdout']:.1f}%</td><td>{top_ref['self_holdout']:.1f}%</td>
            <td>{top_ref['self_holdout']-q9['self_holdout']:+.1f}pp</td></tr>
        <tr><td>nbr_train_median</td><td>{q9['nbr_train_median']:.1f}%</td><td>{top_ref['nbr_train_median']:.1f}%</td>
            <td>{top_ref['nbr_train_median']-q9['nbr_train_median']:+.1f}pp</td></tr>
        <tr><td>nbr_train_min</td><td>{q9['nbr_train_min']:.1f}%</td><td>{top_ref['nbr_train_min']:.1f}%</td>
            <td>{top_ref['nbr_train_min']-q9['nbr_train_min']:+.1f}pp</td></tr>
        <tr><td>nbr_holdout_min</td><td>{q9['nbr_holdout_min']:.1f}%</td><td>{top_ref['nbr_holdout_min']:.1f}%</td>
            <td>{top_ref['nbr_holdout_min']-q9['nbr_holdout_min']:+.1f}pp</td></tr>
        <tr><td>robust_train</td><td>{q9['robust_train']:.1f}</td><td>{top_ref['robust_train']:.1f}</td>
            <td>{top_ref['robust_train']-q9['robust_train']:+.1f}</td></tr>
        <tr><td>n_neighbors</td><td>{q9['n_neighbors']}</td><td>{top_ref['n_neighbors']}</td><td></td></tr>
      </tbody>
    </table>

    <h2 id="decision">决策</h2>
    <div class="{decision_class}">
      <b>{_h(decision_label)}</b><br>
      {_h(details)}
    </div>

    {f'<h3>推荐参数 (应用)</h3><pre><code>{_h(_fmt_params(rec_params))}</code></pre>' if rec_params else ''}

    <h2 id="caveats">注意事项</h2>
    <ul>
      <li><b>网格仍是离散的</b>: 即使半步, 响应面也是采样的不是解析的。
        真正连续的最优可能落在 Phase-2 网格点之间。</li>
      <li><b>Holdout 样本小 (4 anchor)</b>: holdout delta ±1-2pp 在采样
        噪音内。不要把小于 ~2pp 的 holdout 回退当成强证据。</li>
      <li><b>邻域定义是 L1, 不是 L2</b>: 在 2 个以上维度同时变化的 config
        不视为邻居。这是有意为之 (每个维度尺度和含义不同), 但意味着
        多维同时漂移的稳定性没被测试。</li>
      <li><b>Layer blend 当成分类变量处理</b>: 我们从不跨 blend 比较邻居。
        某个 m/m=0.6/0.4 内的鲁棒最优, 如果操作员因其他原因换 blend,
        可能不再鲁棒。</li>
      <li><b>"5pp drop" 下限是人定的</b>: 阈值更严或更松会改变哪些
        config 通过 "无差点" 规则。选 5pp 是因为它大致是 Q8→Q9 train
        提升的尺度。</li>
    </ul>
    """


def main() -> int:
    orig = _load("macro_neighborhood_q9_original.json")
    ref = _load("macro_neighborhood_q9_v2.json")

    decision, details, rec_params = _verdict_decision(orig, ref)

    when = datetime.now().strftime("%Y-%m-%d")
    en_body = _build_en(orig, ref, decision, details, rec_params)
    cn_body = _build_cn(orig, ref, decision, details, rec_params)

    OUT_EN.write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Q9 Neighborhood-Stability Addendum ({when})</title>
{_style()}
</head><body>
<h1>Q9 Macro Calibration — Neighborhood-Stability Addendum (Phase 1 + 2)</h1>
<p class="muted">{when} · checks whether the Q9 winner sits on a parameter
   spike or in a stable basin. User-driven critique of grid-argmax
   selection.</p>
{en_body}
</body></html>
""", encoding="utf-8")
    print(f"wrote {OUT_EN} ({OUT_EN.stat().st_size:,} bytes)")

    OUT_CN.write_text(f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>Q9 邻域稳定性附录 ({when})</title>
{_style()}
</head><body>
<h1>Q9 宏观校准 — 邻域稳定性附录 (Phase 1 + 2)</h1>
<p class="muted">{when} · 检查 Q9 winner 是否站在参数尖刺上还是稳定盆地里。
   源自用户对 grid-argmax 选择规则的方法学批评。</p>
{cn_body}
</body></html>
""", encoding="utf-8")
    print(f"wrote {OUT_CN} ({OUT_CN.stat().st_size:,} bytes)")
    print()
    print(f"DECISION: {decision}")
    print(f"DETAILS: {details}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
