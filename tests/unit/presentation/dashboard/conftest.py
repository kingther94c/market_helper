from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _stub_ibkr_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the dashboard's local-IBKR-port probe so tests don't open real
    sockets to 4001/4002/7496/7497 — both for speed (no 600ms wait when
    nothing's listening) and so test results don't depend on what's running
    on the developer's machine. Tests that exercise the probe itself
    monkeypatch ``socket.socket`` directly to undo this stub.
    """
    import market_helper.presentation.dashboard.pages.portfolio_monitor.state as pm_state

    monkeypatch.setattr(pm_state, "_probe_local_ibkr_port", lambda **_kwargs: None)
