from __future__ import annotations

from pathlib import Path

from market_helper.reporting.performance_html import (
    build_performance_report_view_model,
    load_performance_history_frame,
    render_performance_tab,
)
from market_helper.reporting.risk_html import (
    build_risk_report_view_model,
    render_risk_tab,
)


def build_combined_html_report(
    *,
    positions_csv_path: str | Path,
    output_path: str | Path,
    performance_history_path: str | Path | None = None,
    performance_output_dir: str | Path | None = None,
    performance_report_csv_path: str | Path | None = None,
    returns_path: str | Path | None = None,
    proxy_path: str | Path | None = None,
    regime_path: str | Path | None = None,
    security_reference_path: str | Path | None = None,
    risk_config_path: str | Path | None = None,
    allocation_policy_path: str | Path | None = None,
    vol_method: str = "geomean_1m_3m",
) -> Path:
    history_path = _resolve_performance_history_path(
        performance_history_path=performance_history_path,
        performance_output_dir=performance_output_dir,
    )
    report_csv_path = _resolve_performance_report_csv_path(
        performance_report_csv_path=performance_report_csv_path,
        performance_output_dir=performance_output_dir,
    )
    risk_view_model = build_risk_report_view_model(
        positions_csv_path=positions_csv_path,
        returns_path=returns_path,
        proxy_path=proxy_path,
        regime_path=regime_path,
        security_reference_path=security_reference_path,
        risk_config_path=risk_config_path,
        allocation_policy_path=allocation_policy_path,
        vol_method=vol_method,
    )
    history = load_performance_history_frame(history_path)
    perf_view_model = build_performance_report_view_model(
        history,
        report_csv_path=report_csv_path,
        primary_currency="USD",
        secondary_currency="SGD",
        primary_basis="TWR",
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_combined_html(
            risk_html=render_risk_tab(risk_view_model),
            performance_html=render_performance_tab(perf_view_model),
            as_of=max(risk_view_model.as_of, perf_view_model.as_of),
        ),
        encoding="utf-8",
    )
    return output


def render_combined_html(*, risk_html: str, performance_html: str, as_of: str) -> str:
    return f"""<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8' />
  <title>Combined Portfolio Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; margin: 24px; color: #0f172a; background: #f8fafc; }}
    h1,h2 {{ margin: 0 0 12px 0; }}
    .page-header {{ margin-bottom: 16px; }}
    .tab-nav {{ display: flex; gap: 8px; margin-bottom: 16px; }}
    .tab-button {{ border: 0; border-radius: 999px; padding: 10px 16px; background: #e2e8f0; color: #0f172a; cursor: pointer; font-weight: 600; }}
    .tab-button.is-active {{ background: #0f172a; color: #f8fafc; }}
    .tab-panel {{ display: none; }}
    .tab-panel.is-active {{ display: block; }}
    .card {{ background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(15,23,42,0.1); padding: 16px; margin-bottom: 16px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ border-bottom: 1px solid #e2e8f0; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f1f5f9; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .metrics {{ display: flex; gap: 12px; flex-wrap: wrap; }}
    .metric {{ background: #f1f5f9; padding: 10px 12px; border-radius: 8px; min-width: 220px; }}
    .metric span {{ display: block; color: #475569; font-size: 12px; }}
    .metric strong {{ display: block; font-size: 20px; }}
    .metric small {{ display: block; margin-top: 4px; color: #475569; }}
    .scores {{ display: flex; gap: 12px; flex-wrap: wrap; color: #334155; }}
    .sparkline {{ width: 120px; height: 28px; }}
    .chart {{ display: grid; gap: 8px; margin-bottom: 12px; }}
    .chart-row {{ display: grid; grid-template-columns: 140px 1fr 72px; gap: 10px; align-items: center; }}
    .chart-track {{ position: relative; height: 14px; border-radius: 999px; background: #e2e8f0; overflow: hidden; }}
    .chart-midline {{ position: absolute; left: 50%; top: 0; bottom: 0; width: 1px; background: #94a3b8; }}
    .chart-fill-pos {{ position: absolute; left: 50%; top: 0; bottom: 0; background: #16a34a; }}
    .chart-fill-neg {{ position: absolute; top: 0; bottom: 0; background: #dc2626; }}
    .chart-value {{ text-align: right; color: #334155; font-size: 12px; font-variant-numeric: tabular-nums; }}
    .excluded-row {{ background: #fff7ed; }}
    .perf-chart-svg {{ width: 100%; height: 220px; display: block; background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%); border-radius: 12px; }}
    .perf-chart-svg polyline {{ fill: none; stroke-width: 3; }}
    .perf-chart-svg-positive polyline {{ stroke: #0f766e; }}
    .perf-chart-svg-drawdown polyline {{ stroke: #b91c1c; }}
  </style>
</head>
<body>
  <div class='page-header'>
    <h1>Combined Portfolio Report</h1>
    <p>As of {as_of}</p>
  </div>
  <div class='tab-nav' role='tablist' aria-label='Combined portfolio report tabs'>
    <button class='tab-button' data-tab-target='risk-tab' role='tab' aria-selected='false'>Risk</button>
    <button class='tab-button is-active' data-tab-target='performance-tab' role='tab' aria-selected='true'>Performance</button>
  </div>
  <section id='performance-tab' class='tab-panel is-active' role='tabpanel'>
    {performance_html}
  </section>
  <section id='risk-tab' class='tab-panel' role='tabpanel'>
    {risk_html}
  </section>
  <script>
    const buttons = document.querySelectorAll('.tab-button');
    const panels = document.querySelectorAll('.tab-panel');
    buttons.forEach((button) => {{
      button.addEventListener('click', () => {{
        const targetId = button.getAttribute('data-tab-target');
        buttons.forEach((item) => {{
          item.classList.remove('is-active');
          item.setAttribute('aria-selected', 'false');
        }});
        panels.forEach((panel) => panel.classList.remove('is-active'));
        button.classList.add('is-active');
        button.setAttribute('aria-selected', 'true');
        document.getElementById(targetId)?.classList.add('is-active');
      }});
    }});
  </script>
</body>
</html>
"""


def _resolve_performance_history_path(
    *,
    performance_history_path: str | Path | None,
    performance_output_dir: str | Path | None,
) -> Path:
    if performance_history_path is not None:
        return Path(performance_history_path)
    if performance_output_dir is None:
        raise ValueError("performance_history_path or performance_output_dir is required")
    return Path(performance_output_dir) / "performance_history.feather"


def _resolve_performance_report_csv_path(
    *,
    performance_report_csv_path: str | Path | None,
    performance_output_dir: str | Path | None,
) -> Path | None:
    if performance_report_csv_path is not None:
        return Path(performance_report_csv_path)
    if performance_output_dir is None:
        return None
    candidates = sorted(Path(performance_output_dir).glob("performance_report_*.csv"))
    if not candidates:
        return None
    return candidates[-1]


__all__ = ["build_combined_html_report", "render_combined_html"]
