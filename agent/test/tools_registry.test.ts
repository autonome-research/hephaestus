import { describe, it, expect, vi } from "vitest";
import { buildToolSet, toolNamesForProfile } from "../src/tools/registry.js";
import { ToolProxy, type ProxyContext, type RpcRequest } from "../src/tools/proxy.js";
import { makeInvocation } from "../src/tools/invocation.js";
import type { JsonValue } from "../src/framing.js";

function ctxFor(toolCallId: string): ProxyContext {
  return {
    sessionId: "sess-1",
    runId: "run-1",
    invocation: makeInvocation({
      sessionId: "sess-1",
      entryId: "entry-A",
      ordinal: 0,
      providerCallId: toolCallId,
    }),
  };
}

describe("per-profile availability", () => {
  it("gives the orchestrator delegation + project-global tools", () => {
    const names = toolNamesForProfile("orchestrator");
    expect(names).toContain("delegate_part_agent");
    expect(names).toContain("create_part");
    expect(names).toContain("edit_globals");
    expect(names).toContain("create_project_check");
  });

  it("withholds orchestrator-only tools from part and quick_edit profiles", () => {
    for (const profile of ["part", "quick_edit"] as const) {
      const names = toolNamesForProfile(profile);
      expect(names).not.toContain("delegate_part_agent");
      expect(names).not.toContain("create_part");
      expect(names).not.toContain("edit_globals");
      // read/edit/build/measure remain available.
      expect(names).toContain("edit_part");
      expect(names).toContain("measure");
    }
  });
});

describe("buildToolSet", () => {
  it("declares sequential execution for mutating tools and parallel for read-only", () => {
    const proxy = new ToolProxy((async () => ({ ok: true })) as RpcRequest);
    const tools = buildToolSet("orchestrator", { proxy, resolveContext: ctxFor });
    const byName = new Map(tools.map((t) => [t.name, t]));
    expect(byName.get("edit_part")!.executionMode).toBe("sequential");
    expect(byName.get("delegate_part_agent")!.executionMode).toBe("sequential");
    expect(byName.get("read_part")!.executionMode).toBe("parallel");
    expect(byName.get("measure")!.executionMode).toBe("parallel");
    // parameters + description wired from the generated surface.
    expect(byName.get("measure")!.description).toContain("Metric facade");
  });

  it("routes a tool call through the proxy with the resolved per-call context", async () => {
    const calls: { method: string; params: { [k: string]: JsonValue } }[] = [];
    const request: RpcRequest = async (method, params) => {
      calls.push({ method, params });
      return { value: 1, units: "mm" };
    };
    const proxy = new ToolProxy(request);
    const resolveContext = vi.fn(ctxFor);
    const tools = buildToolSet("part", { proxy, resolveContext });
    const measure = tools.find((t) => t.name === "measure")!;

    const result = await measure.execute("call_7", { kind: "bbox", a: "x" }, undefined, undefined, {
      // ExtensionContext is unused by the proxy; a stub is sufficient here.
    } as never);

    expect(resolveContext).toHaveBeenCalledWith("call_7");
    expect(calls[0]!.method).toBe("py.tool_dispatch");
    expect(calls[0]!.params.tool).toBe("measure");
    // The trusted invocation reflects the resolved context (provider id = call_7).
    expect((calls[0]!.params.invocation as { provider_call_id: string }).provider_call_id).toBe(
      "call_7",
    );
    expect(result.content.some((c) => c.type === "text")).toBe(true);
  });
});
