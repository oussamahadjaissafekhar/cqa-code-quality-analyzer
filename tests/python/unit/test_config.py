from __future__ import annotations

import pytest

from cqa.config import Config, load_config
from cqa.exit_codes import UsageError


def write(path, content):  # type: ignore[no-untyped-def]
    path.write_text(content, encoding="utf-8")
    return path


def test_defaults_are_safe() -> None:
    config = Config(schema_version=1)
    assert config.discover.use_gitignore is True
    assert "**/node_modules/**" in config.discover.exclude
    assert config.thresholds.fail_on == "high"
    assert config.report.formats == ["json"]


def test_load_toml_and_flatten_nested_overrides(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = write(
        tmp_path / "cqa.toml",
        """
schema_version = 1

[discover]
include = ["src/**/*.py"]
use_gitignore = false

[parser]
languages = ["python"]
timeout_s = 30
jobs = 2

[rules]
disable = ["sec.insecure_http"]

[rules.overrides.secrets.hardcoded]
severity = "medium"

[thresholds]
fail_on = "medium"
max_medium = 3

[report]
formats = ["json", "sarif"]
sarif = true
""",
    )
    config, source = load_config(path)
    assert source == path
    assert config.discover.include == ["src/**/*.py"]
    assert config.discover.use_gitignore is False
    assert config.parser.timeout_s == 30
    assert config.rules.disable == ["sec.insecure_http"]
    override = config.rules.overrides["secrets.hardcoded"]
    assert override.severity is not None
    assert override.severity.value == "medium"
    assert config.thresholds.max_medium == 3
    assert config.report.sarif is True


def test_quoted_dotted_override_is_preserved(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = write(
        tmp_path / "cqa.toml",
        """
schema_version = 1

[rules.overrides."sec.eval"]
severity = "low"
""",
    )
    config, _ = load_config(path)
    assert config.rules.overrides["sec.eval"].severity.value == "low"


def test_pyproject_tool_section(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = write(
        tmp_path / "pyproject.toml",
        """
[tool.cqa]
schema_version = 1
[tool.cqa.thresholds]
fail_on = "critical"
""",
    )
    config, source = load_config(path)
    assert source == path
    assert config.thresholds.fail_on == "critical"


def test_auto_detection_prefers_cqa_toml(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    write(tmp_path / "pyproject.toml", "[tool.cqa]\nschema_version = 1\n")
    write(tmp_path / "cqa.toml", "schema_version = 1\nthresholds.fail_on = 'low'\n")
    monkeypatch.chdir(tmp_path)
    config, source = load_config()
    assert source is not None and source.name == "cqa.toml"
    assert config.thresholds.fail_on == "low"


def test_unknown_keys_fail_closed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = write(tmp_path / "cqa.toml", "schema_version = 1\n\n[discover]\nmagic = true\n")
    with pytest.raises(UsageError, match="magic"):
        load_config(path)


def test_unknown_nested_section_fails(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = write(tmp_path / "cqa.toml", "schema_version = 1\n\n[chaos]\nlevel = 9\n")
    with pytest.raises(UsageError):
        load_config(path)


def test_invalid_fail_on(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = write(
        tmp_path / "cqa.toml",
        "schema_version = 1\n\n[thresholds]\nfail_on = 'sometimes'\n",
    )
    with pytest.raises(UsageError, match="fail_on"):
        load_config(path)


def test_explicit_missing_config(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(UsageError, match="not found"):
        load_config(tmp_path / "nope.toml")


def test_invalid_toml(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = write(tmp_path / "cqa.toml", "schema_version = [\n")
    with pytest.raises(UsageError, match="TOML"):
        load_config(path)
