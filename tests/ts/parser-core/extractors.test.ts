import { extractJavascriptFacts, extractPythonFacts, extractTypescriptFacts } from "@cqa/parser-core";
import { validateFileFacts } from "@cqa/shared";

describe("JavaScript/TypeScript extractors", () => {
  const source = `
import { exec } from "child_process";
import fs from "node:fs";
export function handler(command: string): string {
  if (command) {
    exec(command);
  }
  return eval(command);
}
const run = (value: string) => value ? fs.readFileSync("config.json") : null;
`;

  it("extracts static imports with names and lines", () => {
    const facts = extractTypescriptFacts(source);
    expect(facts.imports).toEqual(
      expect.arrayContaining([
        { from: "child_process", names: ["exec"], line: 2 },
        { from: "node:fs", names: ["fs"], line: 3 },
      ])
    );
    expect(validateFileFacts(facts)).toEqual([]);
  });

  it("extracts calls with callee and argument kinds", () => {
    const facts = extractJavascriptFacts(source);
    const execCall = facts.calls.find((call) => call.callee === "exec");
    const evalCall = facts.calls.find((call) => call.callee === "eval");
    const readCall = facts.calls.find((call) => call.callee.endsWith("readFileSync"));
    expect(execCall?.args_kind).toBe("dynamic");
    expect(evalCall?.args_kind).toBe("dynamic");
    expect(readCall?.args_kind).toBe("literal");
    expect(execCall?.line).toBe(6);
  });

  it("extracts literals with 1-based positions", () => {
    const facts = extractJavascriptFacts(source);
    expect(facts.literals.map((item) => item.value)).toEqual(
      expect.arrayContaining(["child_process", "node:fs", "config.json"])
    );
    expect(facts.literals.every((item) => item.line >= 1 && item.col >= 1)).toBe(true);
  });

  it("computes function complexity and handles return type annotations", () => {
    const facts = extractTypescriptFacts(source);
    const handler = facts.functions.find((item) => item.name === "handler");
    const arrow = facts.functions.find((item) => item.name === "run");
    expect(handler).toBeDefined();
    expect(handler?.complexity).toBeGreaterThanOrEqual(2);
    expect(arrow).toBeDefined();
    expect(arrow?.complexity).toBeGreaterThanOrEqual(2);
  });

  it("does not report member calls twice", () => {
    const facts = extractJavascriptFacts("child_process.exec(cmd);");
    expect(facts.calls.filter((call) => call.callee === "exec")).toHaveLength(0);
    expect(facts.calls.filter((call) => call.callee === "child_process.exec")).toHaveLength(1);
  });

  it("marks static templates literal and interpolated templates dynamic", () => {
    const staticFacts = extractJavascriptFacts("const x = `SELECT * FROM t`; run(x);");
    const dynamicFacts = extractJavascriptFacts("const x = `SELECT ${id}`; run(x);");
    expect(staticFacts.literals[0]?.kind).toBe("template");
    expect(dynamicFacts.literals[0]?.kind).toBe("template");
    expect(dynamicFacts.calls[0]?.args_kind).toBe("dynamic");
  });
});

describe("Python extractor", () => {
  const source = `
import yaml
from os import path
import sqlite3

API_KEY = "AKIAIOSFODNN7EXAMPLE"

def classify(value):
    if value < 0:
        return "negative"
    for item in range(3):
        if item:
            return item
    return eval(value)

def load(conn, name):
    query = "SELECT * FROM users WHERE name = '" + name + "'"
    return conn.execute(query)
`;

  it("extracts imports, literals, calls and complexity", () => {
    const facts = extractPythonFacts(source);
    expect(facts.imports).toEqual(
      expect.arrayContaining([
        { from: "yaml", names: ["yaml"], line: 2 },
        { from: "os", names: ["path"], line: 3 },
      ])
    );
    expect(facts.literals.map((item) => item.value)).toEqual(
      expect.arrayContaining(["AKIAIOSFODNN7EXAMPLE", "negative"])
    );
    expect(facts.calls.map((call) => call.callee)).toEqual(
      expect.arrayContaining(["eval", "conn.execute"])
    );
    const classify = facts.functions.find((item) => item.name === "classify");
    expect(classify?.complexity).toBeGreaterThanOrEqual(4);
    expect(validateFileFacts(facts)).toEqual([]);
  });

  it("masks comments and docstrings from structural extraction", () => {
    const facts = extractPythonFacts(
      '"""eval(do_not_call)"""\n# yaml.load(raw)\nx = 1\n'
    );
    expect(facts.calls).toEqual([]);
    expect(facts.literals).toHaveLength(1);
  });
});
