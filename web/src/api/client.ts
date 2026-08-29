// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The one fetch path to `server/http` (INTERFACE.md §2).
//
// Every request carries `Authorization: Bearer <token>` (§2.2) and every refusal
// arrives in §2.4's closed envelope `{status, reason, message, …data}`. This
// module preserves the **reason** rather than flattening refusals into a
// message string: a named refusal that the client renders as generic failure is
// the same defect §4.4 names for provenance — a weak answer that does not say
// why it is weak reads as a bug.

import { workspaceToken, dropToken } from "./token";
import type { RefusalDocument } from "./types";

/** §2.3: "Every route is `/api/v1/…`" — matches `http/app.py::API_PREFIX`. */
export const API_PREFIX = "/api/v1";

/** A refusal the server named. `reason` is the machine word; keep it. */
export class WorkspaceError extends Error {
  readonly status: number;
  readonly reason: string;
  readonly data: Readonly<Record<string, unknown>>;

  constructor(status: number, reason: string, message: string, data: Record<string, unknown> = {}) {
    super(message);
    this.name = "WorkspaceError";
    this.status = status;
    this.reason = reason;
    this.data = data;
  }
}

/** No token at all — §2.2's one non-interactive panel, not an error state. */
export class MissingTokenError extends Error {
  constructor() {
    super("no workspace token");
    this.name = "MissingTokenError";
  }
}

function isRefusal(body: unknown): body is RefusalDocument {
  return (
    typeof body === "object" &&
    body !== null &&
    (body as { status?: unknown }).status === "error" &&
    typeof (body as { reason?: unknown }).reason === "string"
  );
}

/**
 * One authenticated request against the workspace API.
 *
 * `path` is a route template's concrete path **without** the `/api/v1` prefix,
 * e.g. `/parts/widget/build`.
 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = workspaceToken();
  if (token === null) throw new MissingTokenError();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  // JSON unless the caller said otherwise: `/artifacts/{ref}/gltf` answers
  // `model/gltf-binary` and `/bytes` answers the stored mime type (§2.6), and a
  // hard-coded `Accept` would be this client claiming a content type the route
  // does not serve.
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  const response = await fetch(`${API_PREFIX}${path}`, { ...init, headers });
  if (response.status === 401) {
    // The token this tab holds is not the token the server minted — a restarted
    // server mints a new one. Forgetting it puts the app back in §2.2's
    // no-token panel instead of retrying a request that cannot succeed.
    dropToken();
  }
  return response;
}

/** §2.4's envelope, turned into the exception that preserves its `reason`. */
function refusal(status: number, text: string): WorkspaceError {
  let body: unknown = null;
  if (text !== "") {
    try {
      body = JSON.parse(text) as unknown;
    } catch {
      body = null;
    }
  }
  if (isRefusal(body)) {
    const { status: _status, reason, message, ...data } = body as RefusalDocument &
      Record<string, unknown>;
    return new WorkspaceError(status, reason, message, data);
  }
  return new WorkspaceError(status, "transport_error", `HTTP ${status}`);
}

/**
 * The `WorkspaceError` for a non-ok response, envelope preserved.
 *
 * Exported for the one caller that cannot use `apiJson`: §22.4's download reads
 * a `Blob`, not JSON, and a refused download still answers with §2.4's JSON
 * envelope. Without this the download path would either re-issue the request to
 * get its error shape or invent one, and `unknown_export` / `export_too_large`
 * would reach the panel as "the download failed".
 */
export async function refusalFor(response: Response): Promise<WorkspaceError> {
  return refusal(response.status, await response.text());
}

/** One authenticated JSON read, with §2.4's refusal envelope preserved. */
export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, init);
  const text = await response.text();
  if (!response.ok) throw refusal(response.status, text);
  // §2.4 DECISION: a capability refusal is a discriminated result at 200. It is
  // a legitimate body, not an exception, and reaches the caller intact.
  return (text === "" ? null : (JSON.parse(text) as unknown)) as T;
}

/** A binary body plus the response headers that carry its provenance. */
export interface ApiBytes {
  readonly bytes: ArrayBuffer;
  readonly headers: Headers;
}

/**
 * One authenticated **binary** read (§2.6's `/bytes`, §5.1's `/gltf`).
 *
 * The refusal path is `apiJson`'s: a refused binary route still answers with
 * §2.4's JSON envelope, and collapsing it into "the download failed" would lose
 * the named reason — `stale_selection` and `gltf_not_published` are answers, not
 * transport failures.
 */
export async function apiBytes(path: string, init?: RequestInit): Promise<ApiBytes> {
  const response = await apiFetch(path, { ...init, headers: { Accept: "*/*" } });
  if (!response.ok) throw refusal(response.status, await response.text());
  return { bytes: await response.arrayBuffer(), headers: response.headers };
}

/** An artifact ref is opaque and contains `:`; it is a path segment, so encode it. */
export function refSegment(ref: string): string {
  return encodeURIComponent(ref);
}
