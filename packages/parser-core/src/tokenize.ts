/**
 * A small, dependency-free JS/TS lexer.
 *
 * It is not a full ECMAScript parser. It deliberately masks comments and
 * captures strings/templates with exact 1-based positions, which is enough for
 * fact extraction (imports, calls, literals, function complexity) without
 * pulling a compiler or tree-sitter into the image.
 */

export type TokenKind = "ident" | "keyword" | "string" | "template" | "number" | "punct";

export interface Token {
  kind: TokenKind;
  value: string;
  line: number;
  col: number;
  endLine: number;
  endCol: number;
  /** Template literals containing `${...}` are not static values. */
  interpolated?: boolean;
}

const KEYWORDS = new Set([
  "as",
  "async",
  "await",
  "break",
  "case",
  "catch",
  "class",
  "const",
  "continue",
  "debugger",
  "declare",
  "default",
  "delete",
  "do",
  "else",
  "enum",
  "export",
  "extends",
  "false",
  "finally",
  "for",
  "from",
  "function",
  "get",
  "if",
  "implements",
  "import",
  "in",
  "instanceof",
  "interface",
  "let",
  "new",
  "null",
  "of",
  "package",
  "private",
  "protected",
  "public",
  "readonly",
  "return",
  "set",
  "static",
  "super",
  "switch",
  "this",
  "throw",
  "true",
  "try",
  "type",
  "typeof",
  "undefined",
  "var",
  "void",
  "while",
  "with",
  "yield",
]);

const PUNCTUATION = [
  "...",
  "===",
  "!==",
  "**=",
  "<<=",
  ">>=",
  "&&=",
  "||=",
  "??=",
  "=>",
  "?.",
  "??",
  "==",
  "!=",
  "<=",
  ">=",
  "&&",
  "||",
  "++",
  "--",
  "+=",
  "-=",
  "*=",
  "/=",
  "%=",
  "**",
  "<<",
  ">>",
  "&=",
  "|=",
  "^=",
];

const IDENT_START = /[A-Za-z_$]/;
const IDENT_PART = /[A-Za-z0-9_$]/;

export function tokenize(source: string): Token[] {
  const tokens: Token[] = [];
  let index = 0;
  let line = 1;
  let col = 1;

  const advance = (count = 1): void => {
    for (let step = 0; step < count; step += 1) {
      if (source[index] === "\n") {
        line += 1;
        col = 1;
      } else {
        col += 1;
      }
      index += 1;
    }
  };

  while (index < source.length) {
    const char = source[index] ?? "";
    const next = source[index + 1] ?? "";

    if (char === "\n" || char === " " || char === "\t" || char === "\r") {
      advance();
      continue;
    }

    if (char === "/" && next === "/") {
      while (index < source.length && source[index] !== "\n") {
        advance();
      }
      continue;
    }

    if (char === "/" && next === "*") {
      advance(2);
      while (index < source.length && !(source[index] === "*" && source[index + 1] === "/")) {
        advance();
      }
      advance(2);
      continue;
    }

    if (char === '"' || char === "'" || char === "`") {
      const quote = char;
      const startLine = line;
      const startCol = col;
      let value = "";
      let interpolated = false;
      advance();
      while (index < source.length) {
        const current = source[index] ?? "";
        if (current === "\\") {
          const escaped = source[index + 1] ?? "";
          value += escaped;
          advance(2);
          continue;
        }
        if (current === quote) {
          advance();
          break;
        }
        if (quote === "`" && current === "$" && source[index + 1] === "{") {
          interpolated = true;
        }
        value += current;
        advance();
      }
      tokens.push({
        kind: quote === "`" ? "template" : "string",
        value,
        line: startLine,
        col: startCol,
        endLine: line,
        endCol: col,
        ...(quote === "`" ? { interpolated } : {}),
      });
      continue;
    }

    if (/[0-9]/.test(char)) {
      const startLine = line;
      const startCol = col;
      let value = "";
      while (index < source.length && /[0-9a-fA-FxXoObBeE._+\-]/.test(source[index] ?? "")) {
        // Avoid swallowing binary operators that merely look numeric.
        if (
          (source[index] === "+" || source[index] === "-") &&
          !/[eE]/.test(source[index - 1] ?? "")
        ) {
          break;
        }
        value += source[index];
        advance();
      }
      tokens.push({
        kind: "number",
        value,
        line: startLine,
        col: startCol,
        endLine: line,
        endCol: col,
      });
      continue;
    }

    if (IDENT_START.test(char)) {
      const startLine = line;
      const startCol = col;
      let value = "";
      while (index < source.length && IDENT_PART.test(source[index] ?? "")) {
        value += source[index];
        advance();
      }
      tokens.push({
        kind: KEYWORDS.has(value) ? "keyword" : "ident",
        value,
        line: startLine,
        col: startCol,
        endLine: line,
        endCol: col,
      });
      continue;
    }

    const operator = PUNCTUATION.find((candidate) => source.startsWith(candidate, index));
    const value = operator ?? char;
    tokens.push({
      kind: "punct",
      value,
      line,
      col,
      endLine: line,
      endCol: col + value.length,
    });
    advance(value.length);
  }

  return tokens;
}

export function isIdentifier(token: Token | undefined): boolean {
  return token?.kind === "ident";
}

export function findMatching(
  tokens: Token[],
  openIndex: number,
  open = "(",
  close = ")"
): number {
  let depth = 0;
  for (let index = openIndex; index < tokens.length; index += 1) {
    if (tokens[index]?.value === open) {
      depth += 1;
    } else if (tokens[index]?.value === close) {
      depth -= 1;
      if (depth === 0) {
        return index;
      }
    }
  }
  return tokens.length - 1;
}
