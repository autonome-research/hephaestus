// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// A minimal PNG **encoder**, for the tests of the decoder in
// `e2e/helpers/png.ts`.
//
// The decoder's contract is "what Pillow's `encode_png` and Chromium's
// screenshot both produce", and the honest way to test a decoder is to feed it
// files it did not make. This encoder is the independent side of that
// round-trip: it writes the container by hand from the PNG specification, and it
// can emit **each of the five filter types on demand**, which is the branch a
// real file exercises unpredictably and a test must exercise deliberately.
//
// Not exported from `src/`, not shipped: it exists for `test/png.test.ts` and
// `test/maskDelta.test.ts` and nothing else.

import { deflateSync } from "node:zlib";

export type FilterType = 0 | 1 | 2 | 3 | 4;

function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = crc & 1 ? (crc >>> 1) ^ 0xedb88320 : crc >>> 1;
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type: string, body: Uint8Array): Uint8Array {
  const out = new Uint8Array(12 + body.length);
  const view = new DataView(out.buffer);
  view.setUint32(0, body.length, false);
  for (let i = 0; i < 4; i += 1) out[4 + i] = type.charCodeAt(i);
  out.set(body, 8);
  view.setUint32(8 + body.length, crc32(out.subarray(4, 8 + body.length)), false);
  return out;
}

function paeth(a: number, b: number, c: number): number {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  if (pa <= pb && pa <= pc) return a;
  return pb <= pc ? b : c;
}

export interface EncodeOptions {
  readonly width: number;
  readonly height: number;
  readonly channels: 3 | 4;
  /** Row-major samples, `width * height * channels` long. */
  readonly data: Uint8Array;
  /** The filter to apply to every row. Cycles through 0..4 when omitted. */
  readonly filter?: FilterType;
}

/** Encode 8-bit truecolour (RGB/RGBA) PNG bytes. */
export function encodePng(options: EncodeOptions): Uint8Array {
  const { width, height, channels, data } = options;
  const stride = width * channels;
  const raw = new Uint8Array(height * (stride + 1));
  for (let y = 0; y < height; y += 1) {
    const filter: FilterType = options.filter ?? ((y % 5) as FilterType);
    raw[y * (stride + 1)] = filter;
    for (let x = 0; x < stride; x += 1) {
      const value = data[y * stride + x] as number;
      const a = x >= channels ? (data[y * stride + x - channels] as number) : 0;
      const b = y > 0 ? (data[(y - 1) * stride + x] as number) : 0;
      const c = y > 0 && x >= channels ? (data[(y - 1) * stride + x - channels] as number) : 0;
      let encoded: number;
      switch (filter) {
        case 0:
          encoded = value;
          break;
        case 1:
          encoded = value - a;
          break;
        case 2:
          encoded = value - b;
          break;
        case 3:
          encoded = value - ((a + b) >> 1);
          break;
        case 4:
          encoded = value - paeth(a, b, c);
          break;
      }
      raw[y * (stride + 1) + 1 + x] = encoded & 0xff;
    }
  }

  const header = new Uint8Array(13);
  const headerView = new DataView(header.buffer);
  headerView.setUint32(0, width, false);
  headerView.setUint32(4, height, false);
  header[8] = 8;
  header[9] = channels === 4 ? 6 : 2;
  header[10] = 0;
  header[11] = 0;
  header[12] = 0;

  const signature = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const idat = chunk("IDAT", new Uint8Array(deflateSync(Buffer.from(raw))));
  const ihdr = chunk("IHDR", header);
  const iend = chunk("IEND", new Uint8Array(0));

  const out = new Uint8Array(signature.length + ihdr.length + idat.length + iend.length);
  let at = 0;
  for (const part of [signature, ihdr, idat, iend]) {
    out.set(part, at);
    at += part.length;
  }
  return out;
}

/** A solid-colour frame, the usual starting point for a synthetic case. */
export function solidFrame(
  width: number,
  height: number,
  colour: readonly [number, number, number],
  channels: 3 | 4 = 4,
): Uint8Array {
  const data = new Uint8Array(width * height * channels);
  for (let pixel = 0; pixel < width * height; pixel += 1) {
    const at = pixel * channels;
    data[at] = colour[0];
    data[at + 1] = colour[1];
    data[at + 2] = colour[2];
    if (channels === 4) data[at + 3] = 255;
  }
  return data;
}

/** Paint an axis-aligned rectangle into a frame buffer. */
export function paintRect(
  data: Uint8Array,
  frame: { width: number; channels: 3 | 4 },
  rect: { x: number; y: number; w: number; h: number },
  colour: readonly [number, number, number],
): void {
  for (let y = rect.y; y < rect.y + rect.h; y += 1) {
    for (let x = rect.x; x < rect.x + rect.w; x += 1) {
      const at = (y * frame.width + x) * frame.channels;
      data[at] = colour[0];
      data[at + 1] = colour[1];
      data[at + 2] = colour[2];
      if (frame.channels === 4) data[at + 3] = 255;
    }
  }
}
