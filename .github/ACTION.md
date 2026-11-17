# CQA action contract

This document mirrors `.github/actions/cqa/action.yml`. Analysis always runs in
the container image via the `cqa` CLI; the action only forwards inputs and
publishes artifacts.

## Input / output matrix

| Kind | Name | Default | CLI / consumer |
| --- | --- | --- | --- |
| input | `path` | `.` | `analyze PATH` |
| input | `config` | `""` | `--config` |
| input | `fail-on` | `high` | `--fail-on` |
| input | `format` | `github` | `--format` (console only) |
| input | `sarif` | `true` | `--sarif cqa.sarif` |
| input | `upload-sarif` | `true` | `github/codeql-action/upload-sarif` |
| input | `baseline` | `""` | `--baseline` |
| input | `image` | `cqa:local` | `docker run` image |
| input | `extra-args` | `""` | appended to `cqa analyze` |
| output | `json-path` | — | `cqa-results.json` |
| output | `sarif-path` | — | `cqa.sarif` |
| output | `score` | — | `summary.score` |
| output | `failed` | — | `true` for CLI exit 1 |
| output | `finding-count` | — | `summary.findings` |

## Artifact retention

| File | Retention | Consumers |
| --- | --- | --- |
| `cqa-results.json` | 14 days | dashboards, baseline updates, agents |
| `cqa.sarif` | 14 days | GitHub code scanning |
| step summary | ephemeral | PR readers |

## Exit codes

`0` means clean. `1` means the quality gate was hit; the action records
`failed=true` but does not itself fail the step, so callers can choose whether
to block. `2–5` are infrastructure failures and fail the step with
`cqa infrastructure error`.
