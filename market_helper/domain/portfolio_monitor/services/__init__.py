from .security_reference_table import SecurityReference, SecurityReferenceTable

__all__ = [
    "CategorySummaryRow",
    "PortfolioRiskSummary",
    "RegimeReportSummary",
    "RiskInputRow",
    "RiskMetricsRow",
    "SecurityReference",
    "SecurityReferenceTable",
    "load_risk_inputs",
]


def __getattr__(name: str):
    if name in {
        "CategorySummaryRow",
        "PortfolioRiskSummary",
        "RegimeReportSummary",
        "RiskInputRow",
        "RiskMetricsRow",
        "load_risk_inputs",
    }:
        from .risk_analysis import (
            CategorySummaryRow,
            PortfolioRiskSummary,
            RegimeReportSummary,
            RiskInputRow,
            RiskMetricsRow,
            load_risk_inputs,
        )

        exported = {
            "CategorySummaryRow": CategorySummaryRow,
            "PortfolioRiskSummary": PortfolioRiskSummary,
            "RegimeReportSummary": RegimeReportSummary,
            "RiskInputRow": RiskInputRow,
            "RiskMetricsRow": RiskMetricsRow,
            "load_risk_inputs": load_risk_inputs,
        }
        return exported[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
