import { describe, it, expect } from "vitest";
import {
  LIMITS,
  LimitError,
  ImageError,
  validateJsonStructure,
  enforceMaxUtf8Bytes,
  enforceBinaryBudget,
  utf8LenStrict,
  parseImageHeader,
  MAX_JSON_DEPTH,
  MAX_JSON_ARRAY_ITEMS,
  PROMPT_MAX_UTF8_BYTES,
  MAX_BINARY_BYTES,
} from "../src/limits.js";

// Extract the stable `.code` from a thrown LimitError/ImageError.
function code(fn: () => unknown): string {
  try {
    fn();
  } catch (e) {
    return (e as LimitError).code;
  }
  throw new Error("expected the call to throw");
}

describe("limits document", () => {
  it("is loaded from the single source of truth", () => {
    expect(LIMITS.wire.max_frame_bytes).toBe(64 * 1024 * 1024);
    expect(LIMITS.wire.frame_version).toBe(1);
    expect(PROMPT_MAX_UTF8_BYTES).toBe(32768);
    expect(LIMITS.admission.run_slots).toBe(16);
  });
});

describe("validateJsonStructure", () => {
  it("accepts a well-formed value", () => {
    expect(() => validateJsonStructure({ a: [1, 2, { b: "c" }] })).not.toThrow();
  });
  it("rejects excessive nesting depth", () => {
    let node: unknown = 0;
    for (let i = 0; i < MAX_JSON_DEPTH + 2; i++) node = [node];
    expect(() => validateJsonStructure(node as never)).toThrow(LimitError);
  });
  it("rejects an over-long array", () => {
    const arr = new Array(MAX_JSON_ARRAY_ITEMS + 1).fill(0);
    expect(code(() => validateJsonStructure(arr))).toBe("json_array_too_long");
  });
});

describe("enforceMaxUtf8Bytes", () => {
  it("measures exact UTF-8 bytes", () => {
    expect(enforceMaxUtf8Bytes("café", 100)).toBe(5); // é = 2 bytes
    expect(utf8LenStrict("☕")).toBe(3);
  });
  it("rejects over-limit without truncation", () => {
    expect(code(() => enforceMaxUtf8Bytes("x".repeat(33), 32, "prompt"))).toBe("prompt_too_large");
  });
  it("rejects an unpaired high surrogate as invalid_unicode_scalar", () => {
    // U+D800 alone (no low surrogate) — never coerced to U+FFFD.
    const lone = "a" + String.fromCharCode(0xd800) + "b";
    expect(code(() => enforceMaxUtf8Bytes(lone, PROMPT_MAX_UTF8_BYTES))).toBe(
      "invalid_unicode_scalar",
    );
  });
  it("rejects an unpaired low surrogate", () => {
    const lone = String.fromCharCode(0xdc00);
    expect(code(() => utf8LenStrict(lone))).toBe("invalid_unicode_scalar");
  });
  it("accepts a valid surrogate pair (astral char)", () => {
    expect(utf8LenStrict("😀")).toBe(4);
  });
});

// Minimal crafted image headers (bounded parser reads only the header fields).
function pngHeader(width: number, height: number): Buffer {
  const b = Buffer.alloc(24);
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]).copy(b, 0);
  b.write("IHDR", 12, "latin1");
  b.writeUInt32BE(width, 16);
  b.writeUInt32BE(height, 20);
  return b;
}

function jpegHeader(width: number, height: number): Buffer {
  // SOI, then a baseline SOF0 segment carrying dimensions.
  const sof = Buffer.alloc(2 + 2 + 1 + 2 + 2);
  sof[0] = 0xff;
  sof[1] = 0xc0;
  sof.writeUInt16BE(2 + 1 + 2 + 2, 2); // segment length
  sof[4] = 8; // precision
  sof.writeUInt16BE(height, 5);
  sof.writeUInt16BE(width, 7);
  return Buffer.concat([Buffer.from([0xff, 0xd8]), sof]);
}

describe("parseImageHeader", () => {
  it("reads PNG dimensions", () => {
    expect(parseImageHeader(pngHeader(800, 600))).toEqual({ width: 800, height: 600, kind: "png" });
  });
  it("reads JPEG dimensions", () => {
    expect(parseImageHeader(jpegHeader(1024, 768))).toEqual({
      width: 1024,
      height: 768,
      kind: "jpeg",
    });
  });
  it("rejects a dimension bomb (declared size beyond budget) before decode", () => {
    expect(() => parseImageHeader(pngHeader(100000, 100000))).toThrow(ImageError);
  });
  it("rejects an oversized total-pixel PNG", () => {
    // width*height beyond max_total_pixels but each dimension under the per-axis cap
    expect(code(() => parseImageHeader(pngHeader(4096, 4096 + 1)))).toBe("image_too_large");
  });
  it("rejects non-PNG/JPEG data", () => {
    expect(code(() => parseImageHeader(Buffer.from("GIF89a")))).toBe("unsupported_image");
  });
  it("rejects a byte payload over the per-image budget", () => {
    const oversize = Buffer.alloc(LIMITS.image.max_image_bytes + 1);
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]).copy(oversize, 0);
    expect(code(() => parseImageHeader(oversize))).toBe("image_too_large");
  });
});

// J-http-limits-9: the aggregate binary budget of one tool result was
// declared on both sides of the bridge and enforced by neither — a grep
// found only the export and the dead-limit meta-test. Adopted meaning:
// max_binary_bytes IS max_image_bytes * max_images_per_result, so it is the
// per-RESULT aggregate across every image block, not a second per-image cap.
describe("enforceBinaryBudget (J-http-limits-9)", () => {
  it("is exactly the per-image budget times the per-result image count", () => {
    // Not a coincidence: it is the arithmetic evidence the ledger's fix reads
    // "aggregate" from in the first place.
    expect(MAX_BINARY_BYTES).toBe(LIMITS.image.max_image_bytes * LIMITS.image.max_images_per_result);
  });

  it("admits exactly the cap and refuses one byte over", () => {
    expect(() => enforceBinaryBudget(MAX_BINARY_BYTES)).not.toThrow();
    expect(() => enforceBinaryBudget(MAX_BINARY_BYTES + 1)).toThrow(LimitError);
    try {
      enforceBinaryBudget(MAX_BINARY_BYTES + 1);
    } catch (e) {
      expect((e as LimitError).code).toBe("binary_too_large");
    }
  });

  it("names the field in the refusal message", () => {
    try {
      enforceBinaryBudget(MAX_BINARY_BYTES + 1, "inspect_part result");
    } catch (e) {
      expect((e as LimitError).message).toContain("inspect_part result");
    }
  });
});
