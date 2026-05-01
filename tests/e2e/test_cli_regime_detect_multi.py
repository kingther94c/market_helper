from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from market_helper.cli.main import main


def _write_macro_fixtures(tmp_path: Path) -> tuple[Path, Path]:
    panel_path = tmp_path / "macro_panel.feather"
    config_path = tmp_path / "fred_series.yml"
    pd.DataFrame(
        {
            "date": pd.bdate_range("2026-01-01", periods=30),
            "G": [1.0] * 30,
            "I": [-1.0] * 30,
        }
    ).to_feather(panel_path)
    config_path.write_text(
        yaml.safe_dump(
            {
                "series": [
                    {
                        "series_id": "G",
                        "axis": "growth",
                        "transform": "level",
                        "bucket": "fast",
                    },
                    {
                        "series_id": "I",
                        "axis": "inflation",
                        "transform": "level",
                        "bucket": "fast",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return panel_path, config_path


def _write_market_fixtures(tmp_path: Path) -> tuple[Path, Path]:
    panel_path = tmp_path / "market_panel.feather"
    config_path = tmp_path / "market_regime.yml"
    pd.DataFrame(
        {
            "date": pd.bdate_range("2026-01-01", periods=30),
            "SPY": [100.0 + idx for idx in range(30)],
            "USO": [100.0 - idx for idx in range(30)],
            "VIX": [20.0] * 30,
        }
    ).to_feather(panel_path)
    config_path.write_text(
        yaml.safe_dump(
            {
                "growth": {
                    "signals": [
                        {
                            "name": "spy",
                            "axis": "growth",
                            "symbol": "SPY",
                            "transform": "raw_sign",
                            "lookback_days": 1,
                        }
                    ]
                },
                "inflation": {
                    "signals": [
                        {
                            "name": "oil",
                            "axis": "inflation",
                            "symbol": "USO",
                            "transform": "raw_sign",
                            "lookback_days": 1,
                        }
                    ]
                },
                "risk_overlay": {
                    "signals": [
                        {
                            "name": "vix",
                            "axis": "risk",
                            "symbol": "VIX",
                            "transform": "raw_sign",
                            "lookback_days": 1,
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    return panel_path, config_path


def test_cli_regime_detect_multi_all_writes_valid_schema(tmp_path: Path) -> None:
    macro_panel, fred_config = _write_macro_fixtures(tmp_path)
    market_panel, market_config = _write_market_fixtures(tmp_path)
    output_path = tmp_path / "regime_multi.json"

    exit_code = main(
        [
            "regime-detect-multi",
            "--methods",
            "all",
            "--macro-panel",
            str(macro_panel),
            "--fred-series-config",
            str(fred_config),
            "--market-panel",
            str(market_panel),
            "--market-regime-config",
            str(market_config),
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
    assert set(snap["per_method"]) == {"macro_regime", "market_regime"}
    assert snap["ensemble"]["quadrant"] in {
        "Goldilocks",
        "Reflation",
        "Stagflation",
        "Deflationary Slowdown",
    }
    manifest = snap["source_info"]["manifest"]
    assert manifest["methods"]["macro_regime"]["status"] == "ok"
    assert manifest["methods"]["market_regime"]["status"] == "ok"


def test_cli_regime_detect_multi_rejects_legacy_method(tmp_path: Path, capsys) -> None:
    output_path = tmp_path / "regime_multi.json"

    exit_code = main(
        [
            "regime-detect-multi",
            "--methods",
            "legacy_rulebook",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "Unknown regime methods" in captured.err
    assert "macro_regime" in captured.err
    assert "market_regime" in captured.err


def test_cli_regime_detect_multi_fails_when_no_enabled_method_can_run(
    tmp_path: Path, capsys
) -> None:
    output_path = tmp_path / "regime_multi.json"

    exit_code = main(["regime-detect-multi", "--output", str(output_path)])

    assert exit_code == 2
    assert not output_path.exists()
    captured = capsys.readouterr()
    assert "No enabled regime methods can run" in captured.err
    assert "macro_regime missing" in captured.err
    assert "market_regime missing market panel" in captured.err


def test_cli_regime_report_multi_prints_policy(tmp_path: Path, capsys) -> None:
    macro_panel, fred_config = _write_macro_fixtures(tmp_path)
    market_panel, market_config = _write_market_fixtures(tmp_path)
    output_path = tmp_path / "regime_multi.json"
    assert (
        main(
            [
                "regime-detect-multi",
                "--methods",
                "all",
                "--macro-panel",
                str(macro_panel),
                "--fred-series-config",
                str(fred_config),
                "--market-panel",
                str(market_panel),
                "--market-regime-config",
                str(market_config),
                "--output",
                str(output_path),
            ]
        )
        == 0
    )
    capsys.readouterr()

    exit_code = main(["regime-report-multi", "--regime", str(output_path)])
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "ensemble_quadrant=" in captured
    assert "method=macro_regime" in captured
    assert "method=market_regime" in captured
    assert "vol_multiplier=" in captured
    assert "asset_class_targets=" in captured


def test_cli_regime_html_report_writes_html_from_multi_payload(tmp_path: Path) -> None:
    macro_panel, fred_config = _write_macro_fixtures(tmp_path)
    market_panel, market_config = _write_market_fixtures(tmp_path)
    regime_path = tmp_path / "regime_multi.json"
    html_path = tmp_path / "regime_report.html"
    assert (
        main(
            [
                "regime-detect-multi",
                "--methods",
                "all",
                "--macro-panel",
                str(macro_panel),
                "--fred-series-config",
                str(fred_config),
                "--market-panel",
                str(market_panel),
                "--market-regime-config",
                str(market_config),
                "--output",
                str(regime_path),
                "--latest-only",
            ]
        )
        == 0
    )

    exit_code = main(
        [
            "regime-html-report",
            "--regime",
            str(regime_path),
            "--output",
            str(html_path),
        ]
    )

    assert exit_code == 0
    html = html_path.read_text(encoding="utf-8")
    assert "Regime Detection" in html
    assert "Policy Suggestion" in html
    assert "Method Votes" in html
