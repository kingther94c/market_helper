from __future__ import annotations

from pathlib import Path

from market_helper.reporting.mapping_table import (
    export_security_reference_seed_csv,
    extract_security_reference_seed,
    load_security_reference_seed_table,
)


def test_extract_security_reference_seed_reads_target_workbook(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    workbook_path = repo_root / "outputs" / "reports" / "target_report.xlsx"

    table = extract_security_reference_seed(workbook_path)

    assert any(
        row.display_ticker == "LON:SPYL"
        and row.report_category == "DMEQ"
        and row.universe_type == "ETF"
        for row in table.rows
    )
    assert any(
        row.display_ticker == "ZNW00:CBOT"
        and row.canonical_symbol == "ZN"
        and row.universe_type == "FI_FUT"
        for row in table.rows
    )
    assert any(
        row.display_ticker == "CASH (SGD value)"
        and row.universe_type == "CASH"
        and row.fx_source_symbol == "CURRENCY:SGDUSD"
        for row in table.rows
    )

    output_path = tmp_path / "target_report_security_reference.csv"
    export_security_reference_seed_csv(table, output_path)
    loaded = load_security_reference_seed_table(output_path)

    assert loaded.resolve_by_ibkr_alias(symbol="SPYL", sec_type="STK", exchange="LSEETF")
    assert loaded.resolve_by_ibkr_alias(symbol="ZN", sec_type="FUT", exchange="CBOT").display_name == "10Y TF"
