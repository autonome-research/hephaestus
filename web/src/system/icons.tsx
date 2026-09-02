// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The icon sprite (INTERFACE.md §3.12) — closed, repo-owned, 18 ids.
//
// §3.2 tightened an ambiguous sentence in the original §3: "any icon package
// **beyond an inline SVG sprite**" parses two ways, and the permissive reading
// is in force — a repo-owned inline sprite is permitted and is now REQUIRED.
// The evidence that this needed saying is that `web/src` and `web/public`
// contained **zero** `.svg` files and zero `<svg>` elements. The sprite was
// never rejected; nobody built the thing the sentence already allowed.
//
// REFUSAL, unchanged: no icon font, no `@iconify`, no Lucide, no Heroicons. The
// bundle ships inside a Python wheel and its weight is the operator's download.
//
// REFUSAL: icons never replace words in a status. `<Badge>` renders icon **+**
// word, always. The 18 ids exist to make a scan *faster*, never to make it
// *possible*.
//
// THE RULES, all mechanical and all discharged by construction here:
//
//   * one `<path>` per id — `PATHS` is a record of `d` strings and the
//     component renders exactly one element from it;
//   * `viewBox="0 0 16 16"`;
//   * `stroke="currentColor"`, `fill="none"` — so an icon inside a danger-ink
//     badge is red with no icon-specific rule anywhere;
//   * no `<style>`, no gradient, no embedded colour (`no-palette-token`
//     would fail a hex here like anywhere else);
//   * `aria-hidden` unless the icon is a control's only label, in which case
//     the caller passes `label` and the icon becomes `role="img"`.
//
// ADDING AN ID IS A SPEC EDIT, exactly as adding a panel is (§4.2).

/**
 * The closed vocabulary, in §3.12's four groups.
 *
 * The six status ids come first because §3.14's component test asserts a
 * DISTINCT id per `Badge` status: `info` and `dirty` take different ids rather
 * than both taking `dot`, because two statuses sharing an id would make the
 * distinctness assertion false by construction rather than by inspection.
 */
export const ICON_IDS = [
  // status (6) — one per Badge status
  "check",
  "cross",
  "alert",
  "dash",
  "info",
  "dot",
  // structure (4)
  "chevron-right",
  "chevron-down",
  "sidebar",
  "file",
  // object (4)
  "cube",
  "plane",
  "tag",
  "ruler",
  // action (4)
  "close",
  "refresh",
  "download",
  "pin",
  // §7.1(b), amended 2026-09-01: the session strip's create action is "a single
  // icon-only `+` control", and no id in the closed 18 draws a plus. Adding one
  // is a spec edit (§3.12) and it is recorded there as the nineteenth id.
  "plus",
] as const;

export type IconId = (typeof ICON_IDS)[number];

/**
 * One `d` per id. Sub-paths inside a single `d` are still one `<path>`; what
 * §3.12 forbids is a *second element*, because that is where per-icon fills and
 * strokes creep in.
 */
const PATHS: Readonly<Record<IconId, string>> = {
  check: "M3 8.4 L6.4 11.8 L13 4.2",
  cross: "M4.5 4.5 L11.5 11.5 M11.5 4.5 L4.5 11.5",
  alert: "M8 2.2 L14.6 13.6 L1.4 13.6 Z M8 6.2 L8 9.6 M8 11.3 L8 11.6",
  dash: "M3.4 8 L12.6 8",
  info:
    "M14.5 8 A6.5 6.5 0 1 1 1.5 8 A6.5 6.5 0 1 1 14.5 8 " +
    "M8 7.2 L8 11.6 M8 4.4 L8 4.7",
  dot: "M11 8 A3 3 0 1 1 5 8 A3 3 0 1 1 11 8",
  "chevron-right": "M6 3.4 L10.6 8 L6 12.6",
  "chevron-down": "M3.4 6 L8 10.6 L12.6 6",
  sidebar: "M2 3 L14 3 L14 13 L2 13 Z M6.6 3 L6.6 13",
  file: "M9.2 1.8 L3.2 1.8 L3.2 14.2 L12.8 14.2 L12.8 5.4 Z M9.2 1.8 L9.2 5.4 L12.8 5.4",
  cube:
    "M8 1.8 L14.2 5.2 L14.2 10.8 L8 14.2 L1.8 10.8 L1.8 5.2 Z " +
    "M1.8 5.2 L8 8.6 L14.2 5.2 M8 8.6 L8 14.2",
  plane: "M1.4 10.6 L5.6 4.4 L14.6 4.4 L10.4 10.6 Z M4 13.2 L12 13.2",
  tag: "M2.2 2.2 L7.6 2.2 L14 8.6 L8.6 14 L2.2 7.6 Z M5 5 L5.3 5",
  ruler:
    "M1.5 5.4 L14.5 5.4 L14.5 10.6 L1.5 10.6 Z " +
    "M4.6 5.4 L4.6 8 M7.2 5.4 L7.2 8 M9.8 5.4 L9.8 8 M12.4 5.4 L12.4 8",
  close:
    "M14.5 8 A6.5 6.5 0 1 1 1.5 8 A6.5 6.5 0 1 1 14.5 8 " +
    "M5.9 5.9 L10.1 10.1 M10.1 5.9 L5.9 10.1",
  refresh:
    "M13.6 8 A5.6 5.6 0 1 1 11.4 3.6 M11.4 3.6 L14.4 3.1 M11.4 3.6 L11.9 0.9",
  download: "M8 2 L8 10.6 M4.4 7.1 L8 10.8 L11.6 7.1 M2.6 13.6 L13.4 13.6",
  pin: "M6 1.8 L10 1.8 L9.4 6.2 L12 8.6 L4 8.6 L6.6 6.2 Z M8 8.6 L8 14.2",
  plus: "M8 3 L8 13 M3 8 L13 8",
};

export interface IconProps {
  readonly id: IconId;
  /** Edge length in px. The sprite is drawn on a 16-unit grid and scales. */
  readonly size?: number | undefined;
  /**
   * Present only when the icon is a control's **only** label (§3.12). The
   * string comes from `copy.ts` like every other human-facing word; passing it
   * flips the element from `aria-hidden` to `role="img"`.
   */
  readonly label?: string | undefined;
  readonly className?: string | undefined;
}

export function Icon({ id, size = 14, label, className }: IconProps): React.JSX.Element {
  return (
    <svg
      viewBox="0 0 16 16"
      width={size}
      height={size}
      className={className}
      data-icon={id}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      focusable="false"
      {...(label === undefined
        ? { "aria-hidden": true }
        : { role: "img", "aria-label": label })}
    >
      <path d={PATHS[id]} />
    </svg>
  );
}
