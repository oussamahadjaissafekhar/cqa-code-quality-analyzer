/**
 * Deterministic source walker for the TypeScript packages.
 *
 * The Python CLI owns real discovery (gitignore + config). This helper exists
 * for parser-level tooling/tests and mirrors the important safety properties:
 * sorted output, no symlinks, and standard build directories skipped.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import type { Language } from "@cqa/shared";

export const LANGUAGE_BY_EXTENSION: Record<string, Language> = {
  ".py": "python",
  ".pyi": "python",
  ".ts": "typescript",
  ".tsx": "typescript",
  ".mts": "typescript",
  ".cts": "typescript",
  ".js": "javascript",
  ".jsx": "javascript",
  ".mjs": "javascript",
  ".cjs": "javascript",
};

export interface WalkOptions {
  include?: string[];
  exclude?: string[];
  languages?: Language[];
}

const DEFAULT_EXCLUDES = [".git", "node_modules", "dist", "build", ".venv", "venv", "__pycache__"];

function globToRegExp(pattern: string): RegExp {
  const normalized = pattern.replace(/\\/g, "/").replace(/^\.\//, "");
  let source = "";
  for (let index = 0; index < normalized.length; index += 1) {
    const char = normalized[index];
    if (char === "*") {
      if (normalized[index + 1] === "*") {
        index += 1;
        if (normalized[index + 1] === "/") {
          index += 1;
          source += "(?:.*/)?";
        } else {
          source += ".*";
        }
      } else {
        source += "[^/]*";
      }
    } else if (char === "?") {
      source += "[^/]";
    } else {
      source += char?.replace(/[.+^${}()|[\]\\]/g, "\\$&") ?? "";
    }
  }
  return new RegExp(`^${source}$`);
}

function expandBraces(pattern: string): string[] {
  const match = /\{([^{}]+)\}/.exec(pattern);
  if (!match) {
    return [pattern];
  }
  const [full, body] = match;
  return (body ?? "")
    .split(",")
    .flatMap((part) => expandBraces(pattern.replace(full, part)));
}

export function languageForPath(filePath: string): Language | null {
  return LANGUAGE_BY_EXTENSION[path.extname(filePath).toLowerCase()] ?? null;
}

export function walkSourceFiles(root: string, options: WalkOptions = {}): string[] {
  const include = (options.include ?? []).flatMap(expandBraces).map(globToRegExp);
  const exclude = (options.exclude ?? []).flatMap(expandBraces).map(globToRegExp);
  const languages = new Set<Language>(options.languages ?? ["python", "typescript", "javascript"]);
  const found: string[] = [];

  const visit = (directory: string, base: string): void => {
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(directory, { withFileTypes: true });
    } catch {
      return;
    }
    entries.sort((left, right) => left.name.localeCompare(right.name));

    for (const entry of entries) {
      if (entry.isSymbolicLink()) {
        continue;
      }
      const relative = base ? `${base}/${entry.name}` : entry.name;
      if (entry.isDirectory()) {
        if (DEFAULT_EXCLUDES.includes(entry.name)) {
          continue;
        }
        if (exclude.some((regex) => regex.test(relative))) {
          continue;
        }
        visit(path.join(directory, entry.name), relative);
        continue;
      }
      if (!entry.isFile()) {
        continue;
      }
      const language = languageForPath(entry.name);
      if (!language || !languages.has(language)) {
        continue;
      }
      if (include.length > 0 && !include.some((regex) => regex.test(relative))) {
        continue;
      }
      if (exclude.some((regex) => regex.test(relative))) {
        continue;
      }
      found.push(relative);
    }
  };

  if (fs.statSync(root).isFile()) {
    const language = languageForPath(root);
    return language && languages.has(language) ? [path.basename(root)] : [];
  }

  visit(root, "");
  return found;
}
