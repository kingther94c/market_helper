from market_helper.cli.main import main


def test_cli_position_report_dispatches_to_workflow(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_generate_position_report(*, positions_path, prices_path, output_path):
        captured["positions_path"] = positions_path
        captured["prices_path"] = prices_path
        captured["output_path"] = output_path
        return output_path

    monkeypatch.setattr(
        "market_helper.cli.main.generate_position_report",
        fake_generate_position_report,
    )

    exit_code = main(
        [
            "position-report",
            "--positions",
            str(tmp_path / "positions.json"),
            "--prices",
            str(tmp_path / "prices.json"),
            "--output",
            str(tmp_path / "position_report.csv"),
        ]
    )

    assert exit_code == 0
    assert str(captured["positions_path"]).endswith("positions.json")
    assert str(captured["prices_path"]).endswith("prices.json")
    assert str(captured["output_path"]).endswith("position_report.csv")


def test_cli_ibkr_position_report_dispatches_to_ibkr_workflow(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_generate_ibkr_position_report(
        *,
        ibkr_positions_path,
        ibkr_prices_path,
        output_path,
        as_of,
    ):
        captured["ibkr_positions_path"] = ibkr_positions_path
        captured["ibkr_prices_path"] = ibkr_prices_path
        captured["output_path"] = output_path
        captured["as_of"] = as_of
        return output_path

    monkeypatch.setattr(
        "market_helper.cli.main.generate_ibkr_position_report",
        fake_generate_ibkr_position_report,
    )

    exit_code = main(
        [
            "ibkr-position-report",
            "--ibkr-positions",
            str(tmp_path / "ibkr_positions.json"),
            "--ibkr-prices",
            str(tmp_path / "ibkr_prices.json"),
            "--output",
            str(tmp_path / "ibkr_position_report.csv"),
            "--as-of",
            "2026-03-26T00:00:00+00:00",
        ]
    )

    assert exit_code == 0
    assert str(captured["ibkr_positions_path"]).endswith("ibkr_positions.json")
    assert str(captured["ibkr_prices_path"]).endswith("ibkr_prices.json")
    assert str(captured["output_path"]).endswith("ibkr_position_report.csv")
    assert captured["as_of"] == "2026-03-26T00:00:00+00:00"


def test_cli_ibkr_live_position_report_dispatches_to_live_workflow(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_generate_live_ibkr_position_report(
        *,
        output_path,
        base_url,
        account_id,
        verify_ssl,
        as_of,
    ):
        captured["output_path"] = output_path
        captured["base_url"] = base_url
        captured["account_id"] = account_id
        captured["verify_ssl"] = verify_ssl
        captured["as_of"] = as_of
        return output_path

    monkeypatch.setattr(
        "market_helper.cli.main.generate_live_ibkr_position_report",
        fake_generate_live_ibkr_position_report,
    )

    exit_code = main(
        [
            "ibkr-live-position-report",
            "--output",
            str(tmp_path / "live_position_report.csv"),
            "--base-url",
            "https://localhost:5000/v1/api",
            "--account",
            "U12345",
            "--as-of",
            "2026-03-26T00:00:00+00:00",
        ]
    )

    assert exit_code == 0
    assert str(captured["output_path"]).endswith("live_position_report.csv")
    assert captured["base_url"] == "https://localhost:5000/v1/api"
    assert captured["account_id"] == "U12345"
    assert captured["verify_ssl"] is False
    assert captured["as_of"] == "2026-03-26T00:00:00+00:00"
