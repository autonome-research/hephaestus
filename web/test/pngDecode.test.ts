// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The PNG decoder the G4.5 helper reads pixels with (INTERFACE.md §5.4).
//
// A decoder that silently mis-reads one filter type would make the mask delta
// meaningless in a way no assertion downstream could notice, so the round-trip
// is exercised per filter type rather than on whatever a sample file happens to
// use. The refusals are tested too: §5.4's mask is a *palette match*, and a
// decoder that quietly accepted an indexed or 16-bit file would be matching
// something else.

import { describe, expect, it } from "vitest";
import { decodePng, PngFormatError } from "../e2e/helpers/png";
import { encodePng, paintRect, solidFrame, type FilterType } from "./png";

const FILTERS: readonly FilterType[] = [0, 1, 2, 3, 4];

describe("decodePng", () => {
  it.each(FILTERS)("round-trips a 4-channel image under filter type %i", (filter) => {
    const width = 9;
    const height = 7;
    const data = solidFrame(width, height, [10, 20, 30], 4);
    paintRect(data, { width, channels: 4 }, { x: 2, y: 1, w: 4, h: 3 }, [200, 100, 50]);
    paintRect(data, { width, channels: 4 }, { x: 7, y: 5, w: 2, h: 2 }, [1, 2, 3]);

    const decoded = decodePng(encodePng({ width, height, channels: 4, data, filter }));

    expect(decoded.width).toBe(width);
    expect(decoded.height).toBe(height);
    expect(decoded.channels).toBe(4);
    expect([...decoded.data]).toEqual([...data]);
  });

  it("round-trips a 3-channel image with mixed per-row filters", () => {
    const width = 5;
    const height = 5;
    const data = solidFrame(width, height, [7, 8, 9], 3);
    paintRect(data, { width, channels: 3 }, { x: 1, y: 1, w: 3, h: 3 }, [250, 0, 128]);
    // No `filter` option: the encoder cycles 0..4, so every row uses a different
    // one — the shape an adaptive encoder like Pillow's actually produces.
    const decoded = decodePng(encodePng({ width, height, channels: 3, data }));
    expect(decoded.channels).toBe(3);
    expect([...decoded.data]).toEqual([...data]);
  });

  it("refuses a file that is not a PNG", () => {
    expect(() => decodePng(new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8, 9]))).toThrow(PngFormatError);
  });

  it("refuses a colour type it cannot palette-match against", () => {
    const png = encodePng({
      width: 2,
      height: 2,
      channels: 3,
      data: solidFrame(2, 2, [0, 0, 0], 3),
      filter: 0,
    });
    // Rewrite IHDR's colour-type byte to 3 (indexed). Offset: 8 signature +
    // 4 length + 4 type + 9 = 25.
    png[25] = 3;
    expect(() => decodePng(png)).toThrow(/colour type 3/);
  });

  it("refuses an interlaced file rather than decoding it as progressive", () => {
    const png = encodePng({
      width: 2,
      height: 2,
      channels: 4,
      data: solidFrame(2, 2, [0, 0, 0], 4),
      filter: 0,
    });
    png[28] = 1; // IHDR interlace byte
    expect(() => decodePng(png)).toThrow(/interlaced/);
  });
});
