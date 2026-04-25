"""Application services for the portfolio monitor UI."""

from typing import TYPE_CHECKING

from .contracts import (
    ArtifactMetadata,
    EtfSectorSyncInputs,
    FlexPerformanceRefreshInputs,
    GenerateCombinedReportInputs,
    GeneratedReportArtifact,
    LivePortfolioRefreshInputs,
    PortfolioReportData,
    PortfolioReportInputs,
    UiProgressEvent,
    UiProgressSink,
)
from .progress import InMemoryUiProgressSink, UiProgressReporterAdapter

if TYPE_CHECKING:
    from .services import PortfolioMonitorActionService, PortfolioMonitorQueryService


def __getattr__(name: str) -> object:
    if name in {"PortfolioMonitorActionService", "PortfolioMonitorQueryService"}:
        from .services import PortfolioMonitorActionService, PortfolioMonitorQueryService

        return {
            "PortfolioMonitorActionService": PortfolioMonitorActionService,
            "PortfolioMonitorQueryService": PortfolioMonitorQueryService,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "ArtifactMetadata",
    "EtfSectorSyncInputs",
    "FlexPerformanceRefreshInputs",
    "GenerateCombinedReportInputs",
    "GeneratedReportArtifact",
    "InMemoryUiProgressSink",
    "LivePortfolioRefreshInputs",
    "PortfolioReportData",
    "PortfolioMonitorActionService",
    "PortfolioMonitorQueryService",
    "PortfolioReportInputs",
    "UiProgressEvent",
    "UiProgressReporterAdapter",
    "UiProgressSink",
]
