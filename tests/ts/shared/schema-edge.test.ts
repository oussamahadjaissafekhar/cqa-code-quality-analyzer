import {
  ARGS_KINDS,
  ERROR_KINDS,
  LANGUAGES,
  LITERAL_KINDS,
  isEmptyFileFacts,
  isParserRequest,
  validateFileFacts,
  validateParserRequest,
} from "@cqa/shared";

const emptyFacts = { imports: [], calls: [], literals: [], functions: [] };

describe("validateParserRequest edge cases", () => {
  it.each([null, undefined, 1, "request", [], true])("rejects non-object %p", (value) => {
    expect(validateParserRequest(value)).toEqual(["request must be an object"]);
  });

  it("rejects a missing or non-array files field", () => {
    expect(validateParserRequest({ schema_version: 1 })).toContain("files must be an array");
    expect(validateParserRequest({ schema_version: 1, files: {} })).toContain(
      "files must be an array"
    );
  });

  it("rejects non-positive or non-integer jobs", () => {
    for (const jobs of [0, -1, 1.5, Number.NaN]) {
      expect(validateParserRequest({ schema_version: 1, jobs, files: [] })).toContain(
        "jobs must be a positive integer"
      );
    }
    expect(validateParserRequest({ schema_version: 1, jobs: 1, files: [] })).toEqual([]);
  });

  it("reports every bad file field with an index", () => {
    const errors = validateParserRequest({
      schema_version: 2,
      files: [
        null,
        { path: "", language: "ruby", content: 7 },
        { path: "ok.py", language: "python" },
      ],
    });
    expect(errors).toEqual(
      expect.arrayContaining([
        "schema_version must be 1",
        "files[0] must be an object",
        "files[1].path must be a non-empty string",
        "files[1].language is invalid",
        "files[1].content must be a string when present",
      ])
    );
  });

  it("isParserRequest mirrors the validator", () => {
    expect(isParserRequest({ schema_version: 1, files: [] })).toBe(true);
    expect(isParserRequest({ schema_version: 1, files: [{ path: "a.py", language: "python" }] })).toBe(
      true
    );
    expect(isParserRequest({ schema_version: 2, files: [] })).toBe(false);
  });
});

describe("validateFileFacts edge cases", () => {
  it.each([null, [], "facts", 3])("rejects non-object %p", (value) => {
    expect(validateFileFacts(value)).toEqual(["facts must be an object"]);
  });

  it("requires all four fact arrays", () => {
    const errors = validateFileFacts({ imports: [] });
    expect(errors).toEqual(
      expect.arrayContaining([
        "facts.calls must be an array",
        "facts.literals must be an array",
        "facts.functions must be an array",
      ])
    );
  });

  it("accepts empty and populated valid facts", () => {
    expect(validateFileFacts(emptyFacts)).toEqual([]);
    expect(
      validateFileFacts({
        imports: [{ from: "fs", names: ["readFileSync"], line: 1 }],
        calls: [{ callee: "eval", line: 1, col: 1, args_kind: "dynamic" }],
        literals: [{ value: "x", line: 1, col: 1, kind: "string" }],
        functions: [{ name: "f", line: 1, complexity: 1 }],
      })
    ).toEqual([]);
  });

  it("rejects invalid nested facts", () => {
    const errors = validateFileFacts({
      imports: [{ from: 1, names: [], line: 0 }],
      calls: [{ callee: "eval", line: 0, col: 0, args_kind: "sometimes" }],
      literals: [{ value: 1, line: 1, col: 1, kind: "regex" }],
      functions: [{ name: "f", line: 1, complexity: 0 }],
    });
    expect(errors).toEqual([
      "facts.imports[0] is invalid",
      "facts.calls[0] is invalid",
      "facts.literals[0] is invalid",
      "facts.functions[0] is invalid",
    ]);
  });

  it("is_empty fact guard mirrors validation", () => {
    expect(isEmptyFileFacts(emptyFacts)).toBe(true);
    expect(isEmptyFileFacts({})).toBe(false);
  });
});

describe("exported contract enums", () => {
  it("matches the schema v1 allowed values", () => {
    expect(LANGUAGES).toEqual(["python", "typescript", "javascript"]);
    expect(ARGS_KINDS).toEqual(["empty", "literal", "dynamic", "mixed"]);
    expect(LITERAL_KINDS).toEqual(["string", "template", "number", "boolean"]);
    expect(ERROR_KINDS).toEqual(["parse", "io", "internal"]);
  });
});
