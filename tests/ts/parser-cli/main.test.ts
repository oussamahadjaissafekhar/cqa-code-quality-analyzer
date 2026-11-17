import * as fs from "node:fs";
import * as path from "node:path";
import { handleInput } from "../../../packages/parser-cli/src/main";
import { extractFacts } from "@cqa/parser-core";

describe("parser-cli handleInput", () => {
  it("returns a schema-valid response for content in the request", () => {
    const request = {
      schema_version: 1,
      jobs: 2,
      files: [
        { path: "a.ts", language: "typescript", content: "eval(user);\n" },
        { path: "b.py", language: "python", content: "import yaml\nyaml.load(raw)\n" },
      ],
    };
    const { response, exitCode } = handleInput(JSON.stringify(request));
    expect(exitCode).toBe(0);
    expect(response.schema_version).toBe(1);
    expect(response.errors).toEqual([]);
    expect(response.files).toHaveLength(2);
    expect(response.files[0]?.facts.calls[0]?.callee).toBe("eval");
    expect(response.files[0]?.facts.calls[0]?.args_kind).toBe("dynamic");
    expect(response.files[1]?.facts.calls.map((call) => call.callee)).toContain("yaml.load");
  });

  it("rejects invalid JSON with exit code 2", () => {
    const { response, exitCode } = handleInput("{not json");
    expect(exitCode).toBe(2);
    expect(response.files).toEqual([]);
    expect(response.errors[0]?.kind).toBe("internal");
  });

  it("rejects a request that violates the contract", () => {
    const { response, exitCode } = handleInput(
      JSON.stringify({ schema_version: 1, files: [{ path: "x.py" }] })
    );
    expect(exitCode).toBe(2);
    expect(response.errors.length).toBeGreaterThan(0);
  });

  it("isolates unreadable files instead of aborting the batch", () => {
    const { response, exitCode } = handleInput(
      JSON.stringify({
        schema_version: 1,
        files: [
          { path: "missing-file.py", language: "python" },
          { path: "ok.py", language: "python", content: "x = 1\n" },
        ],
      })
    );
    expect(exitCode).toBe(0);
    expect(response.files[0]?.ok).toBe(false);
    expect(response.files[1]?.ok).toBe(true);
    expect(response.errors[0]?.path).toBe("missing-file.py");
  });

  it("produces JSON-serialisable output (IPC contract)", () => {
    const { response } = handleInput(
      JSON.stringify({
        schema_version: 1,
        files: [{ path: "x.ts", language: "typescript", content: "const x = 1;\n" }],
      })
    );
    expect(() => JSON.stringify(response)).not.toThrow();
    expect(Object.keys(response).sort()).toEqual(["errors", "files", "schema_version"]);
  });
});

describe("parser-cli golden facts", () => {
  it("extracts the expected facts from examples/sample-src", () => {
    const root = process.cwd();
    const tsSource = fs.readFileSync(path.join(root, "examples/sample-src/ok.ts"), "utf8");
    const pySource = fs.readFileSync(path.join(root, "examples/sample-src/vuln.py"), "utf8");

    const tsFacts = extractFacts("typescript", tsSource);
    expect(tsFacts.functions.map((item) => item.name)).toEqual(
      expect.arrayContaining(["readConfig", "pick"])
    );
    expect(tsFacts.imports[0]?.from).toBe("node:fs");

    const pyFacts = extractFacts("python", pySource);
    expect(pyFacts.calls.map((call) => call.callee)).toEqual(
      expect.arrayContaining(["yaml.load", "eval", "conn.execute"])
    );
    expect(pyFacts.functions.find((item) => item.name === "classify")?.complexity).toBeGreaterThan(10);
    expect(pyFacts.literals.map((item) => item.value)).toEqual(
      expect.arrayContaining(["AKIAIOSFODNN7EXAMPLE"])
    );
  });
});
