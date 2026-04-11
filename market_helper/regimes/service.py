from __future__ import annotations

"""Orchestration helpers for deterministic regime detection."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from market_helper.common.progress import ProgressReporter, resolve_progress_reporter

from .indicators import compute_factor_snapshots
from .models import FactorSnapshot, RegimeSnapshot
from .rulebook import RulebookConfig, classify_regimes
from .sources import load_regime_inputs


@dataclass(frozen=True)
class RegimeServiceConfig:
    """Runtime configuration for regime detection service."""

    stress_weight_vol: float = 0.55
    stress_weight_credit: float = 0.45
    rulebook: RulebookConfig = RulebookConfig()


def load_service_config(path: str | Path | None) -> RegimeServiceConfig:
    """Load optional YAML config for regime service."""
    if path is None:
        return RegimeServiceConfig()
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("regime config must be a mapping")
    rulebook_payload = payload.get("rulebook") if isinstance(payload.get("rulebook"), dict) else {}
    return RegimeServiceConfig(
        stress_weight_vol=float(payload.get("stress_weight_vol", 0.55)),
        stress_weight_credit=float(payload.get("stress_weight_credit", 0.45)),
        rulebook=RulebookConfig(
            crisis_enter_threshold=float(rulebook_payload.get("crisis_enter_threshold", 0.75)),
            crisis_exit_threshold=float(rulebook_payload.get("crisis_exit_threshold", 0.60)),
            inflationary_rates_threshold=float(rulebook_payload.get("inflationary_rates_threshold", 0.20)),
            recovery_window_days=int(rulebook_payload.get("recovery_window_days", 20)),
            min_non_crisis_days=int(rulebook_payload.get("min_non_crisis_days", 5)),
        ),
    )


def detect_regimes(
    *,
    returns_path: str | Path,
    proxy_path: str | Path,
    config_path: str | Path | None = None,
    latest_only: bool = False,
    output_path: str | Path | None = None,
    indicator_output_path: str | Path | None = None,
    progress: ProgressReporter | None = None,
) -> list[RegimeSnapshot]:
    """Run end-to-end deterministic regime detection from local JSON inputs."""
    reporter = resolve_progress_reporter(progress)
    total_steps = 5 if indicator_output_path is not None or output_path is not None else 4
    current_step = 0
    reporter.stage("Regime detection", current=current_step, total=total_steps)
    cfg = load_service_config(config_path)
    current_step += 1
    reporter.stage("Regime detection: config loaded", current=current_step, total=total_steps)
    bundle = load_regime_inputs(proxy_path=proxy_path, returns_path=returns_path)
    current_step += 1
    reporter.stage("Regime detection: inputs loaded", current=current_step, total=total_steps)
    # Keep feature construction and rule resolution separate so the same factor
    # snapshots can later power validation notebooks and backtests.
    factors = compute_factor_snapshots(
        dates=bundle.dates,
        vix=bundle.vix,
        move=bundle.move,
        hy_oas=bundle.hy_oas,
        y2=bundle.y2,
        y10=bundle.y10,
        eq_returns=bundle.eq_returns,
        fi_returns=bundle.fi_returns,
        stress_weight_vol=cfg.stress_weight_vol,
        stress_weight_credit=cfg.stress_weight_credit,
    )
    current_step += 1
    reporter.stage("Regime detection: factors computed", current=current_step, total=total_steps)
    regimes = classify_regimes(factors, config=cfg.rulebook)
    regimes = _attach_source_info(regimes, bundle.source_info)
    current_step += 1
    reporter.stage("Regime detection: regimes classified", current=current_step, total=total_steps)

    if latest_only and regimes:
        regimes = [regimes[-1]]

    if indicator_output_path is not None:
        _write_json(indicator_output_path, [item.to_dict() for item in factors])
    if output_path is not None:
        _write_json(output_path, [item.to_dict() for item in regimes])
    if indicator_output_path is not None or output_path is not None:
        current_step += 1
        reporter.done("Regime detection", detail="artifacts written")
    else:
        reporter.done("Regime detection")

    return regimes


def _attach_source_info(
    snapshots: list[RegimeSnapshot],
    source_info: dict[str, str],
) -> list[RegimeSnapshot]:
    """Copy provenance into each snapshot so downstream artifacts remain auditable."""
    return [
        RegimeSnapshot(
            as_of=item.as_of,
            regime=item.regime,
            scores=item.scores,
            inputs=item.inputs,
            flags=item.flags,
            version=item.version,
            diagnostics=item.diagnostics,
            source_info=source_info,
        )
        for item in snapshots
    ]


def _write_json(path: str | Path, payload: list[dict[str, Any]]) -> None:
    """Persist JSON artifacts while creating parent directories on demand."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_regime_snapshots(path: str | Path) -> list[RegimeSnapshot]:
    """Load regime snapshots from JSON artifact."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Expected regime snapshots JSON array")
    return [RegimeSnapshot.from_dict(dict(item)) for item in payload if isinstance(item, dict)]


def load_factor_snapshots(path: str | Path) -> list[FactorSnapshot]:
    """Load indicator/factor snapshots from JSON artifact."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Expected indicator snapshots JSON array")
    out: list[FactorSnapshot] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        out.append(
            FactorSnapshot(
                as_of=str(item["as_of"]),
                vol=float(item["vol"]),
                credit=float(item["credit"]),
                rates=float(item["rates"]),
                growth=float(item["growth"]),
                trend=float(item["trend"]),
                stress=float(item["stress"]),
                inputs={str(k): float(v) for k, v in dict(item.get("inputs", {})).items()},
            )
        )
    return out
