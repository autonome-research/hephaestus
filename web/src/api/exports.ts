// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Egress, client side (INTERFACE.md §22, Stage 10A).
//
// Three keyed mutations, one projection, and the download — which is the part of
// this module worth reading twice.
//
// THE DOWNLOAD, AND WHY IT IS NOT AN `<a href download>` (§22.4).
// §2.2's DECISION is that the bearer rides in the URL **fragment**, never a query
// string, so it never enters an access log or a `Referer`. A file download must
// not undo that, and the problem is mechanical: `<a href download>`,
// `window.open` and a form POST all *navigate*, and a navigation carries no
// `Authorization` header. §22.4 rejects each alternative by name — a token in the
// query string (which lands in the browser's *downloads list*, outliving both the
// serve and the `sessionStorage` the token was moved into), a cookie (§2.2: no
// login, no cookie, no user model, and CSRF surface on a route table that has
// none), a one-shot signed capability URL (a second credential with its own
// minting, lifetime and revocation story — an authentication subsystem, which
// §15.6 excludes — that lands in the downloads list too), and a service worker (a
// second runtime with its own cache and update lifecycle, bought for a progress
// bar).
//
// What is left, and what `downloadExport` does: **`fetch` with the bearer header
// → `Blob` → object URL → synthetic click → `URL.revokeObjectURL` in a `finally`
// on every path including the throw.** The token never enters any URL; the object
// URL is same-origin and opaque.
//
// THE COST, NAMED RATHER THAN DISCOVERED. The whole file buffers in the tab's
// memory before it reaches disk, and there is no progress. §22.4's TIGHTENING is
// therefore a client obligation as much as a server one: the panel renders the
// byte count from the exports projection **before** offering the download, and
// the button enters `data-export-state="transferring"` for the duration. A file
// the workspace cannot buffer is the server's `export_too_large` refusal carrying
// the size and the CLI path — not a crashed tab.
//
// THE FILENAME IS NOT DERIVED HERE. §22.4: "the `filename` comes from the export
// **result document** the client already holds, not from parsing
// `Content-Disposition` — the client would otherwise be re-deriving a fact it was
// handed, which §1's lint exists to prevent." The projection carries a
// server-derived `filename` per output and this module passes it through
// untouched. It is never built from `path`, which for an agent-authored `target`
// may legally contain `"` and `;`.

import { apiFetch, apiJson, refusalFor } from "./client";
import { uuid7 } from "./idempotency";
import { workspaceToken } from "./token";

// ---------------------------------------------------------------------------
// the engine's enums (§22.1)
// ---------------------------------------------------------------------------
//
// §22.1: "The engine's enum **is** the closed vocabulary and the client renders
// it from `TOOLS_BY_NAME["export_part"].params`, never from a list of its own —
// §1's no-derived-fact rule reaches enums, not only values."
//
// DEVIATION, and the mechanism that discharges the requirement instead.
// `TOOLS_BY_NAME` is a Python object in `contract/tools_decl.py`; a browser
// cannot reach it, and no route on §2.3's table serves a tool schema. The lists
// below are therefore *transcribed* from the generated, committed
// `schemas/tools/{export_part,generate_drawing,generate_doc}.schema.json` — which
// `contract/toolgen.py` writes from `TOOLS_BY_NAME` — and `test/exports.test.ts`
// reads those files and asserts equality. A seventh format, a fourth drawing kind
// or a renamed layout fails a test rather than silently shipping a picker that
// disagrees with the tool. That is §19.36's drift test in the shape this side of
// the boundary can actually carry, and it is named here rather than left for a
// reader to notice the lists are hand-written.

/** `export_part.params.format` — six, and there is no seventh. */
export const EXPORT_FORMATS = ["step", "dxf", "svg", "gltf", "3mf", "stl"] as const;
export type ExportFormat = (typeof EXPORT_FORMATS)[number];

/** `export_part.params.layout`. */
export const EXPORT_LAYOUTS = ["as_built", "nested_sheet"] as const;
export type ExportLayout = (typeof EXPORT_LAYOUTS)[number];

/**
 * The formats `layout` is offered for, from the tool's own conditional
 * (`allOf[0]`: `layout = nested_sheet` ⇒ `format ∈ {dxf, svg}`).
 *
 * §22.1: layout is "revealed only for `dxf`/`svg` because the tool's own
 * conditional refuses it elsewhere and a control that exists only to produce
 * `invalid_params` is a trap".
 */
export const LAYOUT_FORMATS = ["dxf", "svg"] as const;

/** `generate_drawing.params.kind` — all three are offered (§22.1). */
export const DRAWING_KINDS = ["dimensioned", "assembly", "exploded"] as const;
export type DrawingKind = (typeof DRAWING_KINDS)[number];

/** `generate_drawing.params.sheet`. */
export const DRAWING_SHEETS = ["A4", "A3", "letter"] as const;
export type DrawingSheet = (typeof DRAWING_SHEETS)[number];

/** `generate_doc.params.kind` — all three are offered (§22.1). */
export const DOC_KINDS = ["bom", "assembly_instructions", "spec"] as const;
export type DocKind = (typeof DOC_KINDS)[number];

/**
 * The three things the panel can produce. Not an engine enum — a client-side
 * name for "which of the three routes is this submission for" — so it is
 * declared as what it is rather than smuggled in beside the enums above.
 */
export const EXPORT_SUBJECTS = ["export", "drawing", "doc"] as const;
export type ExportSubject = (typeof EXPORT_SUBJECTS)[number];

/** §22.7's `data-export-state`, closed. */
export const EXPORT_STATES = ["idle", "exporting", "transferring", "refused"] as const;
export type ExportState = (typeof EXPORT_STATES)[number];

// ---------------------------------------------------------------------------
// wire shapes
// ---------------------------------------------------------------------------

/** §22.1's kerf readout: what was applied, from where, and why not. */
export interface KerfDecision {
  readonly applied_mm: number | null;
  readonly source: string;
  readonly process: string | null;
  /** `"kerf_uncompensated"` — a warning on the produced file, not a refusal. */
  readonly note?: string;
  /** Which link was missing: `no_process`, `pack_declares_no_kerf`, … */
  readonly reason?: string;
}

/** One committed output, as `GET /parts/{part}/exports` reports it. */
export interface ExportOutput {
  /** The recorded relative path under `.heph/exports/`. Body text only. */
  readonly path: string;
  readonly blob: string;
  readonly bytes: number;
  readonly content_type: string;
  /** Server-derived. Never built here, never parsed from a header (§22.4). */
  readonly filename: string;
}

/** One committed `tp_exports` row. */
export interface ExportRow {
  readonly op_id: string;
  readonly format: string;
  readonly layout: string;
  readonly state: string;
  readonly source_artifact_ref: string;
  readonly source_input_hashes: Readonly<Record<string, unknown>>;
  readonly extra: Readonly<Record<string, unknown>>;
  readonly outputs: readonly ExportOutput[];
  readonly total_bytes: number;
}

/** `GET /parts/{part}/exports` (§22.6's visible retention). */
export interface ExportsDocument {
  readonly status: "ok";
  readonly part: string;
  readonly exports: readonly ExportRow[];
  /** The running total §22.6 requires the panel to show. The server's number. */
  readonly total_bytes: number;
  /** §22.6: there is no unpin and no delete on this surface, and it says so. */
  readonly unpin_available: boolean;
  /** §22.4's ceiling — a server constant, never a client guess. */
  readonly max_download_bytes: number;
}

/** The tool result the three POSTs return verbatim (§22.3: no bytes). */
export interface ExportResult {
  readonly status?: string;
  readonly paths: readonly string[];
  readonly source_artifact_ref: string;
  readonly source_input_hashes: Readonly<Record<string, unknown>>;
  readonly export_hashes: Readonly<Record<string, string>>;
  readonly kerf?: KerfDecision;
  /** §2.5's normative envelope field on a replayed body. */
  readonly replayed?: boolean;
}

// ---------------------------------------------------------------------------
// the routes
// ---------------------------------------------------------------------------

function part(name: string): string {
  return encodeURIComponent(name);
}

/** `GET /parts/{part}/exports`. */
export async function fetchExports(name: string): Promise<ExportsDocument> {
  return apiJson<ExportsDocument>(`/parts/${part(name)}/exports`);
}

/**
 * The body every export submission carries.
 *
 * `artifact_ref` is `WorkspaceState.artifact_ref` **verbatim** and is never
 * `null`: §22.5's most important decision. With a null ref the engine resolves
 * `current_result` at export time, so the operator looks at build A, clicks
 * Export and receives a STEP of build B. The type makes it required; the server
 * refuses it by name anyway, because a type is not a boundary.
 *
 * There is no `target` and no `kerf_mm` field, in either direction (§22.1).
 */
export interface ExportRequest {
  readonly artifact_ref: string;
  readonly format: ExportFormat;
  readonly layout?: ExportLayout;
  readonly blank?: { readonly width_mm: number; readonly height_mm: number };
}

export interface DrawingRequest {
  readonly artifact_ref: string;
  readonly kind: DrawingKind;
  readonly sheet?: DrawingSheet;
}

export interface DocRequest {
  readonly artifact_ref: string;
  readonly kind: DocKind;
}

async function keyedPost<T>(path: string, body: unknown, key: string): Promise<T> {
  return apiJson<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": key },
    body: JSON.stringify(body),
  });
}

/** `POST /parts/{part}/export` — §22.2's keyed mutation. */
export async function runExport(
  name: string,
  request: ExportRequest,
  key: string,
): Promise<ExportResult> {
  return keyedPost<ExportResult>(`/parts/${part(name)}/export`, request, key);
}

/** `POST /parts/{part}/drawing`. */
export async function runDrawing(
  name: string,
  request: DrawingRequest,
  key: string,
): Promise<ExportResult> {
  return keyedPost<ExportResult>(`/parts/${part(name)}/drawing`, request, key);
}

/** `POST /parts/{part}/doc`. */
export async function runDoc(
  name: string,
  request: DocRequest,
  key: string,
): Promise<ExportResult> {
  return keyedPost<ExportResult>(`/parts/${part(name)}/doc`, request, key);
}

/** A fresh submission key (§22.2's TIGHTENING; the panel owns *when*). */
export function submissionKey(): string {
  return uuid7();
}

// ---------------------------------------------------------------------------
// the download (§22.4)
// ---------------------------------------------------------------------------

/**
 * Whether a download can be attempted at all, from the numbers the server gave.
 *
 * The ceiling is `max_download_bytes` off the projection — a **server** constant
 * (§22.4: "never a client guess"). Reading it back rather than hard-coding it is
 * what keeps the disabled button and the server's refusal from disagreeing.
 */
export function tooLargeToBuffer(output: ExportOutput, document: ExportsDocument): boolean {
  return output.bytes > document.max_download_bytes;
}

/**
 * Fetch one export's bytes and hand them to the browser as a file.
 *
 * The whole §22.4 mechanism, in the order that matters:
 *
 * 1. `apiFetch` puts the bearer in an `Authorization` **header** — no token in
 *    any URL, so nothing lands in the downloads list that outlives the serve;
 * 2. the body becomes a `Blob` and then an **object URL**, which is same-origin
 *    and opaque;
 * 3. a synthetic anchor click hands it to the download manager under the
 *    **server-derived** `filename`;
 * 4. `URL.revokeObjectURL` runs in a `finally`, on every path including the
 *    throw. An object URL that is never revoked pins the whole buffered file in
 *    the tab for the life of the document, which on a large assembly STEP is the
 *    stall §22.4 says to name rather than discover.
 *
 * A refusal (`unknown_export`, `export_too_large`, `artifact_kind_mismatch`)
 * arrives as §2.4's JSON envelope and reaches the caller as a `WorkspaceError`
 * with its `reason` intact — the panel renders the name, never "download
 * failed".
 */
export async function downloadExport(output: ExportOutput): Promise<void> {
  const response = await apiFetch(`/exports/${encodeURIComponent(output.blob)}/bytes`, {
    headers: { Accept: "*/*" },
  });
  // §2.4's envelope, preserved: a refused download carries a *reason*
  // (`unknown_export`, `export_too_large`, `artifact_kind_mismatch`) and the
  // panel renders that name. Collapsing it into "the download failed" is the
  // defect §4.4 names for provenance, one layer down.
  if (!response.ok) throw await refusalFor(response);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = output.filename;
    anchor.rel = "noopener";
    anchor.style.display = "none";
    document.body.appendChild(anchor);
    try {
      anchor.click();
    } finally {
      anchor.remove();
    }
  } finally {
    URL.revokeObjectURL(url);
  }
}

/**
 * The token is never in a download URL, asserted as a function rather than a
 * comment.
 *
 * `web/e2e/export.spec.ts` asserts the same property against every request the
 * browser actually issues; this is the unit-testable half, and it exists so the
 * URL construction has one place that can be checked against the live token.
 */
export function exportBytesPath(blob: string): string {
  const token = workspaceToken();
  const path = `/exports/${encodeURIComponent(blob)}/bytes`;
  if (token !== null && path.includes(token)) {
    // Unreachable by construction — a blob hash is `sha256:<hex>` — and thrown
    // rather than trusted, because §2.2's guarantee is the one thing on this
    // route that a future refactor could quietly undo.
    throw new Error("a workspace token must never appear in a URL");
  }
  return path;
}
