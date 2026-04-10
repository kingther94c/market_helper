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




def test_cli_ibkr_flex_performance_report_dispatches_to_workflow(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_generate_ibkr_flex_performance_report(
        *,
        output_dir,
        flex_xml_path,
        query_id,
        token,
        xml_output_path,
        poll_interval_seconds,
        max_attempts,
    ):
        captured["flex_xml_path"] = flex_xml_path
        captured["output_dir"] = output_dir
        captured["query_id"] = query_id
        captured["token"] = token
        captured["xml_output_path"] = xml_output_path
        captured["poll_interval_seconds"] = poll_interval_seconds
        captured["max_attempts"] = max_attempts
        return output_dir / "performance_report_20260402.csv"

    monkeypatch.setattr(
        "market_helper.cli.main.generate_ibkr_flex_performance_report",
        fake_generate_ibkr_flex_performance_report,
    )

    exit_code = main(
        [
            "ibkr-flex-performance-report",
            "--flex-xml",
            str(tmp_path / "flex_report.xml"),
            "--output-dir",
            str(tmp_path / "outputs"),
        ]
    )

    assert exit_code == 0
    assert str(captured["flex_xml_path"]).endswith("flex_report.xml")
    assert str(captured["output_dir"]).endswith("outputs")
    assert captured["query_id"] is None
    assert captured["token"] is None
    assert captured["xml_output_path"] is None
    assert captured["poll_interval_seconds"] == 5.0
    assert captured["max_attempts"] == 10


def test_cli_ibkr_flex_performance_report_uses_env_backed_query_credentials(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_generate_ibkr_flex_performance_report(
        *,
        output_dir,
        flex_xml_path,
        query_id,
        token,
        xml_output_path,
        poll_interval_seconds,
        max_attempts,
    ):
        captured["output_dir"] = output_dir
        captured["flex_xml_path"] = flex_xml_path
        captured["query_id"] = query_id
        captured["token"] = token
        captured["xml_output_path"] = xml_output_path
        captured["poll_interval_seconds"] = poll_interval_seconds
        captured["max_attempts"] = max_attempts
        return output_dir / "performance_report_20260402.csv"

    monkeypatch.setattr(
        "market_helper.cli.main.generate_ibkr_flex_performance_report",
        fake_generate_ibkr_flex_performance_report,
    )
    monkeypatch.setenv("IBKR_PERFORMANCE_REPORT_ID", "1462703")
    monkeypatch.setenv("IBKR_FLEX_TOKEN", "secret-token")

    exit_code = main(
        [
            "ibkr-flex-performance-report",
            "--output-dir",
            str(tmp_path / "outputs"),
            "--xml-output",
            str(tmp_path / "downloaded.xml"),
            "--poll-interval",
            "2.5",
            "--max-attempts",
            "7",
        ]
    )

    assert exit_code == 0
    assert captured["flex_xml_path"] is None
    assert captured["query_id"] == "1462703"
    assert captured["token"] == "secret-token"
    assert str(captured["xml_output_path"]).endswith("downloaded.xml")
    assert captured["poll_interval_seconds"] == 2.5
    assert captured["max_attempts"] == 7

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
        regime_path,
        security_reference_path,
        risk_config_path,
        allocation_policy_path,
        vol_method,
    ):
        captured["positions_csv_path"] = positions_csv_path
        captured["returns_path"] = returns_path
        captured["output_path"] = output_path
        captured["proxy_path"] = proxy_path
        captured["regime_path"] = regime_path
        captured["security_reference_path"] = security_reference_path
        captured["risk_config_path"] = risk_config_path
        captured["allocation_policy_path"] = allocation_policy_path
        captured["vol_method"] = vol_method
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
            "--regime",
            str(tmp_path / "regime.json"),
            "--security-reference",
            str(tmp_path / "security_reference.csv"),
            "--output",
            str(tmp_path / "portfolio_risk_report.html"),
            "--risk-config",
            str(tmp_path / "report_config.yaml"),
            "--allocation-policy",
            str(tmp_path / "allocation_policy.yaml"),
            "--vol-method",
            "ewma",
        ]
    )

    assert exit_code == 0
    assert str(captured["positions_csv_path"]).endswith("live_ibkr_position_report.csv")
    assert str(captured["returns_path"]).endswith("returns.json")
    assert str(captured["proxy_path"]).endswith("proxy.json")
    assert str(captured["regime_path"]).endswith("regime.json")
    assert str(captured["security_reference_path"]).endswith("security_reference.csv")
    assert str(captured["risk_config_path"]).endswith("report_config.yaml")
    assert str(captured["allocation_policy_path"]).endswith("allocation_policy.yaml")
    assert captured["vol_method"] == "ewma"
    assert str(captured["output_path"]).endswith("portfolio_risk_report.html")


def test_cli_regime_detect_dispatches_to_workflow(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_generate_regime_snapshots(
        *,
        returns_path,
        proxy_path,
        output_path,
        config_path,
        latest_only,
        indicator_output_path,
    ):
        captured["returns_path"] = returns_path
        captured["proxy_path"] = proxy_path
        captured["output_path"] = output_path
        captured["config_path"] = config_path
        captured["latest_only"] = latest_only
        captured["indicator_output_path"] = indicator_output_path
        return []

    monkeypatch.setattr(
        "market_helper.cli.main.generate_regime_snapshots",
        fake_generate_regime_snapshots,
    )

    exit_code = main(
        [
            "regime-detect",
            "--returns",
            str(tmp_path / "returns.json"),
            "--proxy",
            str(tmp_path / "proxy.json"),
            "--output",
            str(tmp_path / "regime.json"),
            "--indicators-output",
            str(tmp_path / "indicators.json"),
            "--config",
            str(tmp_path / "regime.yml"),
            "--latest-only",
        ]
    )

    assert exit_code == 0
    assert captured["latest_only"] is True
    assert str(captured["returns_path"]).endswith("returns.json")


def test_cli_etf_sector_sync_dispatches_to_workflow(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_generate_etf_sector_sync(*, symbols, output_path, api_key):
        captured["symbols"] = symbols
        captured["output_path"] = output_path
        captured["api_key"] = api_key
        return output_path

    monkeypatch.setattr(
        "market_helper.cli.main.generate_etf_sector_sync",
        fake_generate_etf_sector_sync,
    )

    exit_code = main(
        [
            "etf-sector-sync",
            "--symbol",
            "SOXX",
            "--symbol",
            "QQQ",
            "--output",
            str(tmp_path / "us_sector_lookthrough.json"),
            "--api-key",
            "demo-key",
        ]
    )

    assert exit_code == 0
    assert captured["symbols"] == ["SOXX", "QQQ"]
    assert str(captured["output_path"]).endswith("us_sector_lookthrough.json")
    assert captured["api_key"] == "demo-key"


def test_cli_extract_report_mapping_dispatches_to_workflow(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_generate_report_mapping_table(*, workbook_path, output_path):
        captured["workbook_path"] = workbook_path
        captured["output_path"] = output_path
        return output_path

    monkeypatch.setattr(
        "market_helper.cli.main.generate_report_mapping_table",
        fake_generate_report_mapping_table,
    )

    exit_code = main(
        [
            "extract-report-mapping",
            "--workbook",
            str(tmp_path / "target_report.xlsx"),
            "--output",
            str(tmp_path / "target_report_security_reference.csv"),
        ]
    )

    assert exit_code == 0
    assert str(captured["workbook_path"]).endswith("target_report.xlsx")
    assert str(captured["output_path"]).endswith("target_report_security_reference.csv")
