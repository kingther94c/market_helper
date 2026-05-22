"""Probe the same code path the dashboard uses to build the combined HTML.

Confirms the two missing-artifact warnings are gone after the flex feather
and dated performance CSV exist on disk.
"""

from __future__ import annotations

from market_helper.application.portfolio_monitor.contracts import GenerateCombinedReportInputs
from market_helper.application.portfolio_monitor.services import PortfolioMonitorActionService


def main() -> int:
    asvc = PortfolioMonitorActionService()
    artifact = asvc.generate_combined_report(GenerateCombinedReportInputs())
    print(f"output_path={artifact.output_path}")
    print(f"exists={artifact.exists}")
    print(f"as_of={artifact.as_of}")
    print("warnings:")
    for w in artifact.warnings:
        print(f"  - {w}")
    blocking = [
        w
        for w in artifact.warnings
        if "Performance history file not found" in w
        or "Dated performance report CSV is missing" in w
    ]
    if blocking:
        print("FAIL: missing-artifact warnings still present")
        return 1
    print("OK: missing-artifact warnings resolved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
