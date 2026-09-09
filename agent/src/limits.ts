// Bridge limits: the single source of truth loaded from schemas/bridge_limits.json.
//
// Mirror of server/hephaestus/agent_bridge/limits.py. Every architecture §5
// numeric limit is read from the JSON file at import time; NO limit literal is
// duplicated here. Also exports the bounded validators the sidecar runs before
// trusting a payload: JSON structural caps, x-hephaestus-maxUtf8Bytes enforcement
// (with unpaired-surrogate rejection — never replacement-character coercion), and
// a PNG/JPEG header parser that recovers dimensions before any full decode.

import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

export interface DelegationLimits {
  readonly deadline_default_seconds: number;
  readonly deadline_min_seconds: number;
  readonly deadline_max_seconds: number;
  readonly grace_seconds: number;
}

export interface BridgeLimits {
  readonly version: number;
  readonly wire: { readonly frame_version: number; readonly max_frame_bytes: number };
  readonly json: {
    readonly max_depth: number;
    readonly max_members: number;
    readonly max_array_items: number;
    readonly max_string_bytes: number;
  };
  readonly binary: { readonly max_binary_bytes: number };
  readonly image: {
    readonly max_image_bytes: number;
    readonly max_width: number;
    readonly max_height: number;
    readonly max_total_pixels: number;
    readonly max_images_per_result: number;
  };
  readonly rpc: { readonly max_pending: number; readonly py_handler_workers: number };
  readonly admission: { readonly run_slots: number };
  readonly events: { readonly buffered_events: number };
  readonly timeouts: {
    readonly tool_seconds: number;
    readonly cad_build_seconds: number;
    readonly delegation: DelegationLimits;
  };
  readonly prompt: { readonly max_utf8_bytes: number };
  readonly text_result: { readonly max_bytes: number; readonly max_lines: number };
}

// `schemas/bridge_limits.json` is the single source of truth for these bounds:
// Python reads the same file, so a limit can never be raised on one side of the
// bridge alone. That makes *where* it is on disk layout-dependent, and there are
// two layouts:
//
//   - source / `tsc` output: agent/src/limits.ts and agent/dist/limits.js both
//     sit two levels under the repo root, so `../../schemas/` finds it;
//   - the bundled sidecar shipped in the wheel: there is no repo. The bundler
//     copies the schema to `schemas/bridge_limits.json` beside the entry point,
//     where it is covered by the sidecar's integrity manifest — so a tampered
//     limits file is a fail-closed refusal, not a silently widened bound.
//
// Candidates are tried in order and the first that exists wins. An explicit
// HEPHAESTUS_BRIDGE_LIMITS still overrides both (tests pin bounds with it).
const LIMITS_CANDIDATES = [
  new URL("../../schemas/bridge_limits.json", import.meta.url),
  new URL("./schemas/bridge_limits.json", import.meta.url),
];

function loadLimits(): BridgeLimits {
  const override = process.env.HEPHAESTUS_BRIDGE_LIMITS;
  if (override !== undefined) {
    return JSON.parse(readFileSync(override, "utf8")) as BridgeLimits;
  }
  const tried: string[] = [];
  for (const candidate of LIMITS_CANDIDATES) {
    const path = fileURLToPath(candidate);
    tried.push(path);
    if (existsSync(path)) {
      return JSON.parse(readFileSync(path, "utf8")) as BridgeLimits;
    }
  }
  throw new Error(
    `bridge_limits.json not found (tried: ${tried.join(", ")}); ` +
      "set HEPHAESTUS_BRIDGE_LIMITS to name it explicitly",
  );
}

export const LIMITS: BridgeLimits = loadLimits();

export const WIRE_FRAME_VERSION = LIMITS.wire.frame_version;
export const WIRE_MAX_FRAME_BYTES = LIMITS.wire.max_frame_bytes;
export const MAX_JSON_DEPTH = LIMITS.json.max_depth;
export const MAX_JSON_MEMBERS = LIMITS.json.max_members;
export const MAX_JSON_ARRAY_ITEMS = LIMITS.json.max_array_items;
export const MAX_STRING_BYTES = LIMITS.json.max_string_bytes;
export const MAX_BINARY_BYTES = LIMITS.binary.max_binary_bytes;
export const MAX_IMAGE_BYTES = LIMITS.image.max_image_bytes;
export const MAX_IMAGE_WIDTH = LIMITS.image.max_width;
export const MAX_IMAGE_HEIGHT = LIMITS.image.max_height;
export const MAX_TOTAL_PIXELS = LIMITS.image.max_total_pixels;
export const MAX_IMAGES_PER_RESULT = LIMITS.image.max_images_per_result;
export const MAX_PENDING_RPC = LIMITS.rpc.max_pending;
export const PROMPT_MAX_UTF8_BYTES = LIMITS.prompt.max_utf8_bytes;
export const BUFFERED_EVENTS_MAX = LIMITS.events.buffered_events;

// The three outbound deadlines, in milliseconds (audit-2026-09-04
// J-http-limits-11). The shared document states them in SECONDS, because that
// is the unit every other consumer reads; the conversion happens here, once, so
// no caller multiplies by a thousand of its own.
//
// TOOL_TIMEOUT_MS is the peer's default and the deadline of an ordinary tool
// call. CAD_BUILD_TIMEOUT_MS is the class for the tools that run the sandboxed
// worker; it was declared on the Python supervisor, where a build never travels
// (a build goes sidecar->Python), so no call site could ever select it and the
// 300 s three documents state as fact was unreachable — every tool died at the
// peer's hardcoded 120 s. DELEGATION_GRACE_MS is the margin added to a
// synchronous delegation's own deadline so the delegation's `timed_out`
// terminal wins over a transport timeout instead of racing it.
export const TOOL_TIMEOUT_MS = LIMITS.timeouts.tool_seconds * 1000;
export const CAD_BUILD_TIMEOUT_MS = LIMITS.timeouts.cad_build_seconds * 1000;
export const DELEGATION_GRACE_MS = LIMITS.timeouts.delegation.grace_seconds * 1000;

export class LimitError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "LimitError";
  }
}

export class ImageError extends LimitError {
  constructor(code: string, message: string) {
    super(code, message);
    this.name = "ImageError";
  }
}

export interface ImageDims {
  readonly width: number;
  readonly height: number;
  readonly kind: "png" | "jpeg";
}

type JsonNode = null | boolean | number | string | JsonNode[] | { [k: string]: JsonNode };

/** Reject well-formed-but-pathological JSON against the §5 structural caps. */
export function validateJsonStructure(value: JsonNode): void {
  const stack: Array<{ node: JsonNode; depth: number }> = [{ node: value, depth: 1 }];
  while (stack.length > 0) {
    const { node, depth } = stack.pop() as { node: JsonNode; depth: number };
    if (depth > MAX_JSON_DEPTH) {
      throw new LimitError("json_too_deep", `nesting exceeds depth ${MAX_JSON_DEPTH}`);
    }
    if (Array.isArray(node)) {
      if (node.length > MAX_JSON_ARRAY_ITEMS) {
        throw new LimitError(
          "json_array_too_long",
          `array has ${node.length} items (max ${MAX_JSON_ARRAY_ITEMS})`,
        );
      }
      for (const child of node) stack.push({ node: child, depth: depth + 1 });
    } else if (node !== null && typeof node === "object") {
      const keys = Object.keys(node);
      if (keys.length > MAX_JSON_MEMBERS) {
        throw new LimitError(
          "json_too_many_members",
          `object has ${keys.length} members (max ${MAX_JSON_MEMBERS})`,
        );
      }
      for (const key of keys) {
        checkStringBytes(key);
        stack.push({ node: node[key] as JsonNode, depth: depth + 1 });
      }
    } else if (typeof node === "string") {
      checkStringBytes(node);
    }
  }
}

function checkStringBytes(s: string): void {
  const n = utf8LenStrict(s);
  if (n > MAX_STRING_BYTES) {
    throw new LimitError("json_string_too_large", `string is ${n} bytes (max ${MAX_STRING_BYTES})`);
  }
}

/**
 * Exact UTF-8 byte length, rejecting any unpaired UTF-16 surrogate as
 * `invalid_unicode_scalar`. Because JavaScript must not silently coerce lone
 * surrogates to U+FFFD, we validate pairing first, then measure — so
 * Buffer.byteLength only ever sees a well-formed string.
 */
export function utf8LenStrict(s: string): number {
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff) {
      const next = i + 1 < s.length ? s.charCodeAt(i + 1) : 0;
      if (next < 0xdc00 || next > 0xdfff) {
        throw new LimitError(
          "invalid_unicode_scalar",
          `unpaired high surrogate U+${c.toString(16).toUpperCase()} at index ${i}`,
        );
      }
      i++; // consume the valid low surrogate
    } else if (c >= 0xdc00 && c <= 0xdfff) {
      throw new LimitError(
        "invalid_unicode_scalar",
        `unpaired low surrogate U+${c.toString(16).toUpperCase()} at index ${i}`,
      );
    }
  }
  return Buffer.byteLength(s, "utf8");
}

/**
 * Enforce the AGGREGATE binary budget of one tool result (J-http-limits-9).
 *
 * `binary.max_binary_bytes` was declared on both sides and validated by
 * nothing: a grep for it returned the Python export, the TypeScript export and
 * the test that pinned it as dead. It has one defensible subject on this
 * bridge — the only binary payloads that cross it are the base64 image blocks
 * of a tool result, and eight megabytes (`max_image_bytes`) times four
 * (`max_images_per_result`) is exactly this cap, so the intended meaning is the
 * per-result *aggregate*. Nothing summed them, so a result with four maximal
 * images was bounded only by the per-image check passing four times, and any
 * future non-image payload had no bound at all.
 *
 * Enforced on BOTH sides (`limits.py`'s `enforce_binary_budget`), because a
 * limit enforced on one side of this bridge is not enforced.
 */
export function enforceBinaryBudget(totalBytes: number, field = "result"): void {
  if (totalBytes > MAX_BINARY_BYTES) {
    throw new LimitError(
      "binary_too_large",
      `${field} carries ${totalBytes} binary bytes (max ${MAX_BINARY_BYTES})`,
    );
  }
}

/** Enforce x-hephaestus-maxUtf8Bytes; return the exact UTF-8 byte length. */
export function enforceMaxUtf8Bytes(value: string, maxBytes: number, field = "value"): number {
  const n = utf8LenStrict(value);
  if (n > maxBytes) {
    throw new LimitError("prompt_too_large", `${field} is ${n} UTF-8 bytes (max ${maxBytes})`);
  }
  return n;
}

const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
// JPEG SOF markers carrying dimensions (exclude DHT/JPG/DAC/RSTn).
const JPEG_SOF = new Set([
  0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf,
]);

/** Recover image dimensions from a PNG/JPEG header without a full decode. */
export function parseImageHeader(data: Buffer): ImageDims {
  if (data.length > MAX_IMAGE_BYTES) {
    throw new ImageError("image_too_large", `image is ${data.length} bytes (max ${MAX_IMAGE_BYTES})`);
  }
  let dims: ImageDims;
  if (data.length >= 8 && data.subarray(0, 8).equals(PNG_SIGNATURE)) {
    dims = parsePng(data);
  } else if (data.length >= 2 && data[0] === 0xff && data[1] === 0xd8) {
    dims = parseJpeg(data);
  } else {
    throw new ImageError("unsupported_image", "not a PNG or JPEG header");
  }
  checkDims(dims);
  return dims;
}

function checkDims(dims: ImageDims): void {
  if (dims.width <= 0 || dims.height <= 0) {
    throw new ImageError("image_bad_dimensions", "non-positive image dimension");
  }
  if (dims.width > MAX_IMAGE_WIDTH || dims.height > MAX_IMAGE_HEIGHT) {
    throw new ImageError(
      "image_too_large",
      `${dims.width}x${dims.height} exceeds ${MAX_IMAGE_WIDTH}x${MAX_IMAGE_HEIGHT}`,
    );
  }
  if (dims.width * dims.height > MAX_TOTAL_PIXELS) {
    throw new ImageError(
      "image_too_large",
      `${dims.width * dims.height} pixels exceeds total budget ${MAX_TOTAL_PIXELS}`,
    );
  }
}

function parsePng(data: Buffer): ImageDims {
  if (data.length < 24 || data.subarray(12, 16).toString("latin1") !== "IHDR") {
    throw new ImageError("image_malformed", "PNG missing IHDR chunk");
  }
  return { width: data.readUInt32BE(16), height: data.readUInt32BE(20), kind: "png" };
}

function parseJpeg(data: Buffer): ImageDims {
  let i = 2;
  const n = data.length;
  while (i + 1 < n) {
    if (data[i] !== 0xff) {
      i++;
      continue;
    }
    const marker = data[i + 1] as number;
    i += 2;
    if (marker === 0xd8 || marker === 0xd9 || (marker >= 0xd0 && marker <= 0xd7)) {
      continue;
    }
    if (i + 2 > n) break;
    const segLen = data.readUInt16BE(i);
    if (segLen < 2) throw new ImageError("image_malformed", "JPEG segment length underflow");
    if (JPEG_SOF.has(marker)) {
      if (i + 7 > n) throw new ImageError("image_malformed", "JPEG SOF truncated");
      return { width: data.readUInt16BE(i + 5), height: data.readUInt16BE(i + 3), kind: "jpeg" };
    }
    i += segLen;
  }
  throw new ImageError("image_malformed", "no JPEG SOF marker found");
}
