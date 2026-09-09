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
import { LIMITS, TOOL_TIMEOUT_MS } from "../src/limits.js";
import type { JsonValue } from "../src/framing.js";

// --- fakes ------------------------------------------------------------------

interface Recorded {
  method: string;
  params: { [k: string]: JsonValue };
  // Captured whenever the proxy passes a third argument through to the
  // bridge request function — see the J-http-limits-11 describe block below.
  // `RpcRequest`'s declared arity does not (yet) include it; JS does not
  // enforce call arity, so this simply reads `undefined` until the proxy is
  // widened to pass one.
  timeoutMs?: number | undefined;
}

function fakeBridge(responder: (method: string, params: { [k: string]: JsonValue }) => JsonValue) {
  const calls: Recorded[] = [];
  const request: RpcRequest = async (method, params, timeoutMs?: number) => {
    calls.push({ method, params, timeoutMs });
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
  if (method === "py.ask_user") {
    return { selection: "a" };
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

  it("refuses with image_model_required when the reading model is text-only", async () => {
    const bridge = fakeBridge(() => ({
      status: "ok",
      source_artifact_ref: "a",
      render_artifact_refs: ["r1"],
      images: [{ data: tinyPngBase64(), mime_type: "image/png" }],
    }));
    const result = await new ToolProxy(bridge.request).execute("inspect_part", { name: "p" }, {
      ...CTX,
      imagesSupported: false,
    });
    expect(result.content.filter((c) => c.type === "image")).toHaveLength(0);
    expect(result.details.capability).toBe("image_model_required");
    expect(result.details.result).toMatchObject({
      status: "capability_error",
      code: "image_model_required",
      source_artifact_ref: "a",
      render_artifact_refs: ["r1"],
    });
  });

  it("does not refuse an image-free result on a text-only model", async () => {
    const bridge = fakeBridge(() => ({ value: 1, units: "mm" }));
    const result = await new ToolProxy(bridge.request).execute(
      "measure",
      { kind: "bbox", a: "x" },
      { ...CTX, imagesSupported: false },
    );
    expect(result.details.capability).toBeUndefined();
    expect(result.details.result).toMatchObject({ value: 1 });
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

// --- J-http-limits-11: a synchronous delegation is issued with its own -----
// --- deadline + the bridge grace, not the peer's ordinary tool deadline ----
//
// `RpcPeer`'s default deadline is the ordinary `tool_seconds` class
// (J-http-limits-11's other half, `rpc.ts`). A `delegate_part_agent` call
// carries `deadline_seconds` — up to 1200s — entirely inside its own request
// PARAMS, so a peer using its ordinary default would time out the bridge
// request itself, at the tool deadline, long before the delegation state
// machine's own `deadline_seconds` (plus the documented `+ grace`) ever
// elapses. The fix routes a per-call timeout through `buildRequest`'s return
// and `RpcRequest`'s third argument (mirroring the third parameter
// `RpcPeer.request` already has) so the delegate call's OWN bridge-level
// deadline outlives the child's.
describe("delegate_part_agent's own bridge deadline (J-http-limits-11)", () => {
  it("uses deadline_seconds + the delegation grace when deadline_seconds is given", async () => {
    const { request, calls } = proxyWithValidResults();
    const proxy = new ToolProxy(request);
    await proxy.execute(
      "delegate_part_agent",
      { part: "widget", prompt: "make it wider", deadline_seconds: 300 },
      CTX,
    );
    expect(calls).toHaveLength(1);
    expect(calls[0]!.method).toBe("py.delegate");
    // 300s deadline + the delegation grace (schemas/bridge_limits.json
    // timeouts.delegation.grace_seconds), in milliseconds — not the peer's
    // ordinary tool_seconds default, which would time this call out long
    // before a legitimately slow child ever gets there.
    expect(calls[0]!.timeoutMs).toBe((300 + LIMITS.timeouts.delegation.grace_seconds) * 1000);
  });

  it("uses the declared default deadline + grace when deadline_seconds is omitted", async () => {
    const { request, calls } = proxyWithValidResults();
    const proxy = new ToolProxy(request);
    await proxy.execute("delegate_part_agent", { part: "widget", prompt: "go" }, CTX);
    expect(calls).toHaveLength(1);
    const defaultS = LIMITS.timeouts.delegation.deadline_default_seconds;
    expect(calls[0]!.timeoutMs).toBe((defaultS + LIMITS.timeouts.delegation.grace_seconds) * 1000);
  });

  it("never uses the bare peer default (tool_seconds) for a delegation call", async () => {
    // A delegation's own deadline window (1s..1200s) is wider on both ends
    // than the ordinary tool deadline; asserting they differ here catches a
    // regression that silently drops the per-call override back to the
    // peer's ordinary default.
    const { request, calls } = proxyWithValidResults();
    const proxy = new ToolProxy(request);
    await proxy.execute("delegate_part_agent", { part: "widget", prompt: "go" }, CTX);
    expect(calls[0]!.timeoutMs).not.toBe(TOOL_TIMEOUT_MS);
  });
});

// --- J-http-limits-8/-11: a CAD-build tool is issued with the CAD deadline -
describe("per-tool timeout class selection (J-http-limits-8/-11)", () => {
  it("issues a CAD-build tool with the CAD deadline, not the ordinary one", async () => {
    // `run_checks` runs the sandboxed CAD worker and can legitimately take
    // between two and five minutes; the ordinary tool deadline (120s) would
    // die on it long before a genuine build could ever finish.
    const { request, calls } = proxyWithValidResults();
    await new ToolProxy(request).execute("run_checks", { scope: "project" }, CTX);
    expect(calls).toHaveLength(1);
    expect(calls[0]!.timeoutMs).toBe(LIMITS.timeouts.cad_build_seconds * 1000);
    expect(calls[0]!.timeoutMs).not.toBe(TOOL_TIMEOUT_MS);
  });

  it.each([
    ["compare_solids", { part: "widget", target: "part:other" }],
    ["compare_to_scan", { part: "widget", scan: "scan:mesh.stl", units: "mm" }],
    ["check_motion", {}],
  ] as const)(
    "issues %s on the long class: its Python ceiling is cad_build_seconds too",
    async (toolName, args) => {
      // The half of J-http-limits-8 that the first pass missed. These three do
      // not enter `CadOps._run`, but each runs its kernel work in a killable
      // subprocess under the SAME 300 seconds (`core/project_compare.py`
      // COMPARE_TIMEOUT_S, `core/scan_compare.py` SCAN_TIMEOUT_S,
      // `core/motion.py` MOTION_TIMEOUT_S). On the ordinary class a comparison
      // that legitimately runs 150s is killed at the RPC layer while the
      // Python child works on — the exact "layer above gives up before the
      // layer below" defect the item names, and for `check_motion` it also
      // makes the named `motion_timeout` refusal unreachable.
      //
      // Asserted on the ISSUED request, and the stub's generic reply is allowed
      // to fail these tools' result schemas: the deadline is chosen and stamped
      // on the outbound request before any result exists, so what comes back
      // cannot change what is being pinned here.
      const { request, calls } = proxyWithValidResults();
      await new ToolProxy(request).execute(toolName, { ...args }, CTX).catch(() => undefined);
      expect(calls).toHaveLength(1);
      expect(calls[0]!.timeoutMs).toBe(LIMITS.timeouts.cad_build_seconds * 1000);
      expect(calls[0]!.timeoutMs).not.toBe(TOOL_TIMEOUT_MS);
    },
  );

  it("issues an ordinary (non-CAD) tool with the plain tool_seconds deadline", async () => {
    const { request, calls } = proxyWithValidResults();
    await new ToolProxy(request).execute("measure", { kind: "bbox", a: "x" }, CTX);
    expect(calls).toHaveLength(1);
    expect(calls[0]!.timeoutMs).toBe(TOOL_TIMEOUT_MS);
  });

  it("issues ask_user with NO timer (0) — Python owns the human-interaction deadline", async () => {
    const { request, calls } = proxyWithValidResults();
    await new ToolProxy(request).execute("ask_user", { question: "which?", options: ["a", "b"] }, CTX);
    expect(calls).toHaveLength(1);
    expect(calls[0]!.timeoutMs).toBe(0);
  });
});
