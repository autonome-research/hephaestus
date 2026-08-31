// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The two DFM writes INTERFACE.md §6.4 keeps apart.
//
// `[dfm] auto_run` is a *project setting*, not a per-message flag, so the
// workspace exposes (a) a **Run DFM** action → `POST /parts/{part}/dfm` and
// (b) a project-settings toggle → `POST /project/config/dfm`. Collapsing them
// into one composer switch would imply a tool argument that does not exist.
// Both routes require an `Idempotency-Key`; the caller owns *when*.

import { apiJson } from "./client";
import type { DfmDocument, DfmRun } from "./types";

export interface DfmAutoRunDocument {
  readonly status: "ok";
  readonly auto_run: boolean;
}

async function keyedPost<T>(path: string, body: unknown, key: string): Promise<T> {
  return apiJson<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": key },
    body: JSON.stringify(body),
  });
}

/** `POST /project/config/dfm` — the `[dfm] auto_run` project-config write. */
export function writeDfmAutoRun(autoRun: boolean, key: string): Promise<DfmAutoRunDocument> {
  return keyedPost<DfmAutoRunDocument>("/project/config/dfm", { auto_run: autoRun }, key);
}

/**
 * `POST /parts/{part}/dfm` — `run_dfm`, keyed (§2.3).
 *
 * The body is empty by default: process and pack come from the part's own
 * declarations. A caller that has a process from the last run may pass it
 * through; this function does not invent one.
 */
export function runDfm(
  part: string,
  key: string,
  body: Readonly<Record<string, unknown>> = {},
): Promise<DfmRun> {
  return keyedPost<DfmRun>(`/parts/${encodeURIComponent(part)}/dfm`, body, key);
}

/** Re-export the read document so a call site can name one module. */
export type { DfmDocument };
