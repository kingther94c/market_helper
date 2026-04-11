from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_SCRIPT = REPO_ROOT / "scripts" / "run_report.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _prepare_script_project(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "project"
    script_dir = project_root / "scripts"
    script_dir.mkdir(parents=True)

    script_path = script_dir / "run_report.sh"
    _write_executable(script_path, SOURCE_SCRIPT.read_text(encoding="utf-8"))

    fake_conda = tmp_path / "fake_conda.sh"
    _write_executable(
        fake_conda,
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$@\"\n",
    )
    return project_root, fake_conda


def _run_script(project_root: Path, fake_conda: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["CONDA_BIN"] = str(fake_conda)
    env["ENV_NAME"] = "testenv"
    env.pop("ACCOUNT_ENV", None)
    env.pop("DEFAULT_PROD_ACCOUNT_ID", None)
    env.pop("DEFAULT_DEV_ACCOUNT_ID", None)
    return subprocess.run(
        [str(project_root / "scripts" / "run_report.sh"), *args],
        cwd=project_root,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_run_report_uses_canonical_local_account_config(tmp_path: Path) -> None:
    project_root, fake_conda = _prepare_script_project(tmp_path)
    local_config = project_root / "configs" / "portfolio_monitor" / "local.env"
    local_config.parent.mkdir(parents=True)
    local_config.write_text(
        'DEFAULT_PROD_ACCOUNT_ID="U10001"\nDEFAULT_DEV_ACCOUNT_ID="DU10001"\n',
        encoding="utf-8",
    )

    result = _run_script(
        project_root,
        fake_conda,
        "ibkr-live",
        "--output",
        str(project_root / "outputs" / "live.csv"),
    )

    assert result.returncode == 0
    assert "Using default prod live account: U10001" in result.stdout
    assert "--account" in result.stdout
    assert "U10001" in result.stdout
    assert "deprecated" not in result.stderr.lower()


def test_run_report_missing_account_config_points_to_canonical_path(tmp_path: Path) -> None:
    project_root, fake_conda = _prepare_script_project(tmp_path)

    result = _run_script(
        project_root,
        fake_conda,
        "ibkr-live",
        "--output",
        str(project_root / "outputs" / "live.csv"),
    )

    assert result.returncode != 0
    assert "configs/portfolio_monitor/local.env" in result.stderr


def test_run_report_risk_html_forwards_unified_and_legacy_config_flags(tmp_path: Path) -> None:
    project_root, fake_conda = _prepare_script_project(tmp_path)
    positions_csv = project_root / "inputs" / "positions.csv"
    risk_config = project_root / "configs" / "portfolio_monitor" / "report_config.yaml"
    legacy_policy = project_root / "configs" / "portfolio_monitor" / "allocation_policy.yaml"
    positions_csv.parent.mkdir(parents=True)
    risk_config.parent.mkdir(parents=True)

    positions_csv.write_text("as_of,account\n", encoding="utf-8")
    risk_config.write_text("risk_report:\n  policy: {}\n", encoding="utf-8")
    legacy_policy.write_text("policy: {}\n", encoding="utf-8")

    result = _run_script(
        project_root,
        fake_conda,
        "risk-html",
        "--positions-csv",
        str(positions_csv),
        "--risk-config",
        str(risk_config),
        "--allocation-policy",
        str(legacy_policy),
        "--output",
        str(project_root / "outputs" / "risk.html"),
    )

    assert result.returncode == 0
    assert "combined-html-report" in result.stdout
    assert "--risk-config" in result.stdout
    assert str(risk_config) in result.stdout
    assert "--allocation-policy" in result.stdout
    assert str(legacy_policy) in result.stdout
    assert "--performance-output-dir" in result.stdout
    assert "data/artifacts/portfolio_monitor/flex" in result.stdout
    assert "--proxy" not in result.stdout


def test_run_report_combined_html_forwards_performance_inputs(tmp_path: Path) -> None:
    project_root, fake_conda = _prepare_script_project(tmp_path)
    positions_csv = project_root / "inputs" / "positions.csv"
    history_path = project_root / "data" / "artifacts" / "portfolio_monitor" / "flex" / "performance_history.feather"
    report_csv = project_root / "data" / "artifacts" / "portfolio_monitor" / "flex" / "performance_report_20260331.csv"
    positions_csv.parent.mkdir(parents=True)
    history_path.parent.mkdir(parents=True)

    positions_csv.write_text("as_of,account\n", encoding="utf-8")
    history_path.write_text("demo", encoding="utf-8")
    report_csv.write_text("demo", encoding="utf-8")

    result = _run_script(
        project_root,
        fake_conda,
        "combined-html",
        "--positions-csv",
        str(positions_csv),
        "--performance-history",
        str(history_path),
        "--performance-report-csv",
        str(report_csv),
        "--output",
        str(project_root / "outputs" / "combined.html"),
    )

    assert result.returncode == 0
    assert "combined-html-report" in result.stdout
    assert "--performance-history" in result.stdout
    assert str(history_path) in result.stdout
    assert "--performance-report-csv" in result.stdout
    assert str(report_csv) in result.stdout


def test_run_report_ibkr_live_html_defaults_to_combined_report(tmp_path: Path) -> None:
    project_root, fake_conda = _prepare_script_project(tmp_path)
    local_config = project_root / "configs" / "portfolio_monitor" / "local.env"
    local_config.parent.mkdir(parents=True)
    local_config.write_text('DEFAULT_PROD_ACCOUNT_ID="U10001"\n', encoding="utf-8")

    result = _run_script(
        project_root,
        fake_conda,
        "ibkr-live-html",
        "--output",
        str(project_root / "outputs" / "combined.html"),
    )

    assert result.returncode == 0
    assert "ibkr-live-position-report" in result.stdout
    assert "combined-html-report" in result.stdout
    assert "--performance-output-dir" in result.stdout
    assert "portfolio_combined_report.html" not in result.stdout or "--output" in result.stdout


def test_run_report_security_reference_sync_defaults_to_artifacts_cache_path(tmp_path: Path) -> None:
    project_root, fake_conda = _prepare_script_project(tmp_path)

    result = _run_script(
        project_root,
        fake_conda,
        "security-reference-sync",
    )

    assert result.returncode == 0
    assert "data/artifacts/portfolio_monitor/security_reference.csv" in result.stdout


def test_run_report_etf_sector_sync_forwards_symbols_and_output(tmp_path: Path) -> None:
    project_root, fake_conda = _prepare_script_project(tmp_path)

    result = _run_script(
        project_root,
        fake_conda,
        "etf-sector-sync",
        "--symbol",
        "SOXX",
        "--symbol",
        "QQQ",
        "--output",
        str(project_root / "configs" / "portfolio_monitor" / "us_sector_lookthrough.json"),
        "--api-key",
        "demo-key",
    )

    assert result.returncode == 0
    assert "etf-sector-sync" in result.stdout
    assert "--symbol" in result.stdout
    assert "SOXX" in result.stdout
    assert "QQQ" in result.stdout
    assert "--api-key" in result.stdout
