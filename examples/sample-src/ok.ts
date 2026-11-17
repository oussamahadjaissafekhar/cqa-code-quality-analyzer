import { readFileSync } from "node:fs";

/** A small, clean function used as the "ok" parser fixture. */
export function readConfig(path: string): string {
  const content = readFileSync(path, "utf-8");
  return content.trim();
}

export function pick<T>(items: T[], index: number): T | undefined {
  return items[index];
}
