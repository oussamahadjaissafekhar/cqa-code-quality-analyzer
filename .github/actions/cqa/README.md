# CQA composite action

Runs `cqa analyze` inside the CQA container and publishes the machine-readable
results. The action never reimplements analysis; it only invokes the CLI and
maps its exit codes.

## Inputs

| Input | Required | Default | Maps to |
| --- | --- | --- | --- |
| `path` | no | `.` | `analyze PATH` |
| `config` | no | `""` | `--config` when set |
| `fail-on` | no | `high` | `--fail-on` |
| `format` | no | `github` | console `--format` |
| `sarif` | no | `true` | `--sarif cqa.sarif` |
| `upload-sarif` | no | `true` | `github/codeql-action/upload-sarif` |
| `baseline` | no | `""` | `--baseline` when set |
| `image` | no | `cqa:local` | container image to run |
| `extra-args` | no | `""` | appended to `cqa analyze` |

## Outputs

| Output | Source |
| --- | --- |
| `json-path` | `cqa-results.json` |
| `sarif-path` | `cqa.sarif` |
| `score` | `summary.score` |
| `failed` | `true` when the CLI returned exit code 1 |
| `finding-count` | `summary.findings` |

## Exit-code mapping

| CLI exit | Action behavior |
| --- | --- |
| `0` | success |
| `1` | success step, `failed=true` output (the calling workflow decides) |
| `2–5` | step fails with “cqa infrastructure error” |

If you want exit code 1 to fail the job, add a final step:

```yaml
- if: steps.cqa.outputs.failed == 'true'
  run: exit 1
```

## Example

```yaml
permissions:
  contents: read
  security-events: write

steps:
  - uses: actions/checkout@v4

  - name: Build CQA image
    run: docker build -f Dockerfile -t cqa:local .

  - id: cqa
    uses: ./.github/actions/cqa
    with:
      fail-on: high
      upload-sarif: true

  - name: Enforce quality gate
    if: steps.cqa.outputs.failed == 'true'
    run: exit 1
```

The JSON and SARIF artifacts are uploaded with 14-day retention. When
`GITHUB_STEP_SUMMARY` is available the CLI also appends a Markdown summary.

## Notes

* The action mounts `GITHUB_WORKSPACE` at `/workspace` and runs as the runner's
  UID/GID so reports are writable.
* Pin the `image` input to an immutable digest in shared workflows.
* `extra-args` is an escape hatch; prefer first-class inputs.
