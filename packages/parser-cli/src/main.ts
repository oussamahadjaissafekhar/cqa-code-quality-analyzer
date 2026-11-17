/**
 * parser-cli: one JSON request on stdin, one JSON response on stdout.
 *
 * stdout is reserved for the response; every diagnostic goes to stderr. A
 * failure in one file becomes a per-file result/error and never aborts the
 * batch. Invalid requests exit 2 (Python maps that to a parser error).
 */

import { readFileSync } from "node:fs";
import { extractFacts } from "@cqa/parser-core";
import {
  emptyFacts,
  type AnalysisError,
  type ParserFile,
  type ParserFileResult,
  type ParserRequest,
  type ParserResponse,
  validateParserRequest,
} from "@cqa/shared";

export function processFile(file: ParserFile): ParserFileResult {
  let content = file.content;
  if (content === undefined) {
    try {
      content = readFileSync(file.path, "utf8");
    } catch (error) {
      return {
        path: file.path,
        language: file.language,
        ok: false,
        error: `cannot read file: ${error instanceof Error ? error.message : String(error)}`,
        facts: emptyFacts(),
      };
    }
  }

  try {
    return {
      path: file.path,
      language: file.language,
      ok: true,
      facts: extractFacts(file.language, content),
    };
  } catch (error) {
    return {
      path: file.path,
      language: file.language,
      ok: false,
      error: error instanceof Error ? `${error.name}: ${error.message}` : String(error),
      facts: emptyFacts(),
    };
  }
}

export function runRequest(request: ParserRequest): ParserResponse {
  const files: ParserFileResult[] = [];
  const errors: AnalysisError[] = [];

  for (const file of request.files) {
    const result = processFile(file);
    files.push(result);
    if (!result.ok) {
      errors.push({
        path: result.path,
        message: result.error ?? "parse failed",
        kind: "parse",
      });
    }
  }

  return { schema_version: 1, files, errors };
}

export interface HandleResult {
  response: ParserResponse;
  exitCode: number;
}

export function handleInput(raw: string): HandleResult {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (error) {
    return {
      exitCode: 2,
      response: {
        schema_version: 1,
        files: [],
        errors: [
          {
            path: ".",
            message: `invalid JSON request: ${error instanceof Error ? error.message : String(error)}`,
            kind: "internal",
          },
        ],
      },
    };
  }

  const problems = validateParserRequest(parsed);
  if (problems.length > 0) {
    return {
      exitCode: 2,
      response: {
        schema_version: 1,
        files: [],
        errors: problems.slice(0, 20).map((message) => ({
          path: ".",
          message,
          kind: "internal" as const,
        })),
      },
    };
  }

  return { exitCode: 0, response: runRequest(parsed as ParserRequest) };
}

export function main(): void {
  let raw = "";
  try {
    raw = readFileSync(0, "utf8");
  } catch (error) {
    process.stderr.write(
      `parser-cli: cannot read stdin: ${error instanceof Error ? error.message : String(error)}\n`
    );
    process.exitCode = 2;
    return;
  }

  const { response, exitCode } = handleInput(raw);
  process.stdout.write(JSON.stringify(response));
  if (exitCode !== 0) {
    process.exitCode = exitCode;
  }
}

if (require.main === module) {
  main();
}
