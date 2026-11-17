"""Dangerous call and unsafe-deserialization rules."""

from __future__ import annotations

import re

from ...models import Finding, ParsedFile, Severity
from ..engine import RuleContext, make_finding

EVAL_NAMES = {"eval", "exec", "Function"}
YAML_LOAD_RE = re.compile(r"(?:^|\.)yaml\.(?:load|unsafe_load)$")
SAFE_LOADER_RE = re.compile(r"(?:CSafe|Safe|Full)Loader|safe_load")


class EvalRule:
    id = "sec.eval"
    severity = Severity.HIGH
    title = "Dynamic code execution"
    description = "eval/exec/Function execute attacker-influenced strings as code."
    help_uri = "https://cqa.local/rules/sec.eval"

    def check(self, file: ParsedFile, ctx: RuleContext) -> list[Finding]:
        findings: list[Finding] = []
        for call in file.facts.calls:
            if call.callee not in EVAL_NAMES:
                continue
            findings.append(
                make_finding(
                    rule_id=self.id,
                    severity=ctx.severity_for(self.id, self.severity),
                    message=f"Use of {call.callee}() is unsafe",
                    file=file,
                    line=call.line,
                    col=call.col,
                    pattern=call.callee,
                    snippet=file.line_text(call.line).strip(),
                    help_uri=self.help_uri,
                )
            )
        return findings


class YamlUnsafeRule:
    id = "sec.yaml_unsafe"
    severity = Severity.HIGH
    title = "Unsafe YAML deserialization"
    description = "yaml.load without SafeLoader can construct arbitrary Python objects."
    help_uri = "https://cqa.local/rules/sec.yaml_unsafe"

    def check(self, file: ParsedFile, ctx: RuleContext) -> list[Finding]:
        findings: list[Finding] = []
        lines = file.source.splitlines() if file.source else []
        for call in file.facts.calls:
            if not YAML_LOAD_RE.search(call.callee):
                continue
            # SafeLoader is frequently passed on a following line.
            window = "\n".join(lines[max(0, call.line - 1) : call.line + 3])
            if SAFE_LOADER_RE.search(window):
                continue
            findings.append(
                make_finding(
                    rule_id=self.id,
                    severity=ctx.severity_for(self.id, self.severity),
                    message="yaml.load() used without SafeLoader",
                    file=file,
                    line=call.line,
                    col=call.col,
                    pattern="yaml.load",
                    snippet=file.line_text(call.line).strip(),
                    help_uri=self.help_uri,
                )
            )
        return findings


DANGEROUS_RULES = [EvalRule(), YamlUnsafeRule()]
