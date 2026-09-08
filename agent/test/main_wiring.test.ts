// audit-2026-09-04 J-mirrors-and-dx-31: module-level RPC registration in the
// sidecar entry point.
//
// `main.ts` used to construct a peer bound to standard output, register all
// seventeen handlers, attach the stdin reader and log its own pid — all as
// MODULE-LEVEL side effects. Importing the module started a process, so the
// one test covering per-run context scoping had to compile the whole source
// tree and spawn a real child (`golden.test.ts` / `concurrency.test.ts`) —
// the only test in this suite that did either.
//
// The fix separates three roles: `on`/`onNotify` (inside main.ts) DECLARE a
// handler into a module-level table with no peer attached; `registerHandlers`
// BINDS that table to a peer; `main` does the process wiring (stdin, stdout,
// the startup log) and only runs when this module is the process entry point.
//
// These tests prove the seam: importing `main.ts` in-process performs no I/O
// and wires nothing to `process.stdin`, and `registerHandlers` alone —
// against an in-memory peer, no child process — is enough to answer a real
// sidecar-served request. That in-process coverage is exactly what the old
// shape made impossible.
import { describe, it, expect } from "vitest";
import { RpcPeer, SIDECAR_REQUEST_METHODS } from "../src/rpc.js";

describe("importing the sidecar entry module performs no work at import (J-mirrors-and-dx-31)", () => {
  it(
    "registers no stdin listeners merely by being imported",
    async () => {
      const stdinListenersBefore = process.stdin.listenerCount("data");
      // The first import of this large module (and its whole dependency
      // graph) pays real transform cost under the on-the-fly test transpiler,
      // independent of anything under test here — generous timeout so that
      // is never what this assertion is flaky on.
      await import("../src/main.js");
      // The module-scope guard (`isProcessEntryPoint()`) is false under a test
      // runner — `process.argv[1]` is vitest's own worker entry, not this
      // file — so `main()` never runs and `process.stdin` is untouched.
      expect(process.stdin.listenerCount("data")).toBe(stdinListenersBefore);
    },
    60_000,
  );

  it("exports registerHandlers and main as the only seams", async () => {
    const mod = await import("../src/main.js");
    expect(typeof mod.registerHandlers).toBe("function");
    expect(typeof mod.main).toBe("function");
  });
});

describe("registerHandlers binds every declared handler to a peer (no process spawned)", () => {
  it("wires every frozen sidecar-request method onto an in-memory peer", async () => {
    const { registerHandlers } = await import("../src/main.js");
    const peer = new RpcPeer(() => {});
    registerHandlers(peer);

    // `RpcPeer.on` throws "already registered" for a method with a handler —
    // the only externally observable proof a method WAS registered, since the
    // handler map itself is private. Every frozen sidecar-served method (the
    // set `rpc.ts` and `agent_bridge/protocol.py` both freeze) must already be
    // taken.
    for (const method of SIDECAR_REQUEST_METHODS) {
      expect(() => peer.on(method, () => ({}))).toThrow(/already registered/);
    }
  });

  it("answers a real request end to end against the in-memory peer alone", async () => {
    const { registerHandlers } = await import("../src/main.js");
    const frames: Array<{ [k: string]: unknown }> = [];
    const peer = new RpcPeer((frame) => {
      frames.push(frame);
    });
    registerHandlers(peer);

    // `runtime.configure` with no providers is the cheapest handler to drive
    // without a real model: it must not require a live process, only the
    // peer this test built by hand.
    await peer.handleFrame(
      Buffer.from(
        JSON.stringify({
          hv: 1,
          jsonrpc: "2.0",
          id: 1,
          method: "runtime.configure",
          params: { providers: [] },
        }),
      ),
    );
    expect(frames).toHaveLength(1);
    expect(frames[0]).not.toHaveProperty("error");
  });

  it("calling registerHandlers twice on two different peers each gets a full table", async () => {
    // A future caller — a test harness, an embedder — must be able to bind a
    // fresh peer without the shared declaration table being consumed or
    // mutated by an earlier bind.
    const { registerHandlers } = await import("../src/main.js");
    const a = new RpcPeer(() => {});
    const b = new RpcPeer(() => {});
    registerHandlers(a);
    registerHandlers(b);
    for (const method of SIDECAR_REQUEST_METHODS) {
      expect(() => a.on(method, () => ({}))).toThrow();
      expect(() => b.on(method, () => ({}))).toThrow();
    }
  });
});
