import { readFileSync } from "node:fs";

export function readConfig(path: string): string {
  return readFileSync(path, "utf-8").trim();
}
