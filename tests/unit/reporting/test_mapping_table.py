from __future__ import annotations

from pathlib import Path

from market_helper.reporting.mapping_table import (
    _fi_tenor_for_instrument,
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
        and row.asset_class == "EQ"
        and row.ibkr_sec_type == "STK"
        for row in table.rows
    )
    assert any(
        row.display_ticker == "ZNW00:CBOT"
        and row.canonical_symbol == "ZN"
        and row.asset_class == "FI"
        for row in table.rows
    )
    assert any(
        row.display_ticker == "CASH (SGD value)"
        and row.asset_class == "CASH"
        and row.lookup_status == "seeded"
        for row in table.rows
    )

    output_path = tmp_path / "target_report_security_reference.csv"
    export_security_reference_seed_csv(table, output_path)
    loaded = load_security_reference_seed_table(output_path)

    assert loaded.resolve_by_ibkr_alias(symbol="SPYL", sec_type="STK", exchange="LSEETF")
    assert loaded.resolve_by_ibkr_alias(symbol="ZN", sec_type="FUT", exchange="CBOT").display_name == "10Y TF"


def test_fi_tenor_for_instrument_uses_explicit_tenor_semantics() -> None:
    assert (
        _fi_tenor_for_instrument(
            asset_class="FI",
            symbol_key="ZT",
            display_ticker="ZTW00:CBOT",
            display_name="2Y TF",
        )
        == "1-3Y"
    )
    assert (
        _fi_tenor_for_instrument(
            asset_class="FI",
            symbol_key="ZF",
            display_ticker="ZFW00:CBOT",
            display_name="5Y TF",
        )
        == "3-5Y"
    )
    assert (
        _fi_tenor_for_instrument(
            asset_class="FI",
            symbol_key="ZN",
            display_ticker="ZNW00:CBOT",
            display_name="10Y TF",
        )
        == "7-10Y"
    )
    assert (
        _fi_tenor_for_instrument(
            asset_class="FI",
            symbol_key="TLT",
            display_ticker="TLT",
            display_name="FI",
        )
        == "20Y+"
    )
    assert (
        _fi_tenor_for_instrument(
            asset_class="FI",
            symbol_key="LQD",
            display_ticker="LQD",
            display_name="CR",
        )
        == "7-10Y"
    )
    assert (
        _fi_tenor_for_instrument(
            asset_class="FI",
            symbol_key="XM",
            display_ticker="XM",
            display_name="10Y AU",
        )
        == "7-10Y"
    )
    assert (
        _fi_tenor_for_instrument(
            asset_class="FI",
            symbol_key="UNKNOWN",
            display_ticker="ABC",
            display_name="Credit Basket",
        )
        == ""
    )
