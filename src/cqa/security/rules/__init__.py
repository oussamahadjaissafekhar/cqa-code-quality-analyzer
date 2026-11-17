"""Rule pack exports and rule metadata for ``cqa rules``."""

from __future__ import annotations

from typing import TypedDict

from ...models import Severity
from .dangerous_calls import DANGEROUS_RULES
from .injection import INJECTION_RULES
from .secrets import SECRET_RULES


class QualityRuleMeta(TypedDict):
    """Catalogue metadata for rules that do not live in the security engine."""

    id: str
    severity: Severity
    title: str
    description: str
    help_uri: str


def security_rules():
    """Return one instance of every built-in security rule."""

    return [*SECRET_RULES, *INJECTION_RULES, *DANGEROUS_RULES]


# ``quality.complexity`` lives in cqa.quality (metrics, not syntax facts) but is
# part of the public rule catalogue.
QUALITY_RULE_META: QualityRuleMeta = {
    "id": "quality.complexity",
    "severity": Severity.LOW,
    "title": "High cyclomatic complexity",
    "description": "Function complexity exceeds the configured threshold.",
    "help_uri": "https://cqa.local/rules/quality.complexity",
}


__all__ = ["QUALITY_RULE_META", "security_rules"]
