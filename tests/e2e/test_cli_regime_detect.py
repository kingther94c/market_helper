from __future__ import annotations

import json
from pathlib import Path

from market_helper.cli.main import main


def test_cli_regime_detect_writes_valid_schema(tmp_path: Path) -> None:
    dates = [f"2026-01-{idx+1:02d}" for idx in range(30)]
    proxy = {
        "VIX": {d: 18 + (idx % 4) for idx, d in enumerate(dates)},
        "MOVE": {d: 100 + (idx % 5) for idx, d in enumerate(dates)},
        "HY_OAS": {d: 3.5 + (idx % 3) * 0.02 for idx, d in enumerate(dates)},
        "UST2Y": {d: 0.03 + idx * 0.0001 for idx, d in enumerate(dates)},
        "UST10Y": {d: 0.04 + idx * 0.0001 for idx, d in enumerate(dates)},
    }
    returns = {
        "EQ": {d: 0.001 * ((idx % 5) - 2) for idx, d in enumerate(dates)},
        "FI": {d: 0.0006 * ((idx % 3) - 1) for idx, d in enumerate(dates)},
    }
    proxy_path = tmp_path / "proxy.json"
    returns_path = tmp_path / "returns.json"
    output_path = tmp_path / "regime.json"

    proxy_path.write_text(json.dumps(proxy), encoding="utf-8")
    returns_path.write_text(json.dumps(returns), encoding="utf-8")

    exit_code = main(
        [
            "regime-detect",
            "--returns",
            str(returns_path),
            "--proxy",
            str(proxy_path),
            "--output",
            str(output_path),
            "--latest-only",
        ]
    )

    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert len(payload) == 1
    row = payload[0]
    assert row["as_of"]
    assert isinstance(row["regime"], str)
    assert set(["VOL", "CREDIT", "RATES", "GROWTH", "TREND", "STRESS"]).issubset(row["scores"])
