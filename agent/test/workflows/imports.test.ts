// Import hygiene for the thread-phase workflow layer (Stage S disposition 4).
//
// Two independent proofs:
//
//  1. STATIC — the three workflow modules must never name the thread-phase root
//     barrel (or a deep `dist/` path). The eslint `no-restricted-imports` rule
//     enforces this in CI; this assertion makes the failure legible in the unit
//     suite too, and additionally forbids the bundled `SqliteJobStore` /
//     `node:sqlite` (the packaged sidecar carries no database).
//
//  2. DYNAMIC — a resolution trace over a real `node` process: importing the
//     `/session` and `/patterns` subpaths must load ZERO `openai` modules and
//     zero native `.node` addons, while importing the root barrel demonstrably
//     does load `openai` (so the trace is proven sensitive, not vacuous).

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import process from "node:process";
import { describe, expect, it } from "vitest";

const here = path.dirname(fileURLToPath(import.meta.url));
const agentDir = path.resolve(here, "..", "..");
const WORKFLOW_SOURCES = ["jobstore.ts", "runner.ts", "cad_workflow.ts"] as const;

function sourceOf(name: string): string {
  return readFileSync(path.join(agentDir, "src", "workflows", name), "utf8");
}

/** Every module specifier that appears in a static/dynamic import position. */
function importedSpecifiers(source: string): string[] {
  const specifiers: string[] = [];
  const patterns = [
    /\bfrom\s+"([^"]+)"/g,
    /\bimport\s+"([^"]+)"/g,
    /\bimport\(\s*"([^"]+)"\s*\)/g,
    /\brequire\(\s*"([^"]+)"\s*\)/g,
  ];
  for (const pattern of patterns) {
    for (const match of source.matchAll(pattern)) {
      const specifier = match[1];
      if (specifier !== undefined) specifiers.push(specifier);
    }
  }
  return specifiers;
}

interface TraceReport {
  readonly specifier: string;
  readonly total: number;
  readonly openai: number;
  readonly native: string[];
}

/** Trace one import in a child `node` process via `module.registerHooks`. */
function trace(specifier: string): TraceReport {
  const script = `
    import { registerHooks } from "node:module";
    const loaded = [];
    registerHooks({ resolve(s, c, next) { const r = next(s, c); loaded.push(r.url ?? s); return r; } });
    await import(${JSON.stringify(specifier)});
    const openai = loaded.filter((u) => /[/\\\\]openai[@/\\\\]/.test(u));
    const native = loaded.filter((u) => u.endsWith(".node"));
    process.stdout.write(JSON.stringify({
      specifier: ${JSON.stringify(specifier)},
      total: loaded.length,
      openai: openai.length,
      native,
    }));
  `;
  const out = execFileSync(process.execPath, ["--input-type=module", "-e", script], {
    cwd: agentDir,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  return JSON.parse(out) as TraceReport;
}

describe("thread-phase import hygiene", () => {
  it("never names the root barrel, a deep dist path, or sqlite", () => {
    for (const name of WORKFLOW_SOURCES) {
      const specifiers = importedSpecifiers(sourceOf(name));
      expect(specifiers, `${name} imports`).not.toContain("@autonome-research/thread-phase");
      for (const specifier of specifiers) {
        expect(specifier, `${name} imports ${specifier}`).not.toMatch(
          /^@autonome-research\/thread-phase\/dist\//,
        );
        expect(specifier, `${name} imports ${specifier}`).not.toMatch(/sqlite/i);
      }
      for (const specifier of specifiers.filter((s) =>
        s.startsWith("@autonome-research/thread-phase"),
      )) {
        expect(["@autonome-research/thread-phase/session", "@autonome-research/thread-phase/patterns"])
          .toContain(specifier);
      }
      // Mentioning the bundled store in prose is fine; constructing it is not.
      expect(sourceOf(name)).not.toMatch(/new\s+SqliteJobStore/);
      expect(specifiers).not.toContain("node:sqlite");
    }
  });

  it("the eslint config forbids the root barrel inside agent/", () => {
    const config = readFileSync(path.join(agentDir, "eslint.config.js"), "utf8");
    expect(config).toMatch(/no-restricted-imports/);
    expect(config).toMatch(/"@autonome-research\/thread-phase"/);
  });

  it("loads no openai module and no native addon through the used subpaths", () => {
    for (const specifier of [
      "@autonome-research/thread-phase/session",
      "@autonome-research/thread-phase/patterns",
    ]) {
      const report = trace(specifier);
      expect(report.openai, `${specifier} openai modules`).toBe(0);
      expect(report.native, `${specifier} native addons`).toEqual([]);
      expect(report.total).toBeGreaterThan(0);
    }
  });

  it("the trace is sensitive: the root barrel DOES load openai", () => {
    // Guards against a vacuous proof (e.g. a hook that records nothing).
    expect(trace("@autonome-research/thread-phase").openai).toBeGreaterThan(0);
  });
});
