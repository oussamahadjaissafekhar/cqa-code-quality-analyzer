"""Configuration loading, merging, and validation.

Resolution order (spec §4.5): CLI flags > environment > config file > defaults.
This module only handles the "config file > defaults" part; the CLI performs the
final precedence merge so that every option is resolved in one place.

Config files are validated twice:
1. Against ``contracts/config.schema.json`` when the schema is available.
2. By pydantic models with ``extra="forbid"`` so unknown keys fail closed.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on 3.10 only
    import tomli as tomllib

from .exit_codes import UsageError
from .models import ALL_SEVERITIES, Language, Severity, StrictModel

CONFIG_FILENAMES = ("cqa.toml", ".cqa.toml")

DEFAULT_INCLUDE = ["**/*.{py,ts,tsx,js,jsx}"]
DEFAULT_EXCLUDE = [
    "**/node_modules/**",
    "**/.git/**",
    "**/dist/**",
    "**/build/**",
    "**/.venv/**",
    "**/venv/**",
    "**/__pycache__/**",
    "**/.cqa-cache/**",
    "**/coverage/**",
]
DEFAULT_LANGUAGES: list[Language] = ["python", "typescript", "javascript"]
ReportFormat = Literal["json", "sarif", "markdown", "github", "table"]
FORMAT_VALUES = ("json", "sarif", "markdown", "github", "table")
DEFAULT_REPORT_FORMATS: list[ReportFormat] = ["json"]
FAIL_ON_VALUES = ("critical", "high", "medium", "low", "info", "never")


class RuleOverride(StrictModel):
    severity: Severity | None = None
    enabled: bool | None = None


class DiscoverConfig(StrictModel):
    include: list[str] = Field(default_factory=lambda: list(DEFAULT_INCLUDE))
    exclude: list[str] = Field(default_factory=lambda: list(DEFAULT_EXCLUDE))
    use_gitignore: bool = True


class ParserConfig(StrictModel):
    languages: list[Language] = Field(default_factory=lambda: list(DEFAULT_LANGUAGES))
    timeout_s: int = Field(default=120, ge=1)
    jobs: int = Field(default=0, ge=0)


class RulesConfig(StrictModel):
    disable: list[str] = Field(default_factory=list)
    overrides: dict[str, RuleOverride] = Field(default_factory=dict)


class ThresholdsConfig(StrictModel):
    fail_on: str = "high"
    max_critical: int | None = Field(default=None, ge=0)
    max_high: int | None = Field(default=None, ge=0)
    max_medium: int | None = Field(default=None, ge=0)
    max_low: int | None = Field(default=None, ge=0)
    max_info: int | None = Field(default=None, ge=0)

    def max_for(self, severity: Severity) -> int | None:
        return {
            Severity.CRITICAL: self.max_critical,
            Severity.HIGH: self.max_high,
            Severity.MEDIUM: self.max_medium,
            Severity.LOW: self.max_low,
            Severity.INFO: self.max_info,
        }[severity]


class ReportConfig(StrictModel):
    formats: list[ReportFormat] = Field(
        default_factory=lambda: list(DEFAULT_REPORT_FORMATS)
    )
    sarif: bool = False


class Config(StrictModel):
    schema_version: Literal[1]
    discover: DiscoverConfig = Field(default_factory=DiscoverConfig)
    parser: ParserConfig = Field(default_factory=ParserConfig)
    rules: RulesConfig = Field(default_factory=RulesConfig)
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)


def _contracts_dir() -> Path | None:
    """Locate ``contracts/`` in a source checkout or the current directory."""

    candidates = [
        Path.cwd() / "contracts",
        Path(__file__).resolve().parents[2] / "contracts",
    ]
    for candidate in candidates:
        if (candidate / "config.schema.json").is_file():
            return candidate
    return None


def _flatten_overrides(value: Any) -> Any:
    """Flatten nested TOML tables into dotted rule ids.

    ``[rules.overrides.secrets.hardcoded]`` parses as a nested object. Rule ids
    are dotted, so we flatten leading tables that are not override leaves.
    """

    if not isinstance(value, dict):
        return value

    leaf_keys = {"severity", "enabled"}
    result: dict[str, Any] = {}
    for key, child in value.items():
        if isinstance(child, dict) and not leaf_keys.intersection(child):
            for nested_key, nested_value in _flatten_overrides(child).items():
                result[f"{key}.{nested_key}"] = nested_value
        else:
            result[str(key)] = child
    return result


def _normalize_raw(raw: dict[str, Any]) -> dict[str, Any]:
    """Prepare a parsed TOML document for pydantic + JSON Schema validation."""

    normalized = copy.deepcopy(raw)
    rules = normalized.get("rules")
    if isinstance(rules, dict) and "overrides" in rules:
        rules["overrides"] = _flatten_overrides(rules["overrides"])
    return normalized


def _validate_json_schema(raw: dict[str, Any]) -> None:
    """Validate against the frozen JSON Schema when both schema and lib exist.

    A missing schema (e.g. an installed wheel without ``contracts/``) is not an
    error: pydantic remains authoritative at runtime. An invalid document is.
    """

    contracts = _contracts_dir()
    if contracts is None:
        return
    try:
        import jsonschema
    except ImportError:  # pragma: no cover
        return

    schema_path = contracts / "config.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return

    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(raw), key=str)
    if errors:
        details = "; ".join(
            f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: "
            f"{error.message}"
            for error in errors[:5]
        )
        raise UsageError(f"invalid config: {details}")


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UsageError(f"cannot read config {path}: {exc}") from exc
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise UsageError(f"invalid TOML in {path}: {exc}") from exc


def _extract_tool_section(path: Path, document: dict[str, Any]) -> dict[str, Any]:
    """Return the config document from a cqa.toml or pyproject.toml file."""

    if path.name == "pyproject.toml":
        tool = document.get("tool", {})
        if not isinstance(tool, dict) or "cqa" not in tool:
            raise UsageError(f"no [tool.cqa] section in {path}")
        section = tool["cqa"]
        if not isinstance(section, dict):
            raise UsageError(f"[tool.cqa] in {path} must be a table")
        return section
    return document


def find_config(explicit: Path | None, cwd: Path | None = None) -> Path | None:
    """Find the config file using the documented precedence."""

    base = cwd or Path.cwd()
    if explicit is not None:
        path = explicit.expanduser()
        if not path.is_absolute():
            path = base / path
        if not path.is_file():
            raise UsageError(f"config file not found: {path}")
        return path

    for filename in CONFIG_FILENAMES:
        candidate = base / filename
        if candidate.is_file():
            return candidate

    pyproject = base / "pyproject.toml"
    if pyproject.is_file():
        document = _read_toml(pyproject)
        tool = document.get("tool")
        if isinstance(tool, dict) and "cqa" in tool:
            return pyproject
    return None


def load_config(explicit: Path | None = None, cwd: Path | None = None) -> tuple[Config, Path | None]:
    """Load, validate, and return ``(config, source_path)``.

    With no config file present the documented defaults are returned. Unknown
    keys and schema violations raise :class:`UsageError` (exit code 2).
    """

    source = find_config(explicit, cwd)
    if source is None:
        return Config(schema_version=1), None

    raw = _normalize_raw(_extract_tool_section(source, _read_toml(source)))
    _validate_json_schema(raw)
    try:
        config = Config.model_validate(raw)
    except ValidationError as exc:
        messages = []
        for error in exc.errors()[:5]:
            location = ".".join(str(part) for part in error["loc"]) or "<root>"
            messages.append(f"{location}: {error['msg']}")
        raise UsageError(f"invalid config {source}: {'; '.join(messages)}") from exc

    if config.thresholds.fail_on not in FAIL_ON_VALUES:
        raise UsageError(
            f"invalid fail_on value {config.thresholds.fail_on!r}; "
            f"expected one of {', '.join(FAIL_ON_VALUES)}"
        )
    return config, source


def empty_severity_counts() -> dict[str, int]:
    """Zeroed severity histogram shared by summaries and reports."""

    return {severity.value: 0 for severity in ALL_SEVERITIES}


def default_toml() -> str:
    """Content written by ``cqa init``; mirrors the spec's sample config."""

    return """schema_version = 1

[discover]
include = ["**/*.{py,ts,tsx,js,jsx}"]
exclude = [
  "**/node_modules/**",
  "**/.git/**",
  "**/dist/**",
  "**/build/**",
  "**/.venv/**",
  "**/__pycache__/**",
  "**/.cqa-cache/**",
]
use_gitignore = true

[parser]
languages = ["python", "typescript", "javascript"]
timeout_s = 120
jobs = 0  # 0 = auto

[rules]
disable = []
# Rule overrides use nested tables; the id is reconstructed with dots:
# [rules.overrides.secrets.hardcoded]
# severity = "high"

[thresholds]
fail_on = "high"
# max_high = 0
# max_medium = 20

[report]
formats = ["json"]
sarif = false
"""
