// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The `GET /events` transport (INTERFACE.md §2.7). Everything it decides is one
// of the `live.ts` actions; it holds no transcript state of its own.
//
// THE BEARER RIDES A SUBPROTOCOL. §2.2 says the token goes in
// `Authorization: Bearer` on "every request including the WS upgrade", and a
// browser **cannot** set a header on a WebSocket upgrade — there is no API for
// it. The server therefore accepts the token as a second subprotocol value
// (`BEARER_SUBPROTOCOL = "hephaestus.bearer"`, `http/events_ws.py::_bearer`) and
// echoes the first value back on accept. That preserves the property §2.2 argues
// for — the token never enters an access log or a `Referer` — because a
// subprotocol travels in a request header, not in the URL. Putting it in the
// query string, which is the other thing browsers can do, would put it in every
// proxy log on the path, which is exactly what §2.2 forbids.
//
// TWO CONTROL FRAMES AND NO OTHERS. `CONTROL_FRAME_KEYS = {subscribe, resume}`;
// any other key closes the socket `1008`. The vocabulary is closed on the
// client too — a frame is built by the two functions below or not at all.
//
// RECONNECTION IS NOT REPAIR. A `4409 resync_required` close means the server
// dropped this observer to protect the run (§2.7: the browser "never
// participates in `_backpressure_cancel`", because a stalled tab must not kill
// an agent's work). Reconnecting replays only what the live buffer still holds;
// the rest is a labelled break in `live.ts`. This module never fetches history
// to fill one — the two identity namespaces do not compare (§2.8).

import { API_PREFIX } from "../api/client";
import type { EventFrame } from "../api/events";
import { RESYNC_CLOSE_CODE, type LiveCursor } from "./live";
import type { StreamState } from "./transcript";

/** `BEARER_SUBPROTOCOL` in `http/events_ws.py`. */
export const BEARER_SUBPROTOCOL = "hephaestus.bearer";

/** Reconnect backoff, in ms. Bounded and short: a workspace is loopback-local. */
export const RECONNECT_DELAYS_MS = [250, 500, 1000, 2000, 4000] as const;

export interface StreamSocketHandlers {
  readonly onFrame: (frame: EventFrame) => void;
  readonly onStatus: (status: StreamState) => void;
  /** A `4409` close: the panel must show a labelled break before anything else. */
  readonly onResync: () => void;
  /** The cursor to resume from, read at each (re)connect. */
  readonly cursor: () => LiveCursor | null;
}

export interface StreamSocketOptions {
  readonly sessionId: string;
  /**
   * Extra session ids on the same socket (#92). The selected tab still owns
   * `sessionId` for resume; a project-lifetime observer lists every session
   * the rail cares about and does not resume.
   */
  readonly sessionIds?: readonly string[] | undefined;
  readonly token: string;
  /** Injected so the reducer's contract can be driven without a real socket. */
  readonly factory?: (url: string, protocols: readonly string[]) => WebSocket;
  readonly schedule?: (fn: () => void, ms: number) => number;
  readonly cancel?: (handle: number) => void;
}

/** `{"subscribe": {"sessions": [...], "runs": [...]}}` — §2.7's filter frame. */
export function subscribeFrame(sessionId: string | readonly string[]): string {
  const sessions = typeof sessionId === "string" ? [sessionId] : [...sessionId];
  return JSON.stringify({ subscribe: { sessions, runs: [] } });
}

/** `{"resume": {"session_id": …, "after": {"run_id", "seq"}}}`. */
export function resumeFrameJson(sessionId: string, after: LiveCursor): string {
  return JSON.stringify({ resume: { session_id: sessionId, after } });
}

/** `ws(s)://<host>/api/v1/events` — the same origin the REST calls use. */
export function eventsUrl(location: { protocol: string; host: string }): string {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}${API_PREFIX}/events`;
}

function isEventFrame(value: unknown): value is EventFrame {
  if (typeof value !== "object" || value === null) return false;
  const frame = value as Record<string, unknown>;
  return (
    typeof frame["run_id"] === "string" &&
    typeof frame["seq"] === "number" &&
    typeof frame["kind"] === "string"
  );
}

/**
 * One subscription to `GET /events`, for the lifetime of one session tab.
 *
 * `close()` is idempotent and stops reconnection; a component unmounting must
 * call it, because a socket that outlived its panel would keep a server-side
 * observer registered against a queue nobody drains — the precise condition that
 * produces the `4409` this class exists to handle honestly.
 */
export class StreamSocket {
  private socket: WebSocket | null = null;
  private timer: number | null = null;
  private attempt = 0;
  private stopped = false;

  private readonly factory: (url: string, protocols: readonly string[]) => WebSocket;
  private readonly schedule: (fn: () => void, ms: number) => number;
  private readonly cancelTimer: (handle: number) => void;

  constructor(
    private readonly options: StreamSocketOptions,
    private readonly handlers: StreamSocketHandlers,
  ) {
    this.factory =
      options.factory ??
      ((url, protocols) => new WebSocket(url, [...protocols]));
    this.schedule =
      options.schedule ?? ((fn, ms) => window.setTimeout(fn, ms));
    this.cancelTimer = options.cancel ?? ((handle) => { window.clearTimeout(handle); });
  }

  open(url: string): void {
    if (this.stopped) return;
    // No status here. `resyncing` is §7.4's close-and-refill state and it must
    // survive the reconnect that *is* the refill; a `connecting` transition
    // written over it would erase the one state the user needs to see.
    const socket = this.factory(url, [BEARER_SUBPROTOCOL, this.options.token]);
    this.socket = socket;
    socket.onopen = (): void => {
      this.attempt = 0;
      socket.send(subscribeFrame(this.options.sessionIds ?? this.options.sessionId));
      const cursor = this.handlers.cursor();
      if (cursor !== null) {
        // A resume without a prior cursor would ask the server to replay the
        // whole buffer as though this panel had seen part of it. With one, the
        // server replays only what follows — and what it cannot, `live.ts`
        // labels.
        socket.send(resumeFrameJson(this.options.sessionId, cursor));
      }
      this.handlers.onStatus("live");
    };
    socket.onmessage = (event: MessageEvent): void => {
      if (typeof event.data !== "string") return;
      let parsed: unknown;
      try {
        parsed = JSON.parse(event.data) as unknown;
      } catch {
        // A frame this client cannot read is dropped, not guessed at. The server
        // emits the closed vocabulary; anything else is not ours to interpret.
        return;
      }
      if (!isEventFrame(parsed)) return;
      this.handlers.onFrame(parsed);
    };
    socket.onclose = (event: CloseEvent): void => {
      this.socket = null;
      if (this.stopped) return;
      if (event.code === RESYNC_CLOSE_CODE) {
        this.handlers.onResync();
        this.reconnect(url, 0);
        return;
      }
      this.handlers.onStatus("reconnecting");
      this.reconnect(url, this.attempt);
      this.attempt += 1;
    };
    socket.onerror = (): void => {
      // `onclose` always follows; handling both would double-schedule a retry.
    };
  }

  private reconnect(url: string, attempt: number): void {
    const index = Math.min(attempt, RECONNECT_DELAYS_MS.length - 1);
    const delay = RECONNECT_DELAYS_MS[index] ?? 1000;
    this.timer = this.schedule(() => {
      this.timer = null;
      this.open(url);
    }, delay);
  }

  close(): void {
    this.stopped = true;
    if (this.timer !== null) {
      this.cancelTimer(this.timer);
      this.timer = null;
    }
    const socket = this.socket;
    this.socket = null;
    if (socket !== null) {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onclose = null;
      socket.onerror = null;
      socket.close();
    }
    this.handlers.onStatus("detached");
  }
}
