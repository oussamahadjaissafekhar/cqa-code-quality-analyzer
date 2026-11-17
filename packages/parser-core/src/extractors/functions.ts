/**
 * Function and rough cyclomatic-complexity extraction.
 *
 * Detects declarations, methods and arrow functions. Complexity = 1 + decision
 * points (if/for/while/case/catch, logical operators, ternaries) in the body.
 * This is a maintainability heuristic, not a control-flow analysis.
 */

import type { FunctionFact } from "@cqa/shared";
import { findMatching, type Token } from "../tokenize";

const BRANCH_KEYWORDS = new Set(["if", "for", "while", "case", "catch"]);
const BRANCH_OPERATORS = new Set(["&&", "||", "??"]);
const METHOD_PREFIXES = new Set([
  "static",
  "async",
  "get",
  "set",
  "public",
  "private",
  "protected",
  "readonly",
]);
const NOT_FUNCTION_NAMES = new Set([
  "if",
  "for",
  "while",
  "switch",
  "catch",
  "return",
  "function",
  "typeof",
  "with",
  "await",
  "yield",
]);

function complexityBetween(tokens: Token[], start: number, end: number): number {
  let complexity = 1;
  for (let index = start; index <= end && index < tokens.length; index += 1) {
    const token = tokens[index];
    if (!token) {
      continue;
    }
    if (token.kind === "keyword" && BRANCH_KEYWORDS.has(token.value)) {
      complexity += 1;
    } else if (token.kind === "punct" && BRANCH_OPERATORS.has(token.value)) {
      complexity += 1;
    } else if (
      token.value === "?" &&
      tokens[index - 1]?.value !== "." &&
      tokens[index + 1]?.value !== "." &&
      tokens[index + 1]?.value !== "?"
    ) {
      complexity += 1;
    }
  }
  return complexity;
}

function findArrowName(tokens: Token[], arrowIndex: number): string {
  // const name = (...) => ... / name = (...) => ...
  for (let index = arrowIndex - 1; index >= Math.max(0, arrowIndex - 16); index -= 1) {
    if (tokens[index]?.value === "=") {
      const candidate = tokens[index - 1];
      if (candidate?.kind === "ident") {
        return candidate.value;
      }
      break;
    }
  }
  return "<arrow>";
}

function functionFacts(name: string, line: number, complexity: number): FunctionFact {
  return { name, line, complexity: Math.max(1, complexity) };
}

function findBodyStart(tokens: Token[], start: number): number {
  const limit = Math.min(tokens.length, start + 120);
  for (let index = start; index < limit; index += 1) {
    const token = tokens[index];
    if (token?.value === "{") {
      return index;
    }
    if (token?.value === ";" || token?.value === "=>") {
      return -1;
    }
  }
  return -1;
}

export function extractFunctions(tokens: Token[]): FunctionFact[] {
  const functions: FunctionFact[] = [];
  const seen = new Set<string>();

  const add = (name: string, line: number, complexity: number): void => {
    const key = `${name}\u0000${line}`;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    functions.push(functionFacts(name, line, complexity));
  };

  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (!token) {
      continue;
    }

    // function name(...) { ... }
    if (token.kind === "keyword" && token.value === "function") {
      let cursor = index + 1;
      if (tokens[cursor]?.value === "*") {
        cursor += 1;
      }
      const nameToken = tokens[cursor];
      const name = nameToken?.kind === "ident" ? nameToken.value : "<anonymous>";
      if (nameToken?.kind === "ident") {
        cursor += 1;
      }
      // Optional TypeScript generics: function name<T>(...)
      if (tokens[cursor]?.value === "<") {
        let depth = 0;
        while (cursor < tokens.length) {
          if (tokens[cursor]?.value === "<") {
            depth += 1;
          } else if (tokens[cursor]?.value === ">") {
            depth -= 1;
            if (depth === 0) {
              cursor += 1;
              break;
            }
          }
          cursor += 1;
        }
      }
      if (tokens[cursor]?.value === "(") {
        const paramsClose = findMatching(tokens, cursor, "(", ")");
        const bodyStart = findBodyStart(tokens, paramsClose + 1);
        if (bodyStart !== -1) {
          const bodyClose = findMatching(tokens, bodyStart, "{", "}");
          add(name, nameToken?.line ?? token.line, complexityBetween(tokens, bodyStart + 1, bodyClose - 1));
          index = bodyClose;
        }
      }
      continue;
    }

    // const name = (...) => { ... } / name => expression
    if (token.kind === "punct" && token.value === "=>") {
      const name = findArrowName(tokens, index);
      const bodyStart = index + 1;
      if (tokens[bodyStart]?.value === "{") {
        const bodyClose = findMatching(tokens, bodyStart, "{", "}");
        add(name, token.line, complexityBetween(tokens, bodyStart + 1, bodyClose - 1));
      } else {
        // Expression-bodied arrow: scan to the nearest statement boundary.
        let cursor = bodyStart;
        let depth = 0;
        while (cursor < tokens.length) {
          const current = tokens[cursor];
          if (!current) {
            break;
          }
          if (["(", "[", "{"].includes(current.value)) {
            depth += 1;
          } else if ([")", "]", "}"].includes(current.value)) {
            if (depth === 0) {
              break;
            }
            depth -= 1;
          } else if (current.value === ";" && depth === 0) {
            break;
          }
          cursor += 1;
        }
        add(name, token.line, complexityBetween(tokens, bodyStart, cursor - 1));
      }
      continue;
    }

    // Class/object method: name(...) { ... }
    if (token.kind === "ident" && tokens[index + 1]?.value === "(") {
      const before = tokens[index - 1];
      if (before?.value === "." || before?.value === "?.") {
        continue;
      }
      const paramsClose = findMatching(tokens, index + 1, "(", ")");
      const bodyStart = findBodyStart(tokens, paramsClose + 1);
      if (bodyStart === -1) {
        continue;
      }
      const allowedBefore =
        !before ||
        ["{", "}", ";", ","].includes(before.value) ||
        (before.kind === "keyword" && METHOD_PREFIXES.has(before.value));
      if (!allowedBefore) {
        continue;
      }
      if (NOT_FUNCTION_NAMES.has(token.value)) {
        continue;
      }
      const bodyClose = findMatching(tokens, bodyStart, "{", "}");
      add(token.value, token.line, complexityBetween(tokens, bodyStart + 1, bodyClose - 1));
      index = bodyClose;
    }
  }

  return functions;
}
