// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Resync honesty (INTERFACE.md §2.7, §7.4): the break is inserted, labelled, and
// never healed.

import { describe, expect, it } from "vitest";
import type { EventFrame } from "../../src/api/events";
import {
  disconnected,
  emptyLive,
  LIVE_DEDUPE_WINDOW,
  receive,
  RESYNC_CLOSE_CODE,
  RESYNC_CLOSE_REASON,
  resumeFrame,
  resync,
} from "../../src/stream/live";
import {
  BEARER_SUBPROTOCOL,
  eventsUrl,
  resumeFrameJson,
  subscribeFrame,
  StreamSocket,
} from "../../src/stream/socket";
import { liveRows } from "../../src/stream/transcript";
import { fixture } from "./fixture";

function frame(seq: number, runId = fixture.run_id): EventFrame {
  return {
    run_id: runId,
    seq,
    kind: "text_delta",
    session_id: fixture.session_id,
    payload: { text: `delta ${String(seq)}` },
  };
}

describe("the close code is the server's (§2.7)", () => {
  it("names 4409 resync_required exactly", () => {
    expect(RESYNC_CLOSE_CODE).toBe(4409);
    expect(RESYNC_CLOSE_REASON).toBe("resync_required");
  });
});

describe("a resync always leaves a labelled break", () => {
  it("inserts the break at the moment of the drop, not after the replay", () => {
    let state = emptyLive("live");
    state = receive(state, frame(0));
    state = resync(state);
    expect(state.status).toBe("resyncing");
    const entries = state.entries.filter((entry) => entry.entry === "break");
    expect(entries).toHaveLength(1);
    expect(entries[0]?.resync.outcome).toBe("pending");
    expect(entries[0]?.resync.after).toEqual({ run_id: fixture.run_id, seq: 0 });
  });

  it("reports a gap when the replay resumes past the cursor", () => {
    let state = emptyLive("live");
    state = receive(state, frame(0));
    state = receive(state, frame(1));
    state = resync(state);
    // The live buffer had already dropped seq 2 and 3.
    state = receive(state, frame(4));
    const marker = state.entries.find((entry) => entry.entry === "break");
    expect(marker?.resync.outcome).toBe("gap");
    expect(state.status).toBe("live");
  });

  it("reports contiguity when the replay resumes at the very next event", () => {
    let state = emptyLive("live");
    state = receive(state, frame(7));
    state = resync(state);
    state = receive(state, frame(8));
    const marker = state.entries.find((entry) => entry.entry === "break");
    expect(marker?.resync.outcome).toBe("contiguous");
  });

  it("stays undecided while only another run has spoken", () => {
    let state = emptyLive("live");
    state = receive(state, frame(3));
    state = resync(state);
    state = receive(state, frame(0, "run-someone-else"));
    const marker = state.entries.find((entry) => entry.entry === "break");
    // A frame from another run says nothing about the run whose continuity is
    // in question, so it does not get to answer for it.
    expect(marker?.resync.outcome).toBe("pending");
  });

  it("says 'not known' when nothing had been seen before the drop", () => {
    let state = emptyLive("live");
    state = resync(state);
    state = receive(state, frame(12));
    const marker = state.entries.find((entry) => entry.entry === "break");
    expect(marker?.resync.outcome).toBe("unknown");
  });

  it("never removes a break once it is placed", () => {
    let state = emptyLive("live");
    state = receive(state, frame(0));
    state = resync(state);
    state = receive(state, frame(1));
    state = receive(state, frame(2));
    state = resync(state);
    state = receive(state, frame(3));
    expect(state.entries.filter((entry) => entry.entry === "break")).toHaveLength(2);
    expect(state.resyncs).toBe(2);
    // And the panel renders both, in place.
    expect(liveRows(state.entries).filter((row) => row.row === "resync")).toHaveLength(2);
  });

  it("inserts no break for an ordinary disconnect", () => {
    let state = emptyLive("live");
    state = receive(state, frame(0));
    state = disconnected(state, "reconnecting");
    expect(state.entries.some((entry) => entry.entry === "break")).toBe(false);
    expect(state.status).toBe("reconnecting");
  });
});

describe("what a real socket taught this reducer", () => {
  it("drops an event the replay handed back twice", () => {
    // `LiveBuffer.replay` returns the whole buffered suffix when the cursor has
    // already fallen out of the ring, which overlaps what the panel already has.
    // Deduping on `(run_id, seq)` is sound within the live namespace — it is
    // that namespace's own identity — and it is what §2.7 forbids only ACROSS
    // the two namespaces, where the same event has two disjoint identities.
    let state = emptyLive("live");
    state = receive(state, frame(0));
    state = receive(state, frame(1));
    state = resync(state);
    state = receive(state, frame(0));
    state = receive(state, frame(1));
    state = receive(state, frame(2));
    expect(state.entries.filter((entry) => entry.entry === "event")).toHaveLength(3);
  });

  it("does not carry a terminal's seq into a resume cursor", () => {
    // FOUND LIVE. `agent_bridge/events.py` mints a terminal with `seq = 2**62`
    // so terminals sort last, and `2**62` is far past `Number.MAX_SAFE_INTEGER`:
    // a browser's `JSON.parse` rounds it. Echoing the rounded value back in
    // `{"resume": {"after": …}}` would send a number the server never minted,
    // the buffer lookup would miss, and the panel would report a gap that never
    // happened. The cursor therefore holds at the last event whose seq survives
    // the round trip.
    const terminalSeq = 2 ** 62;
    expect(Number.isSafeInteger(terminalSeq)).toBe(false);
    let state = emptyLive("live");
    state = receive(state, frame(5));
    state = receive(state, {
      run_id: fixture.run_id,
      seq: terminalSeq,
      kind: "terminal",
      session_id: fixture.session_id,
      payload: { state: "failed", terminal_id: `terminal:${fixture.run_id}` },
    });
    expect(state.entries).toHaveLength(2);
    expect(state.cursor).toEqual({ run_id: fixture.run_id, seq: 5 });
    expect(resumeFrame(state, fixture.session_id)?.resume.after.seq).toBe(5);
  });

  it("bounds the identities it remembers", () => {
    let state = emptyLive("live");
    for (let i = 0; i < LIVE_DEDUPE_WINDOW + 50; i += 1) state = receive(state, frame(i));
    expect(state.seen).toHaveLength(LIVE_DEDUPE_WINDOW);
    expect(state.entries).toHaveLength(LIVE_DEDUPE_WINDOW + 50);
  });
});

describe("the resume frame (§2.7)", () => {
  it("is null with nothing to resume from", () => {
    expect(resumeFrame(emptyLive(), fixture.session_id)).toBeNull();
  });

  it("carries the last identity this socket actually saw", () => {
    const state = receive(emptyLive("live"), frame(41));
    expect(resumeFrame(state, fixture.session_id)).toEqual({
      resume: { session_id: fixture.session_id, after: { run_id: fixture.run_id, seq: 41 } },
    });
  });
});

// ---------------------------------------------------------------------------
// the transport
// ---------------------------------------------------------------------------

interface FakeSocket {
  url: string;
  protocols: readonly string[];
  sent: string[];
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  send: (data: string) => void;
  close: () => void;
}

function fakeFactory(created: FakeSocket[]): (url: string, protocols: readonly string[]) => WebSocket {
  return (url, protocols) => {
    const socket: FakeSocket = {
      url,
      protocols,
      sent: [],
      onopen: null,
      onmessage: null,
      onclose: null,
      onerror: null,
      send(data: string) {
        this.sent.push(data);
      },
      close() {
        /* the test drives `onclose` itself */
      },
    };
    created.push(socket);
    return socket as unknown as WebSocket;
  };
}

describe("StreamSocket", () => {
  it("carries the bearer as a subprotocol, because a browser cannot set a header", () => {
    const created: FakeSocket[] = [];
    const socket = new StreamSocket(
      { sessionId: fixture.session_id, token: "tok-123", factory: fakeFactory(created) },
      { onFrame: () => undefined, onStatus: () => undefined, onResync: () => undefined, cursor: () => null },
    );
    socket.open("ws://127.0.0.1:8760/api/v1/events");
    expect(created[0]?.protocols).toEqual([BEARER_SUBPROTOCOL, "tok-123"]);
    // §2.2's property is preserved: a subprotocol travels in a request header,
    // so the token is not in the URL and cannot reach an access log.
    expect(created[0]?.url).not.toContain("tok-123");
  });

  it("subscribes on open and resumes only when it has a cursor", () => {
    const created: FakeSocket[] = [];
    let cursor: { run_id: string; seq: number } | null = null;
    const socket = new StreamSocket(
      { sessionId: fixture.session_id, token: "tok", factory: fakeFactory(created) },
      {
        onFrame: () => undefined,
        onStatus: () => undefined,
        onResync: () => undefined,
        cursor: () => cursor,
      },
    );
    socket.open("ws://host/api/v1/events");
    created[0]?.onopen?.(new Event("open"));
    expect(created[0]?.sent).toEqual([subscribeFrame(fixture.session_id)]);

    cursor = { run_id: fixture.run_id, seq: 9 };
    socket.open("ws://host/api/v1/events");
    created[1]?.onopen?.(new Event("open"));
    expect(created[1]?.sent).toEqual([
      subscribeFrame(fixture.session_id),
      resumeFrameJson(fixture.session_id, cursor),
    ]);
  });

  it("sends only the two closed control keys", () => {
    expect(Object.keys(JSON.parse(subscribeFrame("s")) as object)).toEqual(["subscribe"]);
    expect(
      Object.keys(JSON.parse(resumeFrameJson("s", { run_id: "r", seq: 1 })) as object),
    ).toEqual(["resume"]);
  });

  it("reports a 4409 close as a resync and reconnects", () => {
    const created: FakeSocket[] = [];
    const scheduled: (() => void)[] = [];
    let resyncs = 0;
    const socket = new StreamSocket(
      {
        sessionId: fixture.session_id,
        token: "tok",
        factory: fakeFactory(created),
        schedule: (fn) => {
          scheduled.push(fn);
          return scheduled.length;
        },
        cancel: () => undefined,
      },
      {
        onFrame: () => undefined,
        onStatus: () => undefined,
        onResync: () => {
          resyncs += 1;
        },
        cursor: () => null,
      },
    );
    socket.open("ws://host/api/v1/events");
    created[0]?.onclose?.(
      new CloseEvent("close", { code: RESYNC_CLOSE_CODE, reason: RESYNC_CLOSE_REASON }),
    );
    expect(resyncs).toBe(1);
    expect(scheduled).toHaveLength(1);
    scheduled[0]?.();
    expect(created).toHaveLength(2);
  });

  it("does not report a resync for any other close code", () => {
    const created: FakeSocket[] = [];
    let resyncs = 0;
    const statuses: string[] = [];
    const socket = new StreamSocket(
      {
        sessionId: fixture.session_id,
        token: "tok",
        factory: fakeFactory(created),
        schedule: () => 1,
        cancel: () => undefined,
      },
      {
        onFrame: () => undefined,
        onStatus: (status) => statuses.push(status),
        onResync: () => {
          resyncs += 1;
        },
        cursor: () => null,
      },
    );
    socket.open("ws://host/api/v1/events");
    created[0]?.onclose?.(new CloseEvent("close", { code: 1006 }));
    expect(resyncs).toBe(0);
    expect(statuses).toContain("reconnecting");
  });

  it("drops a frame it cannot read rather than guessing at it", () => {
    const created: FakeSocket[] = [];
    const frames: EventFrame[] = [];
    const socket = new StreamSocket(
      { sessionId: fixture.session_id, token: "tok", factory: fakeFactory(created) },
      {
        onFrame: (f) => frames.push(f),
        onStatus: () => undefined,
        onResync: () => undefined,
        cursor: () => null,
      },
    );
    socket.open("ws://host/api/v1/events");
    created[0]?.onmessage?.(new MessageEvent("message", { data: "not json" }));
    created[0]?.onmessage?.(new MessageEvent("message", { data: JSON.stringify({ hello: 1 }) }));
    created[0]?.onmessage?.(
      new MessageEvent("message", { data: JSON.stringify(fixture.live_frames[0]) }),
    );
    expect(frames).toHaveLength(1);
    expect(frames[0]?.kind).toBe("text_delta");
  });

  it("builds the socket URL on the same origin as the REST calls", () => {
    expect(eventsUrl({ protocol: "http:", host: "127.0.0.1:8760" })).toBe(
      "ws://127.0.0.1:8760/api/v1/events",
    );
    expect(eventsUrl({ protocol: "https:", host: "example" })).toBe("wss://example/api/v1/events");
  });
});
