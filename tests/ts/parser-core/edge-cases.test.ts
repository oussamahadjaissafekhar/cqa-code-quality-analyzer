import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import {
  extractFacts,
  extractJavascriptFacts,
  extractPythonFacts,
  extractTypescriptFacts,
  languageForPath,
  tokenize,
  walkSourceFiles,
} from "@cqa/parser-core";
import { validateFileFacts } from "@cqa/shared";

describe("empty sources", () => {
  it.each(["python", "typescript", "javascript"] as const)(
    "returns empty facts for an empty %s file",
    (language) => {
      const facts = extractFacts(language, "");
      expect(facts).toEqual({ imports: [], calls: [], literals: [], functions: [] });
      expect(validateFileFacts(facts)).toEqual([]);
    }
  );

  it.each(["python", "typescript", "javascript"] as const)(
    "ignores whitespace and comments in %s",
    (language) => {
      const source = language === "python" ? "  \n# only a comment\n\n" : " // line\n/* block */\n";
      const facts = extractFacts(language, source);
      expect(facts.imports).toEqual([]);
      expect(facts.calls).toEqual([]);
      expect(facts.functions).toEqual([]);
    }
  );

  it("tokenizes an empty or comment-only file to no tokens", () => {
    expect(tokenize("")).toEqual([]);
    expect(tokenize("  \n\t\r\n")).toEqual([]);
    expect(tokenize("// comment\n/* block */")).toEqual([]);
  });
});

describe("malformed syntax never crashes fact extraction", () => {
  const cases: Array<[string, "python" | "typescript" | "javascript", string]> = [
    ["python", "python", "def broken(:\n    pass\n"],
    ["python-unclosed", "python", "value = (1 + \n"],
    ["python-indent", "python", "def f():\nreturn 1\n"],
    ["ts-unterminated-string", "typescript", "const value = 'unterminated\n"],
    ["ts-unterminated-comment", "typescript", "/* never closed\nconst x = 1;\n"],
    ["ts-broken-arrow", "typescript", "const f = (x) => { if (x) { return ;\n"],
    ["js-broken-call", "javascript", "eval(\n"],
  ];

  it.each(cases)("%s returns schema-valid facts instead of throwing", (_name, language, source) => {
    const facts = extractFacts(language, source);
    expect(validateFileFacts(facts)).toEqual([]);
    expect(Array.isArray(facts.imports)).toBe(true);
    expect(Array.isArray(facts.calls)).toBe(true);
  });
});

describe("Python argument classification and positions", () => {
  const kindOf = (source: string, callee = "conn.execute") =>
    extractPythonFacts(source).calls.find((call) => call.callee === callee)?.args_kind;

  it("marks a single string argument as literal", () => {
    expect(kindOf('conn.execute("SELECT * FROM users")\n')).toBe("literal");
  });

  it("marks numeric literals and tuples as literal", () => {
    expect(kindOf("run(1, 2, -3)\n", "run")).toBe("literal");
  });

  it("marks no arguments as empty", () => {
    expect(kindOf("eval()\n", "eval")).toBe("empty");
  });

  it("marks identifiers and starred arguments as dynamic", () => {
    expect(kindOf("conn.execute(query)\n")).toBe("dynamic");
    expect(kindOf("run(*args)\n", "run")).toBe("dynamic");
  });

  it("marks f-strings as dynamic", () => {
    expect(kindOf('conn.execute(f"SELECT * FROM t WHERE id = {user_id}")\n')).toBe("dynamic");
  });

  it("marks literal/dynamic blends as mixed", () => {
    expect(kindOf('conn.execute("SELECT * FROM users WHERE id = %s", params)\n')).toBe("mixed");
  });

  it("treats containers and keyword literals as literal", () => {
    expect(kindOf("run([1, 2], (3, 4), {'a': 1})\n", "run")).toBe("literal");
    expect(kindOf("run(sql='SELECT 1', limit=10)\n", "run")).toBe("literal");
  });

  it("preserves CRLF positions for literals", () => {
    const facts = extractPythonFacts('x = 1\r\nbad = "value"\r\n');
    const literal = facts.literals.find((item) => item.value === "value");
    expect(literal).toMatchObject({ line: 2, col: 7, kind: "string" });
  });

  it("extracts dotted, aliased and relative imports", () => {
    const facts = extractPythonFacts(
      "import os, sys as system\nfrom . import local\nfrom ..pkg import thing as alias\n"
    );
    expect(facts.imports).toEqual(
      expect.arrayContaining([
        { from: "os", names: ["os"], line: 1 },
        { from: "sys", names: ["system"], line: 1 },
        { from: ".", names: ["local"], line: 2 },
        { from: "..pkg", names: ["alias"], line: 3 },
      ])
    );
  });

  it("does not treat strings or comments as calls", () => {
    const facts = extractPythonFacts('"""eval(no)"""\n# eval(no)\ntext = "eval(no)"\n');
    expect(facts.calls).toEqual([]);
  });
});

describe("JavaScript argument classification", () => {
  const kindOf = (source: string, callee = "eval") =>
    extractJavascriptFacts(source).calls.find((call) => call.callee === callee)?.args_kind;

  it("classifies empty, literal, dynamic and mixed calls", () => {
    expect(kindOf("eval();")).toBe("empty");
    expect(kindOf("eval('x');")).toBe("literal");
    expect(kindOf("eval(value);")).toBe("dynamic");
    expect(kindOf("eval(value, 'x');")).toBe("mixed");
  });

  it("classifies negative numbers, templates and spreads", () => {
    expect(kindOf("eval(-42);")).toBe("literal");
    expect(kindOf("eval(`static`);")).toBe("literal");
    expect(kindOf("eval(`value ${x}`);")).toBe("dynamic");
    expect(kindOf("eval(...args);")).toBe("dynamic");
  });

  it("supports dynamic imports and require", () => {
    const facts = extractJavascriptFacts(
      'const a = await import("dynamic");\nconst b = require("legacy");\n'
    );
    expect(facts.imports.map((item) => item.from)).toEqual(
      expect.arrayContaining(["dynamic", "legacy"])
    );
  });
});

describe("function complexity edge cases", () => {
  const names = (source: string) => extractTypescriptFacts(source).functions;

  it("counts decision points in declarations, arrows and methods", () => {
    const facts = names(
      [
        "function declared(a) { if (a) { return 1; } return 0; }",
        "const arrow = (a) => { if (a) { return 1; } return 0; };",
        "const expression = (a) => a ? 1 : 0;",
        "class Box { method(a) { if (a) { return 1; } } }",
      ].join("\n")
    );
    for (const name of ["declared", "arrow", "expression", "method"]) {
      const fn = facts.find((item) => item.name === name);
      expect(fn?.complexity).toBeGreaterThanOrEqual(2);
    }
  });

  it("does not report declarations without a body as functions", () => {
    expect(names("declare function external(value: string): void;")).toEqual([]);
  });
});

describe("walkSourceFiles edge cases", () => {
  let root: string;

  beforeEach(() => {
    root = fs.mkdtempSync(path.join(os.tmpdir(), "cqa-walk-edge-"));
  });

  afterEach(() => {
    fs.rmSync(root, { recursive: true, force: true });
  });

  it("returns an empty list for an empty directory", () => {
    expect(walkSourceFiles(root)).toEqual([]);
  });

  it("returns only a supported single-file root", () => {
    const file = path.join(root, "single.PY");
    fs.writeFileSync(file, "x = 1\n");
    expect(walkSourceFiles(file)).toEqual(["single.PY"]);
    const text = path.join(root, "notes.txt");
    fs.writeFileSync(text, "hello\n");
    expect(walkSourceFiles(text)).toEqual([]);
  });

  it("supports brace includes and explicit excludes", () => {
    fs.mkdirSync(path.join(root, "src", "nested"), { recursive: true });
    fs.writeFileSync(path.join(root, "src", "a.py"), "x = 1\n");
    fs.writeFileSync(path.join(root, "src", "nested", "b.ts"), "const x = 1;\n");
    fs.writeFileSync(path.join(root, "src", "nested", "skip.py"), "x = 1\n");
    expect(
      walkSourceFiles(root, {
        include: ["src/**/*.{py,ts}"],
        exclude: ["**/skip.py"],
      })
    ).toEqual(["src/a.py", "src/nested/b.ts"]);
  });

  it("maps extensions to languages case-insensitively", () => {
    expect(languageForPath("a.PY")).toBe("python");
    expect(languageForPath("a.TSX")).toBe("typescript");
    expect(languageForPath("a.MJS")).toBe("javascript");
    expect(languageForPath("a.rb")).toBeNull();
  });
});
