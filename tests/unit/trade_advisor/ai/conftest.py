"""Hermetic isolation for AI+ gateway tests.

Point the OpenClaw-config token fallback at a nonexistent path so no test ever
reads the real ``~/.openclaw/openclaw.json`` (mirrors how the GDrive probe is
neutralized elsewhere). Individual tests override ``OPENCLAW_CONFIG_PATH`` when
they want to exercise the fallback against a temp file.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _neutralize_openclaw_config(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(tmp_path / "no-openclaw.json"))
    monkeypatch.delenv("OPENCLAW_STATE_DIR", raising=False)
