import { describe, it, expect } from "vitest";
import { Value } from "@sinclair/typebox/value";
import { TOOLS, TOOL_NAMES } from "../src/tools/schema.gen.js";
import { PROMPT_MAX_UTF8_BYTES } from "../src/limits.js";

describe("generated tool surface", () => {
  it("declares the Stage 2 surface, the Stage 2V ledger and Stage 6 (33 tools)", () => {
    expect(TOOL_NAMES).toHaveLength(33);
    for (const ledger of ["record_requirements", "read_requirements", "update_requirement"]) {
      expect(TOOL_NAMES).toContain(ledger);
    }
    expect(Object.keys(TOOLS).sort()).toEqual([...TOOL_NAMES].sort());
  });

  it("excludes the deferred tools", () => {
    for (const excluded of ["run_fea", "import_geometry"]) {
      expect(TOOL_NAMES).not.toContain(excluded);
    }
  });

  it("carries the Stage 6 manufacturing tools", () => {
    for (const name of ["run_dfm", "generate_drawing", "generate_doc"]) {
      expect(TOOL_NAMES).toContain(name);
    }
  });

  it("carries per-profile availability and sequential/idempotent metadata", () => {
    expect(TOOLS.delegate_part_agent!.meta.profiles).toEqual(["orchestrator"]);
    expect(TOOLS.delegate_part_agent!.meta.sequential).toBe(true);
    expect(TOOLS.delegate_part_agent!.meta.idempotent).toBe(true);
    expect(TOOLS.read_part!.meta.profiles).toContain("part");
    expect(TOOLS.read_part!.meta.sequential).toBe(false);
    expect(TOOLS.create_part!.meta.profiles).toEqual(["orchestrator"]);
  });

  it("records the x-hephaestus-maxUtf8Bytes guarded field for delegation", () => {
    expect(TOOLS.delegate_part_agent!.meta.maxUtf8Fields).toEqual({
      prompt: PROMPT_MAX_UTF8_BYTES,
    });
  });
});

describe("generated TypeBox validates base shape (Value.Check)", () => {
  it("enforces the identifier pattern on create_part.name", () => {
    const s = TOOLS.create_part!.params;
    expect(Value.Check(s, { name: "good_name" })).toBe(true);
    expect(Value.Check(s, { name: "../evil" })).toBe(false);
    expect(Value.Check(s, { name: "Bad" })).toBe(false);
  });
  it("rejects additional properties on strict params", () => {
    expect(Value.Check(TOOLS.create_part!.params, { name: "p", extra: 1 })).toBe(false);
  });
  it("enforces required fields", () => {
    expect(Value.Check(TOOLS.edit_part!.params, { name: "p" })).toBe(false);
    expect(
      Value.Check(TOOLS.edit_part!.params, {
        name: "p",
        expected_hash: "h",
        old_str: "a",
        new_str: "b",
      }),
    ).toBe(true);
  });
  it("enforces enums", () => {
    expect(Value.Check(TOOLS.export_part!.params, { name: "p", format: "step" })).toBe(true);
    expect(Value.Check(TOOLS.export_part!.params, { name: "p", format: "png" })).toBe(false);
  });
  it("enforces integer bounds on delegation deadline", () => {
    const s = TOOLS.delegate_part_agent!.params;
    expect(Value.Check(s, { part: "p", prompt: "hi", deadline_seconds: 600 })).toBe(true);
    expect(Value.Check(s, { part: "p", prompt: "hi", deadline_seconds: 0 })).toBe(false);
    expect(Value.Check(s, { part: "p", prompt: "hi", deadline_seconds: 5000 })).toBe(false);
  });
  it("caps inspect_part views at 4", () => {
    const s = TOOLS.inspect_part!.params;
    expect(Value.Check(s, { name: "p", views: ["iso"] })).toBe(true);
    expect(Value.Check(s, { name: "p", views: ["a", "b", "c", "d", "e"] })).toBe(false);
  });
});
