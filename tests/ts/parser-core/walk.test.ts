import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { walkSourceFiles } from "@cqa/parser-core";

describe("walkSourceFiles", () => {
  let root: string;

  beforeAll(() => {
    root = fs.mkdtempSync(path.join(os.tmpdir(), "cqa-walk-"));
    fs.writeFileSync(path.join(root, "b.py"), "x = 1\n");
    fs.writeFileSync(path.join(root, "a.ts"), "export const x = 1;\n");
    fs.mkdirSync(path.join(root, "src"));
    fs.writeFileSync(path.join(root, "src", "c.js"), "const x = 1;\n");
    fs.writeFileSync(path.join(root, "src", "notes.txt"), "ignore me\n");
    fs.mkdirSync(path.join(root, "node_modules"));
    fs.writeFileSync(path.join(root, "node_modules", "skip.js"), "const x = 1;\n");
  });

  afterAll(() => {
    fs.rmSync(root, { recursive: true, force: true });
  });

  it("returns sorted, root-relative POSIX paths and skips node_modules", () => {
    expect(walkSourceFiles(root)).toEqual(["a.ts", "b.py", "src/c.js"]);
  });

  it("honours language and include filters", () => {
    expect(walkSourceFiles(root, { languages: ["python"] })).toEqual(["b.py"]);
    expect(walkSourceFiles(root, { include: ["src/**/*.js"] })).toEqual(["src/c.js"]);
  });
});
