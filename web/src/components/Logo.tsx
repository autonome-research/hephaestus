// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The product mark (2026-09-20).
//
// NOT A SPRITE ICON, and deliberately not in `system/icons.tsx`. §3.12's sprite
// is a closed vocabulary of UI icons under one geometry: one `<path>`,
// `fill="none"`, `stroke="currentColor"` at one width, so the same id reads
// inside a Badge, a Button and a rail without an icon-specific rule anywhere.
// A brand mark obeys none of that — it is filled, it is two shapes, and its
// proportions are its own. Putting it in the sprite would either break those
// rules for every id or bend the mark to fit them.
//
// What it DOES keep from the sprite's rules, because they are about the app
// rather than about icons: `currentColor`, so the mark takes the ink of
// whatever it sits in and works in both themes with no second definition; and
// `aria-hidden` unless it is a surface's only label, because the product name
// is printed beside it in every place it is drawn.
//
// TRACED, NOT DRAWN BY EYE. The first version of this file was a hexagonal
// ring with a diamond in it, sketched from the supplied artwork; it was not the
// artwork. These two paths come from vectorising the bitmap: threshold, extract
// connected components, follow the crack boundary, simplify with
// Douglas-Peucker at a 2px tolerance, then snap the vertices that land on a
// regular hexagon's corners. Scored against the source bitmap the result covers
// 97.5% of its ink at an IoU of 0.962, the balance being the artwork's slightly
// softened joins.
//
// TWO PIECES, NO HOLES — which is the thing the eye gets wrong and the trace
// got right. The component pass found two ink regions of near-equal area
// (23884px and 23821px) and exactly ONE background region, the outside. So this
// is not a ring with a counter punched through it: it is two interlocking
// hooks, and every light area connects to the outside through the gap between
// them. `B` is `A` rotated 180 degrees about the centre — verified on the trace
// before it was imposed — so the mark has one definition and cannot drift out
// of symmetry.

export interface LogoProps {
  /** Edge length in px. The mark is drawn on a 32-unit grid and scales. */
  readonly size?: number | undefined;
  /** Present only when the mark is a surface's ONLY label. */
  readonly label?: string | undefined;
  readonly className?: string | undefined;
}

/** The upper hook: outer edge from the top vertex round to the right flank. */
const A = "M16 1.0 L28.99 8.5 L28.94 18.44 L16.19 25.82 L7.47 20.94 L7.37 16.91 L16.29 21.42 L25.2 16.14 L25.3 10.78 L16.1 5.31 L3.54 12.5 L3.01 8.5 Z";

/** The lower hook: `A` rotated 180 degrees about (16, 16). */
const B = "M16 31.0 L3.01 23.5 L3.06 13.56 L15.81 6.18 L24.53 11.06 L24.63 15.09 L15.71 10.58 L6.8 15.86 L6.7 21.22 L15.9 26.69 L28.46 19.5 L28.99 23.5 Z";

export function Logo({ size = 20, label, className }: LogoProps): React.JSX.Element {
  return (
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      className={className}
      data-logo=""
      focusable="false"
      {...(label === undefined ? { "aria-hidden": true } : { role: "img", "aria-label": label })}
    >
      <path d={A} fill="currentColor" />
      <path d={B} fill="currentColor" />
    </svg>
  );
}
