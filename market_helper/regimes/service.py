from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from market_helper.utils.io import read_json, read_yaml_mapping, write_json

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
    payload = read_yaml_mapping(path)
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
) -> list[RegimeSnapshot]:
    """Run end-to-end deterministic regime detection from local JSON inputs."""
    cfg = load_service_config(config_path)
    bundle = load_regime_inputs(proxy_path=proxy_path, returns_path=returns_path)
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
    regimes = classify_regimes(factors, config=cfg.rulebook)
    regimes = _attach_source_info(regimes, bundle.source_info)

    if latest_only and regimes:
        regimes = [regimes[-1]]

    if indicator_output_path is not None:
        _write_json(indicator_output_path, [item.to_dict() for item in factors])
    if output_path is not None:
        _write_json(output_path, [item.to_dict() for item in regimes])

    return regimes


def _attach_source_info(
    snapshots: list[RegimeSnapshot],
    source_info: dict[str, str],
) -> list[RegimeSnapshot]:
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
    write_json(path, payload, indent=2)


def load_regime_snapshots(path: str | Path) -> list[RegimeSnapshot]:
    """Load regime snapshots from JSON artifact."""
    payload = read_json(path)
    if not isinstance(payload, list):
        raise ValueError("Expected regime snapshots JSON array")
    return [RegimeSnapshot.from_dict(dict(item)) for item in payload if isinstance(item, dict)]


def load_factor_snapshots(path: str | Path) -> list[FactorSnapshot]:
    """Load indicator/factor snapshots from JSON artifact."""
    payload = read_json(path)
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
