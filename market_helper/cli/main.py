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
        help="Generate a CSV position report from a live TWS / IB Gateway session via ib_async.",
    )
    ibkr_live_position_report.add_argument("--output", required=True, help="Path to output CSV.")
    ibkr_live_position_report.add_argument(
        "--host",
        default="127.0.0.1",
        help="Local TWS / IB Gateway host.",
    )
    ibkr_live_position_report.add_argument(
        "--port",
        type=int,
        default=7497,
        help="Local TWS / IB Gateway API port.",
    )
    ibkr_live_position_report.add_argument(
        "--client-id",
        type=int,
        default=1,
        help="ib_async client id for the TWS / IB Gateway connection.",
    )
    ibkr_live_position_report.add_argument(
        "--account",
        required=False,
        help="Optional account id. Defaults to the first account returned by managedAccounts().",
    )
    ibkr_live_position_report.add_argument(
        "--timeout",
        type=float,
        default=4.0,
        help="Connection timeout in seconds for the TWS / IB Gateway session.",
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
            host=args.host,
            port=args.port,
            client_id=args.client_id,
            account_id=args.account,
            timeout=args.timeout,
            as_of=args.as_of,
        )
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
