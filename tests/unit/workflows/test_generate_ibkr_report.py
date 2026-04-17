import csv
import json

from market_helper.workflows.generate_report import generate_ibkr_position_report


def test_generate_ibkr_position_report_normalizes_raw_payloads_and_writes_csv(tmp_path) -> None:
    positions_path = tmp_path / "ibkr_positions.json"
    prices_path = tmp_path / "ibkr_prices.json"
    output_path = tmp_path / "outputs" / "ibkr_position_report.csv"

    positions_path.write_text(
        json.dumps(
            [
                {
                    "accountId": "U12345",
                    "conid": "756733",
                    "secType": "STK",
                    "symbol": "SPY",
                    "currency": "USD",
                    "exchange": "ARCA",
                    "position": "20",
                    "avgCost": "210.5",
                    "marketValue": "4300",
                }
            ]
        ),
        encoding="utf-8",
    )
    prices_path.write_text(
        json.dumps([{"conid": "756733", "31": "214.8"}]),
        encoding="utf-8",
    )

    written_path = generate_ibkr_position_report(
        ibkr_positions_path=positions_path,
        ibkr_prices_path=prices_path,
        output_path=output_path,
        as_of="2026-03-26T00:00:00+00:00",
    )

    assert written_path == output_path
    with output_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    assert rows == [
        {
            "as_of": "2026-03-26T00:00:00+00:00",
            "account": "U12345",
            "internal_id": "STK:SPY:SMART",
            "con_id": "756733",
            "symbol": "SPY",
            "local_symbol": "US",
            "exchange": "ARCA",
            "currency": "USD",
            "source": "ibkr",
            "quantity": "20.0",
            "avg_cost": "210.5",
            "latest_price": "214.8",
            "market_value": "4300.0",
            "cost_basis": "4210.0",
            "unrealized_pnl": "90.0",
            "weight": "1.0",
        }
    ]


def test_generate_ibkr_position_report_accepts_wrapped_json_arrays(tmp_path) -> None:
    positions_path = tmp_path / "ibkr_positions.json"
    prices_path = tmp_path / "ibkr_prices.json"
    output_path = tmp_path / "ibkr_position_report.csv"

    positions_path.write_text(
        json.dumps(
            {
                "positions": [
                    {
                        "account": "U12345",
                        "con_id": "756733",
                        "sec_type": "STK",
                        "symbol": "SPY",
                        "currency": "USD",
                        "exchange": "ARCA",
                        "position": "20",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    prices_path.write_text(
        json.dumps({"data": [{"conId": "756733", "marketPrice": "214.8"}]}),
        encoding="utf-8",
    )

    generate_ibkr_position_report(
        ibkr_positions_path=positions_path,
        ibkr_prices_path=prices_path,
        output_path=output_path,
        as_of="2026-03-26T00:00:00+00:00",
    )

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    assert rows[0]["internal_id"] == "STK:SPY:SMART"
    assert rows[0]["symbol"] == "SPY"
    assert rows[0]["latest_price"] == "214.8"


def test_generate_ibkr_position_report_writes_proposed_security_reference_for_unmapped_rows(
    tmp_path,
    capsys,
) -> None:
    positions_path = tmp_path / "ibkr_positions.json"
    prices_path = tmp_path / "ibkr_prices.json"
    output_path = tmp_path / "outputs" / "ibkr_position_report.csv"

    positions_path.write_text(
        json.dumps(
            [
                {
                    "accountId": "U12345",
                    "conid": "888888",
                    "secType": "STK",
                    "symbol": "AAPL",
                    "currency": "USD",
                    "exchange": "SMART",
                    "localSymbol": "AAPL",
                    "position": "20",
                }
            ]
        ),
        encoding="utf-8",
    )
    prices_path.write_text(
        json.dumps([{"conid": "888888", "31": "214.8"}]),
        encoding="utf-8",
    )

    generate_ibkr_position_report(
        ibkr_positions_path=positions_path,
        ibkr_prices_path=prices_path,
        output_path=output_path,
        as_of="2026-03-26T00:00:00+00:00",
    )

    proposal_path = output_path.with_name("security_universe_PROPOSED.csv")
    with proposal_path.open("r", encoding="utf-8", newline="") as handle:
        proposal_rows = list(csv.DictReader(handle))

    assert proposal_rows == [
        {
            "asset_class": "EQ",
            "ibkr_symbol": "AAPL",
            "display_name": "AAPL",
            "ibkr_exchange": "SMART",
            "yahoo_symbol": "",
            "eq_country": "",
            "eq_sector_proxy": "",
            "dir_exposure": "L",
            "fi_mod_duration": "",
            "fi_tenor": "",
            "lookup_primary_exchange": "SMART",
            "lookup_currency": "USD",
            "lookup_multiplier": "1",
            "lookup_sec_type": "STK",
            "lookup_conid": "888888",
            "proposal_reason": "unmapped_security",
        }
    ]
    assert "security_universe_PROPOSED.csv" in capsys.readouterr().out
