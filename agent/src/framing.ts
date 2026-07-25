// LF-delimited JSON-RPC 2.0 framing — TypeScript mirror of framing.py.
//
// canonicalJson() + encodeFrame() produce BYTE-FOR-BYTE identical output to the
// Python side for the shared golden fixture (ASCII keys; string/int/bool/null/
// array/object values), because both use recursively sorted object keys, compact
// separators, and raw (non-escaped) UTF-8. The decoder is incremental: it aborts
// as soon as an in-progress frame exceeds the 64 MiB cap, without buffering the
// whole oversized frame.

import { WIRE_MAX_FRAME_BYTES } from "./limits.js";

export type JsonValue = null | boolean | number | string | JsonValue[] | { [k: string]: JsonValue };

const NL = 0x0a;

export class FrameError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "FrameError";
  }
}

export class FrameTooLargeError extends FrameError {
  constructor(
    readonly observedBytes: number,
    readonly maxBytes: number,
  ) {
    super(
      "frame_too_large",
      `frame exceeds ${maxBytes} bytes (observed at least ${observedBytes})`,
    );
    this.name = "FrameTooLargeError";
  }
}

/**
 * Canonical, cross-language-stable JSON text: object keys sorted, compact
 * separators, raw UTF-8. Matches Python `json.dumps(sort_keys=True,
 * separators=(",",":"), ensure_ascii=False)` for the fixture value domain.
 */
export function canonicalJson(value: JsonValue): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return "[" + value.map(canonicalJson).join(",") + "]";
  }
  const obj = value as { [k: string]: JsonValue };
  const keys = Object.keys(obj).sort();
  const members = keys.map((k) => JSON.stringify(k) + ":" + canonicalJson(obj[k] as JsonValue));
  return "{" + members.join(",") + "}";
}

/** Serialize one frame to canonical JSON + "\n"; enforce the outbound cap. */
export function encodeFrame(frame: { [k: string]: JsonValue }): Buffer {
  const buf = Buffer.from(canonicalJson(frame) + "\n", "utf8");
  if (buf.length > WIRE_MAX_FRAME_BYTES) {
    throw new FrameTooLargeError(buf.length, WIRE_MAX_FRAME_BYTES);
  }
  return buf;
}

/**
 * Incremental LF framer with a hard per-frame byte cap. Feed raw chunks via
 * push(); it returns the complete frame payloads (without the trailing newline)
 * found so far, retaining any partial trailing line for the next call. Blank
 * lines are skipped. Exceeding the cap — even before a newline arrives — throws
 * FrameTooLargeError (fail closed): the caller tears the connection down.
 */
export class FrameDecoder {
  private chunks: Buffer[] = [];
  private len = 0;

  push(chunk: Buffer): Buffer[] {
    const frames: Buffer[] = [];
    let start = 0;
    const n = chunk.length;
    while (start < n) {
      const nl = chunk.indexOf(NL, start);
      if (nl === -1) {
        const rest = chunk.subarray(start);
        this.chunks.push(rest);
        this.len += rest.length;
        if (this.len > WIRE_MAX_FRAME_BYTES) {
          throw new FrameTooLargeError(this.len, WIRE_MAX_FRAME_BYTES);
        }
        break;
      }
      const part = chunk.subarray(start, nl);
      this.chunks.push(part);
      this.len += part.length;
      if (this.len > WIRE_MAX_FRAME_BYTES) {
        throw new FrameTooLargeError(this.len, WIRE_MAX_FRAME_BYTES);
      }
      const line = Buffer.concat(this.chunks);
      this.chunks = [];
      this.len = 0;
      start = nl + 1;
      if (line.toString("utf8").trim().length > 0) {
        frames.push(line);
      }
    }
    return frames;
  }

  get buffered(): number {
    return this.len;
  }
}
