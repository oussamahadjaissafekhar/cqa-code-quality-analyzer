/**
 * Hand-aligned TypeScript mirrors of `contracts/*.schema.json`.
 * Contract changes require a spec revision and a schema version bump.
 */

export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type Language = "python" | "typescript" | "javascript";
export type ErrorKind = "parse" | "io" | "internal";
export type ArgsKind = "empty" | "literal" | "dynamic" | "mixed";
export type LiteralKind = "string" | "template" | "number" | "boolean";

export interface Finding {
  schema_version: 1;
  rule_id: string;
  severity: Severity;
  message: string;
  path: string;
  start_line: number;
  start_col: number;
  end_line: number;
  end_col: number;
  fingerprint: string;
  snippet?: string;
  help_uri?: string;
}

export interface AnalysisError {
  path: string;
  message: string;
  kind: ErrorKind;
}

export interface AnalysisSummary {
  files_scanned: number;
  findings: number;
  by_severity: Record<Severity, number>;
  score: number;
  truncated: boolean;
  failed: boolean;
}

export interface ToolInfo {
  name: "cqa";
  version: string;
  parser_version: string;
}

export interface AnalysisResult {
  schema_version: 1;
  tool: ToolInfo;
  generated_at: string;
  root: string;
  summary: AnalysisSummary;
  findings: Finding[];
  errors: AnalysisError[];
}

export interface ImportFact {
  from: string;
  names: string[];
  line: number;
}

export interface CallFact {
  callee: string;
  line: number;
  col: number;
  args_kind: ArgsKind;
}

export interface LiteralFact {
  value: string;
  line: number;
  col: number;
  kind: LiteralKind;
}

export interface FunctionFact {
  name: string;
  line: number;
  complexity: number;
}

export interface FileFacts {
  imports: ImportFact[];
  calls: CallFact[];
  literals: LiteralFact[];
  functions: FunctionFact[];
}

export interface ParserFile {
  path: string;
  language: Language;
  content?: string;
}

export interface ParserRequest {
  schema_version: 1;
  jobs?: number;
  files: ParserFile[];
}

export interface ParserFileResult {
  path: string;
  language: string;
  ok: boolean;
  error?: string;
  facts: FileFacts;
}

export interface ParserResponse {
  schema_version: 1;
  files: ParserFileResult[];
  errors: AnalysisError[];
}

export function emptyFacts(): FileFacts {
  return { imports: [], calls: [], literals: [], functions: [] };
}
