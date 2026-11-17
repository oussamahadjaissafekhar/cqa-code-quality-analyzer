"""Security rule engine.

Parsers emit facts; rules turn facts into findings. Rules are pure with respect
to the filesystem: all source needed for a decision arrives in :class:`ParsedFile`
(parsers are asked to include content in the bridge request). Failures inside a
single rule/file pair are isolated and surfaced as ``errors[]`` entries.

Adding a rule:
1. create a module under ``cqa/security/rules/``;
2. export instances from ``builtin_rules()``;
3. add a pytest fixture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, cast

from ..config import Config
from ..logging import get_logger
from ..models import (
    AnalysisError,
    Finding,
    ParsedFile,
    Severity,
    fingerprint,
)
from .severity import is_at_or_above

LOGGER = get_logger("security")

HELP_BASE = "https://cqa.local/rules"
MAX_SNIPPET = 4096


@dataclass
class RuleContext:
    """Read-only information rules may use besides the file facts."""

    config: Config
    root: str = "."

    def severity_for(self, rule_id: str, default: Severity) -> Severity:
        override = self.config.rules.overrides.get(rule_id)
        return override.severity if override and override.severity else default

    def enabled_for(self, rule_id: str, disabled: set[str] | None = None) -> bool:
        override = self.config.rules.overrides.get(rule_id)
        if override and override.enabled is False:
            return False
        if rule_id in self.config.rules.disable:
            return False
        return not (disabled and rule_id in disabled)


class Rule(Protocol):
    """Structural protocol for a rule (spec §5.2)."""

    id: str
    severity: Severity
    title: str
    description: str
    help_uri: str

    def check(self, file: ParsedFile, ctx: RuleContext) -> list[Finding]: ...


@dataclass
class EngineResult:
    findings: list[Finding] = field(default_factory=list)
    errors: list[AnalysisError] = field(default_factory=list)


def make_finding(
    *,
    rule_id: str,
    severity: Severity,
    message: str,
    file: ParsedFile,
    line: int,
    col: int,
    pattern: str,
    snippet: str | None = None,
    help_uri: str | None = None,
    end_line: int | None = None,
    end_col: int | None = None,
) -> Finding:
    """Build a finding with a bounded snippet and secret-free fingerprint."""

    bounded = (snippet or "")[:MAX_SNIPPET] or None
    return Finding(
        rule_id=rule_id,
        severity=severity,
        message=message,
        path=file.path,
        start_line=max(1, line),
        start_col=max(1, col),
        end_line=max(1, end_line or line),
        end_col=max(1, end_col or col + 1),
        fingerprint=fingerprint(rule_id, file.path, max(1, line), pattern),
        snippet=bounded,
        help_uri=help_uri or f"{HELP_BASE}/{rule_id}",
    )


def _builtin_rule_instances() -> list[Rule]:
    # Imported lazily to keep rule modules free to import engine helpers.
    from .rules.dangerous_calls import DANGEROUS_RULES
    from .rules.injection import INJECTION_RULES
    from .rules.secrets import SECRET_RULES

    # The concrete rule classes differ per pack, so normalize the join explicitly.
    return cast(list[Rule], [*SECRET_RULES, *INJECTION_RULES, *DANGEROUS_RULES])


class SecurityEngine:
    """Runs enabled rules over parsed files and isolates failures."""

    def __init__(
        self,
        context: RuleContext,
        rules: list[Rule] | None = None,
        allow: set[str] | None = None,
        disabled: set[str] | None = None,
    ) -> None:
        candidates = rules if rules is not None else _builtin_rule_instances()
        self.context = context
        self.rules = [
            rule
            for rule in candidates
            if context.enabled_for(rule.id, disabled)
            and (allow is None or rule.id in allow)
        ]

    def run(self, files: list[ParsedFile]) -> EngineResult:
        result = EngineResult()
        for file in files:
            for rule in self.rules:
                try:
                    result.findings.extend(rule.check(file, self.context))
                except Exception as exc:  # a single rule must never abort the run
                    LOGGER.debug("rule %s failed on %s: %s", rule.id, file.path, exc)
                    result.errors.append(
                        AnalysisError(
                            path=file.path,
                            message=f"rule {rule.id} failed: {exc}",
                            kind="internal",
                        )
                    )
        return result


def apply_severity_overrides(findings: list[Finding], ctx: RuleContext) -> list[Finding]:
    """Apply configured severity overrides after rule execution.

    Rules emit their default severity; overrides are policy, not parsing logic.
    """

    for finding in findings:
        override = ctx.config.rules.overrides.get(finding.rule_id)
        if override and override.severity:
            finding.severity = override.severity
    return findings


__all__ = [
    "EngineResult",
    "Rule",
    "RuleContext",
    "SecurityEngine",
    "apply_severity_overrides",
    "is_at_or_above",
    "make_finding",
]
