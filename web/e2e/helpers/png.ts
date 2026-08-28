// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// A PNG decoder for the **test harness** (INTERFACE.md §5.4).
//
// §5.4's step 1: "Fetch the **solid-ID pass PNG** for the pinned build from
// `/artifacts/{ref}/bytes` (§2.6, byte-exact, no transformation) and decode it
// **test-side** to a mask `M` for the target solid's palette value." Step 3
// compares two viewport screenshots. Both need pixels out of a PNG, and both are
// harness work: "All three steps run in the **test harness**, never in the
// workspace. §1's closed list bars the *client* from decoding a shaded viewport
// frame or a palette, and that bar is untouched: **the app ships no pixel
// reader**."
//
// That last clause is why this file is under `e2e/` and not `src/`. Nothing in
// `web/src` imports it, the bundle does not contain it, and `pnpm build` never
// sees it.
//
// WHY IT IS HAND-WRITTEN RATHER THAN A DEPENDENCY. §19 item 15 makes the `web/`
// dependency set a **recorded, pinned** list in `repo_conventions.md`; adding an
// image library to decode two well-known PNG shapes would put a new name on that
// list, in the *test* tier, for about a hundred lines of work. `node:zlib` is a
// Node builtin and does the only hard part. The decoder is deliberately narrow
// and **refuses by name** rather than guessing:
//
//   * 8-bit only          — `encode_png` (`core/render/channels.py`:523-540)
//     writes 8-bit RGB/RGBA through Pillow, and Chromium screenshots are 8-bit
//     RGBA. A 16-bit input is a different file than either.
//   * colour types 2 and 6 only — truecolour and truecolour+alpha. A palette or
//     greyscale PNG would decode to indices, and a mask built from indices is
//     not the palette match §5.4 asks for.
//   * non-interlaced only — neither producer emits Adam7.
//
// A refusal here is a test that fails loudly at the decode, which is what should
// happen when the pixel source stops being what this comparison assumes.

import { inflateSync } from "node:zlib";

/** A decoded PNG: 8-bit samples, `channels` per pixel, row-major. */
export interface DecodedPng {
  readonly width: number;
  readonly height: number;
  /** 3 for RGB, 4 for RGBA. */
  readonly channels: 3 | 4;
  /** `width * height * channels` bytes. */
  readonly data: Uint8Array;
}

/** The decoder refused this file, and says which assumption it broke. */
export class PngFormatError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PngFormatError";
  }
}

const SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
const CHANNELS_BY_COLOUR_TYPE: Readonly<Record<number, 3 | 4>> = { 2: 3, 6: 4 };

interface Header {
  readonly width: number;
  readonly height: number;
  readonly channels: 3 | 4;
}

function readHeader(view: DataView, offset: number, length: number): Header {
  if (length !== 13) throw new PngFormatError(`IHDR is ${length} bytes, not 13`);
  const width = view.getUint32(offset, false);
  const height = view.getUint32(offset + 4, false);
  const bitDepth = view.getUint8(offset + 8);
  const colourType = view.getUint8(offset + 9);
  const compression = view.getUint8(offset + 10);
  const filter = view.getUint8(offset + 11);
  const interlace = view.getUint8(offset + 12);
  if (bitDepth !== 8) throw new PngFormatError(`bit depth ${bitDepth} is not 8`);
  const channels = CHANNELS_BY_COLOUR_TYPE[colourType];
  if (channels === undefined) {
    throw new PngFormatError(`colour type ${colourType} is not truecolour (2) or truecolour+alpha (6)`);
  }
  if (compression !== 0) throw new PngFormatError(`compression method ${compression} is not deflate`);
  if (filter !== 0) throw new PngFormatError(`filter method ${filter} is not the adaptive one`);
  if (interlace !== 0) throw new PngFormatError("interlaced (Adam7) PNGs are not decoded here");
  if (width === 0 || height === 0) throw new PngFormatError("PNG has a zero dimension");
  return { width, height, channels };
}

/** Paeth predictor, straight from the PNG specification's own pseudocode. */
function paeth(a: number, b: number, c: number): number {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  if (pa <= pb && pa <= pc) return a;
  return pb <= pc ? b : c;
}

/** Reverse the per-scanline adaptive filter, in place into a fresh buffer. */
function unfilter(raw: Uint8Array, header: Header): Uint8Array {
  const { width, height, channels } = header;
  const stride = width * channels;
  const expected = height * (stride + 1);
  if (raw.length < expected) {
    throw new PngFormatError(`inflated to ${raw.length} bytes, expected at least ${expected}`);
  }
  const out = new Uint8Array(height * stride);
  for (let y = 0; y < height; y += 1) {
    const filterType = raw[y * (stride + 1)] as number;
    const line = y * (stride + 1) + 1;
    const target = y * stride;
    const previous = target - stride;
    for (let x = 0; x < stride; x += 1) {
      const value = raw[line + x] as number;
      const a = x >= channels ? (out[target + x - channels] as number) : 0;
      const b = y > 0 ? (out[previous + x] as number) : 0;
      const c = y > 0 && x >= channels ? (out[previous + x - channels] as number) : 0;
      let restored: number;
      switch (filterType) {
        case 0:
          restored = value;
          break;
        case 1:
          restored = value + a;
          break;
        case 2:
          restored = value + b;
          break;
        case 3:
          restored = value + ((a + b) >> 1);
          break;
        case 4:
          restored = value + paeth(a, b, c);
          break;
        default:
          throw new PngFormatError(`row ${y} uses filter type ${filterType}`);
      }
      out[target + x] = restored & 0xff;
    }
  }
  return out;
}

/** Decode an 8-bit, non-interlaced, truecolour PNG. */
export function decodePng(bytes: Uint8Array): DecodedPng {
  if (bytes.length < 8) throw new PngFormatError("shorter than the PNG signature");
  for (let i = 0; i < SIGNATURE.length; i += 1) {
    if (bytes[i] !== SIGNATURE[i]) throw new PngFormatError("not a PNG (bad signature)");
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let offset = 8;
  let header: Header | null = null;
  const parts: Uint8Array[] = [];

  while (offset + 8 <= bytes.length) {
    const length = view.getUint32(offset, false);
    const type = String.fromCharCode(
      bytes[offset + 4] as number,
      bytes[offset + 5] as number,
      bytes[offset + 6] as number,
      bytes[offset + 7] as number,
    );
    const start = offset + 8;
    if (start + length + 4 > bytes.length) {
      throw new PngFormatError(`chunk ${type} at byte ${offset} runs past the file`);
    }
    if (type === "IHDR") header = readHeader(view, start, length);
    else if (type === "IDAT") parts.push(bytes.subarray(start, start + length));
    else if (type === "IEND") break;
    offset = start + length + 4; // + CRC
  }

  if (header === null) throw new PngFormatError("PNG has no IHDR");
  if (parts.length === 0) throw new PngFormatError("PNG has no IDAT");

  const compressed = Buffer.concat(parts.map((part) => Buffer.from(part)));
  const raw = new Uint8Array(inflateSync(compressed));
  return { ...header, data: unfilter(raw, header) };
}
