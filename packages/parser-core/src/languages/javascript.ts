/** JavaScript fact extraction (also the base for TypeScript). */

import type { FileFacts } from "@cqa/shared";
import { tokenize } from "../tokenize";
import { extractCalls } from "../extractors/calls";
import { extractFunctions } from "../extractors/functions";
import { extractImports } from "../extractors/imports";
import { extractLiterals } from "../extractors/literals";

export function extractJavascriptFacts(source: string): FileFacts {
  const tokens = tokenize(source);
  return {
    imports: extractImports(tokens),
    calls: extractCalls(tokens),
    literals: extractLiterals(tokens),
    functions: extractFunctions(tokens),
  };
}
