from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parent
CONFIGS_DIR = REPO_ROOT / "configs"
DATA_DIR = REPO_ROOT / "data"
ARTIFACTS_DIR = DATA_DIR / "artifacts"
PORTFOLIO_ARTIFACTS_DIR = ARTIFACTS_DIR / "portfolio_monitor"
REGIME_ARTIFACTS_DIR = ARTIFACTS_DIR / "regime_detection"
INTEGRATION_ARTIFACTS_DIR = ARTIFACTS_DIR / "integration"
