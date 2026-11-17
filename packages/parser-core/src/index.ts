/** Public parser-core API: facts only, never verdicts. */

import type { FileFacts, Language } from "@cqa/shared";
import { extractJavascriptFacts } from "./languages/javascript";
import { extractPythonFacts } from "./languages/python";
import { extractTypescriptFacts } from "./languages/typescript";

export { extractJavascriptFacts } from "./languages/javascript";
export { extractTypescriptFacts } from "./languages/typescript";
export { extractPythonFacts } from "./languages/python";
export { extractCalls } from "./extractors/calls";
export { extractFunctions } from "./extractors/functions";
export { extractImports } from "./extractors/imports";
export { extractLiterals } from "./extractors/literals";
export { tokenize } from "./tokenize";
export { walkSourceFiles, languageForPath } from "./walk";

export function extractFacts(language: Language, source: string): FileFacts {
  switch (language) {
    case "python":
      return extractPythonFacts(source);
    case "typescript":
      return extractTypescriptFacts(source);
    case "javascript":
      return extractJavascriptFacts(source);
    default: {
      // Exhaustiveness guard for future contract changes.
      const exhaustive: never = language;
      throw new Error(`unsupported language: ${String(exhaustive)}`);
    }
  }
}
