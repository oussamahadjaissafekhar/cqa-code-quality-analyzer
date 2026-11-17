"""Application service: the single analysis pipeline.

``run_analyze`` is the only entrypoint integration code (CLI, tests, future
GitHub Action) needs. Pipeline order is fixed by the spec (§5.6):

1. load/validate config
2. discover files
3. parse (cache-aware)
4. security + quality rules
5. baseline filter
6. summary + gate
7. return the contract model (the CLI renders reports / maps exit codes)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import Config, load_config
from .exit_codes import IoError, UsageError
from .fs.cache import FactCache
from .fs.discover import DiscoverOptions, SourceFile, discover_files, read_stdin_files
from .logging import get_logger
from .models import (
    AnalysisError,
    AnalysisResult,
    Finding,
    ParsedFile,
    ParserFile,
    Severity,
    ToolInfo,
    fingerprint,
    sort_findings,
    utc_now_iso,
)
from .parsers.node_bridge import create_parser
from .parsers.protocol import ParserPort
from .quality.metrics import build_summary, complexity_findings
from .security.engine import RuleContext, SecurityEngine, apply_severity_overrides
from .version import SCHEMA_VERSION, TOOL_VERSION, parser_version

LOGGER = get_logger("app")
SUPPORTED_LANGUAGES = ("python", "typescript", "javascript")


@dataclass
class AnalyzeOptions:
    """Resolved-ish CLI options.

    Fields that default to ``None`` mean "fall back to config"; the app performs
    the final precedence merge after loading the config file.
    """

    path: str = "."
    config_path: str | None = None
    include: tuple[str, ...] = field(default_factory=tuple)
    exclude: tuple[str, ...] = field(default_factory=tuple)
    no_gitignore: bool = False
    languages: str | None = None
    rules: str | None = None
    disable_rules: tuple[str, ...] = field(default_factory=tuple)
    format: str = "json"
    output: str = "-"
    sarif: str | None = None
    fail_on: str | None = None
    max_findings: int = 0
    baseline: str | None = None
    update_baseline: bool = False
    cache_dir: str = ".cqa-cache"
    no_cache: bool = False
    jobs: int | None = None
    timeout_s: int | None = None
    parser_bin: str | None = None
    stdin_files: bool = False
    verbose: int = 0
    clock: datetime | None = None


@dataclass
class _Effective:
    include: list[str]
    exclude: list[str]
    use_gitignore: bool
    languages: list[str]
    jobs: int
    timeout_s: int
    fail_on: str
    allow_rules: set[str] | None
    disabled_rules: set[str]


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _effective(options: AnalyzeOptions, config: Config) -> _Effective:
    languages = _csv(options.languages) or list(config.parser.languages)
    invalid = [language for language in languages if language not in SUPPORTED_LANGUAGES]
    if invalid:
        raise UsageError(
            f"unsupported language(s): {', '.join(invalid)}; "
            f"choose from {', '.join(SUPPORTED_LANGUAGES)}"
        )

    allow = set(_csv(options.rules)) or None
    disabled = set(config.rules.disable) | set(options.disable_rules)
    fail_on = options.fail_on or config.thresholds.fail_on
    if fail_on not in {"critical", "high", "medium", "low", "info", "never"}:
        raise UsageError(f"invalid fail-on threshold: {fail_on}")

    jobs = options.jobs if options.jobs and options.jobs > 0 else config.parser.jobs
    if jobs <= 0:
        jobs = os.cpu_count() or 1

    return _Effective(
        include=list(options.include) or list(config.discover.include),
        exclude=list(options.exclude) or list(config.discover.exclude),
        use_gitignore=(
            False if options.no_gitignore else config.discover.use_gitignore
        ),
        languages=languages,
        jobs=max(1, jobs),
        timeout_s=options.timeout_s if options.timeout_s is not None else config.parser.timeout_s,
        fail_on=fail_on,
        allow_rules=allow,
        disabled_rules=disabled,
    )


def _analysis_root(path: str) -> tuple[Path, Path, str]:
    """Return ``(root_dir, target, display_root)`` for a file or directory."""

    target = Path(path).expanduser()
    if not target.exists():
        raise IoError(f"path not found: {target}")
    resolved = target.resolve()
    root_dir = resolved if resolved.is_dir() else resolved.parent

    try:
        relative = root_dir.relative_to(Path.cwd().resolve()).as_posix()
        display = relative or "."
    except ValueError:
        display = root_dir.as_posix()
    return root_dir, resolved, display


def _read_sources(
    files: list[SourceFile],
) -> tuple[dict[str, str], list[AnalysisError]]:
    """Read all file contents, converting failures into per-file errors."""

    sources: dict[str, str] = {}
    errors: list[AnalysisError] = []
    for file in files:
        try:
            raw = file.absolute.read_bytes()
        except OSError as exc:
            errors.append(AnalysisError(path=file.path, message=str(exc), kind="io"))
            continue
        try:
            sources[file.path] = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            errors.append(
                AnalysisError(
                    path=file.path,
                    message=f"invalid UTF-8: {exc}",
                    kind="parse",
                )
            )
    return sources, errors


def _parse(
    parser: ParserPort,
    files: list[SourceFile],
    sources: dict[str, str],
    cache: FactCache,
) -> tuple[list[ParsedFile], list[AnalysisError]]:
    """Parse uncached files in one bridge call and merge cached facts."""

    languages = {file.path: file.language for file in files}
    parsed: dict[str, ParsedFile] = {}
    to_parse: list[ParserFile] = []

    for path, content in sources.items():
        language = languages[path]
        cached = cache.get(path, language, content)
        if cached is not None:
            parsed[path] = ParsedFile(
                path=path, language=language, facts=cached, source=content
            )
            continue
        to_parse.append(ParserFile(path=path, language=language, content=content))  # type: ignore[arg-type]

    errors: list[AnalysisError] = []
    if to_parse:
        outcome = parser.parse(to_parse)
        errors.extend(outcome.errors)
        for item in outcome.files:
            parsed[item.path] = item
            source_text = sources.get(item.path)
            if source_text is not None:
                cache.put(item.path, languages[item.path], source_text, item.facts)

    # Preserve discovery order for deterministic rule execution.
    ordered = [parsed[file.path] for file in files if file.path in parsed]
    return ordered, errors


def _load_baseline(path: Path) -> set[str]:
    if not path.is_file():
        raise IoError(f"baseline not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UsageError(f"invalid baseline {path}: {exc}") from exc

    if isinstance(payload, dict) and isinstance(payload.get("fingerprints"), list):
        return {str(item) for item in payload["fingerprints"] if isinstance(item, str)}
    if isinstance(payload, dict) and isinstance(payload.get("findings"), list):
        return {
            str(item["fingerprint"])
            for item in payload["findings"]
            if isinstance(item, dict) and "fingerprint" in item
        }
    raise UsageError(f"invalid baseline {path}: expected findings[] or fingerprints[]")


def _write_baseline(path: Path, fingerprints: set[str]) -> None:
    from .ci.artifacts import write_artifact

    payload = {
        "schema_version": 1,
        "fingerprints": sorted(fingerprints),
    }
    write_artifact(
        path,
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )


def _parser_error_findings(errors: list[AnalysisError]) -> list[Finding]:
    """Per-file parse failures are also info findings (spec §1.3)."""

    findings: list[Finding] = []
    for error in errors:
        if error.kind != "parse":
            continue
        findings.append(
            Finding(
                rule_id="parser.error",
                severity=Severity.INFO,
                message=f"Parser error: {error.message}",
                path=error.path,
                start_line=1,
                start_col=1,
                end_line=1,
                end_col=2,
                fingerprint=fingerprint("parser.error", error.path, 1, "parse"),
                help_uri=None,
            )
        )
    return findings


def _dedupe(findings: list[Finding]) -> list[Finding]:
    unique: dict[str, Finding] = {}
    for finding in findings:
        unique.setdefault(finding.fingerprint, finding)
    return list(unique.values())


def run_analyze(
    options: AnalyzeOptions,
    *,
    config: Config | None = None,
    parser: ParserPort | None = None,
) -> AnalysisResult:
    """Execute the full analysis pipeline and return the contract model."""

    if options.update_baseline and not options.baseline:
        raise UsageError("--update-baseline requires --baseline PATH")

    config_path = Path(options.config_path) if options.config_path else None
    if config is None:
        config, _ = load_config(config_path)
    effective = _effective(options, config)

    root_dir, target, display_root = _analysis_root(options.path)

    explicit = read_stdin_files() if options.stdin_files else ()
    discover_options = DiscoverOptions(
        include=tuple(effective.include),
        exclude=tuple(effective.exclude),
        use_gitignore=effective.use_gitignore,
        languages=tuple(effective.languages),
        explicit_files=tuple(explicit),
    )
    try:
        files = discover_files(target, discover_options)
    except FileNotFoundError as exc:
        raise IoError(f"path not found: {exc}") from exc
    LOGGER.info("discovered %d file(s) under %s", len(files), display_root)

    sources, read_errors = _read_sources(files)

    active_parser = parser or create_parser(
        options.parser_bin,
        timeout_s=effective.timeout_s,
        jobs=effective.jobs,
    )
    parser_used_version = str(getattr(active_parser, "parser_version", parser_version()))

    cache_dir = Path(options.cache_dir).expanduser()
    cache = FactCache(
        cache_dir,
        parser_version=parser_used_version,
        enabled=not options.no_cache,
    )
    parsed_files, parse_errors = _parse(active_parser, files, sources, cache)
    errors = _dedupe_errors(read_errors + parse_errors)

    context = RuleContext(config=config, root=display_root)
    findings: list[Finding] = []
    try:
        engine = SecurityEngine(
            context,
            allow=effective.allow_rules,
            disabled=effective.disabled_rules,
        )
        engine_result = engine.run(parsed_files)
        findings.extend(engine_result.findings)
        errors.extend(engine_result.errors)
        findings.extend(
            complexity_findings(
                parsed_files,
                config,
                allow=effective.allow_rules,
                disabled=effective.disabled_rules,
            )
        )
    except Exception as exc:  # pragma: no cover - defensive boundary
        LOGGER.debug("analysis engine failed: %s", exc)
        errors.append(AnalysisError(path=".", message=str(exc), kind="internal"))

    findings.extend(_parser_error_findings(errors))
    apply_severity_overrides(findings, context)
    findings = sort_findings(_dedupe(findings))

    if options.baseline:
        baseline_path = Path(options.baseline).expanduser()
        if options.update_baseline and not baseline_path.is_file():
            known: set[str] = set()
        else:
            known = _load_baseline(baseline_path)
        if options.update_baseline:
            # Union keeps accepted old fingerprints from churning on every run.
            _write_baseline(
                baseline_path,
                known | {finding.fingerprint for finding in findings},
            )
        findings = [finding for finding in findings if finding.fingerprint not in known]

    summary = build_summary(findings, len(files), config, effective.fail_on)

    if options.max_findings and options.max_findings > 0 and len(findings) > options.max_findings:
        summary.truncated = True
        listed = findings[: options.max_findings]
    else:
        listed = findings

    return AnalysisResult(
        schema_version=SCHEMA_VERSION,
        tool=ToolInfo(
            version=TOOL_VERSION,
            parser_version=str(parser_used_version),
        ),
        generated_at=utc_now_iso(options.clock),
        root=display_root,
        summary=summary,
        findings=listed,
        errors=_dedupe_errors(errors),
    )


def _dedupe_errors(errors: list[AnalysisError]) -> list[AnalysisError]:
    unique: dict[tuple[str, str, str], AnalysisError] = {}
    for error in errors:
        unique.setdefault((error.path, error.kind, error.message), error)
    return [unique[key] for key in sorted(unique)]


__all__ = ["AnalyzeOptions", "run_analyze"]
