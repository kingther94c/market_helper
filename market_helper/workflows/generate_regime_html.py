from __future__ import annotations

"""Workflow facade for standalone regime HTML reports."""

from pathlib import Path

from market_helper.reporting.regime_html import write_regime_html_report


def generate_regime_html_report(
    *,
    regime_path: str | Path,
    output_path: str | Path,
    policy_path: str | Path | None = None,
) -> Path:
    return write_regime_html_report(
        regime_path=regime_path,
        output_path=output_path,
        policy_path=policy_path,
    )


__all__ = ["generate_regime_html_report"]
