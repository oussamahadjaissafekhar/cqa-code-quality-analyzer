"""Canonical JSON report (``analysis-result.schema.json``).

Byte stability matters for golden tests and baselines: keys are sorted, findings
are sorted by the engine, and compact separators are used unless ``pretty`` is
requested (``--verbose`` locally).
"""

from __future__ import annotations

import json

from ..models import AnalysisResult


def render_json(result: AnalysisResult, *, pretty: bool = False) -> str:
    payload = result.model_dump(mode="json", exclude_none=True)
    if pretty:
        text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    else:
        text = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    return text + "\n"
