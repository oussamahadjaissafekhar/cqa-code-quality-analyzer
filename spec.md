# Technical Specification: Code Quality Analysis CLI & CI/CD Pipeline

**Product name:** `cqa` (Code Quality Analyzer)  
**Document status:** Implementation-ready (v1.0)  
**Audience:** Human maintainers and AI coding agents  
**Stack:** Python 3.12+ (CLI core), TypeScript 5.x (parsers), Docker, GitHub Actions, Jest

---

## 0. How to use this spec (AI-agent workflow)

This document is the **single source of truth**. Implement in the order listed in [§13 Implementation slices](#13-implementation-slices-ai-agent-backlog). Do not invent APIs that contradict [§6 Contracts](#6-contracts-schemas--interfaces).

**Agent rules**

1. One slice per PR/commit when possible. Each slice must leave tests green.
2. Contracts (`contracts/*.schema.json`, `packages/shared/src/types.ts`, `src/cqa/models.py`) are frozen until a spec revision.
3. Never couple parsers to report rendering. Parsers emit `Finding[]` only.
4. Prefer injecting ports (filesystem, subprocess, clock) over touching OS directly in core logic.
5. Every public CLI flag in [§4](#4-cli-command-architecture) must have a unit test and a golden-output fixture.
6. If a requirement is missing, add an `Open questions` note in the PR; do not silently change contracts.

**Definition of done (global)**

- `cqa analyze` produces valid `AnalysisResult` JSON (schema v1).
- GitHub Action wraps the same binary; CI never reimplements analysis.
- Docker image is the only runtime used in CI.
- Jest covers TypeScript parsers; pytest covers Python orchestration.

---

## 1. Goals, non-goals, and quality bar

### 1.1 Goals

- Provide a local CLI and an identical CI check for static quality, security heuristics, and structured reporting.
- Keep language-specific parsing in TypeScript (tree-sitter / TS compiler APIs) and orchestration, scoring, and I/O in Python.
- Fail CI on configurable severity thresholds without noisy false positives as the default.
- Emit machine-readable artifacts (JSON, SARIF) plus a human Markdown summary.

### 1.2 Non-goals (v1)

- Full language servers, auto-fix application, or interactive TUI.
- Replacing Bandit / ESLint / Semgrep as a general SAST platform.
- Multi-repo fleet dashboards or a hosted SaaS.
- Dynamic analysis, secret *rotation*, or runtime instrumentation.

### 1.3 Quality bar

| Area | Bar |
| --- | --- |
| CLI UX | Deterministic exit codes; `--help` complete; no stack traces on user errors |
| Performance | 10k files / ≤ 2 min in Docker on GitHub-hosted `ubuntu-latest` (typical OSS repo) |
| Correctness | Parsers never crash the process; per-file errors become `Finding` with `rule_id=parser.error` |
| Reproducibility | Same git tree + same config → byte-stable JSON (sorted keys, sorted findings) |

---

## 2. Directory structure and file tree

Monorepo. Python package `cqa` is the CLI entrypoint. TypeScript lives in `packages/` and is invoked as a subprocess (`node dist/parser-cli.js`) with JSON-lines IPC.

```text
.
├── spec.md                          # this document
├── README.md                        # human quickstart (generated after slice 0)
├── LICENSE
├── .gitignore
├── .editorconfig
├── .pre-commit-config.yaml
├── Makefile                         # agent-friendly: make test / lint / docker
├── pyproject.toml                   # cqa Python package + pytest/ruff/mypy
├── package.json                     # workspace root (npm workspaces)
├── package-lock.json
├── tsconfig.base.json
├── docker/
│   ├── Dockerfile                   # multi-stage: node build + python runtime
│   ├── docker-compose.yml           # local parity with CI
│   └── entrypoint.sh                # exec cqa with forwarded args
├── .github/
│   ├── ACTION.md                    # action input/output matrix (mirrors action.yml)
│   ├── workflows/
│   │   ├── ci.yml                   # test Python + TS + docker build
│   │   ├── release.yml              # tag → GHCR image + PyPI (optional later)
│   │   └── code-quality.yml         # dogfood: run cqa on this repo
│   └── actions/
│       └── cqa/
│           ├── action.yml           # composite: docker run + SARIF upload
│           └── README.md
├── contracts/
│   ├── analysis-result.schema.json  # JSON Schema draft 2020-12
│   ├── finding.schema.json
│   ├── config.schema.json
│   ├── parser-request.schema.json
│   └── parser-response.schema.json
├── src/
│   └── cqa/
│       ├── __init__.py
│       ├── __main__.py              # python -m cqa
│       ├── py.typed
│       ├── cli.py                   # argparse / click thin layer
│       ├── app.py                   # Application service: wire modules
│       ├── config.py                # load/merge/validate config
│       ├── models.py                # pydantic v2 models mirroring contracts
│       ├── exit_codes.py
│       ├── logging.py
│       ├── version.py
│       ├── parsers/
│       │   ├── __init__.py
│       │   ├── protocol.py          # ParserPort
│       │   ├── node_bridge.py       # spawn TS parser-cli
│       │   └── fallback_python.py   # ast-based fallback if node missing (optional)
│       ├── security/
│       │   ├── __init__.py
│       │   ├── engine.py            # rule runner
│       │   ├── rules/
│       │   │   ├── __init__.py
│       │   │   ├── secrets.py
│       │   │   ├── injection.py
│       │   │   └── dangerous_calls.py
│       │   └── severity.py
│       ├── quality/
│       │   ├── __init__.py
│       │   ├── metrics.py           # complexity, duplication hints
│       │   └── thresholds.py
│       ├── report/
│       │   ├── __init__.py
│       │   ├── json_report.py
│       │   ├── sarif_report.py
│       │   ├── markdown_report.py
│       │   └── github_annotations.py
│       ├── ci/
│       │   ├── __init__.py
│       │   ├── github.py            # GITHUB_* env, step summary, annotations
│       │   └── artifacts.py
│       └── fs/
│           ├── __init__.py
│           ├── discover.py          # gitignore-aware file walk
│           └── cache.py             # content-hash cache (v1 optional)
├── packages/
│   ├── shared/
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   └── src/
│   │       ├── index.ts
│   │       ├── types.ts             # Finding, ParserRequest, ParserResponse
│   │       └── schema.ts            # ajv validators generated from contracts/
│   ├── parser-core/
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   └── src/
│   │       ├── index.ts
│   │       ├── walk.ts
│   │       ├── languages/
│   │       │   ├── typescript.ts
│   │       │   ├── javascript.ts
│   │       │   └── python.ts        # tree-sitter-python or lightweight CST
│   │       └── extractors/
│   │           ├── imports.ts
│   │           ├── calls.ts
│   │           └── literals.ts
│   └── parser-cli/
│       ├── package.json
│       ├── tsconfig.json
│       └── src/
│           └── main.ts              # stdin JSON request → stdout JSON response
├── tests/
│   ├── python/
│   │   ├── conftest.py
│   │   ├── unit/
│   │   │   ├── test_cli.py
│   │   │   ├── test_config.py
│   │   │   ├── test_security_engine.py
│   │   │   └── test_report.py
│   │   ├── integration/
│   │   │   ├── test_analyze_golden.py
│   │   │   └── test_node_bridge.py
│   │   └── fixtures/
│   │       ├── repos/
│   │       └── golden/
│   └── ts/
│       ├── jest.config.ts           # or packages/*/jest.config.ts
│       ├── parser-core/
│       │   ├── walk.test.ts
│       │   └── extractors.test.ts
│       └── parser-cli/
│           └── main.test.ts
├── examples/
│   ├── cqa.toml                     # sample project config
│   └── sample-src/
│       ├── ok.ts
│       └── vuln.py
└── docs/
    ├── architecture.md              # short C4-style notes (optional, after v1)
    └── adr/
        └── 0001-python-cli-ts-parsers.md
```

### 2.1 Ownership map (who may import whom)

```text
cli.py → app.py → {config, parsers, security, quality, report, ci, fs}
parsers.node_bridge → contracts only (JSON)
security.engine → models + parser AST facts (not TS packages)
report.* → models only
packages/parser-cli → packages/parser-core → packages/shared
GitHub Action → docker image → `cqa` CLI only
```

**Forbidden:** Python importing TS source; Action YAML embedding rule logic; report modules calling parsers.

---

## 3. Runtime architecture

```text
┌─────────────┐     argv/env/config      ┌──────────────────┐
│  User / GHA │ ───────────────────────► │  cqa CLI (Py)    │
└─────────────┘                          │  cli.py / app.py │
                                         └────────┬─────────┘
                    discover files                │
                                         ┌────────▼─────────┐
                                         │  fs.discover     │
                                         └────────┬─────────┘
                    ParserRequest JSON            │
                                         ┌────────▼─────────┐
                                         │  node_bridge     │──► packages/parser-cli (Node)
                                         └────────┬─────────┘
                    ParserResponse                │
                    (facts + parse errors)        │
                                         ┌────────▼─────────┐
                                         │ security.engine  │
                                         │ quality.metrics  │
                                         └────────┬─────────┘
                    AnalysisResult                │
                                         ┌────────▼─────────┐
                                         │ report generators│──► stdout / files / GITHUB_STEP_SUMMARY
                                         └──────────────────┘
```

Python owns: config, discovery, scoring, thresholds, exit codes, GitHub integration, reports.  
TypeScript owns: syntax trees, import/call/literal extraction, language-specific facts.

---

## 4. CLI command architecture

**Binary:** `cqa`  
**Invocation:** `cqa <command> [options]`  
**Library:** Click 8.x (or argparse if Click is rejected in slice 0; Click is the default).

### 4.1 Global options (all commands)

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `--config PATH` | path | auto: `cqa.toml` then `.cqa.toml` then `pyproject.toml [tool.cqa]` | Config file |
| `--verbose` / `-v` | count | 0 | DEBUG logs to stderr |
| `--quiet` / `-q` | flag | false | Only errors on stderr |
| `--no-color` | flag | false; auto if `NO_COLOR` or non-TTY | Disable ANSI |
| `--version` | flag | — | Print version and exit 0 |

Stderr = logs. Stdout = primary machine/human report unless `--output` writes a file (then stdout may still emit the chosen format if `--stdout` is set).

### 4.2 Commands

#### `cqa analyze` (primary)

Analyze a path (file or directory). Default command if we later add a default; v1 requires the subcommand.

```text
cqa analyze [PATH] [options]
```

| Flag | Type | Default | Description |
| --- | --- | --- | --- |
| `PATH` | path | `.` | Root to analyze |
| `--include GLOB` | repeatable | from config | Include globs |
| `--exclude GLOB` | repeatable | from config | Exclude globs (always apply `.gitignore` unless `--no-gitignore`) |
| `--no-gitignore` | flag | false | Walk all files |
| `--languages LIST` | csv | `python,typescript,javascript` | Limit parsers |
| `--rules LIST` | csv | all enabled | Rule id allow-list |
| `--disable-rule ID` | repeatable | — | Disable rule |
| `--format FMT` | enum | `json` | `json` \| `sarif` \| `markdown` \| `github` \| `table` |
| `--output PATH` / `-o` | path | `-` (stdout) | Write report |
| `--sarif PATH` | path | unset | Extra SARIF file (in addition to `--format`) |
| `--fail-on LEVEL` | enum | `high` | `info` \| `low` \| `medium` \| `high` \| `critical` \| `never` |
| `--max-findings N` | int | 0 (unlimited) | Cap listed findings; still count all |
| `--baseline PATH` | path | unset | Ignore findings present in baseline JSON |
| `--update-baseline` | flag | false | Write baseline after run (local only; CI should not use unless explicit) |
| `--cache-dir PATH` | path | `.cqa-cache` | Analysis cache |
| `--no-cache` | flag | false | Disable cache |
| `--jobs N` / `-j` | int | CPU count | Parallel file parse (Python fans out; one Node process with internal pool) |
| `--timeout-s N` | int | 120 | Hard timeout for Node parser subprocess |
| `--parser-bin PATH` | path | bundled `parser-cli` | Override Node CLI |
| `--stdin-files` | flag | false | Read NUL-separated paths from stdin (CI incremental) |

#### `cqa rules`

List rule IDs, severity, and help.

```text
cqa rules [--format json|table]
```

#### `cqa init`

Write `cqa.toml` in the current directory.

```text
cqa init [--force]
```

#### `cqa version`

Same as `--version`; also prints parser-cli and schema versions as JSON when `--format json`.

### 4.3 Exit codes

| Code | Constant | Meaning |
| --- | --- | --- |
| 0 | `OK` | Success; no findings at/above `--fail-on` |
| 1 | `FINDINGS` | Findings at/above fail threshold |
| 2 | `USAGE` | Invalid args / config |
| 3 | `IO` | Path missing, permission, write failure |
| 4 | `PARSER` | Parser subprocess crashed (not per-file parse error) |
| 5 | `TIMEOUT` | Parser or run exceeded timeout |
| 130 | `SIGINT` | Interrupted |

CI must treat `1` as a quality gate failure and `2–5` as infrastructure failures.

### 4.4 Output formats

**JSON (`--format json`)** — canonical. Matches `contracts/analysis-result.schema.json`. Pretty-print with `--verbose`; compact by default in CI (`CI=true`).

**SARIF 2.1.0** — GitHub code scanning compatible. One run, tool `cqa`.

**Markdown** — GitHub Step Summary friendly: counts by severity, top 20 findings, then “truncated” note.

**github** — GitHub workflow commands:

```text
::error file={path},line={line},col={col},title={rule_id}::{message}
::warning ...
::notice ...
```

**table** — TTY-only aligned columns; if stdout is not a TTY, fall back to JSON and warn on stderr.

### 4.5 Environment variables

| Variable | Maps to |
| --- | --- |
| `CQA_CONFIG` | `--config` |
| `CQA_FAIL_ON` | `--fail-on` |
| `CQA_FORMAT` | `--format` |
| `CQA_NO_COLOR` | `--no-color` |
| `CQA_PARSER_BIN` | `--parser-bin` |
| `CI` | compact JSON; github annotations if `GITHUB_ACTIONS=true` |
| `GITHUB_ACTIONS`, `GITHUB_STEP_SUMMARY`, `GITHUB_WORKSPACE` | CI adapters |

Precedence: **CLI flags > env > config file > defaults.**

### 4.6 Config file (`cqa.toml`)

```toml
schema_version = 1

[discover]
include = ["**/*.{py,ts,tsx,js,jsx}"]
exclude = ["**/node_modules/**", "**/.git/**", "**/dist/**", "**/.venv/**"]
use_gitignore = true

[parser]
languages = ["python", "typescript", "javascript"]
timeout_s = 120
jobs = 0  # 0 = auto

[rules]
disable = []
# optional per-rule
# [rules.overrides.secrets.hardcoded]
# severity = "high"

[thresholds]
fail_on = "high"
# optional counts
# max_high = 0
# max_medium = 20

[report]
formats = ["json"]
sarif = true
```

Validate against `contracts/config.schema.json` on load. Unknown keys = error (fail closed) so agents cannot drift.

---

## 5. Core module responsibilities

### 5.1 Parser module (TypeScript + Python bridge)

**Packages:** `packages/parser-core`, `packages/parser-cli`  
**Python port:** `cqa.parsers.protocol.ParserPort`

**Responsibilities**

- Accept `ParserRequest`: list of files `{ path, language, content? }`. If `content` omitted, parser reads from disk (paths must be inside the analysis root).
- Produce per-file **facts**, not verdicts:
  - imports / requires
  - call expressions (callee name, arg literal values when statically known)
  - string / template literals
  - function complexity (cyclomatic, rough)
  - parse errors
- Normalize locations to 1-based line/column.
- Isolate failures: one bad file never aborts the batch.

**Non-responsibilities**

- Severity, scoring, secret entropy policy, report formatting, gitignore.

**Python `node_bridge`**

- Resolves parser binary: `--parser-bin` → `CQA_PARSER_BIN` → `node packages/parser-cli/dist/main.js` in repo → image path `/opt/cqa/parser-cli.js`.
- Sends one JSON object on stdin; reads one JSON object on stdout. Stderr of Node is forwarded at DEBUG.
- Enforces `--timeout-s` and `--jobs` (passed in request).
- Validates response with pydantic + JSON Schema.

**Jest surface (required)**

- Golden AST-fact tests per language under `tests/ts/` using `examples/sample-src/`.
- Property: output matches `parser-response.schema.json`.
- Crash test: invalid UTF-8 / truncated file → `parse_error` finding-equivalent in `errors[]`.

### 5.2 Security check module (Python)

**Package:** `cqa.security`

**Responsibilities**

- Load enabled rules; apply allow/deny lists.
- Consume parser facts + raw snippets (bounded; max 4 KB per finding).
- Emit `Finding` objects with stable `fingerprint` (see §6.3).
- Default rule packs for v1:

| Rule ID | Severity | Input facts | Intent |
| --- | --- | --- | --- |
| `secrets.hardcoded` | critical | literals matching key/token regex + entropy | Hardcoded credentials |
| `secrets.aws_key` | critical | `AKIA` / AWS secret patterns | Cloud keys |
| `sec.eval` | high | calls to `eval`, `Function(`, `exec` | Dynamic code execution |
| `sec.child_process` | high | `child_process.exec` with non-literal | Command injection heuristic |
| `sec.sql_concat` | high | string concat/f-string into execute | SQL injection heuristic |
| `sec.insecure_http` | medium | `http://` in URLs (non-test paths) | Cleartext HTTP |
| `sec.yaml_unsafe` | high | `yaml.load` without `SafeLoader` | Unsafe deserialization |
| `quality.complexity` | low/medium | cyclomatic > thresholds | Maintainability |

Rules are pure functions:

```python
class Rule(Protocol):
    id: str
    def check(self, file: FileFacts, ctx: RuleContext) -> list[Finding]: ...
```

**Non-responsibilities:** parsing source; writing files; GitHub API.

### 5.3 Quality metrics module

**Package:** `cqa.quality`

- Aggregates complexity, file size, TODO density (optional, default off).
- Converts metric breaches to findings using config thresholds.
- Computes `summary.score` (0–100): start 100; subtract weighted severity counts (critical 25, high 10, medium 3, low 1, info 0), clamped.

### 5.4 Report generator module

**Package:** `cqa.report`

**Responsibilities**

- Serialize `AnalysisResult` to JSON / SARIF / Markdown / GitHub annotations / table.
- Stable ordering: `severity desc, path asc, line asc, rule_id asc`.
- JSON key sort for byte stability.
- Truncation messages when `--max-findings` applies (`summary.truncated = true`).

**SARIF mapping**

- `ruleId` ← `finding.rule_id`
- `level` ← severity: critical/high → `error`; medium → `warning`; low/info → `note`
- `partialFingerprints.cqa/v1` ← `finding.fingerprint`

### 5.5 CI adapter module

**Package:** `cqa.ci`

- Detect `GITHUB_ACTIONS`.
- Append Markdown to `GITHUB_STEP_SUMMARY` when present.
- Write `github` workflow commands when `--format github` or when `CI` + actions detected and format is not JSON-only.
- Resolve paths relative to `GITHUB_WORKSPACE`.
- Never call GitHub REST API in v1 (upload is the Action’s job).

### 5.6 Application service

**Module:** `cqa.app.run_analyze(opts) -> AnalysisResult`

Pipeline (strict order):

1. Load and validate config.
2. Discover files.
3. Call parser port.
4. Run security + quality engines.
5. Apply baseline filter.
6. Compute summary + exit decision.
7. Render reports.
8. Return result (CLI maps to exit code).

This function is the only thing GitHub Action needs; tests should prefer `run_analyze` over Click invocation except for CLI parsing tests.

---

## 6. Contracts (schemas & interfaces)

### 6.1 `Finding`

```json
{
  "schema_version": 1,
  "rule_id": "sec.eval",
  "severity": "high",
  "message": "Use of eval() is unsafe",
  "path": "src/app.ts",
  "start_line": 12,
  "start_col": 3,
  "end_line": 12,
  "end_col": 7,
  "fingerprint": "cqa:v1:a1b2c3d4",
  "snippet": "eval(user)",
  "help_uri": "https://example.local/rules/sec.eval"
}
```

`path` is always POSIX-style, relative to analysis root. No absolute paths in artifacts.

### 6.2 `AnalysisResult`

```json
{
  "schema_version": 1,
  "tool": { "name": "cqa", "version": "0.1.0", "parser_version": "0.1.0" },
  "generated_at": "1970-01-01T00:00:00Z",
  "root": ".",
  "summary": {
    "files_scanned": 0,
    "findings": 0,
    "by_severity": { "critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0 },
    "score": 100,
    "truncated": false,
    "failed": false
  },
  "findings": [],
  "errors": []
}
```

`generated_at` is ISO-8601 UTC. For golden tests, freeze clock via injectable `Clock` (`1970-01-01T00:00:00Z`).

`errors[]` items: `{ "path": "...", "message": "...", "kind": "parse"|"io"|"internal" }`.

### 6.3 Fingerprint

```text
sha256("cqa:v1|" + rule_id + "|" + path + "|" + normalized_snippet)[:16]
```

`normalized_snippet` = collapse whitespace, strip string contents to `*` for secret rules so rotation does not churn baselines incorrectly? **v1 decision:** hash **rule_id + path + start_line + callee/pattern id**, not raw secret text (avoids leaking secrets into fingerprints and into logs).

### 6.4 Parser IPC

**Request**

```json
{
  "schema_version": 1,
  "jobs": 4,
  "files": [
    { "path": "a.ts", "language": "typescript" }
  ]
}
```

**Response**

```json
{
  "schema_version": 1,
  "files": [
    {
      "path": "a.ts",
      "language": "typescript",
      "ok": true,
      "facts": {
        "imports": [{ "from": "fs", "names": ["readFileSync"], "line": 1 }],
        "calls": [{ "callee": "eval", "line": 10, "col": 1, "args_kind": "dynamic" }],
        "literals": [{ "value": "AKIA...", "line": 4, "kind": "string" }],
        "functions": [{ "name": "main", "line": 8, "complexity": 3 }]
      }
    }
  ],
  "errors": []
}
```

Literal `value` in IPC may be truncated to 120 chars. Security rules that need full line re-read from disk via Python (bounded).

### 6.5 Shared TypeScript types (`packages/shared/src/types.ts`)

Must be hand-aligned with JSON Schema. In slice 1, add a Jest test: ajv-validate a fixture; in Python, pytest against the same fixture file in `contracts/examples/` (add `contracts/examples/finding.min.json` during slice 1).

---

## 7. Data flow: CLI ↔ GitHub Actions

### 7.1 Principle

**The Action is a thin wrapper.** All analysis logic runs inside the Docker image via `cqa analyze`. YAML must not duplicate rules or scoring.

### 7.2 Composite action contract (`.github/actions/cqa/action.yml`)

**Inputs**

| Input | Required | Default | Maps to CLI |
| --- | --- | --- | --- |
| `path` | no | `.` | `analyze PATH` |
| `config` | no | `""` | `--config` if set |
| `fail-on` | no | `high` | `--fail-on` |
| `format` | no | `github` | `--format` |
| `sarif` | no | `true` | `--sarif cqa.sarif` |
| `upload-sarif` | no | `true` | `github/codeql-action/upload-sarif` |
| `baseline` | no | `""` | `--baseline` |
| `extra-args` | no | `""` | appended (documented escape hatch; prefer first-class inputs) |

**Outputs**

| Output | Source |
| --- | --- |
| `json-path` | `cqa-results.json` |
| `sarif-path` | `cqa.sarif` |
| `score` | parsed from JSON summary |
| `failed` | `true` if CLI exit 1 |
| `finding-count` | summary.findings |

Implementation note: capture CLI exit code; do not `set -e` before mapping 1 vs 2–5. Write `$GITHUB_OUTPUT`.

### 7.3 Sequence (CI job)

```text
1. checkout (fetch-depth: 1 sufficient unless baseline from git history)
2. docker pull ghcr.io/<org>/cqa:<tag>   # or build in this repo’s ci.yml
3. docker run --rm
     -v $GITHUB_WORKSPACE:/workspace
     -e GITHUB_ACTIONS=true
     -e GITHUB_WORKSPACE=/workspace
     -e GITHUB_STEP_SUMMARY
     -w /workspace
     ghcr.io/<org>/cqa:<tag>
     analyze /workspace
       --format github
       --output /workspace/cqa-results.json
       --sarif /workspace/cqa.sarif
       --fail-on ${{ inputs.fail-on }}
4. if sarif exists and upload-sarif: upload-sarif
5. upload-artifact: cqa-results.json, cqa.sarif
6. job status:
     - CLI 0 → success
     - CLI 1 → fail job (quality gate)
     - CLI 2+ → fail job (infra); message “cqa infrastructure error”
```

Mount `GITHUB_STEP_SUMMARY` file into the container (GitHub provides a path). The Python CI adapter appends the Markdown report.

### 7.4 Consumer workflow example

```yaml
# .github/workflows/code-quality.yml
name: Code quality
on:
  pull_request:
  push:
    branches: [main]
jobs:
  cqa:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write
    steps:
      - uses: actions/checkout@v4
      - uses: ./ .github/actions/cqa   # path: .github/actions/cqa
        with:
          fail-on: high
          upload-sarif: true
```

(Exact `uses:` path is `.github/actions/cqa`.)

### 7.5 Artifact contract

| File | Retention | Consumers |
| --- | --- | --- |
| `cqa-results.json` | 14 days | dashboards, baseline updates, agents |
| `cqa.sarif` | 14 days | GitHub code scanning |
| Step summary | ephemeral | humans on PR |

### 7.6 Incremental / PR mode (v1.1 optional)

If `github.event.pull_request` and input `changed-only: true`:

- Action runs `git diff --name-only -z origin/<base>...HEAD`
- Pipes to `cqa analyze --stdin-files`

v1 ships the flag; Action input can wait until slice 9.

### 7.7 Local parity

```bash
docker compose -f docker/docker-compose.yml run --rm cqa analyze . --format table
```

Same image digest as CI when `CQA_IMAGE` is pinned.

---

## 8. Docker

**Multi-stage**

1. **node-build:** `npm ci && npm run build -w parser-cli`  
2. **python-build:** `pip install .` into venv  
3. **runtime:** distroless or `python:3.12-slim` + Node 20 (parser needs Node). Pin digests.

**Image layout**

```text
/opt/cqa/venv/           # python env, PATH
/opt/cqa/parser-cli.js   # bundled node entry (with node_modules production)
/entrypoint.sh           # exec cqa "$@"
```

`WORKDIR` default `/workspace`. USER non-root (`cqa:1000`). Read-only rootfs compatible except `/tmp` and cache dir.

**Labels:** `org.opencontainers.image.source`, `cqa.schema_version=1`.

---

## 9. Testing strategy

| Layer | Tool | Scope |
| --- | --- | --- |
| TS unit | Jest | extractors, walk, schema validation |
| Py unit | pytest | rules, reports, config merge, exit codes |
| Bridge | pytest + node | golden `ParserResponse` |
| CLI | pytest `CliRunner` | flags, formats |
| Image | GHA `ci.yml` | `docker build` + `docker run analyze examples/sample-src` |
| Contract | both | JSON Schema on shared fixtures |

**Golden tests:** freeze clock, sort findings, compare to `tests/python/fixtures/golden/*.json`. Update via `pytest --update-goldens` (opt-in flag in conftest; never default-on in CI).

**Coverage gates:** 80% lines on `src/cqa/{security,report,config}` and `packages/parser-core/src/extractors`.

---

## 10. GitHub Actions for *this* repository (`ci.yml`)

Jobs:

1. **ts** — `npm ci`, `npm test` (Jest), `npm run typecheck`
2. **py** — `pip install -e ".[dev]"`, `ruff`, `mypy`, `pytest`
3. **docker** — build image, run `cqa analyze examples/sample-src --fail-on never`, schema-validate output
4. **action-smoke** — uses `nektos/act` locally optional; in GHA, `uses: ./.github/actions/cqa` with `upload-sarif: false`

---

## 11. Security, privacy, and supply chain

- Do not print secret `snippet` at `critical` for `secrets.*` in Markdown/table; redact to `[REDACTED]`. JSON may include truncated snippet for tools; SARIF uses redacted snippet.
- Pin GitHub Action versions by SHA in published examples.
- Dependabot / npm + pip.
- Parser subprocess: no shell; `subprocess.run([node, bin], ...)` argument list only.
- Refuse to follow symlinks outside analysis root.

---

## 12. Versioning

- **Tool semver:** `cqa.version`  
- **Schema:** `schema_version` integer in all JSON; v1 is additive-only. Breaking schema bump = major tool version.
- Parser-cli version reported in `AnalysisResult.tool.parser_version`.

---

## 13. Implementation slices (AI-agent backlog)

Implement **in order**. Each slice lists files to touch and tests that must pass.

| Slice | Deliverable | Tests |
| --- | --- | --- |
| **0** | Repo skeleton: pyproject, package.json workspaces, Makefile, empty packages, Docker stub | `make bootstrap` documented |
| **1** | `contracts/*.schema.json` + pydantic `models.py` + TS `types.ts` + example fixtures | schema round-trip |
| **2** | `parser-core` extractors for TS/JS (calls, literals, imports) | Jest unit |
| **3** | `parser-cli` stdin/stdout + Python `node_bridge` | integration test |
| **4** | `fs.discover` + config load | pytest |
| **5** | Security engine + v1 rules | pytest with fixtures |
| **6** | Report JSON + Markdown + SARIF | golden files |
| **7** | Click CLI: `analyze`, `rules`, `init`, exit codes | CliRunner |
| **8** | Docker image + entrypoint | docker smoke |
| **9** | Composite Action + `code-quality.yml` | action-smoke job |
| **10** | Python parser facts (tree-sitter or TS python grammar) | Jest + 1 py fixture |
| **11** | Baseline + cache (optional) | pytest |
| **12** | Docs README + dogfood on this repo | CI green |

Do not start slice N+1 if slice N tests fail.

---

## 14. Makefile targets (required)

```text
make bootstrap   # npm ci && pip install -e ".[dev]"
make test        # pytest && npm test
make lint        # ruff + mypy + eslint/tsc
make contracts   # validate schemas
make docker      # docker build
make analyze     # cqa analyze . --format table
```

---

## 15. Open questions (resolved defaults)

| Topic | Default for v1 | Change process |
| --- | --- | --- |
| CLI framework | Click | ADR |
| Python parser | tree-sitter-python via Node, not CPython `ast`, for one IPC path | ADR if too slow |
| Default `--format` | `json` locally; Action overrides to `github` | — |
| Secret redaction | always in human formats | — |
| Auto-default command | none; require `analyze` | — |

---

## 16. Glossary

| Term | Meaning |
| --- | --- |
| Fact | Parser-extracted syntax data, no verdict |
| Finding | Rule verdict with location and fingerprint |
| Bridge | Python subprocess wrapper around parser-cli |
| Slice | Independently mergeable implementation unit |
| Baseline | Previously accepted finding fingerprints to suppress |

---

## Appendix A — Example CLI sessions

```bash
cqa init
cqa analyze ./src --format table --fail-on high
cqa analyze . --format json -o cqa-results.json --sarif cqa.sarif
cqa rules --format json
```

CI (inside container):

```bash
cqa analyze /workspace \
  --format github \
  --output /workspace/cqa-results.json \
  --sarif /workspace/cqa.sarif \
  --fail-on high
```

## Appendix B — Minimal `action.yml` sketch

```yaml
name: CQA
description: Run Code Quality Analyzer
inputs:
  path: { default: "." }
  fail-on: { default: "high" }
  upload-sarif: { default: "true" }
outputs:
  json-path: { value: "${{ steps.run.outputs.json-path }}" }
  score: { value: "${{ steps.run.outputs.score }}" }
runs:
  using: composite
  steps:
    - id: run
      shell: bash
      run: |
        # docker run … cqa analyze …
```

Full implementation belongs in slice 9; this appendix is the interface freeze.
