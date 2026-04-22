from __future__ import annotations

import os
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parent
CONFIGS_DIR = REPO_ROOT / "configs"
# DATA_DIR can be overridden via MARKET_HELPER_DATA_DIR so git worktrees (and
# other non-canonical checkouts) can share the main repo's cache/artifacts
# instead of refetching everything from scratch.
_DATA_DIR_OVERRIDE = os.environ.get("MARKET_HELPER_DATA_DIR")
DATA_DIR = Path(_DATA_DIR_OVERRIDE).expanduser() if _DATA_DIR_OVERRIDE else REPO_ROOT / "data"
ARTIFACTS_DIR = DATA_DIR / "artifacts"
PORTFOLIO_ARTIFACTS_DIR = ARTIFACTS_DIR / "portfolio_monitor"
REGIME_ARTIFACTS_DIR = ARTIFACTS_DIR / "regime_detection"
INTEGRATION_ARTIFACTS_DIR = ARTIFACTS_DIR / "integration"
