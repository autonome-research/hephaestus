// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// What one tool result SAYS, in one line (INTERFACE.md §7.2, §3.3).
//
// §7.2 fixes the chip's `data-*` contract and this module does not touch it:
// `data-field` still names exactly `keys(JSON.parse(payload.text))`, which is
// what `toolResult.ts` computes and what the gate reads. What §7.2 does **not**
// fix is how a chip READS, and the shipped chip read as its own wire format —
// every key of every result document as a mono row, opaque digests included, so
// `read_part` returning a `part_param_state_hash` printed a 71-character sha256
// where a sentence belonged. §3.3's first principle is that this column is a
// collaborator rather than a console; a transcript whose successful calls are
// walls of hash is a console.
//
// TWO DECISIONS, both about presentation and neither about content:
//
// **1. An opaque digest is elided, never hidden.** A sha256 is an identity: the
// reader needs to know one is there and needs to be able to copy it, and needs
// approximately none of its 64 hex digits to recognise the row. So a digest
// renders head-and-tail through `formatRef` with the whole value on `title`, the
// same treatment §4.7 already gives the header pin and the composer's artifact
// chip. Nothing is dropped from the DOM.
//
// **2. The headline is chosen from the document, never composed.** `summaryOf`
// picks fields the document actually carries, prefers the ones that answer "what
// happened" (`status`, then the subject, then a message), and prints the rest as
// a COUNT. It never re-words a value, never counts anything the server did not
// send, and returns `null` rather than inventing a sentence when a document
// carries nothing legible — §4.4's discipline: a summary that had to be guessed
// at is not a summary, and the collapsed field list below it is the answer.

import { formatRef } from "../system/format";
import { fieldDisplay, type ToolResultDocument } from "./toolResult";

/**
 * Longest value that still reads as a phrase rather than as a dump.
 *
 * Sized to the STREAM column at 1280px: the well is ~380px, and a mono line
 * that long is about 44 glyphs before it wraps. A headline that wraps twice is
 * the wall this module exists to remove, so the budget is under one line.
 */
export const SUMMARY_VALUE_MAX = 40;

/** Glyphs an elided digest keeps. Head plus tail, so two digests never collide. */
export const DIGEST_GLYPHS = 18;

/** How many headline fields one line may carry before it stops being one line. */
export const SUMMARY_FIELDS_MAX = 2;

/**
 * Fields that answer "what happened", in the order a reader asks it.
 *
 * Not a schema and not a closed set: a document that carries none of these is
 * summarised from its own first legible field instead (see `summaryOf`). The
 * list only decides *precedence* among keys the document already has, so it can
 * never name a field the payload lacks — §7.2's groundedness, applied to the
 * headline as well as to the field set.
 */
export const HEADLINE_FIELDS: readonly string[] = [
  "part",
  "name",
  "path",
  "file",
  "question",
  "artifact",
  "message",
  "reason",
  "state",
];

/**
 * Result keys that answer "how much / which generation", not "which operand".
 *
 * These stay behind the disclosure. Putting `line_count` or `status` on the
 * face is what made three `read_part` chips identical (#48). `status` is
 * already the chip badge.
 */
export const HEADLINE_METADATA: ReadonlySet<string> = new Set([
  "status",
  "line_count",
  "lines",
  "truncated",
  "generation",
  "current",
  "count",
]);

/** Call-argument keys that name the operand the operator already knows. */
export const OPERAND_FIELDS: readonly string[] = [
  "part",
  "name",
  "path",
  "file",
  "question",
  "artifact",
];

/**
 * Is this string an opaque content address rather than something to read?
 *
 * Three shapes, all of them identities the engine mints: a prefixed ref
 * (`artifact:build:sha256:…`), an algorithm-prefixed digest (`sha256:…`), and a
 * bare long hex run, which is how a `*_state_hash` reaches the transcript. The
 * test is on SHAPE, never on the key's name: a hash under an unexpected key is
 * still a hash, and a key called `hash` carrying `"none"` is still readable.
 */
export function isOpaqueDigest(value: string): boolean {
  if (/^[a-z0-9_]+:/i.test(value) && /[0-9a-f]{16,}/i.test(value)) return true;
  return /^[0-9a-f]{32,}$/i.test(value);
}

/**
 * One field's value as a reader should see it: elided if opaque, else verbatim.
 *
 * The return carries both forms because the caller needs both — the short one
 * for the row and the full one for `title` and for a copy — and computing them
 * in two places is how they drift.
 */
export interface DisplayValue {
  readonly text: string;
  readonly full: string;
  readonly elided: boolean;
}

export function displayValue(value: unknown): DisplayValue {
  const full = fieldDisplay(value);
  if (typeof value === "string" && isOpaqueDigest(value)) {
    const text = formatRef(value, DIGEST_GLYPHS);
    return { text, full, elided: text !== full };
  }
  if (full.length <= SUMMARY_VALUE_MAX * 2) return { text: full, full, elided: false };
  // A long structure — a findings array, an inlined script — is not a digest and
  // must not be dressed as one, but a 4kB row is a scroll bar in a transcript.
  // It is cut with the same ellipsis and says so through `elided`.
  return { text: `${full.slice(0, SUMMARY_VALUE_MAX * 2)}…`, full, elided: true };
}

/** One headline pair: the document's own key, and a short form of its value. */
export interface SummaryPart {
  readonly field: string;
  readonly value: string;
}

/** A tool result's one-line reading. `parts` may be empty; `fields` never lies. */
export interface ToolSummary {
  readonly parts: readonly SummaryPart[];
  /** Every key of the result document, including the ones not on the line. */
  readonly fields: number;
}

/**
 * Can this value be a headline? Short scalars only.
 *
 * A number or a boolean always can. A string can when it is neither an opaque
 * digest nor longer than one phrase. A structure never can: `{"a":1,"b":2}` on
 * the headline is the JSON dump one row further up the page.
 */
function headlineValue(value: unknown): string | null {
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (trimmed === "") return null;
  if (isOpaqueDigest(trimmed)) return null;
  if (trimmed.length > SUMMARY_VALUE_MAX) return null;
  if (trimmed.includes("\n")) return null;
  return trimmed;
}

/**
 * The chip's headline for one parsed result document.
 *
 * Precedence first, then the document's own insertion order for whatever is
 * left, so a tool whose result carries none of `HEADLINE_FIELDS` still gets a
 * line out of its own first legible field rather than nothing.
 */
export function summaryOf(doc: ToolResultDocument, fields: readonly string[]): ToolSummary {
  const ordered = [
    ...HEADLINE_FIELDS.filter((field) => fields.includes(field)),
    ...fields.filter((field) => !HEADLINE_FIELDS.includes(field) && !HEADLINE_METADATA.has(field)),
  ];
  const parts: SummaryPart[] = [];
  for (const field of ordered) {
    if (parts.length === SUMMARY_FIELDS_MAX) break;
    if (HEADLINE_METADATA.has(field)) continue;
    const value = headlineValue(doc[field]);
    if (value === null) continue;
    parts.push({ field, value });
  }
  return { parts, fields: fields.length };
}

/**
 * The operand on a tool call's arguments, if one is short enough to read.
 *
 * Used for the chip face while `running` (no result yet) and after `ok` when
 * the result document omitted the part (#69). Never written as `data-field`.
 */
export function operandFromArgs(args: unknown): SummaryPart | null {
  if (args === null || typeof args !== "object" || Array.isArray(args)) return null;
  const record = args as Readonly<Record<string, unknown>>;
  for (const field of OPERAND_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(record, field)) continue;
    const value = headlineValue(record[field]);
    if (value === null) continue;
    return { field, value };
  }
  return null;
}

export interface ChipHeadlineInput {
  readonly args?: unknown;
  readonly doc?: ToolResultDocument | null;
  readonly fields?: readonly string[];
}

/**
 * Face of the chip: argument operand first, then a result headline, else none.
 *
 * `fields` is still the result document's key count — the disclosure label
 * — even when the visible line came from the call.
 */
export function chipHeadline(input: ChipHeadlineInput): ToolSummary {
  const fieldCount = input.fields?.length ?? 0;
  const operand = operandFromArgs(input.args);
  if (operand !== null) return { parts: [operand], fields: fieldCount };
  if (input.doc !== null && input.doc !== undefined && input.fields !== undefined) {
    return summaryOf(input.doc, input.fields);
  }
  return { parts: [], fields: fieldCount };
}
