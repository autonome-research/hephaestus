// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The client half of INTERFACE.md §2.5's key ladder: minting a UUIDv7.
//
// §2.5's first two rungs are the client's to satisfy — a key-required route with
// no header is `400 idempotency_key_required`, and a header that is not a UUIDv7
// is `400 idempotency_key_malformed`. Both are "no execution", so a client that
// mints a wrong-shaped key never runs anything and never learns why from a
// spinner.
//
// **WHY the version matters and is not decorative.** `http/idempotency.py`
// reads the *timestamp embedded in the key* (`_uuid7_timestamp`) to apply the
// first-sight freshness rung, and refuses `key_timestamp_skew` outside ±300 s. A
// UUIDv4 has no timestamp to read, which is why the server refuses it as
// malformed rather than accepting it as an opaque string.
//
// §22.2's TIGHTENING binds who calls this and when: **the key is minted once per
// *submission*, not once per click.** A transport retry of one export reuses its
// key — that is the whole point, because `_commit_export` installs create-only
// and a keyless or re-keyed retry collides with its own first attempt. A fresh
// key is minted the moment any field changes. Both halves live in
// `ExportPanel`; this module only mints.

/** Bytes of randomness after the 48-bit timestamp and the version nibble. */
const RANDOM_BYTES = 10;

const HEX = "0123456789abcdef";

function hex(byte: number): string {
  return `${HEX[(byte >> 4) & 0xf] ?? "0"}${HEX[byte & 0xf] ?? "0"}`;
}

/**
 * A UUIDv7 whose embedded timestamp is now.
 *
 * Layout (RFC 9562): 48 bits of Unix milliseconds, 4 bits of version `7`, 12
 * bits random, 2 bits variant `0b10`, 62 bits random. Hand-assembled rather than
 * taken from a dependency because `crypto.randomUUID` mints v4 — which this
 * server refuses by name — and a UUID library would be a dependency whose only
 * output is these twenty lines.
 */
export function uuid7(at: number = Date.now()): string {
  const bytes = new Uint8Array(6 + RANDOM_BYTES);
  let millis = Math.max(0, Math.floor(at));
  for (let i = 5; i >= 0; i -= 1) {
    bytes[i] = millis % 256;
    millis = Math.floor(millis / 256);
  }
  crypto.getRandomValues(bytes.subarray(6));
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x70; // version 7
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80; // RFC 9562 variant
  const digits = Array.from(bytes, hex).join("");
  return [
    digits.slice(0, 8),
    digits.slice(8, 12),
    digits.slice(12, 16),
    digits.slice(16, 20),
    digits.slice(20, 32),
  ].join("-");
}

/**
 * The same function under the name the §23 provider client calls it by.
 *
 * An alias rather than a second implementation: two key minters in one client is
 * exactly the duplication mission rule 6 forbids, and the shape the server
 * accepts is one shape. `uuid7` is what this *is*; `mintIdempotencyKey` is what
 * it is *for*, and a call site that reads better with the second name is welcome
 * to it.
 */
export const mintIdempotencyKey = uuid7;
