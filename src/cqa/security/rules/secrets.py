"""Secret detection rules: hardcoded credentials and cloud keys."""

from __future__ import annotations

import math
import re

from ...models import Finding, ParsedFile, Severity
from ..engine import RuleContext, make_finding

# Keywords that make an assignment a likely credential.
ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|apikey|secret|client[_-]?secret|access[_-]?token|auth[_-]?token|"
    r"token|passwd|password|pwd|credential|private[_-]?key)\b\s*[:=]"
)

# Provider-specific prefixes catch values that are not assigned nearby.
TOKEN_PREFIX_RE = re.compile(
    r"(?:AKIA|ASIA)[0-9A-Z]{16}|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"sk-[A-Za-z0-9]{20,}|"
    r"AIza[0-9A-Za-z_-]{35}"
)

AWS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
AWS_SECRET_RE = re.compile(
    r"(?i)aws_?secret_?access_?key\b\s*[:=]\s*[\"']?([A-Za-z0-9/+=]{40})"
)

# Values that are obviously placeholders or test data.
PLACEHOLDER_RE = re.compile(
    r"(?i)^(?:changeme|change_me|example|sample|dummy|placeholder|your[_-]|xxx+|"
    r"password|secret|token|test|foobar|redacted|null|none|todo)"
)

SHORT_VALUE = 8


def shannon_entropy(value: str) -> float:
    """Return Shannon entropy in bits per character."""

    if not value:
        return 0.0
    counts = {char: value.count(char) for char in set(value)}
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def looks_like_placeholder(value: str) -> bool:
    return bool(PLACEHOLDER_RE.search(value.strip())) or value.strip() in {"", "..."}


class HardcodedSecretRule:
    id = "secrets.hardcoded"
    severity = Severity.CRITICAL
    title = "Hardcoded credential"
    description = "A string literal near a credential keyword has high entropy or a token shape."
    help_uri = "https://cqa.local/rules/secrets.hardcoded"

    def check(self, file: ParsedFile, ctx: RuleContext) -> list[Finding]:
        findings: list[Finding] = []
        for literal in file.facts.literals:
            value = literal.value.strip()
            if len(value) < SHORT_VALUE or looks_like_placeholder(value):
                continue
            # Cloud key rules own their own, more specific findings.
            if AWS_KEY_RE.search(value):
                continue

            line_text = file.line_text(literal.line)
            has_assignment = bool(ASSIGNMENT_RE.search(line_text))
            has_prefix = bool(TOKEN_PREFIX_RE.search(value))
            high_entropy = len(value) >= 16 and shannon_entropy(value) >= 3.5

            if not (has_prefix or (has_assignment and high_entropy)):
                continue

            pattern = "assignment" if has_assignment and not has_prefix else "token-prefix"
            findings.append(
                make_finding(
                    rule_id=self.id,
                    severity=ctx.severity_for(self.id, self.severity),
                    message="Possible hardcoded credential in source code",
                    file=file,
                    line=literal.line,
                    col=literal.col,
                    pattern=pattern,
                    snippet=line_text.strip(),
                    help_uri=self.help_uri,
                )
            )
        return findings


class AwsKeyRule:
    id = "secrets.aws_key"
    severity = Severity.CRITICAL
    title = "AWS access key"
    description = "Detects AWS access key ids and secret access key assignments."
    help_uri = "https://cqa.local/rules/secrets.aws_key"

    def check(self, file: ParsedFile, ctx: RuleContext) -> list[Finding]:
        findings: list[Finding] = []
        seen: set[tuple[int, str]] = set()

        for literal in file.facts.literals:
            match = AWS_KEY_RE.search(literal.value)
            if match:
                seen.add((literal.line, "key-id"))
                findings.append(
                    make_finding(
                        rule_id=self.id,
                        severity=ctx.severity_for(self.id, self.severity),
                        message="AWS access key id committed to source",
                        file=file,
                        line=literal.line,
                        col=literal.col,
                        pattern="access-key-id",
                        snippet=file.line_text(literal.line).strip(),
                        help_uri=self.help_uri,
                    )
                )

        if file.source:
            for offset, text in enumerate(file.source.splitlines(), start=1):
                match = AWS_SECRET_RE.search(text)
                if match and (offset, "secret") not in seen:
                    seen.add((offset, "secret"))
                    findings.append(
                        make_finding(
                            rule_id=self.id,
                            severity=ctx.severity_for(self.id, self.severity),
                            message="AWS secret access key committed to source",
                            file=file,
                            line=offset,
                            col=match.start(1) + 1,
                            pattern="secret-access-key",
                            snippet=text.strip(),
                            help_uri=self.help_uri,
                        )
                    )
        return findings


SECRET_RULES = [HardcodedSecretRule(), AwsKeyRule()]
