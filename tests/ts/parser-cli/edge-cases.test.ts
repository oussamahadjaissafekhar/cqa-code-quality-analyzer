import { handleInput, processFile, runRequest } from "../../../packages/parser-cli/src/main";
import type { ParserRequest } from "@cqa/shared";

describe("parser-cli empty and malformed batches", () => {
  it("accepts an empty file list", () => {
    const { response, exitCode } = handleInput(JSON.stringify({ schema_version: 1, files: [] }));
    expect(exitCode).toBe(0);
    expect(response).toEqual({ schema_version: 1, files: [], errors: [] });
  });

  it.each(["python", "typescript", "javascript"] as const)(
    "returns empty facts for empty %s content",
    (language) => {
      const { response, exitCode } = handleInput(
        JSON.stringify({
          schema_version: 1,
          files: [{ path: `empty.${language}`, language, content: "" }],
        })
      );
      expect(exitCode).toBe(0);
      expect(response.errors).toEqual([]);
      expect(response.files[0]).toMatchObject({
        ok: true,
        facts: { imports: [], calls: [], literals: [], functions: [] },
      });
    }
  );

  it("keeps going after malformed source in the same batch", () => {
    const { response, exitCode } = handleInput(
      JSON.stringify({
        schema_version: 1,
        files: [
          { path: "broken.py", language: "python", content: "def broken(:\n" },
          { path: "fine.py", language: "python", content: "eval(user)\n" },
        ],
      })
    );
    expect(exitCode).toBe(0);
    expect(response.files).toHaveLength(2);
    expect(response.files[0]?.ok).toBe(true);
    expect(response.files[1]?.facts.calls.map((call) => call.callee)).toContain("eval");
  });

  it.each([
    ["content is not a string", { schema_version: 1, files: [{ path: "a.py", language: "python", content: 1 }] }],
    ["files is not an array", { schema_version: 1, files: {} }],
    ["schema version is wrong", { schema_version: 2, files: [] }],
    ["language is unknown", { schema_version: 1, files: [{ path: "a.rb", language: "ruby" }] }],
  ])("rejects a contract violation: %s", (_name, request) => {
    const { response, exitCode } = handleInput(JSON.stringify(request));
    expect(exitCode).toBe(2);
    expect(response.files).toEqual([]);
    expect(response.errors.length).toBeGreaterThan(0);
    expect(response.errors.every((error) => error.kind === "internal")).toBe(true);
  });

  it("processFile returns an isolated error for an unreadable path", () => {
    const result = processFile({ path: "definitely-missing.py", language: "python" });
    expect(result.ok).toBe(false);
    expect(result.error).toContain("cannot read file");
    expect(result.facts).toEqual({ imports: [], calls: [], literals: [], functions: [] });
  });

  it("runRequest preserves request order and reports one error per bad file", () => {
    const request: ParserRequest = {
      schema_version: 1,
      files: [
        { path: "a.py", language: "python", content: "eval(x)\n" },
        { path: "missing.py", language: "python" },
        { path: "b.ts", language: "typescript", content: "eval(x);\n" },
      ],
    };
    const response = runRequest(request);
    expect(response.files.map((file) => file.path)).toEqual(["a.py", "missing.py", "b.ts"]);
    expect(response.errors.map((error) => error.path)).toEqual(["missing.py"]);
    expect(response.errors[0]?.kind).toBe("parse");
  });
});
