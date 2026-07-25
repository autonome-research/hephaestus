import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { encodeFrame, FrameDecoder, type JsonValue } from "../src/framing.js";

// Cross-language golden: the SAME fixture is asserted by server/tests/test_golden.py.
// The .wire bytes were produced by the Python canonical encoder; the two sides
// must emit and parse them byte-for-byte identically.
const valuesPath = fileURLToPath(new URL("./fixtures/golden_frames.json", import.meta.url));
const wirePath = fileURLToPath(new URL("./fixtures/golden_frames.wire", import.meta.url));

const values = JSON.parse(readFileSync(valuesPath, "utf8")) as Array<{ [k: string]: JsonValue }>;
const wire = readFileSync(wirePath);

describe("cross-language golden frames", () => {
  it("encodeFrame reproduces the committed wire bytes exactly", () => {
    const emitted = Buffer.concat(values.map((v) => encodeFrame(v)));
    expect(emitted.equals(wire)).toBe(true);
  });

  it("decodes the committed wire bytes back to the fixture values", () => {
    const dec = new FrameDecoder();
    const frames = dec.push(wire);
    expect(frames).toHaveLength(values.length);
    const parsed = frames.map((f) => JSON.parse(f.toString("utf8")));
    expect(parsed).toEqual(values);
  });

  it("survives arbitrary chunk boundaries", () => {
    const dec = new FrameDecoder();
    const out: Buffer[] = [];
    for (let i = 0; i < wire.length; i += 7) {
      out.push(...dec.push(wire.subarray(i, i + 7)));
    }
    expect(out.map((f) => JSON.parse(f.toString("utf8")))).toEqual(values);
  });
});
