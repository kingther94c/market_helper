from __future__ import annotations

"""CLI entrypoint for the read-only market_helper workflows."""

import argparse
from pathlib import Path
from typing import Sequence

from market_helper.workflows.generate_report import (
    generate_combined_html_report,
    generate_etf_sector_sync,
    generate_ibkr_flex_performance_report,
    generate_ibkr_position_report,
    generate_live_ibkr_position_report,
    generate_position_report,
    generate_report_mapping_table,
    generate_risk_html_report,
    generate_security_reference_sync,
)
from market_helper.workflows.generate_regime import generate_regime_snapshots
from market_helper.domain.regime_detection.policies.regime_policy import (
    load_regime_policy,
    resolve_policy,
)
from market_helper.domain.regime_detection.services.detection_service import load_regime_snapshots


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser.

    The command names are intentionally kept stable even though the underlying
    implementation has been moved into the new domain-driven package layout.
    """
    parser = argparse.ArgumentParser(prog="market-helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    position_report = subparsers.add_parser(
        "position-report",
        help="Generate a CSV position report from local normalized snapshot files.",
    )
    position_report.add_argument("--positions", required=True, help="Path to positions JSON.")
    position_report.add_argument("--prices", required=True, help="Path to prices JSON.")
    position_report.add_argument("--output", required=True, help="Path to output CSV.")


    ibkr_flex_performance_report = subparsers.add_parser(
        "ibkr-flex-performance-report",
        help="Parse an IBKR Flex XML and export a dated horizon performance CSV (MTD/YTD/1M, MWR/TWR, USD/SGD).",
    )
    ibkr_flex_performance_report.add_argument("--flex-xml", required=True, help="Path to downloaded Flex XML file.")
    ibkr_flex_performance_report.add_argument("--output-dir", required=True, help="Directory for generated CSV outputs.")

    ibkr_position_report = subparsers.add_parser(
        "ibkr-position-report",
        help="Generate a CSV position report directly from raw IBKR JSON payloads.",
    )
    ibkr_position_report.add_argument("--ibkr-positions", required=True, help="Path to raw IBKR positions JSON.")
    ibkr_position_report.add_argument("--ibkr-prices", required=True, help="Path to raw IBKR prices JSON.")
    ibkr_position_report.add_argument("--output", required=True, help="Path to output CSV.")
    ibkr_position_report.add_argument("--as-of", required=False, help="Optional timestamp override.")

    ibkr_live_position_report = subparsers.add_parser(
        "ibkr-live-position-report",
        help="Generate a CSV position report from a live TWS / IB Gateway session via ib_async.",
    )
    ibkr_live_position_report.add_argument("--output", required=True, help="Path to output CSV.")
    ibkr_live_position_report.add_argument("--host", default="127.0.0.1", help="Local TWS / IB Gateway host.")
    ibkr_live_position_report.add_argument("--port", type=int, default=7497, help="TWS / IB Gateway API port.")
    ibkr_live_position_report.add_argument("--client-id", type=int, default=1, help="ib_async client id.")
    ibkr_live_position_report.add_argument("--account", required=False, help="Optional account id.")
    ibkr_live_position_report.add_argument("--timeout", type=float, default=4.0, help="Timeout seconds.")
    ibkr_live_position_report.add_argument("--as-of", required=False, help="Optional timestamp override.")

    risk_html_report = subparsers.add_parser(
        "risk-html-report",
        help="Generate an HTML risk report from a position CSV and daily-return inputs.",
    )
    risk_html_report.add_argument("--positions-csv", required=True, help="Path to position CSV.")
    risk_html_report.add_argument("--returns", required=False, help="Optional returns JSON override.")
    risk_html_report.add_argument("--output", required=True, help="Path to output HTML.")
    risk_html_report.add_argument("--proxy", required=False, help="Optional estimate vol proxy JSON.")
    risk_html_report.add_argument("--regime", required=False, help="Optional regime snapshot JSON path.")
    risk_html_report.add_argument(
        "--security-reference",
        "--mapping-table",
        dest="security_reference",
        required=False,
        help="Optional generated security-reference CSV path. Defaults to data/artifacts/portfolio_monitor/security_reference.csv.",
    )
    risk_html_report.add_argument(
        "--risk-config",
        required=False,
        help="Recommended: optional unified risk-report YAML config path (lookthrough + policy). Defaults to configs/portfolio_monitor/report_config.yaml.",
    )
    risk_html_report.add_argument(
        "--allocation-policy",
        required=False,
        help="Deprecated compatibility-only: optional policy-only YAML override path.",
    )
    risk_html_report.add_argument(
        "--vol-method",
        required=False,
        default="geomean_1m_3m",
        choices=["geomean_1m_3m", "5y_realized", "ewma", "forward_looking"],
        help="Volatility method used for contribution views.",
    )
    risk_html_report.add_argument(
        "--inter-asset-corr",
        required=False,
        default="historical",
        choices=["historical", "corr_0", "corr_1"],
        help="Inter-asset-class correlation assumption used to aggregate asset-class loadings into portfolio vol.",
    )

    combined_html_report = subparsers.add_parser(
        "combined-html-report",
        help="Generate a combined HTML report with performance and risk tabs.",
    )
    combined_html_report.add_argument("--positions-csv", required=True, help="Path to position CSV.")
    combined_html_report.add_argument("--output", required=True, help="Path to output HTML.")
    combined_html_report.add_argument("--performance-history", required=False, help="Optional nav_cashflow_history.feather path.")
    combined_html_report.add_argument("--performance-output-dir", required=False, help="Optional performance artifact directory.")
    combined_html_report.add_argument("--performance-report-csv", required=False, help="Optional dated performance report CSV path.")
    combined_html_report.add_argument("--returns", required=False, help="Optional returns JSON override.")
    combined_html_report.add_argument("--proxy", required=False, help="Optional estimate vol proxy JSON.")
    combined_html_report.add_argument("--regime", required=False, help="Optional regime snapshot JSON path.")
    combined_html_report.add_argument(
        "--security-reference",
        "--mapping-table",
        dest="security_reference",
        required=False,
        help="Optional generated security-reference CSV path. Defaults to data/artifacts/portfolio_monitor/security_reference.csv.",
    )
    combined_html_report.add_argument(
        "--risk-config",
        required=False,
        help="Optional unified risk-report YAML config path.",
    )
    combined_html_report.add_argument(
        "--allocation-policy",
        required=False,
        help="Deprecated compatibility-only: optional policy-only YAML override path.",
    )
    combined_html_report.add_argument(
        "--vol-method",
        required=False,
        default="geomean_1m_3m",
        choices=["geomean_1m_3m", "5y_realized", "ewma", "forward_looking"],
        help="Volatility method used for contribution views.",
    )
    combined_html_report.add_argument(
        "--inter-asset-corr",
        required=False,
        default="historical",
        choices=["historical", "corr_0", "corr_1"],
        help="Inter-asset-class correlation assumption used to aggregate asset-class loadings into portfolio vol.",
    )

    security_reference_sync = subparsers.add_parser(
        "security-reference-sync",
        help="Rebuild the generated security-reference CSV from the tracked security universe.",
    )
    security_reference_sync.add_argument(
        "--output",
        required=False,
        help="Optional output path. Defaults to data/artifacts/portfolio_monitor/security_reference.csv.",
    )

    etf_sector_sync = subparsers.add_parser(
        "etf-sector-sync",
        help="Fetch ETF sector weights from FMP and merge them into us_sector_lookthrough.json.",
    )
    etf_sector_sync.add_argument(
        "--symbol",
        action="append",
        required=True,
        help="ETF ticker to fetch. Repeat for multiple symbols.",
    )
    etf_sector_sync.add_argument(
        "--output",
        required=False,
        help="Optional output path. Defaults to configs/portfolio_monitor/us_sector_lookthrough.json.",
    )
    etf_sector_sync.add_argument(
        "--api-key",
        required=False,
        help="Optional FMP API key. Falls back to FMP_API_KEY or configs/portfolio_monitor/local.env.",
    )

    regime_detect = subparsers.add_parser(
        "regime-detect",
        help="Run deterministic rule-based regime detection and write JSON snapshots.",
    )
    regime_detect.add_argument("--returns", required=True, help="Path to returns JSON with EQ/FI series.")
    regime_detect.add_argument("--proxy", required=True, help="Path to proxy JSON with VIX/MOVE/HY_OAS/UST2Y/UST10Y.")
    regime_detect.add_argument("--output", required=True, help="Path to output regime snapshots JSON.")
    regime_detect.add_argument("--indicators-output", required=False, help="Optional indicator snapshot output JSON.")
    regime_detect.add_argument(
        "--config",
        required=False,
        help="Optional regime config YAML path. Example template: configs/regime_detection/regime_config.example.yml.",
    )
    regime_detect.add_argument("--latest-only", action="store_true", help="Write latest snapshot only.")

    regime_report = subparsers.add_parser(
        "regime-report",
        help="Print human-readable summary of latest regime plus policy suggestion.",
    )
    regime_report.add_argument("--regime", required=True, help="Path to regime snapshots JSON.")
    regime_report.add_argument(
        "--policy",
        required=False,
        help="Optional policy YAML overrides. Example template: configs/regime_detection/regime_policy.example.yml.",
    )

    mapping_table_report = subparsers.add_parser(
        "extract-report-mapping",
        help="Extract stable mapping fields from a target workbook into a security-reference CSV seed.",
    )
    mapping_table_report.add_argument(
        "--workbook",
        required=True,
        help="Path to the source workbook, e.g. outputs/reports/target_report.xlsx.",
    )
    mapping_table_report.add_argument(
        "--output",
        required=True,
        help="Path to output security-reference CSV seed.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Keep dispatch explicit instead of clever: this is the stable public API
    # surface and it is easier to maintain when each command branch is visible.
    if args.command == "position-report":
        generate_position_report(positions_path=Path(args.positions), prices_path=Path(args.prices), output_path=Path(args.output))
        return 0
    if args.command == "ibkr-flex-performance-report":
        generate_ibkr_flex_performance_report(
            flex_xml_path=Path(args.flex_xml),
            output_dir=Path(args.output_dir),
        )
        return 0
    if args.command == "ibkr-position-report":
        generate_ibkr_position_report(
            ibkr_positions_path=Path(args.ibkr_positions),
            ibkr_prices_path=Path(args.ibkr_prices),
            output_path=Path(args.output),
            as_of=args.as_of,
        )
        return 0
    if args.command == "ibkr-live-position-report":
        generate_live_ibkr_position_report(
            output_path=Path(args.output),
            host=args.host,
            port=args.port,
            client_id=args.client_id,
            account_id=args.account,
            timeout=args.timeout,
            as_of=args.as_of,
        )
        return 0
    if args.command == "risk-html-report":
        generate_risk_html_report(
            positions_csv_path=Path(args.positions_csv),
            returns_path=Path(args.returns) if args.returns else None,
            output_path=Path(args.output),
            proxy_path=Path(args.proxy) if args.proxy else None,
            regime_path=Path(args.regime) if args.regime else None,
            security_reference_path=Path(args.security_reference) if args.security_reference else None,
            risk_config_path=Path(args.risk_config) if args.risk_config else None,
            allocation_policy_path=Path(args.allocation_policy) if args.allocation_policy else None,
            vol_method=args.vol_method,
            inter_asset_corr=args.inter_asset_corr,
        )
        return 0
    if args.command == "combined-html-report":
        generate_combined_html_report(
            positions_csv_path=Path(args.positions_csv),
            output_path=Path(args.output),
            performance_history_path=Path(args.performance_history) if args.performance_history else None,
            performance_output_dir=Path(args.performance_output_dir) if args.performance_output_dir else None,
            performance_report_csv_path=Path(args.performance_report_csv) if args.performance_report_csv else None,
            returns_path=Path(args.returns) if args.returns else None,
            proxy_path=Path(args.proxy) if args.proxy else None,
            regime_path=Path(args.regime) if args.regime else None,
            security_reference_path=Path(args.security_reference) if args.security_reference else None,
            risk_config_path=Path(args.risk_config) if args.risk_config else None,
            allocation_policy_path=Path(args.allocation_policy) if args.allocation_policy else None,
            vol_method=args.vol_method,
            inter_asset_corr=args.inter_asset_corr,
        )
        return 0
    if args.command == "security-reference-sync":
        generate_security_reference_sync(
            output_path=Path(args.output) if args.output else None,
        )
        return 0
    if args.command == "etf-sector-sync":
        generate_etf_sector_sync(
            symbols=list(args.symbol),
            output_path=Path(args.output) if args.output else None,
            api_key=args.api_key,
        )
        return 0
    if args.command == "extract-report-mapping":
        generate_report_mapping_table(
            workbook_path=Path(args.workbook),
            output_path=Path(args.output),
        )
        return 0
    if args.command == "regime-detect":
        generate_regime_snapshots(
            returns_path=Path(args.returns),
            proxy_path=Path(args.proxy),
            output_path=Path(args.output),
            config_path=Path(args.config) if args.config else None,
            latest_only=bool(args.latest_only),
            indicator_output_path=Path(args.indicators_output) if args.indicators_output else None,
        )
        return 0
    if args.command == "regime-report":
        snapshots = load_regime_snapshots(Path(args.regime))
        if not snapshots:
            print("No regime snapshots found.")
            return 0
        latest = snapshots[-1]
        policy = load_regime_policy(Path(args.policy) if args.policy else None)
        decision = resolve_policy(latest, policy=policy)
        print(f"as_of={latest.as_of}")
        print(f"regime={latest.regime}")
        print(f"stress={latest.scores.get('STRESS', 0.0):.3f}")
        print(f"vol_multiplier={decision.vol_multiplier:.2f}")
        print(f"asset_class_targets={decision.asset_class_targets}")
        if decision.notes:
            print(f"notes={decision.notes}")
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
