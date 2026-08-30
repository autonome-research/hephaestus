// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The PARAMS write path (INTERFACE.md §10).
//
// A slider commits through `set_params` (a persisted override carrying
// `expected_state_hash`), then a default `build_part` with **no transient
// params**. Transient overrides always return `current=false` and mint a
// preview artifact; a slider wired that way would move the picture and never
// the design.

import { apiJson } from "./client";
import type { BuildDocument, SetParamsResult } from "./types";

export interface SetParamsRequest {
  readonly values: Readonly<Record<string, number>>;
  readonly expected_state_hash: string;
  readonly scope?: "part";
}

async function keyedPost<T>(path: string, body: unknown, key: string): Promise<T> {
  return apiJson<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": key },
    body: JSON.stringify(body),
  });
}

/** `POST /parts/{part}/params` — `set_params`, keyed (§2.3). */
export function postParams(
  part: string,
  request: SetParamsRequest,
  key: string,
): Promise<SetParamsResult> {
  return keyedPost<SetParamsResult>(
    `/parts/${encodeURIComponent(part)}/params`,
    { scope: "part", ...request },
    key,
  );
}

/**
 * `POST /parts/{part}/build` — a default `build_part`.
 *
 * The body is empty on purpose: §10 forbids sending transient `params` here.
 */
export function postBuild(part: string, key: string): Promise<BuildDocument> {
  return keyedPost<BuildDocument>(`/parts/${encodeURIComponent(part)}/build`, {}, key);
}
