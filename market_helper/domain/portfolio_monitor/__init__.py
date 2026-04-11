"""Universe-first portfolio monitor package."""

from .models import PortfolioPositionView, PortfolioSnapshot
from .services.security_reference_table import SecurityReference, SecurityReferenceTable

__all__ = [
    "PortfolioPositionView",
    "PortfolioSnapshot",
    "SecurityReference",
    "SecurityReferenceTable",
    "build_live_ibkr_position_security_table",
    "build_portfolio_snapshot",
    "build_security_reference",
    "generate_combined_html_report",
    "generate_etf_sector_sync",
    "generate_ibkr_position_report",
    "generate_live_ibkr_position_report",
    "generate_position_report",
    "generate_report_mapping_table",
    "generate_risk_html_report",
    "generate_security_reference_sync",
]


def __getattr__(name: str):
    if name in {
        "build_live_ibkr_position_security_table",
        "build_portfolio_snapshot",
        "build_security_reference",
        "generate_combined_html_report",
        "generate_etf_sector_sync",
        "generate_ibkr_position_report",
        "generate_live_ibkr_position_report",
        "generate_position_report",
        "generate_report_mapping_table",
        "generate_risk_html_report",
        "generate_security_reference_sync",
    }:
        from .pipelines import (
            build_live_ibkr_position_security_table,
            build_portfolio_snapshot,
            build_security_reference,
            generate_combined_html_report,
            generate_etf_sector_sync,
            generate_ibkr_position_report,
            generate_live_ibkr_position_report,
            generate_position_report,
            generate_report_mapping_table,
            generate_risk_html_report,
            generate_security_reference_sync,
        )

        exported = {
            "build_live_ibkr_position_security_table": build_live_ibkr_position_security_table,
            "build_portfolio_snapshot": build_portfolio_snapshot,
            "build_security_reference": build_security_reference,
            "generate_combined_html_report": generate_combined_html_report,
            "generate_etf_sector_sync": generate_etf_sector_sync,
            "generate_ibkr_position_report": generate_ibkr_position_report,
            "generate_live_ibkr_position_report": generate_live_ibkr_position_report,
            "generate_position_report": generate_position_report,
            "generate_report_mapping_table": generate_report_mapping_table,
            "generate_risk_html_report": generate_risk_html_report,
            "generate_security_reference_sync": generate_security_reference_sync,
        }
        return exported[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
