from __future__ import annotations

import pytest

from market_helper.config import local_env


@pytest.fixture(autouse=True)
def _isolate_machine_local_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("MARKET_HELPER_GDRIVE_ROOT", raising=False)
    monkeypatch.delenv("IBKR_PORT", raising=False)
    monkeypatch.delenv("IBKR_HOST", raising=False)
    # Neutralize the Windows registry fallback AND the OS-aware default
    # probe in `read_gdrive_root` / `resolve_local_config_path` for the whole
    # unit suite, so tests that monkeypatch `os.environ` but don't pass an
    # explicit `environ=` still see a hermetic environment instead of
    # leaking the developer's real MARKET_HELPER_GDRIVE_ROOT (either from
    # HKCU\Environment or from a Google Drive mount on the host). Tests
    # that specifically exercise these fallbacks (`test_local_env.py`)
    # re-monkeypatch them back as needed.
    monkeypatch.setattr(local_env, "read_windows_user_env", lambda key: "")
    monkeypatch.setattr(local_env, "_probe_gdrive_root", lambda: "")
