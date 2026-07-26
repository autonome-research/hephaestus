import { describe, it, expect } from "vitest";
import { TOOLS } from "../../src/tools/schema.gen.js";
import {
  profileDefinition,
  toolsForProfile,
  systemPromptForProfile,
  sessionDirFor,
  PROVENANCE_INSTRUCTION,
  QUERY_SNAPSHOT_MAX_OUTPUT_TOKENS,
  QUERY_SNAPSHOT_MAX_TURNS,
  QUERY_SNAPSHOT_TIMEOUT_MS,
  REVIEWER_MAX_OUTPUT_TOKENS,
  REVIEWER_MAX_TURNS,
  REVIEWER_TIMEOUT_MS,
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

  it("reviewer gets the read-only measurement/render subset only", () => {
    const reviewer = toolsForProfile("reviewer");
    expect(reviewer.sort()).toEqual(["inspect_part", "measure", "read_artifact"].sort());
    // No mutation, no delegation, and not the agent's own checks (VALIDATION §5).
    for (const name of [...ORCHESTRATOR_ONLY, "write_part", "edit_part", "build_part", "run_checks", "export_part", "set_params", "record_requirements", "update_requirement"]) {
      expect(reviewer).not.toContain(name);
    }
    for (const name of reviewer) {
      expect(TOOLS[name]!.meta.idempotent).toBe(false);
    }
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

  it("reviewer: ephemeral, no extensions, its own budget", () => {
    const def = profileDefinition("reviewer");
    expect(def.persist).toBe(false);
    expect(def.extensions).toBe(false);
    expect(def.budget.maxTurns).toBe(REVIEWER_MAX_TURNS);
    expect(def.budget.maxOutputTokens).toBe(REVIEWER_MAX_OUTPUT_TOKENS);
    expect(def.budget.timeoutMs).toBe(REVIEWER_TIMEOUT_MS);
    // Its charter, not the authoring cheatsheet: it cannot author anything.
    expect(def.systemPrompt).toContain("independent termination reviewer");
    expect(def.systemPrompt).not.toContain("PART-SCRIPT CONTRACT");
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
    for (const profile of ["part", "orchestrator", "quick_edit", "query_snapshot", "reviewer"] as const) {
      expect(systemPromptForProfile(profile)).toContain(PROVENANCE_INSTRUCTION);
    }
  });

  it("names the bound part when provided", () => {
    expect(systemPromptForProfile("part", { part: "widget" })).toContain("widget");
  });

  // VALIDATION.md §2/§3/§7. The harness is what binds these rules — build_part is
  // refused without a ledger — so the prompt only spares the model the round-trip
  // of learning that by being refused. It is necessary, never sufficient.
  it("teaches the requirement ledger to every authoring profile", () => {
    for (const profile of ["part", "orchestrator", "quick_edit"] as const) {
      const prompt = systemPromptForProfile(profile);
      expect(prompt).toContain("record_requirements");
      expect(prompt).toContain("no_ledger");
      expect(prompt).toContain("ask_user(requirement_ids=");
      expect(prompt).toContain("NOT charged against your tool-call budget");
    }
  });

  it("does not hand the reviewer the authoring rules", () => {
    const prompt = systemPromptForProfile("reviewer");
    expect(prompt).not.toContain("record_requirements");
    expect(prompt).not.toContain("PART-SCRIPT CONTRACT");
  });
});

describe("session directory", () => {
  it("is <root>/.heph/sessions/<id>", () => {
    expect(sessionDirFor("/proj", "abc")).toBe("/proj/.heph/sessions/abc");
  });
});
