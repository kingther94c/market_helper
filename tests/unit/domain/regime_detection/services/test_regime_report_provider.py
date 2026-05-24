"""Tests for the combined-report regime provider.

Staleness uses the same trading-day predicate
(`market_helper.common.datetime_display.is_as_of_stale`) as the report's
overall as-of freshness note — these tests pin a fixed ``now`` so the
expected T-1 date is deterministic.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from market_helper.domain.regime_detection.services import regime_report_provider
from market_helper.domain.regime_detection.services.regime_report_provider import (
    RegimeArtifactState,
    provide_regime_view_model,
)


# Pinned ‟now": a Wednesday 14:00 SGT. Expected T-1 = the previous weekday in
# SGT-anchored terms = Tue 2026-05-19.
_FROZEN_NOW = datetime(2026, 5, 20, 6, 0, tzinfo=timezone.utc)  # 14:00 SGT Wed
_EXPECTED_T1_ISO = "2026-05-19"  # Tue
_STALE_AS_OF_ISO = "2026-05-15"  # Fri prior week
_FRESH_AS_OF_ISO = "2026-05-19"  # exactly T-1


def _make_view_model(as_of: str) -> SimpleNamespace:
    return SimpleNamespace(as_of=as_of, regime="Goldilocks")


def _stub_build_view_model(monkeypatch: pytest.MonkeyPatch, view_model) -> None:
    monkeypatch.setattr(
        regime_report_provider,
        "build_regime_html_view_model",
        lambda *, regime_path, policy_path=None: view_model,
    )


def _frozen_now() -> datetime:
    return _FROZEN_NOW


def _no_op_refresh(*, output_regime_path: Path) -> None:
    raise AssertionError(
        f"refresh_callable should not be invoked in this scenario "
        f"(output_regime_path={output_regime_path})"
    )


def _write_regime_snapshot(path: Path, *, as_of: str) -> Path:
    """Write a minimal regime_snapshots.json the provider's peek logic can parse."""
    path.write_text(
        json.dumps([{"date": as_of, "final_regime": "Goldilocks"}]),
        encoding="utf-8",
    )
    return path


def test_cached_mode_returns_ok_for_fresh_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_build_view_model(monkeypatch, _make_view_model(_FRESH_AS_OF_ISO))
    regime_path = _write_regime_snapshot(tmp_path / "regime.json", as_of=_FRESH_AS_OF_ISO)

    state = provide_regime_view_model(
        regime_path=regime_path,
        mode="cached",
        refresh_callable=_no_op_refresh,
        now=_frozen_now,
    )

    assert state.state == "ok"
    assert state.mode_used == "cached"
    assert state.regime_as_of == _FRESH_AS_OF_ISO
    assert state.last_run_at is not None
    assert state.error_message is None


def test_cached_mode_tags_stale_artifact_but_still_returns_view_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_build_view_model(monkeypatch, _make_view_model(_STALE_AS_OF_ISO))
    regime_path = _write_regime_snapshot(tmp_path / "regime.json", as_of=_STALE_AS_OF_ISO)

    state = provide_regime_view_model(
        regime_path=regime_path,
        mode="cached",
        refresh_callable=_no_op_refresh,
        now=_frozen_now,
    )

    assert state.state == "stale"
    assert state.regime_as_of == _STALE_AS_OF_ISO
    assert state.view_model is not None
    assert state.error_message is None


def test_cached_mode_missing_artifact_returns_missing_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_build_view_model(monkeypatch, _make_view_model(_FRESH_AS_OF_ISO))
    regime_path = tmp_path / "absent.json"

    state = provide_regime_view_model(
        regime_path=regime_path,
        mode="cached",
        refresh_callable=_no_op_refresh,
        now=_frozen_now,
    )

    assert state.state == "missing"
    assert state.view_model is None
    assert "not found" in (state.error_message or "")


def test_refresh_if_stale_triggers_refresh_when_artifact_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_build_view_model(monkeypatch, _make_view_model(_FRESH_AS_OF_ISO))
    regime_path = tmp_path / "regime.json"
    refresh_calls: list[Path] = []

    def fake_refresh(*, output_regime_path: Path) -> None:
        refresh_calls.append(output_regime_path)
        # Simulate the engine writing a fresh artifact during refresh.
        _write_regime_snapshot(output_regime_path, as_of=_FRESH_AS_OF_ISO)

    state = provide_regime_view_model(
        regime_path=regime_path,
        mode="refresh-if-stale",
        refresh_callable=fake_refresh,
        now=_frozen_now,
    )

    assert refresh_calls == [regime_path]
    assert state.state == "ok"
    assert state.mode_used == "refresh-if-stale"


def test_refresh_if_stale_skips_refresh_when_artifact_already_at_t1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_build_view_model(monkeypatch, _make_view_model(_FRESH_AS_OF_ISO))
    regime_path = _write_regime_snapshot(tmp_path / "regime.json", as_of=_FRESH_AS_OF_ISO)

    state = provide_regime_view_model(
        regime_path=regime_path,
        mode="refresh-if-stale",
        refresh_callable=_no_op_refresh,  # asserts on call
        now=_frozen_now,
    )

    assert state.state == "ok"


def test_refresh_if_stale_runs_engine_when_artifact_lags_t1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The on-disk artifact has as_of=2026-05-15 (last Friday) while T-1 is
    2026-05-19 (Tuesday). The provider must run the engine before loading."""
    _stub_build_view_model(monkeypatch, _make_view_model(_FRESH_AS_OF_ISO))
    regime_path = _write_regime_snapshot(tmp_path / "regime.json", as_of=_STALE_AS_OF_ISO)
    refresh_calls: list[Path] = []

    def fake_refresh(*, output_regime_path: Path) -> None:
        refresh_calls.append(output_regime_path)
        # Simulate the engine bringing the artifact up to T-1.
        _write_regime_snapshot(output_regime_path, as_of=_FRESH_AS_OF_ISO)

    state = provide_regime_view_model(
        regime_path=regime_path,
        mode="refresh-if-stale",
        refresh_callable=fake_refresh,
        now=_frozen_now,
    )

    assert refresh_calls == [regime_path]
    assert state.state == "ok"


def test_force_refresh_always_runs_engine_even_on_fresh_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_build_view_model(monkeypatch, _make_view_model(_FRESH_AS_OF_ISO))
    regime_path = _write_regime_snapshot(tmp_path / "regime.json", as_of=_FRESH_AS_OF_ISO)
    refresh_calls: list[Path] = []

    def fake_refresh(*, output_regime_path: Path) -> None:
        refresh_calls.append(output_regime_path)

    state = provide_regime_view_model(
        regime_path=regime_path,
        mode="force-refresh",
        refresh_callable=fake_refresh,
        now=_frozen_now,
    )

    assert refresh_calls == [regime_path]
    assert state.state == "ok"
    assert state.mode_used == "force-refresh"


def test_engine_failure_yields_engine_error_state_without_raising(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_build_view_model(monkeypatch, _make_view_model(_FRESH_AS_OF_ISO))
    regime_path = tmp_path / "regime.json"  # absent — refresh would create it

    def failing_refresh(*, output_regime_path: Path) -> None:
        raise RuntimeError("FRED sync timed out")

    state = provide_regime_view_model(
        regime_path=regime_path,
        mode="refresh-if-stale",
        refresh_callable=failing_refresh,
        now=_frozen_now,
    )

    assert state.state == "engine_error"
    assert state.view_model is None
    assert "FRED sync timed out" in (state.error_message or "")


def test_engine_failure_falls_back_to_prior_snapshot_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If refresh fails but an older artifact exists, surface engine_error but
    still load the stale data so the report has *some* regime context to show."""
    stale_vm = _make_view_model(_STALE_AS_OF_ISO)
    _stub_build_view_model(monkeypatch, stale_vm)
    regime_path = _write_regime_snapshot(tmp_path / "regime.json", as_of=_STALE_AS_OF_ISO)

    def failing_refresh(*, output_regime_path: Path) -> None:
        raise RuntimeError("network down")

    state = provide_regime_view_model(
        regime_path=regime_path,
        mode="refresh-if-stale",
        refresh_callable=failing_refresh,
        now=_frozen_now,
    )

    assert state.state == "engine_error"
    assert state.view_model is stale_vm  # fell back to the cached file
    assert "network down" in (state.error_message or "")


def test_parse_failure_yields_engine_error_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If the artifact file exists but the view-model builder fails, surface
    engine_error. The peek-for-trigger reads JSON shape; the load uses the
    real builder which can fail on schema mismatch."""

    def fake_builder(*, regime_path, policy_path=None):
        raise ValueError("bad shape")

    monkeypatch.setattr(
        regime_report_provider, "build_regime_html_view_model", fake_builder
    )
    regime_path = _write_regime_snapshot(tmp_path / "regime.json", as_of=_FRESH_AS_OF_ISO)

    state = provide_regime_view_model(
        regime_path=regime_path,
        mode="cached",
        refresh_callable=_no_op_refresh,
        now=_frozen_now,
    )

    assert state.state == "engine_error"
    assert state.view_model is None
    assert "bad shape" in (state.error_message or "")


def test_malformed_peek_does_not_trigger_extra_refresh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If the artifact exists but the peek can't parse the latest as_of, the
    refresh trigger does NOT fire — the load path is responsible for tagging
    the failure via engine_error. We don't want a malformed file to silently
    trigger an expensive FRED sync."""

    def fake_builder(*, regime_path, policy_path=None):
        raise ValueError("schema mismatch")

    monkeypatch.setattr(
        regime_report_provider, "build_regime_html_view_model", fake_builder
    )
    regime_path = tmp_path / "regime.json"
    regime_path.write_text("{not even an array}", encoding="utf-8")

    state = provide_regime_view_model(
        regime_path=regime_path,
        mode="refresh-if-stale",
        refresh_callable=_no_op_refresh,  # asserts no refresh
        now=_frozen_now,
    )

    assert state.state == "engine_error"
    assert "schema mismatch" in (state.error_message or "")


def test_view_model_with_unparseable_as_of_is_tagged_stale(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """is_as_of_stale treats unparseable strings as stale — producers must
    emit a real timestamp. The provider mirrors that."""
    _stub_build_view_model(monkeypatch, _make_view_model("not-a-date"))
    regime_path = _write_regime_snapshot(tmp_path / "regime.json", as_of=_FRESH_AS_OF_ISO)

    state = provide_regime_view_model(
        regime_path=regime_path,
        mode="cached",
        refresh_callable=_no_op_refresh,
        now=_frozen_now,
    )

    assert state.state == "stale"


def test_is_renderable_property_distinguishes_renderable_states() -> None:
    vm = _make_view_model(_FRESH_AS_OF_ISO)
    ok = RegimeArtifactState(
        state="ok",
        mode_used="cached",
        view_model=vm,
        regime_as_of=vm.as_of,
        last_run_at=None,
        error_message=None,
    )
    stale = RegimeArtifactState(
        state="stale",
        mode_used="cached",
        view_model=vm,
        regime_as_of=vm.as_of,
        last_run_at=None,
        error_message=None,
    )
    missing = RegimeArtifactState(
        state="missing",
        mode_used="cached",
        view_model=None,
        regime_as_of=None,
        last_run_at=None,
        error_message="absent",
    )
    engine_error = RegimeArtifactState(
        state="engine_error",
        mode_used="cached",
        view_model=None,
        regime_as_of=None,
        last_run_at=None,
        error_message="boom",
    )

    assert ok.is_renderable
    assert stale.is_renderable
    assert not missing.is_renderable
    assert not engine_error.is_renderable
