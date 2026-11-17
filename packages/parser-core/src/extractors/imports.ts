/**
 * Import/require extraction from JS/TS tokens.
 *
 * Handles static imports (default, namespace, named), side-effect imports,
 * re-exports with a `from` clause, dynamic `import()` and CommonJS `require()`.
 */

import type { ImportFact } from "@cqa/shared";
import { type Token } from "../tokenize";

function isStringToken(token: Token | undefined): boolean {
  return token?.kind === "string" || token?.kind === "template";
}

const CLAUSE_IGNORED = new Set(["as", "type", "from", "import", "export", "default"]);

export function extractImports(tokens: Token[]): ImportFact[] {
  const imports: ImportFact[] = [];
  const seen = new Set<string>();

  const add = (source: string, names: string[], line: number): void => {
    const key = `${source}\u0000${line}\u0000${names.join(",")}`;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    imports.push({ from: source, names, line });
  };

  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (!token) {
      continue;
    }

    if ((token.value === "import" || token.value === "export") && token.kind === "keyword") {
      const next = tokens[index + 1];

      // Dynamic import("module")
      if (next?.value === "(") {
        const argument = tokens[index + 2];
        if (isStringToken(argument)) {
          add(argument?.value ?? "", [], token.line);
        }
        continue;
      }

      // Side-effect import "module"
      if (token.value === "import" && isStringToken(next)) {
        add(next?.value ?? "", [], token.line);
        continue;
      }

      const names: string[] = [];
      let source: string | null = null;
      let cursor = index + 1;
      // A statement cannot run forever; 200 tokens is far beyond any import.
      const limit = Math.min(tokens.length, index + 200);
      while (cursor < limit) {
        const current = tokens[cursor];
        if (!current) {
          break;
        }
        if (current.value === ";") {
          break;
        }
        if (
          (current.value === "from" || current.value === "export") &&
          isStringToken(tokens[cursor + 1])
        ) {
          source = tokens[cursor + 1]?.value ?? "";
          break;
        }
        if (current.kind === "ident" && !CLAUSE_IGNORED.has(current.value)) {
          names.push(current.value);
        }
        cursor += 1;
      }
      if (source !== null) {
        add(source, names, token.line);
      }
      continue;
    }

    // CommonJS require("module")
    if (token.kind === "ident" && token.value === "require") {
      const open = tokens[index + 1];
      const argument = tokens[index + 2];
      const close = tokens[index + 3];
      if (open?.value === "(" && isStringToken(argument) && close?.value === ")") {
        add(argument?.value ?? "", [], token.line);
      }
    }
  }

  return imports;
}
