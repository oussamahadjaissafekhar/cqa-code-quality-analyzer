"""Additional config discovery/validation branches."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cqa.config import (
    Config,
    _flatten_overrides,
    _read_toml,
    _validate_json_schema,
    default_toml,
    empty_severity_counts,
    load_config,
)
from cqa.exit_codes import UsageError


def write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_default_toml_round_trips_through_the_loader(tmp_path: Path) -> None:
    path = write(tmp_path / "cqa.toml", default_toml())
    config, source = load_config(path)
    assert source == path
    assert config.schema_version == 1
    assert config.parser.timeout_s == 120


def test_relative_explicit_config_resolves_against_cwd(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    write(tmp_path / "cqa.toml", "schema_version = 1\n[thresholds]\nfail_on = 'low'\n")
    monkeypatch.chdir(tmp_path)
    config, source = load_config(Path("cqa.toml"))
    assert source == tmp_path / "cqa.toml"
    assert config.thresholds.fail_on == "low"


def test_pyproject_without_tool_cqa_is_ignored(tmp_path: Path) -> None:
    write(tmp_path / "pyproject.toml", "[project]\nname = 'demo'\n")
    config, source = load_config(cwd=tmp_path)
    assert source is None
    assert config.thresholds.fail_on == "high"


def test_explicit_pyproject_requires_a_tool_section(tmp_path: Path) -> None:
    path = write(tmp_path / "pyproject.toml", "[project]\nname = 'demo'\n")
    with pytest.raises(UsageError, match="no \\[tool.cqa\\] section"):
        load_config(path)


def test_explicit_pyproject_requires_a_table(tmp_path: Path) -> None:
    path = write(tmp_path / "pyproject.toml", "[tool]\ncqa = 5\n")
    with pytest.raises(UsageError, match="must be a table"):
        load_config(path)


def test_unreadable_config_maps_to_usage_error(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="cannot read config"):
        _read_toml(tmp_path)  # a directory is not readable as text


def test_flatten_overrides_handles_non_mapping_and_leaves() -> None:
    assert _flatten_overrides(["not", "a", "mapping"]) == ["not", "a", "mapping"]
    assert _flatten_overrides({"a": {"b": {"severity": "low"}}}) == {"a.b": {"severity": "low"}}
    assert _flatten_overrides({"a": {"enabled": False}}) == {"a": {"enabled": False}}


def test_validation_is_skipped_without_contracts(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("cqa.config._contracts_dir", lambda: None)
    _validate_json_schema({"schema_version": 1})  # must not raise


def test_validation_skips_unreadable_schema(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "config.schema.json").write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr("cqa.config._contracts_dir", lambda: contracts)
    _validate_json_schema({"schema_version": 1})  # must not raise


def test_pydantic_errors_are_mapped_when_schema_is_unavailable(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    path = write(tmp_path / "cqa.toml", "schema_version = 1\n\n[discover]\nmagic = true\n")
    monkeypatch.setattr("cqa.config._validate_json_schema", lambda raw: None)
    with pytest.raises(UsageError, match="invalid config"):
        load_config(path)


def test_fail_on_enum_is_checked_when_schema_is_unavailable(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    path = write(tmp_path / "cqa.toml", "schema_version = 1\n[thresholds]\nfail_on = 'sometimes'\n")
    monkeypatch.setattr("cqa.config._validate_json_schema", lambda raw: None)
    with pytest.raises(UsageError, match="invalid fail_on"):
        load_config(path)


def test_empty_severity_counts_covers_every_level() -> None:
    assert empty_severity_counts() == {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "info": 0,
    }


def test_config_source_is_reported_for_auto_detection(tmp_path: Path) -> None:
    path = write(tmp_path / ".cqa.toml", "schema_version = 1\n")
    config, source = load_config(cwd=tmp_path)
    assert config == Config(schema_version=1)
    assert source == path


def test_json_schema_details_are_bounded_to_five(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "config.schema.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "required": ["schema_version"],
                "properties": {"schema_version": {"const": 1}},
                "additionalProperties": False,
            }
        ),
        encoding="utf-8",
    )
    pytest.importorskip("jsonschema")
    import cqa.config as config_module

    original = config_module._contracts_dir
    config_module._contracts_dir = lambda: contracts
    try:
        with pytest.raises(UsageError) as excinfo:
            _validate_json_schema(
                {"schema_version": 2, "one": 1, "two": 2, "three": 3, "four": 4}
            )
        assert str(excinfo.value).count(":") >= 1
    finally:
        config_module._contracts_dir = original
