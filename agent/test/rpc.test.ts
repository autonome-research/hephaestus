import { describe, it, expect } from "vitest";
import { RpcPeer, RpcError, ErrorCode, FRAME_VERSION } from "../src/rpc.js";
import { FrameDecoder, encodeFrame, type JsonValue } from "../src/framing.js";

// Wire two peers together through the real framing codec.
function connect(): { a: RpcPeer; b: RpcPeer } {
  const decA = new FrameDecoder();
  const decB = new FrameDecoder();
  const peers: { a?: RpcPeer; b?: RpcPeer } = {};
  peers.a = new RpcPeer((frame) => {
    for (const f of decB.push(encodeFrame(frame))) void peers.b!.handleFrame(f);
  });
  peers.b = new RpcPeer((frame) => {
    for (const f of decA.push(encodeFrame(frame))) void peers.a!.handleFrame(f);
  });
  return { a: peers.a, b: peers.b };
}

describe("RpcPeer request/response correlation", () => {
  it("resolves a served request", async () => {
    const { a, b } = connect();
    b.on("echo", (p) => p as JsonValue);
    await expect(a.request("echo", { x: 1, y: [2, 3] })).resolves.toEqual({ x: 1, y: [2, 3] });
  });

  it("correlates many concurrent requests independently", async () => {
    const { a, b } = connect();
    b.on("echo", (p) => p as JsonValue);
    const results = await Promise.all(
      Array.from({ length: 20 }, (_, i) => a.request("echo", { i })),
    );
    expect(results).toEqual(Array.from({ length: 20 }, (_, i) => ({ i })));
  });

  it("returns method_not_found for an unknown method", async () => {
    const { a } = connect();
    await expect(a.request("does.not.exist")).rejects.toMatchObject({
      code: ErrorCode.METHOD_NOT_FOUND,
    });
  });

  it("propagates a handler RpcError with its code", async () => {
    const { a, b } = connect();
    b.on("py.tool_dispatch", () => {
      throw new RpcError(ErrorCode.INVALID_PARAMS, "bad args");
    });
    await expect(a.request("py.tool_dispatch")).rejects.toMatchObject({
      code: ErrorCode.INVALID_PARAMS,
      message: "bad args",
    });
  });

  it("is bidirectional (both peers serve and originate)", async () => {
    const { a, b } = connect();
    a.on("py.admission_capacity", () => ({ available: 5 }));
    b.on("session.create", () => ({ session_id: "s1" }));
    await expect(b.request("py.admission_capacity")).resolves.toEqual({ available: 5 });
    await expect(a.request("session.create")).resolves.toEqual({ session_id: "s1" });
  });

  it("delivers notifications without a response", () => {
    const { a, b } = connect();
    let seen: JsonValue | null = null;
    b.onNotify("cancel", (p) => {
      seen = p as JsonValue;
    });
    a.notify("cancel", { run_id: "r9" });
    expect(seen).toEqual({ run_id: "r9" });
  });
});

describe("RpcPeer guards", () => {
  it("rejects with BUSY when the pending map is full", async () => {
    const dropped = new RpcPeer(() => {}, { maxPending: 1, defaultTimeoutMs: 0 });
    void dropped.request("slow.one"); // occupies the only slot, never resolves
    await expect(dropped.request("slow.two")).rejects.toMatchObject({ code: ErrorCode.BUSY });
    expect(dropped.pendingCount).toBe(1);
  });

  it("times out a request with no response", async () => {
    const dropped = new RpcPeer(() => {});
    await expect(dropped.request("void", {}, 20)).rejects.toMatchObject({
      code: ErrorCode.TIMEOUT,
    });
  });

  it("fails closed on an unknown hv (version negotiation)", async () => {
    const sent: Array<{ [k: string]: JsonValue }> = [];
    const peer = new RpcPeer((f) => sent.push(f));
    await peer.handleFrame(
      Buffer.from(JSON.stringify({ hv: 2, jsonrpc: "2.0", id: 5, method: "echo" })),
    );
    expect(sent).toHaveLength(1);
    expect(sent[0]).toMatchObject({
      hv: FRAME_VERSION,
      id: 5,
      error: { code: ErrorCode.UNSUPPORTED_VERSION },
    });
  });

  it("emits a parse error (id null) for malformed JSON", async () => {
    const sent: Array<{ [k: string]: JsonValue }> = [];
    const peer = new RpcPeer((f) => sent.push(f));
    await peer.handleFrame(Buffer.from("{not json"));
    expect(sent[0]).toMatchObject({ id: null, error: { code: ErrorCode.PARSE_ERROR } });
  });
});
