"""Injection heuristics: command execution, SQL concatenation, cleartext HTTP."""

from __future__ import annotations

import re

from ...models import Finding, ParsedFile, Severity
from ..engine import RuleContext, make_finding

CHILD_PROCESS_RE = re.compile(
    r"(?:^|\.)child_process\.(?:exec|execSync|spawn|spawnSync|execFile|execFileSync)$"
)
SHELL_IMPORT_RE = re.compile(r"^(?:node:)?child_process$")

SQL_CALL_RE = re.compile(r"(?:^|\.)(?:execute|executemany|query|raw|prepare)$")
SQL_KEYWORD_RE = re.compile(r"(?i)\b(select|insert|update|delete|replace|where|from|join)\b")

HTTP_RE = re.compile(r"^http://", re.IGNORECASE)
TEST_PATH_RE = re.compile(
    r"(?i)(?:^|/)(?:tests?|__tests__|spec|specs|fixtures?)(?:/|$)|"
    r"(?:\.test\.|\.spec\.|_test\.|^test_)"
)


def is_test_path(path: str) -> bool:
    """Test paths may intentionally contain weak URLs and credentials."""

    return bool(TEST_PATH_RE.search(path))


class ChildProcessRule:
    id = "sec.child_process"
    severity = Severity.HIGH
    title = "Dynamic command execution"
    description = "child_process execution with non-literal arguments can permit command injection."
    help_uri = "https://cqa.local/rules/sec.child_process"

    def check(self, file: ParsedFile, ctx: RuleContext) -> list[Finding]:
        imports_shell = any(SHELL_IMPORT_RE.match(item.from_) for item in file.facts.imports)
        findings: list[Finding] = []
        for call in file.facts.calls:
            direct = bool(CHILD_PROCESS_RE.search(call.callee))
            imported = imports_shell and call.callee.split(".")[-1] in {
                "exec",
                "execSync",
                "spawn",
                "spawnSync",
                "execFile",
                "execFileSync",
            }
            if not (direct or imported):
                continue
            if call.args_kind in {"literal", "empty"}:
                continue
            findings.append(
                make_finding(
                    rule_id=self.id,
                    severity=ctx.severity_for(self.id, self.severity),
                    message=f"Dynamic argument passed to {call.callee}()",
                    file=file,
                    line=call.line,
                    col=call.col,
                    pattern=call.callee,
                    snippet=file.line_text(call.line).strip(),
                    help_uri=self.help_uri,
                )
            )
        return findings


class SqlConcatRule:
    id = "sec.sql_concat"
    severity = Severity.HIGH
    title = "SQL built from dynamic input"
    description = "A SQL execution API receives a non-literal argument; parameterize queries instead."
    help_uri = "https://cqa.local/rules/sec.sql_concat"

    def check(self, file: ParsedFile, ctx: RuleContext) -> list[Finding]:
        findings: list[Finding] = []
        lines = file.source.splitlines() if file.source else []
        for call in file.facts.calls:
            if not SQL_CALL_RE.search(call.callee):
                continue
            if call.args_kind in {"literal", "empty"}:
                continue
            # Look around the call: SQL is often split across a multi-line
            # concatenation or assigned on the previous line.
            window = "\n".join(lines[max(0, call.line - 3) : call.line + 2])
            if not SQL_KEYWORD_RE.search(window):
                continue
            findings.append(
                make_finding(
                    rule_id=self.id,
                    severity=ctx.severity_for(self.id, self.severity),
                    message=f"SQL query built dynamically and passed to {call.callee}()",
                    file=file,
                    line=call.line,
                    col=call.col,
                    pattern="dynamic-sql",
                    snippet=file.line_text(call.line).strip(),
                    help_uri=self.help_uri,
                )
            )
        return findings


class InsecureHttpRule:
    id = "sec.insecure_http"
    severity = Severity.MEDIUM
    title = "Cleartext HTTP URL"
    description = "Literal http:// URL in non-test code; prefer HTTPS."
    help_uri = "https://cqa.local/rules/sec.insecure_http"

    def check(self, file: ParsedFile, ctx: RuleContext) -> list[Finding]:
        if is_test_path(file.path):
            return []
        findings: list[Finding] = []
        for literal in file.facts.literals:
            if not HTTP_RE.match(literal.value.strip()):
                continue
            findings.append(
                make_finding(
                    rule_id=self.id,
                    severity=ctx.severity_for(self.id, self.severity),
                    message="Cleartext HTTP URL in source code",
                    file=file,
                    line=literal.line,
                    col=literal.col,
                    pattern="http-url",
                    snippet=file.line_text(literal.line).strip(),
                    help_uri=self.help_uri,
                )
            )
        return findings


INJECTION_RULES = [ChildProcessRule(), SqlConcatRule(), InsecureHttpRule()]
