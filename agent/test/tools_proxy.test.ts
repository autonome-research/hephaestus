import { describe, it, expect } from "vitest";
import {
  ToolProxy,
  ProxyValidationError,
  ProxyResultError,
  type RpcRequest,
  type ProxyContext,
} from "../src/tools/proxy.js";
import { makeInvocation } from "../src/tools/invocation.js";
import { RpcError, ErrorCode } from "../src/rpc.js";
import type { JsonValue } from "../src/framing.js";

// --- fakes ------------------------------------------------------------------

interface Recorded {
  method: string;
  params: { [k: string]: JsonValue };
}

function fakeBridge(responder: (method: string, params: { [k: string]: JsonValue }) => JsonValue) {
  const calls: Recorded[] = [];
  const request: RpcRequest = async (method, params) => {
    calls.push({ method, params });
    return responder(method, params);
  };
  return { calls, request };
}

const CTX: ProxyContext = {
  sessionId: "sess-1",
  runId: "run-1",
  invocation: makeInvocation({
    sessionId: "sess-1",
    entryId: "entry-A",
    ordinal: 0,
    providerCallId: "call_0",
  }),
};

// Canned VALID results per tool so that a validation-passing input reaches a
// clean render (keyed by the tool name inside py.tool_dispatch, or the method).
function validResult(method: string, params: { [k: string]: JsonValue }): JsonValue {
  if (method === "py.delegate") {
    return { status: "queued", part_session_id: "s", child_run_id: "c", delegation_ref: "d" };
  }
  const tool = params.tool as string;
  switch (tool) {
    case "set_params":
      return { effective: {}, rejected: [] };
    case "run_checks":
      return { status: "ok" };
    case "measure":
      return { value: 1, units: "mm" };
    case "inspect_part":
      return { status: "ok", source_artifact_ref: "a", render_artifact_refs: ["r"] };
    case "export_part":
      return { paths: ["p"], source_artifact_ref: "a" };
    default:
      return { ok: true };
  }
}

function proxyWithValidResults() {
  return fakeBridge((m, p) => validResult(m, p));
}

// A minimal 2x2 PNG header (24 bytes) that parseImageHeader accepts.
function tinyPngBase64(): string {
  const buf = Buffer.alloc(24);
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]).copy(buf, 0);
  buf.write("IHDR", 12, "latin1");
  buf.writeUInt32BE(2, 16); // width
  buf.writeUInt32BE(2, 20); // height
  return buf.toString("base64");
}

// --- conditional matrix -----------------------------------------------------

describe("conditional enforcement (Value.Check ignores these)", () => {
  it("set_params: name required iff scope is part (or omitted)", async () => {
    const { request, calls } = proxyWithValidResults();
    const proxy = new ToolProxy(request);

    // scope omitted (defaults to part semantics) + no name -> rejected pre-dispatch.
    await expect(
      proxy.execute("set_params", { values: { a: 1 }, expected_state_hash: "h" }, CTX),
    ).rejects.toBeInstanceOf(ProxyValidationError);
    expect(calls).toHaveLength(0);

    // part scope with a name -> valid.
    await expect(
      proxy.execute(
        "set_params",
        { values: { a: 1 }, expected_state_hash: "h", scope: "part", name: "widget" },
        CTX,
      ),
    ).resolves.toBeDefined();

    // project scope with a name -> rejected (name must be null for project).
    await expect(
      proxy.execute(
        "set_params",
        { values: { a: 1 }, expected_state_hash: "h", scope: "project", name: "widget" },
        CTX,
      ),
    ).rejects.toBeInstanceOf(ProxyValidationError);

    // project scope with null name -> valid.
    await expect(
      proxy.execute(
        "set_params",
        { values: { a: 1 }, expected_state_hash: "h", scope: "project", name: null },
        CTX,
      ),
    ).resolves.toBeDefined();
  });

  it("measure: b required iff kind is interference/clearance/distance; forbidden otherwise", async () => {
    const { request } = proxyWithValidResults();
    const proxy = new ToolProxy(request);

    await expect(proxy.execute("measure", { kind: "distance", a: "x", b: "y" }, CTX)).resolves.toBeDefined();
    await expect(proxy.execute("measure", { kind: "distance", a: "x" }, CTX)).rejects.toBeInstanceOf(
      ProxyValidationError,
    );
    await expect(proxy.execute("measure", { kind: "bbox", a: "x" }, CTX)).resolves.toBeDefined();
    await expect(
      proxy.execute("measure", { kind: "bbox", a: "x", b: "y" }, CTX),
    ).rejects.toBeInstanceOf(ProxyValidationError);
  });

  it("measure: artifact_ref and project_snapshot_ref are mutually exclusive (not both)", async () => {
    const { request } = proxyWithValidResults();
    const proxy = new ToolProxy(request);
    await expect(
      proxy.execute(
        "measure",
        { kind: "bbox", a: "x", artifact_ref: "r1", project_snapshot_ref: "r2" },
        CTX,
      ),
    ).rejects.toBeInstanceOf(ProxyValidationError);
    await expect(
      proxy.execute("measure", { kind: "bbox", a: "x", artifact_ref: "r1" }, CTX),
    ).resolves.toBeDefined();
  });

  it("inspect_part: section_plane required iff channel is section", async () => {
    const { request } = proxyWithValidResults();
    const proxy = new ToolProxy(request);
    await expect(
      proxy.execute("inspect_part", { name: "p", channel: "section", section_plane: "XY" }, CTX),
    ).resolves.toBeDefined();
    await expect(
      proxy.execute("inspect_part", { name: "p", channel: "section" }, CTX),
    ).rejects.toBeInstanceOf(ProxyValidationError);
    await expect(
      proxy.execute("inspect_part", { name: "p", channel: "rgb", section_plane: "XY" }, CTX),
    ).rejects.toBeInstanceOf(ProxyValidationError);
  });

  it("inspect_part: artifact_ref must be null when last_good is true", async () => {
    const { request } = proxyWithValidResults();
    const proxy = new ToolProxy(request);
    await expect(
      proxy.execute("inspect_part", { name: "p", last_good: true, artifact_ref: "r" }, CTX),
    ).rejects.toBeInstanceOf(ProxyValidationError);
    await expect(
      proxy.execute("inspect_part", { name: "p", last_good: true }, CTX),
    ).resolves.toBeDefined();
    await expect(
      proxy.execute("inspect_part", { name: "p", last_good: false, artifact_ref: "r" }, CTX),
    ).resolves.toBeDefined();
  });

  it("inspect_part: base shape still rejects a 5th view", async () => {
    const { request, calls } = proxyWithValidResults();
    const proxy = new ToolProxy(request);
    await expect(
      proxy.execute("inspect_part", { name: "p", views: ["a", "b", "c", "d", "e"] }, CTX),
    ).rejects.toBeInstanceOf(ProxyValidationError);
    expect(calls).toHaveLength(0);
  });

  it("export_part: nested_sheet rejected for non-dxf/svg; allowed for dxf -> capability_not_available passthrough", async () => {
    // nested_sheet + stl violates the conditional -> rejected pre-dispatch.
    const rejectBridge = proxyWithValidResults();
    const rejectProxy = new ToolProxy(rejectBridge.request);
    await expect(
      rejectProxy.execute(
        "export_part",
        { name: "p", format: "stl", layout: "nested_sheet" },
        CTX,
      ),
    ).rejects.toBeInstanceOf(ProxyValidationError);
    expect(rejectBridge.calls).toHaveLength(0);

    // nested_sheet + dxf is schema-valid; Python raises a structured capability
    // error that is passed THROUGH to the model rather than failing closed.
    const capBridge = fakeBridge(() => {
      throw new RpcError(ErrorCode.INTERNAL_ERROR, "not until stage 6", {
        code: "capability_not_available",
      });
    });
    const capProxy = new ToolProxy(capBridge.request);
    const result = await capProxy.execute(
      "export_part",
      { name: "p", format: "dxf", layout: "nested_sheet" },
      CTX,
    );
    expect(capBridge.calls).toHaveLength(1);
    expect(result.details.capability).toBe("capability_not_available");
    expect(result.content[0]).toMatchObject({ type: "text" });
    expect(JSON.stringify(result.content)).toContain("capability_not_available");
  });
});

// --- 32 KiB prompt boundary -------------------------------------------------

describe("delegate_part_agent prompt: exact 32 KiB UTF-8 boundary", () => {
  function proxy() {
    return new ToolProxy(proxyWithValidResults().request);
  }
  const okArgs = (prompt: string) => ({ part: "widget", prompt });

  it("accepts exactly 32768 UTF-8 bytes and rejects 32769", async () => {
    const p = proxy();
    await expect(proxy().execute("delegate_part_agent", okArgs("a".repeat(32768)), CTX)).resolves.toBeDefined();
    await expect(
      p.execute("delegate_part_agent", okArgs("a".repeat(32769)), CTX),
    ).rejects.toMatchObject({ code: "prompt_too_large" });
  });

  it("measures exact UTF-8 bytes for multibyte code points", async () => {
    // 10923 x U+20AC (3 bytes) = 32769 bytes -> reject.
    await expect(
      proxy().execute("delegate_part_agent", okArgs("\u20AC".repeat(10923)), CTX),
    ).rejects.toMatchObject({ code: "prompt_too_large" });
    // 16384 x U+00E9 (2 bytes) = 32768 bytes -> pass.
    await expect(
      proxy().execute("delegate_part_agent", okArgs("\u00E9".repeat(16384)), CTX),
    ).resolves.toBeDefined();
  });

  it("treats NFC and NFD as distinct byte payloads (no normalization)", async () => {
    // Same 16384 accented characters, different normal forms:
    //   NFC  U+00E9        = 2 bytes each = 32768 bytes (pass)
    //   NFD  "e" + U+0301  = 3 bytes each = 49152 bytes (reject)
    const nfc = "\u00E9".repeat(16384); // precomposed, 2 bytes each
    const nfd = "e\u0301".repeat(16384); // e + combining acute, 3 bytes each
    expect(Buffer.byteLength(nfc, "utf8")).toBe(32768);
    expect(Buffer.byteLength(nfd, "utf8")).toBe(49152);
    await expect(proxy().execute("delegate_part_agent", okArgs(nfc), CTX)).resolves.toBeDefined();
    await expect(
      proxy().execute("delegate_part_agent", okArgs(nfd), CTX),
    ).rejects.toMatchObject({ code: "prompt_too_large" });
  });

  it("rejects a lone surrogate as invalid_unicode_scalar before sizing", async () => {
    await expect(
      proxy().execute("delegate_part_agent", okArgs("\uD800"), CTX),
    ).rejects.toMatchObject({ code: "invalid_unicode_scalar" });
  });
});

// --- routing + invocation metadata ------------------------------------------

describe("bridge routing and trusted invocation", () => {
  it("routes generic tools to py.tool_dispatch with invocation metadata", async () => {
    const { request, calls } = proxyWithValidResults();
    await new ToolProxy(request).execute("measure", { kind: "bbox", a: "x" }, CTX);
    expect(calls[0]!.method).toBe("py.tool_dispatch");
    expect(calls[0]!.params).toMatchObject({
      session_id: "sess-1",
      run_id: "run-1",
      tool: "measure",
    });
    expect((calls[0]!.params.invocation as { invocation_id: string }).invocation_id).toBe(
      CTX.invocation.invocation_id,
    );
  });

  it("routes delegate_part_agent to py.delegate and ask_user to py.ask_user", async () => {
    const del = proxyWithValidResults();
    await new ToolProxy(del.request).execute(
      "delegate_part_agent",
      { part: "widget", prompt: "go" },
      CTX,
    );
    expect(del.calls[0]!.method).toBe("py.delegate");
    expect(del.calls[0]!.params).toMatchObject({ parent_run_id: "run-1", part: "widget", prompt: "go" });

    const ask = fakeBridge(() => ({ selection: "yes" }));
    await new ToolProxy(ask.request).execute(
      "ask_user",
      { question: "ok?", options: ["yes", "no"] },
      CTX,
    );
    expect(ask.calls[0]!.method).toBe("py.ask_user");
    expect(ask.calls[0]!.params).toMatchObject({ run_id: "run-1", question: "ok?" });
    // ask_user carries no trusted invocation metadata by wire contract.
    expect(ask.calls[0]!.params.invocation).toBeUndefined();
  });
});

// --- result rendering + fail-closed -----------------------------------------

describe("result rendering", () => {
  it("renders inline images within budget and strips base64 from the text", async () => {
    const bridge = fakeBridge(() => ({
      status: "ok",
      source_artifact_ref: "a",
      render_artifact_refs: ["r1"],
      images: [{ data: tinyPngBase64(), mime_type: "image/png" }],
    }));
    const result = await new ToolProxy(bridge.request).execute(
      "inspect_part",
      { name: "p" },
      CTX,
    );
    const imageBlocks = result.content.filter((c) => c.type === "image");
    expect(imageBlocks).toHaveLength(1);
    expect(result.details.images).toBe(1);
    const textBlock = result.content.find((c) => c.type === "text");
    // Artifact ref preserved; base64 payload NOT inlined into the text.
    expect(textBlock && "text" in textBlock ? textBlock.text : "").toContain("r1");
    expect(JSON.stringify(textBlock)).not.toContain(tinyPngBase64());
  });

  it("fails closed when the image payload is over budget (never reaches the model)", async () => {
    // Width beyond MAX_IMAGE_WIDTH -> parseImageHeader rejects -> ProxyResultError.
    const bad = Buffer.alloc(24);
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]).copy(bad, 0);
    bad.write("IHDR", 12, "latin1");
    bad.writeUInt32BE(999999, 16);
    bad.writeUInt32BE(999999, 20);
    const bridge = fakeBridge(() => ({
      status: "ok",
      source_artifact_ref: "a",
      render_artifact_refs: ["r1"],
      images: [{ data: bad.toString("base64"), mime_type: "image/png" }],
    }));
    await expect(
      new ToolProxy(bridge.request).execute("inspect_part", { name: "p" }, CTX),
    ).rejects.toBeInstanceOf(ProxyResultError);
  });
});

describe("fail-closed result validation", () => {
  it("throws ProxyResultError on a malformed py result; content never rendered", async () => {
    // queued variant is missing required part_session_id/child_run_id/delegation_ref.
    const bridge = fakeBridge(() => ({ status: "queued" }));
    const proxy = new ToolProxy(bridge.request);
    const err = await proxy
      .execute("delegate_part_agent", { part: "widget", prompt: "go" }, CTX)
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ProxyResultError);
    // The generic error message must not leak the malformed payload.
    expect((err as ProxyResultError).message).not.toContain("queued");
  });

  it("rethrows a non-capability RPC error as an ordinary tool error", async () => {
    const bridge = fakeBridge(() => {
      throw new RpcError(ErrorCode.BUSY, "busy");
    });
    await expect(
      new ToolProxy(bridge.request).execute("measure", { kind: "bbox", a: "x" }, CTX),
    ).rejects.toBeInstanceOf(RpcError);
  });
});
