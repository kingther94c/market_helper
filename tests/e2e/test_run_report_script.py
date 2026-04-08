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
    local_config = project_root / "configs" / "portfolio_monitor" / "report_accounts.local.env"
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


def test_run_report_uses_legacy_local_account_config_with_warning(tmp_path: Path) -> None:
    project_root, fake_conda = _prepare_script_project(tmp_path)
    legacy_config = project_root / "configs" / "report_accounts.local.env"
    legacy_config.parent.mkdir(parents=True)
    legacy_config.write_text(
        'DEFAULT_PROD_ACCOUNT_ID="U20002"\nDEFAULT_DEV_ACCOUNT_ID="DU20002"\n',
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
    assert "Using default prod live account: U20002" in result.stdout
    assert "--account" in result.stdout
    assert "U20002" in result.stdout
    assert "deprecated" in result.stderr.lower()
    assert "configs/portfolio_monitor/report_accounts.local.env" in result.stderr


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
    assert "configs/portfolio_monitor/report_accounts.local.env" in result.stderr
    assert "configs/report_accounts.local.env" not in result.stderr


def test_run_report_risk_html_forwards_unified_and_legacy_config_flags(tmp_path: Path) -> None:
    project_root, fake_conda = _prepare_script_project(tmp_path)
    positions_csv = project_root / "inputs" / "positions.csv"
    risk_config = project_root / "configs" / "portfolio_monitor" / "risk_report.yaml"
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
    assert "--risk-config" in result.stdout
    assert str(risk_config) in result.stdout
    assert "--allocation-policy" in result.stdout
    assert str(legacy_policy) in result.stdout
