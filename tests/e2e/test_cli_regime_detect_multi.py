from __future__ import annotations

import json
from pathlib import Path

from market_helper.cli.main import main


def _write_legacy_fixtures(tmp_path: Path) -> tuple[Path, Path]:
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
    proxy_path.write_text(json.dumps(proxy), encoding="utf-8")
    returns_path.write_text(json.dumps(returns), encoding="utf-8")
    return proxy_path, returns_path


def test_cli_regime_detect_multi_legacy_only_writes_valid_schema(tmp_path: Path) -> None:
    proxy_path, returns_path = _write_legacy_fixtures(tmp_path)
    output_path = tmp_path / "regime_multi.json"

    exit_code = main(
        [
            "regime-detect-multi",
            "--methods",
            "legacy_rulebook",
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
    assert isinstance(payload, list) and len(payload) == 1
    snap = payload[0]
    assert snap["as_of"]
    assert snap["version"] == "regime-multi-v1"
    assert "legacy_rulebook" in snap["per_method"]
    ensemble = snap["ensemble"]
    assert ensemble["quadrant"] in {
        "Goldilocks",
        "Reflation",
        "Stagflation",
        "Deflationary Slowdown",
    }
    manifest = snap["source_info"]["manifest"]
    assert manifest["methods"]["legacy_rulebook"]["status"] == "ok"


def test_cli_regime_report_multi_prints_policy(tmp_path: Path, capsys) -> None:
    proxy_path, returns_path = _write_legacy_fixtures(tmp_path)
    output_path = tmp_path / "regime_multi.json"
    assert (
        main(
            [
                "regime-detect-multi",
                "--methods",
                "legacy_rulebook",
                "--returns",
                str(returns_path),
                "--proxy",
                str(proxy_path),
                "--output",
                str(output_path),
            ]
        )
        == 0
    )
    capsys.readouterr()  # clear detect output

    exit_code = main(["regime-report-multi", "--regime", str(output_path)])
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "ensemble_quadrant=" in captured
    assert "method=legacy_rulebook" in captured
    assert "vol_multiplier=" in captured
    assert "asset_class_targets=" in captured
