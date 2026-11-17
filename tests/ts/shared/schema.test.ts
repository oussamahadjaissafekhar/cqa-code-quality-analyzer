import { validateFileFacts, validateParserRequest } from "@cqa/shared";

describe("shared contract guards", () => {
  it("accepts a minimal parser request", () => {
    expect(
      validateParserRequest({
        schema_version: 1,
        files: [{ path: "a.py", language: "python", content: "x = 1\n" }],
      })
    ).toEqual([]);
  });

  it("rejects unknown languages and bad versions", () => {
    const errors = validateParserRequest({
      schema_version: 2,
      files: [{ path: "a.rb", language: "ruby" }],
    });
    expect(errors.length).toBeGreaterThanOrEqual(2);
  });

  it("rejects malformed facts", () => {
    const errors = validateFileFacts({
      imports: [{ from: "fs", names: [], line: 0 }],
      calls: [],
      literals: [],
      functions: [],
    });
    expect(errors.length).toBe(1);
  });
});
