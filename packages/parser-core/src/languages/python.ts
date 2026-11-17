/**
 * Python fact extraction.
 *
 * A lightweight scanner masks comments/strings (with triple-quote support) for
 * structural regexes, while literal positions are preserved for security rules.
 * This mirrors the fallback parser on the Python side but is the single IPC path
 * used in production (spec §15: tree-sitter is an implementation detail we can
 * swap in later without changing contracts).
 */

import type { CallFact, FileFacts, FunctionFact, ImportFact, LiteralFact } from "@cqa/shared";
import { bisectLineStarts, lineStarts } from "../lines";

interface PythonString {
  start: number;
  end: number;
  value: string;
  kind: "string" | "template";
}

interface ScanResult {
  masked: string;
  strings: PythonString[];
}

const IDENT = "[A-Za-z_]\\w*";
const CALL_RE = new RegExp(`(${IDENT}(?:\\.${IDENT})*)\\s*\\(`, "g");
const FROM_IMPORT_RE = /^\s*from\s+([.\w]+)\s+import\s+(.+)$/;
const IMPORT_RE = /^\s*import\s+(.+)$/;
const DEF_RE = /^(\s*)(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(/;
const CALL_KEYWORDS = new Set([
  "if",
  "elif",
  "for",
  "while",
  "with",
  "return",
  "yield",
  "assert",
  "except",
  "raise",
  "del",
  "lambda",
  "not",
  "and",
  "or",
  "in",
  "is",
  "match",
  "case",
  "print",
  "import",
  "from",
  "class",
  "def",
  "async",
  "global",
  "nonlocal",
  "try",
  "finally",
  "else",
  "pass",
  "continue",
  "break",
  "await",
]);
const BRANCH_RE = /\b(?:if|elif|for|while|and|or|except|assert|case)\b/g;

function scanPython(source: string): ScanResult {
  const chars = source.split("");
  const strings: PythonString[] = [];
  let index = 0;

  const mask = (start: number, end: number): void => {
    for (let position = start; position < end; position += 1) {
      if (chars[position] !== "\n") {
        chars[position] = " ";
      }
    }
  };

  while (index < source.length) {
    const char = source[index] ?? "";

    if (char === "#") {
      const end = source.indexOf("\n", index);
      const stop = end === -1 ? source.length : end;
      mask(index, stop);
      index = stop;
      continue;
    }

    if (char === '"' || char === "'") {
      // Collect a contiguous string prefix (r/b/u/f combinations).
      let prefixStart = index;
      while (prefixStart > 0 && /[rRbBuUfF]/.test(source[prefixStart - 1] ?? "")) {
        prefixStart -= 1;
      }
      const prefix = source.slice(prefixStart, index).toLowerCase();
      const quote = char;
      const triple = source.startsWith(quote.repeat(3), index);
      const contentStart = index + (triple ? 3 : 1);
      let cursor = contentStart;
      let value = "";

      while (cursor < source.length) {
        if (source[cursor] === "\\") {
          value += source[cursor + 1] ?? "";
          cursor += 2;
          continue;
        }
        if (triple) {
          if (source.startsWith(quote.repeat(3), cursor)) {
            cursor += 3;
            break;
          }
        } else if (source[cursor] === quote) {
          cursor += 1;
          break;
        }
        value += source[cursor];
        cursor += 1;
      }

      const end = cursor;
      strings.push({
        start: index,
        end,
        value,
        kind: prefix.includes("f") ? "template" : "string",
      });
      mask(prefixStart, end);
      index = end;
      continue;
    }

    index += 1;
  }

  return { masked: chars.join(""), strings };
}

function parseNames(clause: string): string[] {
  return clause
    .replace(/[()]/g, " ")
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const [name, alias] = part.split(/\s+as\s+/);
      return (alias ?? name ?? "").trim();
    })
    .filter((name) => name.length > 0 && name !== "*");
}

function extractPythonImports(masked: string): ImportFact[] {
  const imports: ImportFact[] = [];
  const lines = masked.split(/\r?\n/);

  lines.forEach((lineText, lineIndex) => {
    const fromMatch = FROM_IMPORT_RE.exec(lineText);
    if (fromMatch) {
      imports.push({
        from: fromMatch[1] ?? "",
        names: parseNames(fromMatch[2] ?? ""),
        line: lineIndex + 1,
      });
      return;
    }
    const importMatch = IMPORT_RE.exec(lineText);
    if (importMatch) {
      const clause = (importMatch[1] ?? "").split("#")[0] ?? "";
      // `import a, b as c`: emit one fact per module, matching AST semantics.
      for (const segment of clause.split(",")) {
        const [moduleName, alias] = segment.trim().split(/\s+as\s+/);
        if (!moduleName) {
          continue;
        }
        imports.push({
          from: moduleName.trim(),
          names: [(alias ?? moduleName.split(".").pop() ?? "").trim()],
          line: lineIndex + 1,
        });
      }
    }
  });

  return imports;
}

function matchingParen(masked: string, openIndex: number): number {
  let depth = 0;
  for (let index = openIndex; index < masked.length; index += 1) {
    if (masked[index] === "(") {
      depth += 1;
    } else if (masked[index] === ")") {
      depth -= 1;
      if (depth === 0) {
        return index;
      }
    }
  }
  return masked.length - 1;
}

/** Split top-level comma-separated argument ranges inside ``[start, end)``. */
function splitArguments(masked: string, start: number, end: number): Array<[number, number]> {
  const ranges: Array<[number, number]> = [];
  let depth = 0;
  let segmentStart = start;

  for (let index = start; index < end; index += 1) {
    const char = masked[index];
    if (char === "(" || char === "[" || char === "{") {
      depth += 1;
    } else if (char === ")" || char === "]" || char === "}") {
      depth = Math.max(0, depth - 1);
    } else if (char === "," && depth === 0) {
      ranges.push([segmentStart, index]);
      segmentStart = index + 1;
    }
  }
  ranges.push([segmentStart, end]);
  return ranges;
}

/** True when ``text`` (already stripped of strings) contains no dynamic code. */
function isLiteralText(text: string): boolean {
  if (text.trim() === "") {
    return true;
  }
  const withoutKeywords = text.replace(/\b(?:True|False|None)\b/g, "");
  return !/[A-Za-z_]/.test(withoutKeywords) && !/["'#]/.test(withoutKeywords);
}

/**
 * Classify one argument segment.
 *
 * Strings are blanked in ``masked``, so literal detection has to consult the
 * captured string spans. A segment that contains only strings/numbers is
 * ``literal``; an f-string or any identifier makes it ``dynamic``.
 */
function classifyArgument(
  masked: string,
  strings: PythonString[],
  start: number,
  end: number
): "literal" | "dynamic" | "blank" {
  const segmentStrings = strings.filter(
    (item) => item.start >= start && item.end <= end
  );
  let text = masked.slice(start, end).trim();

  if (text === "" && segmentStrings.length === 0) {
    return "blank";
  }
  if (text.startsWith("*")) {
    return "dynamic";
  }

  // Drop one keyword label (`sql="..."`, `timeout=10`); `==` is not a keyword.
  const keyword = /^[A-Za-z_]\w*\s*=(?!=)([\s\S]*)$/.exec(text);
  if (keyword) {
    text = (keyword[1] ?? "").trim();
  }

  if (segmentStrings.length > 0) {
    if (segmentStrings.some((item) => item.kind === "template")) {
      return "dynamic";
    }
    return isLiteralText(text) ? "literal" : "dynamic";
  }
  return isLiteralText(text) ? "literal" : "dynamic";
}

function extractPythonCalls(masked: string, strings: PythonString[]): CallFact[] {
  const starts = lineStarts(masked);
  const calls: CallFact[] = [];

  for (const match of masked.matchAll(CALL_RE)) {
    const callee = match[1] ?? "";
    if (!callee) {
      continue;
    }
    const start = match.index ?? 0;
    const before = masked.slice(Math.max(0, start - 12), start);
    if (/\b(?:def|class)\s+$/.test(before)) {
      continue;
    }
    const lastPart = callee.split(".").pop() ?? callee;
    if (CALL_KEYWORDS.has(lastPart) && !callee.includes(".")) {
      continue;
    }

    const openIndex = start + match[0].length - 1;
    const closeIndex = matchingParen(masked, openIndex);
    const { line, col } = bisectLineStarts(starts, start);

    const kinds = splitArguments(masked, openIndex + 1, closeIndex)
      .map(([argStart, argEnd]) => classifyArgument(masked, strings, argStart, argEnd))
      .filter((kind) => kind !== "blank");

    let argsKind: CallFact["args_kind"];
    if (kinds.length === 0) {
      argsKind = "empty";
    } else if (kinds.every((kind) => kind === "literal")) {
      argsKind = "literal";
    } else if (kinds.every((kind) => kind === "dynamic")) {
      argsKind = "dynamic";
    } else {
      argsKind = "mixed";
    }

    calls.push({ callee, line, col, args_kind: argsKind });
  }

  return calls;
}

function extractPythonFunctions(masked: string): FunctionFact[] {
  const functions: FunctionFact[] = [];
  const lines = masked.split(/\r?\n/);

  lines.forEach((lineText, index) => {
    const match = DEF_RE.exec(lineText);
    if (!match) {
      return;
    }
    const indent = (match[1] ?? "").length;
    let complexity = 1;

    for (let cursor = index + 1; cursor < lines.length; cursor += 1) {
      const bodyLine = lines[cursor] ?? "";
      if (bodyLine.trim() === "") {
        continue;
      }
      const bodyIndent = (bodyLine.match(/^\s*/)?.[0] ?? "").length;
      if (bodyIndent <= indent) {
        break;
      }
      complexity += bodyLine.match(BRANCH_RE)?.length ?? 0;
    }

    functions.push({
      name: match[2] ?? "<anonymous>",
      line: index + 1,
      complexity,
    });
  });

  return functions;
}

function extractPythonLiterals(masked: string, strings: PythonString[]): LiteralFact[] {
  const starts = lineStarts(masked);
  return strings.map((item) => {
    const { line, col } = bisectLineStarts(starts, item.start);
    return {
      value: item.value.slice(0, 120),
      line,
      col,
      kind: item.kind,
    };
  });
}

export function extractPythonFacts(source: string): FileFacts {
  const { masked, strings } = scanPython(source);
  return {
    imports: extractPythonImports(masked),
    calls: extractPythonCalls(masked, strings),
    literals: extractPythonLiterals(masked, strings),
    functions: extractPythonFunctions(masked),
  };
}
