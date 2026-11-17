from __future__ import annotations

import json
from pathlib import Path

import pytest

from cqa.report import render_json

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "golden" / "sample.json"


def test_analysis_result_matches_golden(sample_result, update_goldens: bool) -> None:
    payload = json.loads(render_json(sample_result))
    if update_goldens:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    assert GOLDEN.is_file(), "golden file missing; run pytest --update-goldens"
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert payload == expected


def test_validates_against_analysis_result_schema(
    sample_result, repo_root: Path
) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    contracts = repo_root / "contracts"
    schema = json.loads((contracts / "analysis-result.schema.json").read_text(encoding="utf-8"))
    finding_schema = json.loads((contracts / "finding.schema.json").read_text(encoding="utf-8"))

    try:
        from referencing import Registry, Resource

        registry = Registry().with_resources(
            [
                (
                    "https://cqa.local/schemas/finding.schema.json",
                    Resource.from_contents(finding_schema),
                )
            ]
        )
        validator = jsonschema.Draft202012Validator(schema, registry=registry)
    except ImportError:  # pragma: no cover - older jsonschema
        resolver = jsonschema.RefResolver.from_schema(
            schema, store={"finding.schema.json": finding_schema}
        )
        validator = jsonschema.Draft202012Validator(schema, resolver=resolver)

    payload = json.loads(render_json(sample_result))
    validator.validate(payload)


def test_finding_example_validates(repo_root: Path) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(
        (repo_root / "contracts" / "finding.schema.json").read_text(encoding="utf-8")
    )
    payload = json.loads(
        (repo_root / "contracts" / "examples" / "finding.min.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(payload)


def test_parser_contract_examples_validate(repo_root: Path) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    contracts = repo_root / "contracts"
    request_schema = json.loads(
        (contracts / "parser-request.schema.json").read_text(encoding="utf-8")
    )
    request = {
        "schema_version": 1,
        "jobs": 2,
        "files": [
            {"path": "a.py", "language": "python", "content": "x = 1\n"},
        ],
    }
    jsonschema.Draft202012Validator(request_schema).validate(request)
