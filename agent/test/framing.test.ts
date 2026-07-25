import { describe, it, expect } from "vitest";
import {
  canonicalJson,
  encodeFrame,
  FrameDecoder,
  FrameTooLargeError,
} from "../src/framing.js";
import { WIRE_MAX_FRAME_BYTES } from "../src/limits.js";

describe("canonicalJson", () => {
  it("sorts object keys recursively and uses compact separators", () => {
    expect(canonicalJson({ z: 1, a: 2, m: { y: 1, x: 2 } })).toBe('{"a":2,"m":{"x":2,"y":1},"z":1}');
  });
  it("emits raw non-ASCII UTF-8 (no \\u escaping)", () => {
    expect(canonicalJson({ t: "café ☕" })).toBe('{"t":"café ☕"}');
  });
});

describe("encodeFrame", () => {
  it("appends exactly one newline", () => {
    const buf = encodeFrame({ hv: 1, jsonrpc: "2.0", id: 1 });
    expect(buf[buf.length - 1]).toBe(0x0a);
    expect(buf.toString("utf8").slice(0, -1)).toBe('{"hv":1,"id":1,"jsonrpc":"2.0"}');
  });
  it("refuses to emit an oversized frame (outbound guard)", () => {
    const huge = "x".repeat(WIRE_MAX_FRAME_BYTES);
    expect(() => encodeFrame({ big: huge })).toThrow(FrameTooLargeError);
  });
});

describe("FrameDecoder LF handling", () => {
  it("splits multiple frames in one chunk", () => {
    const dec = new FrameDecoder();
    const frames = dec.push(Buffer.from('{"a":1}\n{"b":2}\n'));
    expect(frames.map((f) => f.toString("utf8"))).toEqual(['{"a":1}', '{"b":2}']);
  });
  it("reassembles a frame split across chunk boundaries", () => {
    const dec = new FrameDecoder();
    expect(dec.push(Buffer.from('{"a":'))).toEqual([]);
    expect(dec.push(Buffer.from("1}"))).toEqual([]);
    const frames = dec.push(Buffer.from("\n"));
    expect(frames.map((f) => f.toString("utf8"))).toEqual(['{"a":1}']);
  });
  it("skips blank lines", () => {
    const dec = new FrameDecoder();
    const frames = dec.push(Buffer.from('\n\n{"a":1}\n\n'));
    expect(frames.map((f) => f.toString("utf8"))).toEqual(['{"a":1}']);
  });
  it("round-trips encodeFrame output", () => {
    const dec = new FrameDecoder();
    const value = { hv: 1, jsonrpc: "2.0", method: "event", params: { seq: 3 } };
    const frames = dec.push(encodeFrame(value));
    expect(JSON.parse(frames[0]!.toString("utf8"))).toEqual(value);
  });
});

describe("FrameDecoder incremental oversize abort", () => {
  it("aborts as soon as the cap is exceeded, before any newline arrives", () => {
    const dec = new FrameDecoder();
    // A full-cap chunk with no newline is accepted (buffered == cap)...
    expect(dec.push(Buffer.alloc(WIRE_MAX_FRAME_BYTES, 0x61))).toEqual([]);
    expect(dec.buffered).toBe(WIRE_MAX_FRAME_BYTES);
    // ...but one more byte (still no newline) fails closed incrementally.
    expect(() => dec.push(Buffer.from("a"))).toThrow(FrameTooLargeError);
  });
  it("aborts a single oversized chunk without buffering it whole", () => {
    const dec = new FrameDecoder();
    expect(() => dec.push(Buffer.alloc(WIRE_MAX_FRAME_BYTES + 1, 0x61))).toThrow(
      FrameTooLargeError,
    );
  });
});
