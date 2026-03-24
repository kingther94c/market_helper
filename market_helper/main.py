from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Optional

from market_helper.data_sources import fetch_recent_one_week_moves
from market_helper.regime_rulebook import combine_views, score_macro, score_market


def _load_macro_json(path: Path) -> Dict[str, float]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return {k: float(v) for k, v in data.items()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rulebook-first market regime helper")
    parser.add_argument("--macro-json", type=Path, help="Path to macro input JSON", default=None)
    parser.add_argument("--use-live-market", action="store_true", help="Fetch live 1W market moves")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    macro_scores = None
    market_scores = None

    if args.macro_json:
        macro = _load_macro_json(args.macro_json)
        macro_scores = score_macro(macro)

    if args.use_live_market:
        market_moves = fetch_recent_one_week_moves()
        market_scores = score_market(market_moves)

    if not macro_scores and not market_scores:
        raise SystemExit("Provide at least --macro-json or --use-live-market")

    result = combine_views(macro_scores, market_scores)

    payload: Dict[str, Optional[object]] = {
        "result": result,
        "macro_scores": {k: v.score for k, v in macro_scores.items()} if macro_scores else None,
        "market_scores": {k: v.score for k, v in market_scores.items()} if market_scores else None,
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
