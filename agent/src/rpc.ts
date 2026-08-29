// Bidirectional JSON-RPC 2.0 correlation over the framed transport.
//
// The sidecar is the SERVER for session.*/history.*/query.*/runtime.*/shutdown
// requests the supervisor sends, and the CLIENT for py.* requests it originates.
// Frozen method names and the {"hv":1,"jsonrpc":"2.0",...} envelope are fixed by
// agent/DESIGN.md; the Python mirror lives in agent_bridge/protocol.py. Unknown
// `hv` fails closed. Per-request timeouts and a bounded pending map (64) guard
// the client side.

import { WIRE_FRAME_VERSION, MAX_PENDING_RPC } from "./limits.js";
import type { JsonValue } from "./framing.js";

export const FRAME_VERSION = WIRE_FRAME_VERSION;
export const JSONRPC_VERSION = "2.0";

export const ErrorCode = {
  PARSE_ERROR: -32700,
  INVALID_REQUEST: -32600,
  METHOD_NOT_FOUND: -32601,
  INVALID_PARAMS: -32602,
  INTERNAL_ERROR: -32603,
  BUSY: -32000,
  FRAME_TOO_LARGE: -32001,
  UNSUPPORTED_VERSION: -32002,
  TIMEOUT: -32003,
  PROCESS_DOWN: -32004,
  CANCELLED: -32800,
} as const;

// Requests the sidecar SERVES (supervisor -> sidecar).
export const SIDECAR_REQUEST_METHODS: ReadonlySet<string> = new Set([
  "session.create",
  "session.prompt",
  "session.cancel",
  "session.compact",
  "history.page",
  "query.snapshot",
  "runtime.configure",
  "shutdown",
  // INTERFACE.md §23.14 item 3 — the bridge credential methods over Pi's own
  // login/logout/setRuntimeApiKey/listCredentials/getProviderAuthStatus. Pi
  // stays the single credential authority; these are a relay for a flow this
  // repo does not implement (mission rule 6). Requests rather than events:
  // §17 exclusion 10 (no event-vocabulary extension) is not amended by §23.
  "providers.list",
  "credentials.status",
  "credentials.set_key",
  "credentials.signout",
  "login.begin",
  "login.status",
  "login.complete",
  "login.cancel",
]);

// Requests the sidecar ORIGINATES (sidecar -> supervisor).
export const PY_REQUEST_METHODS: ReadonlySet<string> = new Set([
  "py.tool_dispatch",
  "py.jobstore_get",
  "py.jobstore_put",
  "py.jobstore_list",
  "py.jobstore_delete",
  "py.jobstore_checkpoint",
  "py.admission_capacity",
  "py.delegate",
  "py.ask_user",
]);

export const SIDECAR_NOTIFICATIONS: ReadonlySet<string> = new Set(["event", "terminal"]);
export const PY_NOTIFICATIONS: ReadonlySet<string> = new Set([
  "cancel",
  "terminal.ack",
  "session.answer",
]);

export class RpcError extends Error {
  constructor(
    readonly code: number,
    message: string,
    readonly data?: JsonValue,
  ) {
    super(message);
    this.name = "RpcError";
  }
}

type Params = { [k: string]: JsonValue };
export type RequestHandler = (params: Params) => Promise<JsonValue> | JsonValue;
export type NotificationHandler = (params: Params) => void;
export type FrameSink = (frame: { [k: string]: JsonValue }) => void;

interface Pending {
  resolve: (value: JsonValue) => void;
  reject: (err: RpcError) => void;
  timer: ReturnType<typeof setTimeout> | null;
}

export interface RpcOptions {
  readonly maxPending?: number;
  readonly defaultTimeoutMs?: number;
}

export class RpcPeer {
  private nextId = 1;
  private readonly pending = new Map<number, Pending>();
  private readonly handlers = new Map<string, RequestHandler>();
  private readonly notifyHandlers = new Map<string, NotificationHandler>();
  private readonly maxPending: number;
  private readonly defaultTimeoutMs: number;

  constructor(
    private readonly sink: FrameSink,
    options: RpcOptions = {},
  ) {
    this.maxPending = options.maxPending ?? MAX_PENDING_RPC;
    this.defaultTimeoutMs = options.defaultTimeoutMs ?? 120_000;
  }

  /** Register a handler for an incoming request method (server role). */
  on(method: string, handler: RequestHandler): void {
    if (this.handlers.has(method)) {
      throw new Error(`request handler already registered for ${method}`);
    }
    this.handlers.set(method, handler);
  }

  /** Register a handler for an incoming notification (server role). */
  onNotify(method: string, handler: NotificationHandler): void {
    if (this.notifyHandlers.has(method)) {
      throw new Error(`notification handler already registered for ${method}`);
    }
    this.notifyHandlers.set(method, handler);
  }

  get pendingCount(): number {
    return this.pending.size;
  }

  /** Originate a request (client role); resolves with the peer's result. */
  request(method: string, params: Params = {}, timeoutMs?: number): Promise<JsonValue> {
    if (this.pending.size >= this.maxPending) {
      return Promise.reject(
        new RpcError(ErrorCode.BUSY, `pending request queue full (max ${this.maxPending})`),
      );
    }
    const id = this.nextId++;
    return new Promise<JsonValue>((resolve, reject) => {
      const ms = timeoutMs ?? this.defaultTimeoutMs;
      const timer =
        ms > 0
          ? setTimeout(() => {
              this.pending.delete(id);
              reject(new RpcError(ErrorCode.TIMEOUT, `no response for ${method} within ${ms}ms`));
            }, ms)
          : null;
      if (timer && typeof timer.unref === "function") timer.unref();
      this.pending.set(id, { resolve, reject, timer });
      this.sink({
        hv: FRAME_VERSION,
        jsonrpc: JSONRPC_VERSION,
        id,
        method,
        params,
      });
    });
  }

  /** Send a notification (no response expected). */
  notify(method: string, params: Params = {}): void {
    this.sink({ hv: FRAME_VERSION, jsonrpc: JSONRPC_VERSION, method, params });
  }

  /** Fail every in-flight outgoing request (e.g. transport loss). */
  rejectAllPending(err: RpcError): void {
    for (const [, entry] of this.pending) {
      if (entry.timer) clearTimeout(entry.timer);
      entry.reject(err);
    }
    this.pending.clear();
  }

  /** Parse and route one raw frame payload (without the trailing newline). */
  async handleFrame(raw: Buffer): Promise<void> {
    let frame: unknown;
    try {
      frame = JSON.parse(raw.toString("utf8"));
    } catch {
      this.sink(errorFrame(null, ErrorCode.PARSE_ERROR, "parse error"));
      return;
    }
    if (frame === null || typeof frame !== "object" || Array.isArray(frame)) {
      this.sink(errorFrame(null, ErrorCode.INVALID_REQUEST, "frame is not a JSON object"));
      return;
    }
    const msg = frame as { [k: string]: JsonValue };
    if (msg.hv !== FRAME_VERSION) {
      const id = isIdValue(msg.id) ? msg.id : null;
      this.sink(
        errorFrame(
          id,
          ErrorCode.UNSUPPORTED_VERSION,
          `unsupported hv ${String(msg.hv)}; this bridge speaks hv=${FRAME_VERSION}`,
        ),
      );
      return;
    }
    if (msg.jsonrpc !== JSONRPC_VERSION) {
      const id = isIdValue(msg.id) ? msg.id : null;
      this.sink(errorFrame(id, ErrorCode.INVALID_REQUEST, "jsonrpc must be 2.0"));
      return;
    }

    const method = typeof msg.method === "string" ? msg.method : undefined;
    const hasId = isIdValue(msg.id);

    if (method !== undefined && hasId) {
      await this.dispatchRequest(msg.id as number | string, method, asParams(msg.params));
      return;
    }
    if (method !== undefined) {
      const handler = this.notifyHandlers.get(method);
      if (handler) handler(asParams(msg.params));
      return;
    }
    if (hasId) {
      this.resolveResponse(msg);
      return;
    }
    this.sink(errorFrame(null, ErrorCode.INVALID_REQUEST, "frame is neither request/response"));
  }

  private async dispatchRequest(
    id: number | string,
    method: string,
    params: Params,
  ): Promise<void> {
    const handler = this.handlers.get(method);
    if (!handler) {
      this.sink(errorFrame(id, ErrorCode.METHOD_NOT_FOUND, `method not found: ${method}`));
      return;
    }
    try {
      const result = await handler(params);
      this.sink({ hv: FRAME_VERSION, jsonrpc: JSONRPC_VERSION, id, result });
    } catch (err) {
      if (err instanceof RpcError) {
        this.sink(errorFrame(id, err.code, err.message, err.data));
      } else {
        const message = err instanceof Error ? err.message : String(err);
        this.sink(errorFrame(id, ErrorCode.INTERNAL_ERROR, message));
      }
    }
  }

  private resolveResponse(msg: { [k: string]: JsonValue }): void {
    const id = msg.id;
    if (typeof id !== "number") return; // we only originate numeric ids
    const entry = this.pending.get(id);
    if (!entry) return; // late/duplicate response after timeout: ignore
    this.pending.delete(id);
    if (entry.timer) clearTimeout(entry.timer);
    if ("error" in msg && msg.error !== undefined && msg.error !== null) {
      const e = msg.error as { code?: JsonValue; message?: JsonValue; data?: JsonValue };
      const code = typeof e.code === "number" ? e.code : ErrorCode.INTERNAL_ERROR;
      const message = typeof e.message === "string" ? e.message : "rpc error";
      entry.reject(new RpcError(code, message, e.data));
    } else {
      entry.resolve(msg.result ?? null);
    }
  }
}

function isIdValue(v: JsonValue | undefined): v is number | string {
  return typeof v === "number" || typeof v === "string";
}

function asParams(v: JsonValue | undefined): { [k: string]: JsonValue } {
  if (v !== null && typeof v === "object" && !Array.isArray(v)) {
    return v as { [k: string]: JsonValue };
  }
  return {};
}

function errorFrame(
  id: number | string | null,
  code: number,
  message: string,
  data?: JsonValue,
): { [k: string]: JsonValue } {
  const error: { [k: string]: JsonValue } = { code, message };
  if (data !== undefined) error.data = data;
  return { hv: FRAME_VERSION, jsonrpc: JSONRPC_VERSION, id, error };
}
