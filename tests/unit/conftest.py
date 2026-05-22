from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_machine_local_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.delenv("MARKET_HELPER_GDRIVE_ROOT", raising=False)
