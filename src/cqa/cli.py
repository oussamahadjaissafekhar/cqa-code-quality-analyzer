"""Click CLI: a thin adapter over :func:`cqa.app.run_analyze`.

Responsibilities kept here on purpose:
* argument parsing and environment-variable precedence
* report destination handling (stdout vs file vs CI artifacts)
* mapping the analysis result to documented exit codes

No rule logic, parsing, or scoring lives in this module.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import click

from .app import AnalyzeOptions, run_analyze
from .ci.artifacts import write_artifact
from .ci.github import append_step_summary, detect_github, resolve_workspace_path
from .config import FORMAT_VALUES, default_toml, load_config
from .exit_codes import CqaError, ExitCode, UsageError
from .logging import configure_logging
from .models import AnalysisResult
from .report import render_markdown, render_result, render_sarif
from .security.rules import QUALITY_RULE_META, security_rules
from .version import SCHEMA_VERSION, TOOL_VERSION, parser_version, version_info

RULES_FORMATS = ("json", "table")


def _version_callback(ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    click.echo(f"cqa {TOOL_VERSION}")
    ctx.exit()


@click.group(
    context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 100},
    no_args_is_help=True,
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=str),
    envvar="CQA_CONFIG",
    help="Config file (default: cqa.toml, .cqa.toml, or pyproject.toml [tool.cqa]).",
)
@click.option("-v", "--verbose", count=True, help="Increase log verbosity (stderr).")
@click.option("-q", "--quiet", is_flag=True, help="Only errors on stderr.")
@click.option(
    "--no-color",
    "no_color",
    is_flag=True,
    envvar="CQA_NO_COLOR",
    help="Disable ANSI color (also implied by NO_COLOR / non-TTY).",
)
@click.option(
    "--version",
    "show_version",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_version_callback,
    help="Print version and exit 0.",
)
@click.pass_context
def cli(
    ctx: click.Context,
    config_path: str | None,
    verbose: int,
    quiet: bool,
    no_color: bool,
) -> None:
    """Code Quality Analyzer: static quality, security heuristics, CI reports."""

    configure_logging(verbosity=verbose, quiet=quiet)
    ctx.ensure_object(dict)
    ctx.obj.update(
        {
            "config_path": config_path,
            "verbose": verbose,
            "quiet": quiet,
            "no_color": no_color or bool(sys.stderr.isatty() is False),
        }
    )


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("path", default=".", type=str)
@click.option("--include", "include", multiple=True, help="Include glob (repeatable).")
@click.option("--exclude", "exclude", multiple=True, help="Exclude glob (repeatable).")
@click.option("--no-gitignore", is_flag=True, default=None, help="Do not apply .gitignore.")
@click.option(
    "--languages",
    "languages",
    default=None,
    help="Comma-separated languages (python,typescript,javascript).",
)
@click.option("--rules", "rules", default=None, help="Comma-separated rule-id allow-list.")
@click.option(
    "--disable-rule", "disable_rule", multiple=True, help="Disable a rule (repeatable)."
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(FORMAT_VALUES),
    default=None,
    envvar="CQA_FORMAT",
    help="Report format (default: json).",
)
@click.option(
    "-o",
    "--output",
    default="-",
    show_default=True,
    help="Write report to PATH ('-' = stdout).",
)
@click.option("--sarif", "sarif", type=click.Path(dir_okay=False), default=None, help="Extra SARIF file.")
@click.option(
    "--fail-on",
    "fail_on",
    type=click.Choice(("critical", "high", "medium", "low", "info", "never")),
    default=None,
    envvar="CQA_FAIL_ON",
    help="Fail when findings reach this severity (default: high).",
)
@click.option("--max-findings", type=click.IntRange(min=0), default=0, show_default=True)
@click.option("--baseline", type=click.Path(dir_okay=False), default=None)
@click.option("--update-baseline", is_flag=True, help="Write accepted fingerprints to baseline.")
@click.option("--cache-dir", type=click.Path(file_okay=False), default=".cqa-cache", show_default=True)
@click.option("--no-cache", is_flag=True, help="Disable the parser fact cache.")
@click.option(
    "-j",
    "--jobs",
    type=click.IntRange(min=0),
    default=None,
    help="Worker count (0 = auto).",
)
@click.option("--timeout-s", type=click.IntRange(min=1), default=None, help="Parser timeout.")
@click.option(
    "--parser-bin",
    type=click.Path(dir_okay=False),
    default=None,
    envvar="CQA_PARSER_BIN",
    help="Override the Node parser entrypoint.",
)
@click.option(
    "--stdin-files",
    is_flag=True,
    help="Read NUL-separated paths from stdin (CI incremental mode).",
)
@click.pass_context
def analyze(
    ctx: click.Context,
    path: str,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    no_gitignore: bool | None,
    languages: str | None,
    rules: str | None,
    disable_rule: tuple[str, ...],
    fmt: str | None,
    output: str,
    sarif: str | None,
    fail_on: str | None,
    max_findings: int,
    baseline: str | None,
    update_baseline: bool,
    cache_dir: str,
    no_cache: bool,
    jobs: int | None,
    timeout_s: int | None,
    parser_bin: str | None,
    stdin_files: bool,
) -> int:
    """Analyze PATH (file or directory) and emit a report."""

    config_path = ctx.obj.get("config_path")
    config, _source = load_config(Path(config_path) if config_path else None)

    # CLI/env (Click) > config > defaults. Click resolves env into the argument.
    effective_format = fmt or (config.report.formats[0] if config.report.formats else "json")
    effective_sarif = sarif
    if effective_sarif is None and config.report.sarif and effective_format != "sarif":
        effective_sarif = "cqa.sarif"

    options = AnalyzeOptions(
        path=path,
        config_path=config_path,
        include=tuple(include),
        exclude=tuple(exclude),
        no_gitignore=bool(no_gitignore),
        languages=languages,
        rules=rules,
        disable_rules=tuple(disable_rule),
        format=effective_format,
        output=output,
        sarif=effective_sarif,
        fail_on=fail_on,
        max_findings=max_findings,
        baseline=baseline,
        update_baseline=update_baseline,
        cache_dir=cache_dir,
        no_cache=no_cache,
        jobs=jobs,
        timeout_s=timeout_s,
        parser_bin=parser_bin,
        stdin_files=stdin_files,
        verbose=int(ctx.obj.get("verbose", 0)),
    )

    result = run_analyze(options, config=config)
    _emit_reports(result, options, verbose=int(ctx.obj.get("verbose", 0)))
    return int(ExitCode.FINDINGS if result.summary.failed else ExitCode.OK)


def _emit_reports(result: AnalysisResult, options: AnalyzeOptions, *, verbose: int) -> None:
    """Render the selected format, plus the optional SARIF/step-summary side channels."""

    fmt = options.format
    github = detect_github()

    # Spec §4.4: table is TTY-only; otherwise fall back to JSON with a warning.
    if fmt == "table" and options.output == "-" and not sys.stdout.isatty():
        click.echo("cqa: warning: table format requires a TTY; falling back to JSON", err=True)
        fmt = "json"

    text = render_result(result, fmt, pretty=bool(verbose) and fmt == "json")

    output_path = options.output
    if output_path != "-":
        target = resolve_workspace_path(Path(output_path), github)
        write_artifact(target, text)
    else:
        click.echo(text, nl=False)

    if options.sarif:
        sarif_target = resolve_workspace_path(Path(options.sarif), github)
        write_artifact(sarif_target, render_sarif(result))

    if github.actions and fmt not in {"json", "github"} and options.output != "-":
        # Workflow commands must go to stdout; only safe when the report is a file.
        click.echo(render_result(result, "github"), nl=False)

    if github.actions and github.step_summary is not None:
        append_step_summary(render_markdown(result), github)


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------


@cli.command("rules")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(RULES_FORMATS),
    default="table",
    show_default=True,
)
@click.pass_context
def rules_command(ctx: click.Context, fmt: str) -> int:
    """List rule IDs, effective severity, and help."""

    config_path = ctx.obj.get("config_path")
    config, _source = load_config(Path(config_path) if config_path else None)

    entries: list[dict[str, object]] = []
    for rule in [*security_rules()]:
        override = config.rules.overrides.get(rule.id)
        severity = override.severity.value if override and override.severity else rule.severity.value
        enabled = not (
            rule.id in config.rules.disable or (override and override.enabled is False)
        )
        entries.append(
            {
                "id": rule.id,
                "severity": severity,
                "title": rule.title,
                "description": rule.description,
                "help_uri": rule.help_uri,
                "enabled": enabled,
            }
        )

    quality_id = str(QUALITY_RULE_META["id"])
    quality_severity = QUALITY_RULE_META["severity"]
    quality_override = config.rules.overrides.get(quality_id)
    entries.append(
        {
            "id": quality_id,
            "severity": (
                quality_override.severity.value
                if quality_override and quality_override.severity
                else quality_severity.value
            ),
            "title": QUALITY_RULE_META["title"],
            "description": QUALITY_RULE_META["description"],
            "help_uri": QUALITY_RULE_META["help_uri"],
            "enabled": not (
                quality_id in config.rules.disable
                or (quality_override and quality_override.enabled is False)
            ),
        }
    )
    entries.sort(key=lambda entry: str(entry["id"]))

    if fmt == "json":
        click.echo(
            json.dumps(
                {"schema_version": SCHEMA_VERSION, "rules": entries},
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
        )
        return 0

    headers = ("ID", "SEVERITY", "ENABLED", "TITLE")
    widths = [len(header) for header in headers]
    rows = [
        (str(entry["id"]), str(entry["severity"]), "yes" if entry["enabled"] else "no", str(entry["title"]))
        for entry in entries
    ]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    click.echo("  ".join(header.ljust(widths[i]) for i, header in enumerate(headers)).rstrip())
    click.echo("  ".join("-" * width for width in widths))
    for row in rows:
        click.echo("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    return 0


# ---------------------------------------------------------------------------
# init / version
# ---------------------------------------------------------------------------


@cli.command("init")
@click.option("--force", is_flag=True, help="Overwrite an existing cqa.toml.")
def init_command(force: bool) -> int:
    """Write a starter cqa.toml in the current directory."""

    target = Path.cwd() / "cqa.toml"
    if target.exists() and not force:
        raise UsageError("cqa.toml already exists; pass --force to overwrite")
    write_artifact(target, default_toml())
    click.echo(f"wrote {target}")
    return 0


@cli.command("version")
@click.option("--format", "fmt", type=click.Choice(("json", "table")), default="table")
def version_command(fmt: str) -> int:
    """Print tool, schema, and parser versions."""

    if fmt == "json":
        click.echo(json.dumps(version_info(), indent=2, sort_keys=True))
    else:
        click.echo(
            f"cqa {TOOL_VERSION} (schema v{SCHEMA_VERSION}, parser {parser_version()})"
        )
    return 0


# ---------------------------------------------------------------------------
# Process entrypoint
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and map every failure to a documented exit code."""

    try:
        value = cli.main(
            args=argv,
            prog_name="cqa",
            standalone_mode=False,
        )
        return int(value) if value is not None else int(ExitCode.OK)
    except click.exceptions.Exit as exc:
        return int(exc.exit_code)
    except click.ClickException as exc:
        exc.show(file=sys.stderr)
        return int(exc.exit_code)
    except click.Abort:
        click.echo("cqa: aborted", err=True)
        return int(ExitCode.SIGINT)
    except CqaError as exc:
        click.echo(f"cqa: error: {exc.message}", err=True)
        return int(exc.exit_code)
    except KeyboardInterrupt:
        click.echo("cqa: interrupted", err=True)
        return int(ExitCode.SIGINT)
    except BrokenPipeError:
        return int(ExitCode.OK)
    except Exception as exc:  # noqa: BLE001 - top-level boundary
        if "--verbose" in sys.argv or "-v" in sys.argv:
            traceback.print_exc()
        click.echo(f"cqa: internal error: {exc}", err=True)
        return int(ExitCode.PARSER)


if __name__ == "__main__":
    sys.exit(main())
