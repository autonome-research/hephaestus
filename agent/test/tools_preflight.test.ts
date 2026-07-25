import { describe, it, expect } from "vitest";
import {
  preflight,
  isMutating,
  ASK_USER_MUST_BE_ALONE,
  type ToolCall,
} from "../src/tools/preflight.js";

function call(toolName: string, id = toolName): ToolCall {
  return { toolCallId: id, toolName };
}

function blocked(plan: ReturnType<typeof preflight>): string[] {
  return plan.decisions.filter((d) => d.action === "block").map((d) => d.toolName);
}
function running(plan: ReturnType<typeof preflight>): string[] {
  return plan.decisions.filter((d) => d.action === "run").map((d) => d.toolName);
}

describe("mutation classification", () => {
  it("uses generated sequential metadata; read-only tools are non-mutating", () => {
    expect(isMutating("edit_part")).toBe(true);
    expect(isMutating("build_part")).toBe(true);
    expect(isMutating("delegate_part_agent")).toBe(true);
    expect(isMutating("ask_user")).toBe(true);
    expect(isMutating("read_part")).toBe(false);
    expect(isMutating("measure")).toBe(false);
    // Unknown tool: fail safe (treated as mutating).
    expect(isMutating("nonexistent_tool")).toBe(true);
  });
});

describe("ask_user isolation (both source orders)", () => {
  it("blocks a mutating sibling when ask_user comes first", () => {
    const plan = preflight([call("ask_user"), call("edit_part")]);
    expect(blocked(plan)).toEqual(["edit_part"]);
    expect(running(plan)).toEqual(["ask_user"]);
    const editDecision = plan.decisions.find((d) => d.toolName === "edit_part");
    expect(editDecision).toMatchObject({ action: "block", reason: ASK_USER_MUST_BE_ALONE });
  });

  it("blocks a mutating sibling when ask_user comes last", () => {
    const plan = preflight([call("edit_part"), call("ask_user")]);
    expect(blocked(plan)).toEqual(["edit_part"]);
    expect(running(plan)).toEqual(["ask_user"]);
  });

  it("blocks EVERY sibling (read-only included) once a mutating sibling triggers isolation", () => {
    const plan = preflight([call("read_part"), call("ask_user"), call("edit_part")]);
    expect(blocked(plan).sort()).toEqual(["edit_part", "read_part"]);
    expect(running(plan)).toEqual(["ask_user"]);
  });

  it("does NOT isolate when ask_user has only read-only siblings", () => {
    const plan = preflight([call("ask_user"), call("read_part"), call("measure")]);
    expect(blocked(plan)).toEqual([]);
    // ask_user is itself sequential; the read-only siblings run in parallel.
    expect(plan.decisions.find((d) => d.toolName === "ask_user")).toMatchObject({
      action: "run",
      mode: "sequential",
    });
    expect(plan.decisions.find((d) => d.toolName === "read_part")).toMatchObject({
      action: "run",
      mode: "parallel",
    });
  });
});

describe("mutation sequencing without ask_user", () => {
  it("serializes the sequential set and lets read-only tools run concurrently", () => {
    const plan = preflight([
      call("edit_part", "c1"),
      call("read_part", "c2"),
      call("write_part", "c3"),
      call("measure", "c4"),
    ]);
    expect(blocked(plan)).toEqual([]);
    expect(plan.serializedOrder).toEqual(["c1", "c3"]);
    expect(plan.decisions.find((d) => d.toolName === "measure")).toMatchObject({
      action: "run",
      mode: "parallel",
    });
  });
});
