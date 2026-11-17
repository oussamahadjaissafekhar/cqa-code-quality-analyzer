/** String/template literal extraction. Values are truncated to 120 chars (IPC). */

import type { LiteralFact } from "@cqa/shared";
import type { Token } from "../tokenize";

export const MAX_LITERAL_LENGTH = 120;

export function extractLiterals(tokens: Token[]): LiteralFact[] {
  const literals: LiteralFact[] = [];
  for (const token of tokens) {
    if (token.kind !== "string" && token.kind !== "template") {
      continue;
    }
    literals.push({
      value: token.value.slice(0, MAX_LITERAL_LENGTH),
      line: token.line,
      col: token.col,
      kind: token.kind === "template" ? "template" : "string",
    });
  }
  return literals;
}
