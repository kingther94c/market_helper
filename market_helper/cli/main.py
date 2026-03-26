from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from market_helper.workflows.generate_report import (
    generate_ibkr_position_report,
    generate_live_ibkr_position_report,
    generate_position_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="market-helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    position_report = subparsers.add_parser(
        "position-report",
        help="Generate a CSV position report from local normalized snapshot files.",
    )
    position_report.add_argument("--positions", required=True, help="Path to positions JSON.")
    position_report.add_argument("--prices", required=True, help="Path to prices JSON.")
    position_report.add_argument("--output", required=True, help="Path to output CSV.")

    ibkr_position_report = subparsers.add_parser(
        "ibkr-position-report",
        help="Generate a CSV position report directly from raw IBKR JSON payloads.",
    )
    ibkr_position_report.add_argument(
        "--ibkr-positions",
        required=True,
        help="Path to raw IBKR positions JSON.",
    )
    ibkr_position_report.add_argument(
        "--ibkr-prices",
        required=True,
        help="Path to raw IBKR prices JSON.",
    )
    ibkr_position_report.add_argument("--output", required=True, help="Path to output CSV.")
    ibkr_position_report.add_argument(
        "--as-of",
        required=False,
        help="Optional timestamp override for normalized snapshots.",
    )

    ibkr_live_position_report = subparsers.add_parser(
        "ibkr-live-position-report",
        help="Generate a CSV position report from a live local IBKR Client Portal Gateway session.",
    )
    ibkr_live_position_report.add_argument("--output", required=True, help="Path to output CSV.")
    ibkr_live_position_report.add_argument(
        "--base-url",
        default="https://localhost:5000/v1/api",
        help="Local Client Portal Gateway base URL.",
    )
    ibkr_live_position_report.add_argument(
        "--account",
        required=False,
        help="Optional account id. Defaults to the first account returned by /portfolio/accounts.",
    )
    ibkr_live_position_report.add_argument(
        "--verify-ssl",
        action="store_true",
        help="Enable local SSL verification for the Client Portal Gateway.",
    )
    ibkr_live_position_report.add_argument(
        "--as-of",
        required=False,
        help="Optional timestamp override for normalized snapshots.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "position-report":
        generate_position_report(
            positions_path=Path(args.positions),
            prices_path=Path(args.prices),
            output_path=Path(args.output),
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
            base_url=args.base_url,
            account_id=args.account,
            verify_ssl=args.verify_ssl,
            as_of=args.as_of,
        )
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
