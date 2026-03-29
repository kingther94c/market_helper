from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def read_json(path: str | Path) -> Any:
    """Read and decode JSON from a file path."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any, *, indent: int = 2) -> Path:
    """Write JSON to disk, creating parent directories as needed."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=indent), encoding="utf-8")
    return output_path


def read_yaml_mapping(path: str | Path) -> dict[str, Any]:
    """Read YAML and require a mapping payload."""
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("YAML payload must be a mapping")
    return dict(payload)
