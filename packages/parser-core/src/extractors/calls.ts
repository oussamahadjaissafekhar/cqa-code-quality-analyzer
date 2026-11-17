/**
 * Call-expression extraction.
 *
 * Emits the dotted callee as written (`child_process.exec`, `yaml.load`,
 * `cursor.execute`) plus:

 * - 1-based line/column of the callee
 * - an `args_kind` classification used by security heuristics
 *
 * Method *definitions* are skipped; calls whose arguments are all static
 * literals are marked `literal`, all dynamic `dynamic`, a blend `mixed`.
 */

import type { ArgsKind, CallFact } from "@cqa/shared";
import { findMatching, type Token } from "../tokenize";

const NON_CALL_KEYWORDS = new Set([
  "if",
  "for",
  "while",
  "switch",
  "catch",
  "function",
  "class",
  "extends",
  "import",
  "export",
]);

const LITERAL_KEYWORDS = new Set(["true", "false", "null", "undefined"]);

function previousBeforeChain(tokens: Token[], start: number): Token | undefined {
  return tokens[start - 1];
}

function looksLikeMethodDefinition(tokens: Token[], start: number, closeIndex: number): boolean {
  const before = previousBeforeChain(tokens, start);
  const after = tokens[closeIndex + 1];
  if (after?.value !== "{") {
    return false;
  }
  if (!before) {
    return true;
  }
  return ["{", "}", ";", ",", "static", "async", "get", "set", "public", "private", "protected"].includes(
    before.value
  );
}

function classifyArguments(tokens: Token[], openIndex: number, closeIndex: number): ArgsKind {
  if (closeIndex === openIndex + 1) {
    return "empty";
  }

  // Split top-level arguments on commas.
  const groups: Token[][] = [[]];
  let depth = 0;
  for (let index = openIndex + 1; index < closeIndex; index += 1) {
    const token = tokens[index];
    if (!token) {
      continue;
    }
    if (["(", "[", "{"].includes(token.value)) {
      depth += 1;
    } else if ([")", "]", "}"].includes(token.value)) {
      depth -= 1;
    }
    if (token.value === "," && depth === 0) {
      groups.push([]);
      continue;
    }
    groups[groups.length - 1]?.push(token);
  }

  let literal = 0;
  let dynamic = 0;
  for (const group of groups) {
    if (group.length === 0) {
      continue;
    }
    if (group.some((token) => token.value === "...")) {
      dynamic += 1;
      continue;
    }
    if (group.length === 1) {
      const only = group[0];
      if (!only) {
        continue;
      }
      if (only.kind === "string") {
        literal += 1;
      } else if (only.kind === "template") {
        if (only.interpolated) {
          dynamic += 1;
        } else {
          literal += 1;
        }
      } else if (only.kind === "number") {
        literal += 1;
      } else if (only.kind === "keyword" && LITERAL_KEYWORDS.has(only.value)) {
        literal += 1;
      } else if (only.kind === "ident" && LITERAL_KEYWORDS.has(only.value)) {
        literal += 1;
      } else {
        dynamic += 1;
      }
    } else if (
      group.length === 2 &&
      (group[0]?.value === "-" || group[0]?.value === "+") &&
      group[1]?.kind === "number"
    ) {
      literal += 1;
    } else {
      dynamic += 1;
    }
  }

  if (literal === 0 && dynamic === 0) {
    return "empty";
  }
  if (dynamic === 0) {
    return "literal";
  }
  if (literal === 0) {
    return "dynamic";
  }
  return "mixed";
}

export function extractCalls(tokens: Token[]): CallFact[] {
  const calls: CallFact[] = [];

  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (!token || token.kind !== "ident") {
      continue;
    }
    const before = previousBeforeChain(tokens, index);
    if (before?.value === "." || before?.value === "?." || before?.value === "function") {
      continue;
    }
    if (before?.kind === "keyword" && NON_CALL_KEYWORDS.has(before.value)) {
      continue;
    }
    if (before?.value === "class") {
      continue;
    }

    let cursor = index + 1;
    let callee = token.value;
    while (
      (tokens[cursor]?.value === "." || tokens[cursor]?.value === "?.") &&
      tokens[cursor + 1]?.kind === "ident"
    ) {
      callee += `.${tokens[cursor + 1]?.value ?? ""}`;
      cursor += 2;
    }

    if (tokens[cursor]?.value !== "(") {
      continue;
    }
    const closeIndex = findMatching(tokens, cursor, "(", ")");
    if (looksLikeMethodDefinition(tokens, index, closeIndex)) {
      continue;
    }

    calls.push({
      callee,
      line: token.line,
      col: token.col,
      args_kind: classifyArguments(tokens, cursor, closeIndex),
    });

    // Skip the chain so `obj.method()` is reported once, not as `method()` too.
    index = cursor;
  }

  return calls;
}
