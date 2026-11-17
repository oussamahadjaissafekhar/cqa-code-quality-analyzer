/**
 * Runtime validation for the parser IPC boundary.
 *
 * The contracts are JSON Schema; this hand-written guard keeps the parser
 * dependency-free while enforcing the same required fields and enums. Python
 * re-validates every response with pydantic, so both sides fail closed.
 */

import type { ArgsKind, ErrorKind, FileFacts, Language, LiteralKind, ParserRequest } from "./types";

const LANGUAGES: Language[] = ["python", "typescript", "javascript"];
const ARGS_KINDS: ArgsKind[] = ["empty", "literal", "dynamic", "mixed"];
const LITERAL_KINDS: LiteralKind[] = ["string", "template", "number", "boolean"];
const ERROR_KINDS: ErrorKind[] = ["parse", "io", "internal"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPositiveInt(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1;
}

/** Return a list of human-readable errors; empty means valid. */
export function validateParserRequest(value: unknown): string[] {
  const errors: string[] = [];
  if (!isRecord(value)) {
    return ["request must be an object"];
  }
  if (value.schema_version !== 1) {
    errors.push("schema_version must be 1");
  }
  if (value.jobs !== undefined && (!isPositiveInt(value.jobs) || value.jobs < 1)) {
    errors.push("jobs must be a positive integer");
  }
  if (!Array.isArray(value.files)) {
    errors.push("files must be an array");
    return errors;
  }
  value.files.forEach((file, index) => {
    if (!isRecord(file)) {
      errors.push(`files[${index}] must be an object`);
      return;
    }
    if (typeof file.path !== "string" || file.path.length === 0) {
      errors.push(`files[${index}].path must be a non-empty string`);
    }
    if (!LANGUAGES.includes(file.language as Language)) {
      errors.push(`files[${index}].language is invalid`);
    }
    if (file.content !== undefined && typeof file.content !== "string") {
      errors.push(`files[${index}].content must be a string when present`);
    }
  });
  return errors;
}

export function validateFileFacts(value: unknown): string[] {
  const errors: string[] = [];
  if (!isRecord(value)) {
    return ["facts must be an object"];
  }
  for (const key of ["imports", "calls", "literals", "functions"] as const) {
    if (!Array.isArray(value[key])) {
      errors.push(`facts.${key} must be an array`);
    }
  }
  if (errors.length > 0) {
    return errors;
  }

  (value.imports as unknown[]).forEach((item, index) => {
    if (!isRecord(item) || typeof item.from !== "string" || !isPositiveInt(item.line)) {
      errors.push(`facts.imports[${index}] is invalid`);
    }
  });
  (value.calls as unknown[]).forEach((item, index) => {
    if (
      !isRecord(item) ||
      typeof item.callee !== "string" ||
      !isPositiveInt(item.line) ||
      !isPositiveInt(item.col) ||
      !ARGS_KINDS.includes(item.args_kind as ArgsKind)
    ) {
      errors.push(`facts.calls[${index}] is invalid`);
    }
  });
  (value.literals as unknown[]).forEach((item, index) => {
    if (
      !isRecord(item) ||
      typeof item.value !== "string" ||
      !isPositiveInt(item.line) ||
      !isPositiveInt(item.col) ||
      !LITERAL_KINDS.includes(item.kind as LiteralKind)
    ) {
      errors.push(`facts.literals[${index}] is invalid`);
    }
  });
  (value.functions as unknown[]).forEach((item, index) => {
    if (
      !isRecord(item) ||
      typeof item.name !== "string" ||
      !isPositiveInt(item.line) ||
      !isPositiveInt(item.complexity)
    ) {
      errors.push(`facts.functions[${index}] is invalid`);
    }
  });
  return errors;
}

export function isParserRequest(value: unknown): value is ParserRequest {
  return validateParserRequest(value).length === 0;
}

export function isEmptyFileFacts(value: unknown): value is FileFacts {
  return validateFileFacts(value).length === 0;
}

export { ARGS_KINDS, ERROR_KINDS, LANGUAGES, LITERAL_KINDS };
