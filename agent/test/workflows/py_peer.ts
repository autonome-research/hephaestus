// A scripted Python bridge peer for the workflow tests.
//
// Answers the five frozen `py.jobstore_*` requests with the SAME semantics as
// `hephaestus.agent_bridge.jobstore.JobStore` (upsert on `(namespace, key)`,
// insertion-ordered listing with optional key prefix, delete reporting whether a
// row existed, checkpoints upserted on `(job_id, checkpoint_key)`), plus
// `py.admission_capacity` / `py.delegate` / `py.tool_dispatch` stubs the workflow
// tests script. Nothing here talks to a real process: it is the peer *contract*,
// which the Python-side tests then re-prove against the real store.

import type { JsonValue } from "../../src/framing.js";

export interface RecordedCall {
  readonly method: string;
  readonly params: { [k: string]: JsonValue };
}

export interface CheckpointRow {
  readonly workflowVersion: string;
  readonly inputHash: string;
  readonly outputHash: string;
  readonly value: JsonValue;
}

export type Handler = (params: { [k: string]: JsonValue }) => JsonValue | Promise<JsonValue>;

export class ScriptedPyPeer {
  /** `namespace -> key -> value`, insertion-ordered exactly like the SQL `seq`. */
  readonly rows = new Map<string, Map<string, JsonValue>>();
  readonly checkpoints = new Map<string, CheckpointRow>();
  readonly calls: RecordedCall[] = [];
  readonly #handlers = new Map<string, Handler>();
  /** Set to make every bridge call reject (transport-loss simulation). */
  down = false;

  /** Register/override a handler for a non-jobstore `py.*` method. */
  handle(method: string, handler: Handler): void {
    this.#handlers.set(method, handler);
  }

  readonly call = async (
    method: string,
    params: { [k: string]: JsonValue },
  ): Promise<JsonValue> => {
    this.calls.push({ method, params });
    if (this.down) throw new Error(`bridge down: ${method}`);
    const scripted = this.#handlers.get(method);
    if (scripted !== undefined) return scripted(params);
    switch (method) {
      case "py.jobstore_put": {
        const ns = this.#ns(String(params.namespace));
        ns.set(String(params.key), params.value ?? null);
        return { ok: true };
      }
      case "py.jobstore_get": {
        const ns = this.#ns(String(params.namespace));
        const value = ns.get(String(params.key));
        return { value: value === undefined ? null : value };
      }
      case "py.jobstore_list": {
        const ns = this.#ns(String(params.namespace));
        const prefix = typeof params.prefix === "string" ? params.prefix : null;
        const limit = typeof params.limit === "number" ? params.limit : null;
        const items: JsonValue[] = [];
        for (const [key, value] of ns) {
          if (prefix !== null && !key.startsWith(prefix)) continue;
          items.push({ key, value });
          if (limit !== null && items.length >= limit) break;
        }
        return { items };
      }
      case "py.jobstore_delete": {
        const ns = this.#ns(String(params.namespace));
        return { deleted: ns.delete(String(params.key)) };
      }
      case "py.jobstore_checkpoint": {
        this.checkpoints.set(`${String(params.job_id)}#${String(params.checkpoint_key)}`, {
          workflowVersion: String(params.workflow_version),
          inputHash: String(params.input_hash),
          outputHash: String(params.output_hash),
          value: params.value ?? null,
        });
        return { ok: true, updated_at: 1 };
      }
      default:
        throw new Error(`unhandled bridge method ${method}`);
    }
  };

  methodCalls(method: string): RecordedCall[] {
    return this.calls.filter((entry) => entry.method === method);
  }

  #ns(namespace: string): Map<string, JsonValue> {
    const existing = this.rows.get(namespace);
    if (existing !== undefined) return existing;
    const created = new Map<string, JsonValue>();
    this.rows.set(namespace, created);
    return created;
  }
}
