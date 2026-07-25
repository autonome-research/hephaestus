import { describe, it, expect } from "vitest";
import {
  profileDefinition,
  toolsForProfile,
  systemPromptForProfile,
  sessionDirFor,
  PROVENANCE_INSTRUCTION,
  QUERY_SNAPSHOT_MAX_OUTPUT_TOKENS,
  QUERY_SNAPSHOT_MAX_TURNS,
  QUERY_SNAPSHOT_TIMEOUT_MS,
} from "../../src/session/profiles.js";

const ORCHESTRATOR_ONLY = [
  "create_part",
  "read_globals",
  "edit_globals",
  "list_project_checks",
  "create_project_check",
  "read_project_check",
  "edit_project_check",
  "delegate_part_agent",
  "get_delegation_status",
  "cancel_delegation",
];

describe("profile tool subsets", () => {
  it("part profile excludes every orchestrator-only tool", () => {
    const part = toolsForProfile("part");
    for (const name of ORCHESTRATOR_ONLY) {
      expect(part).not.toContain(name);
    }
  });

  it("part profile keeps the shared authoring/read tools", () => {
    const part = toolsForProfile("part");
    for (const name of ["read_part", "edit_part", "build_part", "inspect_part", "measure", "export_part"]) {
      expect(part).toContain(name);
    }
  });

  it("orchestrator profile is a strict superset of the part profile", () => {
    const part = new Set(toolsForProfile("part"));
    const orch = new Set(toolsForProfile("orchestrator"));
    for (const name of part) expect(orch.has(name)).toBe(true);
    for (const name of ORCHESTRATOR_ONLY) expect(orch.has(name)).toBe(true);
    expect(orch.size).toBeGreaterThan(part.size);
  });

  it("quick_edit has no orchestrator tools", () => {
    const quick = toolsForProfile("quick_edit");
    for (const name of ORCHESTRATOR_ONLY) expect(quick).not.toContain(name);
    expect(quick).toContain("edit_part");
  });

  it("query_snapshot is toolless", () => {
    expect(toolsForProfile("query_snapshot")).toEqual([]);
  });
});

describe("profile definitions", () => {
  it("query_snapshot: no persistence, no extensions, single-turn/token/time budget", () => {
    const def = profileDefinition("query_snapshot");
    expect(def.tools).toEqual([]);
    expect(def.persist).toBe(false);
    expect(def.extensions).toBe(false);
    expect(def.budget.maxTurns).toBe(QUERY_SNAPSHOT_MAX_TURNS);
    expect(def.budget.maxOutputTokens).toBe(QUERY_SNAPSHOT_MAX_OUTPUT_TOKENS);
    expect(def.budget.timeoutMs).toBe(QUERY_SNAPSHOT_TIMEOUT_MS);
    expect(QUERY_SNAPSHOT_MAX_TURNS).toBe(1);
    expect(QUERY_SNAPSHOT_MAX_OUTPUT_TOKENS).toBe(1024);
    expect(QUERY_SNAPSHOT_TIMEOUT_MS).toBe(60_000);
  });

  it("part/orchestrator persist with no ambient extensions", () => {
    for (const profile of ["part", "orchestrator", "quick_edit"] as const) {
      const def = profileDefinition(profile);
      expect(def.persist).toBe(true);
      expect(def.extensions).toBe(false);
    }
  });
});

describe("system prompt", () => {
  it("always carries the provenance instruction", () => {
    for (const profile of ["part", "orchestrator", "quick_edit", "query_snapshot"] as const) {
      expect(systemPromptForProfile(profile)).toContain(PROVENANCE_INSTRUCTION);
    }
  });

  it("names the bound part when provided", () => {
    expect(systemPromptForProfile("part", { part: "widget" })).toContain("widget");
  });
});

describe("session directory", () => {
  it("is <root>/.heph/sessions/<id>", () => {
    expect(sessionDirFor("/proj", "abc")).toBe("/proj/.heph/sessions/abc");
  });
});
