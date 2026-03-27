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
        host,
        port,
        client_id,
        account_id,
        timeout,
        as_of,
    ):
        captured["output_path"] = output_path
        captured["host"] = host
        captured["port"] = port
        captured["client_id"] = client_id
        captured["account_id"] = account_id
        captured["timeout"] = timeout
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
            "--host",
            "127.0.0.1",
            "--port",
            "7497",
            "--client-id",
            "7",
            "--account",
            "U12345",
            "--timeout",
            "9.5",
            "--as-of",
            "2026-03-26T00:00:00+00:00",
        ]
    )

    assert exit_code == 0
    assert str(captured["output_path"]).endswith("live_position_report.csv")
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 7497
    assert captured["client_id"] == 7
    assert captured["account_id"] == "U12345"
    assert captured["timeout"] == 9.5
    assert captured["as_of"] == "2026-03-26T00:00:00+00:00"


def test_cli_risk_html_report_dispatches_to_workflow(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_generate_risk_html_report(
        *,
        positions_csv_path,
        returns_path,
        output_path,
        proxy_path,
        duration_path,
        futures_dv01_path,
        strict_futures_dv01,
    ):
        captured["positions_csv_path"] = positions_csv_path
        captured["returns_path"] = returns_path
        captured["output_path"] = output_path
        captured["proxy_path"] = proxy_path
        captured["duration_path"] = duration_path
        captured["futures_dv01_path"] = futures_dv01_path
        captured["strict_futures_dv01"] = strict_futures_dv01
        return output_path

    monkeypatch.setattr(
        "market_helper.cli.main.generate_risk_html_report",
        fake_generate_risk_html_report,
    )

    exit_code = main(
        [
            "risk-html-report",
            "--positions-csv",
            str(tmp_path / "live_ibkr_position_report.csv"),
            "--returns",
            str(tmp_path / "returns.json"),
            "--proxy",
            str(tmp_path / "proxy.json"),
            "--duration-map",
            str(tmp_path / "duration_map.json"),
            "--futures-dv01-map",
            str(tmp_path / "futures_dv01_map.json"),
            "--strict-futures-dv01",
            "--output",
            str(tmp_path / "portfolio_risk_report.html"),
        ]
    )

    assert exit_code == 0
    assert str(captured["positions_csv_path"]).endswith("live_ibkr_position_report.csv")
    assert str(captured["returns_path"]).endswith("returns.json")
    assert str(captured["proxy_path"]).endswith("proxy.json")
    assert str(captured["duration_path"]).endswith("duration_map.json")
    assert str(captured["futures_dv01_path"]).endswith("futures_dv01_map.json")
    assert captured["strict_futures_dv01"] is True
    assert str(captured["output_path"]).endswith("portfolio_risk_report.html")
