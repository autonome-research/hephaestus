// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// §7.2's chip substrate: the **parsed result document**, and the field set the
// chip renders from it.
//
// THE SUBSTRATE, and why it is not the event payload. A normalized `tool_result`
// payload has exactly two keys — `toolName` and `text` — and neither is a schema
// output field. The structured result is serialized **inside `text`** as a
// single canonical-JSON block (`agent/src/tools/proxy.ts`:
// `content: [{type: "text", text: JSON.stringify(payload)}]`). §7.2 states this
// once and in full, because an earlier draft intersected the schema's required
// fields with the *envelope's* keys, which is empty for every tool — so a chip
// with zero `data-field` nodes satisfied the assertion. The predicate is over
// `D = JSON.parse(payload.text)`.
//
// THE PREDICATE, restated as the contract this module satisfies. With
// `K = keys(D)`, `R` = the tool's required output fields from
// `schemas/tools/<name>.schema.json`, `references(D)` = the keys of `D` ending in
// `_ref`, and `F` = the chip's `data-field` values:
//
//   1. Completeness (containment): `F ⊇ (R ∪ references(D)) ∩ K`
//   2. Groundedness (closure):     `F ⊆ K`
//
// **This module makes `F = K`.** That satisfies (1) for every tool without the
// client ever holding a copy of the schemas, and it satisfies (2) by
// construction: every field the chip names is a key the payload actually
// carries. §7.2 permits it in as many words — "a chip rendering additional
// fields passes" — and the alternative, shipping the generated schemas into the
// bundle so the client could compute `R`, would put a second copy of the
// contract in the browser for no gain: assertion (2) is what kills placeholder
// fabrication, and `F = K` cannot fabricate.
//
// THE NAMED FAILURE MODE. If `payload.text` is not JSON, or does not parse to a
// JSON object, the chip renders **plainly degraded**: zero `data-field` nodes,
// `data-field-state="unparsed"`, and a stated reason in the body. §7.2 requires
// exactly this, because the one case where the predicate is vacuous is otherwise
// indistinguishable from success. "The result arrived as multiple content
// blocks" reaches us the same way: `normalizeEntries` joins every text block
// into one string, and two concatenated JSON documents do not parse — so the
// degraded branch covers it without the client guessing at block counts.

/** Why a result document could not be read. Closed, and each renders its own copy. */
export const UNPARSED_REASONS = ["empty", "not_json", "not_an_object"] as const;
export type UnparsedReason = (typeof UNPARSED_REASONS)[number];

export type ToolResultDocument = Readonly<Record<string, unknown>>;

export type ParsedToolResult =
  | {
      readonly state: "parsed";
      readonly doc: ToolResultDocument;
      /** `F`, and it is exactly `K`. Insertion order of the server's own JSON. */
      readonly fields: readonly string[];
    }
  | { readonly state: "unparsed"; readonly reason: UnparsedReason };

/** Field-state attribute values, mirrored into `data-field-state`. */
export const FIELD_STATES = ["parsed", "unparsed"] as const;
export type FieldState = (typeof FIELD_STATES)[number];

/**
 * Parse one `tool_result` payload's `text` into §7.2's result document.
 *
 * Total: every input yields a value, and a malformed one yields a *visible*
 * refusal carrying its cause rather than an empty success.
 */
export function parseToolResult(text: string): ParsedToolResult {
  if (text.trim() === "") return { state: "unparsed", reason: "empty" };
  let parsed: unknown;
  try {
    parsed = JSON.parse(text) as unknown;
  } catch {
    return { state: "unparsed", reason: "not_json" };
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return { state: "unparsed", reason: "not_an_object" };
  }
  const doc = parsed as ToolResultDocument;
  return { state: "parsed", doc, fields: Object.keys(doc) };
}

/**
 * The subset of `F` that §7.2 calls `references(D)`: keys ending in `_ref`.
 *
 * Not used to *choose* what to render — `F = K` already contains them — but the
 * chip marks them, because a ref is the provenance spine's currency (§4.3) and
 * a reader scanning a chip for "which artifact is this about" should not have to
 * read every row.
 */
export function referenceFields(fields: readonly string[]): readonly string[] {
  return fields.filter((field) => field.endsWith("_ref"));
}

/** The display form of one field's value: JSON for structure, raw for strings. */
export function fieldDisplay(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === undefined) return "";
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    // A cyclic value cannot come out of `JSON.parse`, but a total function that
    // says so beats one that throws inside a render.
    return "";
  }
}
