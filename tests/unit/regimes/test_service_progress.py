from __future__ import annotations

import json

from market_helper.common.progress import RecordingProgressReporter
from market_helper.regimes.service import detect_regimes


def test_detect_regimes_reports_progress(tmp_path) -> None:
    returns_path = tmp_path / "returns.json"
    proxy_path = tmp_path / "proxy.json"
    output_path = tmp_path / "regime.json"
    indicator_path = tmp_path / "indicators.json"
    reporter = RecordingProgressReporter()

    returns_path.write_text(
        json.dumps(
            {
                "EQ": {"2026-01-01": 0.01, "2026-01-02": 0.0},
                "FI": {"2026-01-01": 0.002, "2026-01-02": 0.001},
            }
        ),
        encoding="utf-8",
    )
    proxy_path.write_text(
        json.dumps(
            {
                "VIX": {"2026-01-01": 20.0, "2026-01-02": 19.0},
                "MOVE": {"2026-01-01": 100.0, "2026-01-02": 99.0},
                "HY_OAS": {"2026-01-01": 3.5, "2026-01-02": 3.4},
                "UST2Y": {"2026-01-01": 4.0, "2026-01-02": 4.0},
                "UST10Y": {"2026-01-01": 4.5, "2026-01-02": 4.4},
            }
        ),
        encoding="utf-8",
    )

    detect_regimes(
        returns_path=returns_path,
        proxy_path=proxy_path,
        output_path=output_path,
        indicator_output_path=indicator_path,
        progress=reporter,
    )

    assert reporter.events[:4] == [
        {"kind": "stage", "label": "Regime detection", "current": 0, "total": 5},
        {"kind": "stage", "label": "Regime detection: config loaded", "current": 1, "total": 5},
        {"kind": "stage", "label": "Regime detection: inputs loaded", "current": 2, "total": 5},
        {"kind": "stage", "label": "Regime detection: factors computed", "current": 3, "total": 5},
    ]
    assert reporter.events[-1] == {
        "kind": "done",
        "label": "Regime detection",
        "detail": "artifacts written",
    }
