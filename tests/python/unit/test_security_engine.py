from __future__ import annotations

from cqa.config import Config, RuleOverride, RulesConfig
from cqa.models import ParsedFile, ParserFile, Severity
from cqa.parsers.fallback_python import FallbackParser
from cqa.quality.metrics import complexity_findings
from cqa.security.engine import RuleContext, SecurityEngine
from cqa.security.severity import is_at_or_above


def parsed(source: str, path: str = "app.py") -> ParsedFile:
    outcome = FallbackParser().parse(
        [ParserFile(path=path, language="python", content=source)]
    )
    assert outcome.files
    return outcome.files[0]


def findings_for(source: str, path: str = "app.py", config: Config | None = None):
    file = parsed(source, path)
    ctx = RuleContext(config=config or Config(schema_version=1))
    return SecurityEngine(ctx).run([file])


def test_eval_rule_emits_high_with_fingerprint() -> None:
    result = findings_for("def f(user):\n    return eval(user)\n")
    rule_ids = [finding.rule_id for finding in result.findings]
    assert "sec.eval" in rule_ids
    finding = next(item for item in result.findings if item.rule_id == "sec.eval")
    assert finding.severity is Severity.HIGH
    assert finding.path == "app.py"
    assert finding.start_line == 2
    assert finding.fingerprint.startswith("cqa:v1:")
    assert len(finding.fingerprint) == len("cqa:v1:") + 16


def test_hardcoded_secret_and_aws_key() -> None:
    source = (
        'API_KEY = "sk-live-1234567890abcdef"\n'
        'AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"\n'
    )
    result = findings_for(source)
    rule_ids = [finding.rule_id for finding in result.findings]
    assert "secrets.hardcoded" in rule_ids
    assert "secrets.aws_key" in rule_ids
    secret = next(item for item in result.findings if item.rule_id == "secrets.hardcoded")
    # Fingerprints must never contain secret material.
    assert "1234567890abcdef" not in secret.fingerprint


def test_aws_key_is_not_duplicated_as_generic_secret() -> None:
    result = findings_for('AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"\n')
    rule_ids = [finding.rule_id for finding in result.findings]
    assert rule_ids.count("secrets.aws_key") == 1
    assert "secrets.hardcoded" not in rule_ids


def test_yaml_unsafe_and_safe_loader() -> None:
    unsafe = findings_for("import yaml\nyaml.load(raw)\n")
    assert any(finding.rule_id == "sec.yaml_unsafe" for finding in unsafe.findings)

    safe = findings_for("import yaml\nyaml.load(raw, Loader=yaml.SafeLoader)\n")
    assert not any(finding.rule_id == "sec.yaml_unsafe" for finding in safe.findings)


def test_sql_concat_requires_dynamic_sql() -> None:
    dynamic = findings_for(
        'def q(conn, name):\n    sql = "SELECT * FROM users WHERE n = " + name\n    return conn.execute(sql)\n'
    )
    assert any(finding.rule_id == "sec.sql_concat" for finding in dynamic.findings)

    static = findings_for('conn.execute("SELECT * FROM users")\n')
    assert not any(finding.rule_id == "sec.sql_concat" for finding in static.findings)


def test_insecure_http_skips_test_paths() -> None:
    source = 'URL = "http://example.com/api"\n'
    prod = findings_for(source, path="src/app.py")
    assert any(finding.rule_id == "sec.insecure_http" for finding in prod.findings)
    test = findings_for(source, path="tests/test_app.py")
    assert not any(finding.rule_id == "sec.insecure_http" for finding in test.findings)


def test_severity_override_and_disable() -> None:
    config = Config(
        schema_version=1,
        rules=RulesConfig(
            disable=["sec.eval"],
            overrides={"secrets.hardcoded": RuleOverride(severity=Severity.LOW)},
        ),
    )
    source = 'API_KEY = "sk-live-1234567890abcdef"\neval(user)\n'
    result = findings_for(source, config=config)
    rule_ids = [finding.rule_id for finding in result.findings]
    assert "secrets.hardcoded" in rule_ids
    assert "sec.eval" not in rule_ids
    secret = next(item for item in result.findings if item.rule_id == "secrets.hardcoded")
    assert secret.severity is Severity.LOW


def test_allow_list_limits_rules() -> None:
    file = parsed("eval(user)\n")
    ctx = RuleContext(config=Config(schema_version=1))
    result = SecurityEngine(ctx, allow={"sec.eval"}).run([file])
    assert {finding.rule_id for finding in result.findings} == {"sec.eval"}


def test_complexity_rule_thresholds() -> None:
    body = "\n".join(f"    if value < {index}:\n        return {index}" for index in range(12))
    source = f"def complex_fn(value):\n{body}\n    return 99\n"
    file = parsed(source)
    complexity = complexity_findings([file], Config(schema_version=1))
    assert len(complexity) == 1
    assert complexity[0].rule_id == "quality.complexity"
    assert complexity[0].severity in {Severity.LOW, Severity.MEDIUM}


def test_rule_failure_is_isolated() -> None:
    class Exploding:
        id = "test.explode"
        severity = Severity.HIGH
        title = "explode"
        description = "always fails"
        help_uri = "https://example.invalid"

        def check(self, file, ctx):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    file = parsed("x = 1\n")
    ctx = RuleContext(config=Config(schema_version=1))
    result = SecurityEngine(ctx, rules=[Exploding()]).run([file])
    assert result.findings == []
    assert len(result.errors) == 1
    assert result.errors[0].kind == "internal"
    assert "boom" in result.errors[0].message


def test_threshold_helpers() -> None:
    assert is_at_or_above(Severity.CRITICAL, "high") is True
    assert is_at_or_above(Severity.MEDIUM, "high") is False
    assert is_at_or_above(Severity.CRITICAL, "never") is False
