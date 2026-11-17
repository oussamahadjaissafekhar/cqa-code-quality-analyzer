/**
 * TypeScript is a JavaScript superset for the facts CQA needs. Type-only
 * syntax (`interface`, `type`, annotations) is harmless to the tokenizer, so we
 * reuse the JS extractor rather than duplicating it.
 */

import type { FileFacts } from "@cqa/shared";
import { extractJavascriptFacts } from "./javascript";

export function extractTypescriptFacts(source: string): FileFacts {
  return extractJavascriptFacts(source);
}
