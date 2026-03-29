from market_helper.presentation.exporters.csv import POSITION_REPORT_HEADERS
from market_helper.presentation.tables.portfolio_report import PositionReportRow


def test_presentation_facades_export_expected_symbols() -> None:
    assert "internal_id" in POSITION_REPORT_HEADERS
    assert PositionReportRow.__name__ == "PositionReportRow"
