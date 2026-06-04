from market_helper.cli.main import main


def test_cli_advise_dispatches_to_workflow(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_generate_trade_advisory(
        *,
        positions_csv_path,
        regime_path,
        output_path,
        endpoint_base_url,
        model,
        session_key,
        advisor_token,
    ):
        captured["positions_csv_path"] = positions_csv_path
        captured["regime_path"] = regime_path
        captured["output_path"] = output_path
        captured["endpoint_base_url"] = endpoint_base_url
        captured["model"] = model
        captured["session_key"] = session_key
        captured["advisor_token"] = advisor_token
        return output_path

    monkeypatch.setattr(
        "market_helper.cli.main.generate_trade_advisory",
        fake_generate_trade_advisory,
    )

    exit_code = main(
        [
            "advise",
            "--positions-csv",
            str(tmp_path / "positions.csv"),
            "--regime",
            str(tmp_path / "regime_snapshots.json"),
            "--output",
            str(tmp_path / "advisory.md"),
            "--advisor-endpoint",
            "http://127.0.0.1:18789/v1",
            "--model",
            "openclaw/trade-advisor-panel",
            "--session-key",
            "conv-1",
            "--advisor-token",
            "test-token",
        ]
    )

    assert exit_code == 0
    assert str(captured["positions_csv_path"]).endswith("positions.csv")
    assert str(captured["regime_path"]).endswith("regime_snapshots.json")
    assert str(captured["output_path"]).endswith("advisory.md")
    assert captured["endpoint_base_url"] == "http://127.0.0.1:18789/v1"
    assert captured["model"] == "openclaw/trade-advisor-panel"
    assert captured["session_key"] == "conv-1"
    assert captured["advisor_token"] == "test-token"


def test_cli_advise_defaults(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_generate_trade_advisory(**kwargs):
        captured.update(kwargs)
        return kwargs["output_path"]

    monkeypatch.setattr(
        "market_helper.cli.main.generate_trade_advisory",
        fake_generate_trade_advisory,
    )

    exit_code = main(
        [
            "advise",
            "--positions-csv",
            str(tmp_path / "positions.csv"),
            "--output",
            str(tmp_path / "advisory.md"),
        ]
    )

    assert exit_code == 0
    assert captured["endpoint_base_url"] == "http://127.0.0.1:18789/v1"
    assert captured["model"] == "openclaw/trade-advisor"
    assert captured["session_key"] is None
    assert captured["advisor_token"] is None
