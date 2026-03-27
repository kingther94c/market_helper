from __future__ import annotations

from pathlib import Path

from market_helper.reporting.mapping_table import (
    build_instrument_mapping_indexes,
    export_report_mapping_table_json,
    extract_report_mapping_table,
    load_report_mapping_table,
)


def test_extract_report_mapping_table_reads_target_workbook(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    workbook_path = repo_root / "outputs" / "reports" / "target_report.xlsx"

    table = extract_report_mapping_table(workbook_path)

    assert any(
        row.display_ticker == "LON:SPYL" and row.category == "DMEQ" and row.venue == "INTL"
        for row in table.instruments
    )
    assert any(
        row.display_ticker == "ZNW00:CBOT" and row.symbol_key == "ZN" and row.venue == "CBOT"
        for row in table.instruments
    )
    assert any(row.currency_pair == "EURUSD" for row in table.fx_sources)
    assert any(row.proxy_name == "VIX" and row.risk_bucket == "EQ" for row in table.risk_proxies)

    output_path = tmp_path / "target_report_mapping.json"
    export_report_mapping_table_json(table, output_path)
    loaded = load_report_mapping_table(output_path)
    exact, unique = build_instrument_mapping_indexes(loaded)

    assert ("SPYL", "INTL") in exact
    assert "SPY" in unique
    assert "DBMF" not in unique
