import json
from pathlib import Path

import pytest

from market_helper.utils.io import read_json, read_yaml_mapping, write_json


def test_read_json_and_write_json_roundtrip(tmp_path: Path) -> None:
    payload = {"a": 1, "b": [1, 2, 3]}
    output = tmp_path / "nested" / "payload.json"

    written = write_json(output, payload)

    assert written == output
    assert read_json(output) == payload


def test_read_yaml_mapping_accepts_mapping(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text("foo: 1\nbar: baz\n", encoding="utf-8")

    loaded = read_yaml_mapping(path)

    assert loaded == {"foo": 1, "bar": "baz"}


def test_read_yaml_mapping_rejects_non_mapping(tmp_path: Path) -> None:
    path = tmp_path / "bad.yml"
    path.write_text("- 1\n- 2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="mapping"):
        read_yaml_mapping(path)
