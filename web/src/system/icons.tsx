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
  // structure (5)
  "chevron-right",
  // §4.1's Views bar (2026-09-20) collapses leftward, and no id in the set drew
  // a left chevron — `chevron-right` mirrored in CSS would be a transform that
  // has to be remembered at every call site, and `sidebar` names a different
  // thing. Added the way `plus` was: a spec edit, recorded here, as the
  // twenty-eighth id.
  "chevron-up",
  "chevron-down",
  "image",
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
  // Compact agent-composer actions.
  "arrow-up",
  "stop",
  "plan",
  "wrench",
  "view",
  "view-off",
  "levels",
  "geometry-network",
  // §4.1's Agent toggle (2026-09-20). A compose glyph, and MONOCHROME: the
  // reference was a colour-gradient app icon, which §3.12 forbids outright —
  // one `<path>`, `stroke="currentColor"`, `fill="none"`, no embedded colour,
  // so the same id is legible inside a danger-ink badge and on every surface.
  "compose",
  // The side panel's toggle (2026-09-20): three bars, drawn THICKER than the
  // sprite's 1.5 stroke because a hamburger read at 1.5px is three hairlines.
  // `Icon` sets one stroke width for every id, so the weight is carried by the
  // path — three 2px-tall rounded caps rather than three lines.
  "menu",
  // The stage rail's viewport controls (2026-09-20). They arrived as one row:
  // a column of word-buttons — Grid, Wireframe, Ortho, Material — was wider
  // than the model it sat beside, and widening the rail to fit the longest word
  // is the wrong end to solve it from. Each keeps its word as its accessible
  // name.
  //
  // `code` (2026-09-20). The Script view was drawn with `file`, which is the
  // id for "a document" and is what the project tree, the timeline and part
  // chrome all draw. Script is not a document among documents — it is the
  // part's SOURCE, the one view you leave the model for — and an angle-bracket
  // pair is the one glyph that says so without a word. `file` keeps every
  // other call site.
  "code",
  // `fit` arrived with them and left the same day, with the Fit control itself.
  // REMOVING an id is a spec edit too: the vocabulary is closed in both
  // directions, and an id no component draws is a glyph the next author has to
  // decide the meaning of. It is recorded here rather than kept warm.
  "grid",
  "wireframe",
  "ortho",
  "material",
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
  // `chevron-up` REPLACED `chevron-left` (2026-09-20), one out for one in, so
  // the vocabulary is the same size. Nothing drew `chevron-left`: it was added
  // for a rail-collapse control that was struck the same week. The inspector's
  // fold needs the opposite of `chevron-down` and the set had no up.
  "chevron-up": "M3.4 10 L8 5.4 L12.6 10",
  "chevron-down": "M3.4 6 L8 10.6 L12.6 6",
  // `image` REPLACED `sidebar` (2026-09-20), one out for one in, so §3.12's
  // vocabulary is the same size. Nothing drew `sidebar` — the rail's toggle is
  // the hamburger. A frame with a horizon and a sun is the one glyph every
  // operator already reads as "a picture", which is what the composer's
  // attachment control needed.
  image:
    "M2.2 3.4 L13.8 3.4 L13.8 12.6 L2.2 12.6 Z " +
    "M2.2 10.2 L5.8 6.8 L9 10 M8.2 9.2 L10.4 7.2 L13.8 10.4 " +
    "M11.2 6.2 A1.1 1.1 0 1 1 9 6.2 A1.1 1.1 0 1 1 11.2 6.2",
  file: "M9.2 1.8 L3.2 1.8 L3.2 14.2 L12.8 14.2 L12.8 5.4 Z M9.2 1.8 L9.2 5.4 L12.8 5.4",
  cube:
    "M8 1.8 L14.2 5.2 L14.2 10.8 L8 14.2 L1.8 10.8 L1.8 5.2 Z " +
    "M1.8 5.2 L8 8.6 L14.2 5.2 M8 8.6 L8 14.2",
  plane: "M1.4 10.6 L5.6 4.4 L14.6 4.4 L10.4 10.6 Z M4 13.2 L12 13.2",
  tag: "M2.2 2.2 L7.6 2.2 L14 8.6 L8.6 14 L2.2 7.6 Z M5 5 L5.3 5",
  ruler:
    "M1.5 5.4 L14.5 5.4 L14.5 10.6 L1.5 10.6 Z " +
    "M4.6 5.4 L4.6 8 M7.2 5.4 L7.2 8 M9.8 5.4 L9.8 8 M12.4 5.4 L12.4 8",
  // A BARE CROSS (2026-09-20). This drew a 6.5r circle with a 4.2-unit cross
  // inside it, and at the 13px the chrome asks for, the ring took most of the
  // glyph's area and left the cross reading as a smudge. The ring was also
  // decoration no other id carries: `material`'s circle is the sphere it
  // means and `refresh`'s arc is the turn it means, whereas this one enclosed
  // a meaning that was already complete. The cross now spans the same 10.2
  // units the ring did, so the glyph got bigger without the box changing.
  close: "M3.6 3.6 L12.4 12.4 M12.4 3.6 L3.6 12.4",
  refresh:
    "M13.6 8 A5.6 5.6 0 1 1 11.4 3.6 M11.4 3.6 L14.4 3.1 M11.4 3.6 L11.9 0.9",
  download: "M8 2 L8 10.6 M4.4 7.1 L8 10.8 L11.6 7.1 M2.6 13.6 L13.4 13.6",
  pin: "M6 1.8 L10 1.8 L9.4 6.2 L12 8.6 L4 8.6 L6.6 6.2 Z M8 8.6 L8 14.2",
  plus: "M8 3 L8 13 M3 8 L13 8",
  // The brackets sit WIDER and the slash is steeper than the obvious
  // `M9.2 2.6 L6.8 13.4` (2026-09-20): at a glyph this small the three marks
  // ran together into a single wedge. Pulling the chevrons out to 1.4/14.6
  // and narrowing the slash's run leaves visible ground on both sides of it.
  code: "M5.4 4.2 L1.4 8 L5.4 11.8 M10.6 4.2 L14.6 8 L10.6 11.8 M9 3 L7 13",
  "arrow-up": "M8 1.5 L14.2 13.8 L8 10.8 L1.8 13.8 Z M8 10.8 L8 7.2",
  stop: "M4 4 L12 4 L12 12 L4 12 Z",
  plan: "M3 12.5 L3 9.5 L8 9.5 L8 6.5 L13 6.5 M3 9.5 L3 3.5 M8 9.5 L8 12.5 M13 6.5 L13 3.5",
  wrench: "M9.5 3.2 A3.4 3.4 0 0 0 5.6 7.8 L2.4 11 L5 13.6 L8.2 10.4 A3.4 3.4 0 0 0 12.8 6.5 L10.6 8.7 L7.3 5.4 Z",
  view: "M1.5 8 C3.2 4.9 5.4 3.4 8 3.4 C10.6 3.4 12.8 4.9 14.5 8 C12.8 11.1 10.6 12.6 8 12.6 C5.4 12.6 3.2 11.1 1.5 8 Z M10 8 A2 2 0 1 1 6 8 A2 2 0 1 1 10 8",
  // `view-off` REPLACED `context` (2026-09-20): one out, one in, so §3.12's
  // vocabulary is the same size. Nothing drew `context` — the control that
  // would have was struck from the composer the same day. This is `view` with
  // a slash through it, because an eye toggle that only changes its pressed
  // FILL is the state-by-colour defect §3.13.2 names: the glyph has to say
  // which way it is set on its own.
  "view-off":
    "M1.5 8 C3.2 4.9 5.4 3.4 8 3.4 C10.6 3.4 12.8 4.9 14.5 8 " +
    "C12.8 11.1 10.6 12.6 8 12.6 C5.4 12.6 3.2 11.1 1.5 8 Z " +
    "M10 8 A2 2 0 1 1 6 8 A2 2 0 1 1 10 8 M2.6 2.6 L13.4 13.4",
  levels: "M3 12 L3 9 M8 12 L8 6 M13 12 L13 3",
  // Corner brackets — frame the thing, which is what Fit does.
  grid: "M2.4 2.4 L13.6 2.4 L13.6 13.6 L2.4 13.6 Z M6.1 2.4 L6.1 13.6 M9.9 2.4 L9.9 13.6 M2.4 6.1 L13.6 6.1 M2.4 9.9 L13.6 9.9",
  // A surface with its edges showing through — the silhouette kept, fill gone.
  wireframe: "M2.4 2.4 L13.6 2.4 L13.6 13.6 L2.4 13.6 Z M2.4 2.4 L13.6 13.6 M13.6 2.4 L2.4 13.6 M2.4 8 L13.6 8 M8 2.4 L8 13.6",
  // A box whose parallel edges stay parallel: orthographic, not perspective.
  ortho: "M2.4 5.6 L10.4 5.6 L10.4 13.6 L2.4 13.6 Z M5.6 2.4 L13.6 2.4 L13.6 10.4 L10.4 10.4 M2.4 5.6 L5.6 2.4 M10.4 5.6 L13.6 2.4",
  // A sphere, lit from one side — the override this toggles is a material.
  material: "M14.2 8 A6.2 6.2 0 1 1 1.8 8 A6.2 6.2 0 1 1 14.2 8 M8 1.9 L8 14.1 M8.9 4.4 L11.9 4.4 M8.9 8 L14.1 8 M8.9 11.6 L11.9 11.6",
  menu: "M2.6 4.2 L13.4 4.2 M2.6 8 L13.4 8 M2.6 11.8 L13.4 11.8",
  // A SPEECH BUBBLE WITH SPARKS (2026-09-20). This was a pencil, which said
  // "write something" — true of any text field in the workspace. The control
  // it labels opens the AGENT, and the bubble-and-spark pair is what that
  // means everywhere else the operator has seen it. Same id, same meaning,
  // better glyph: no call site moves.
  // REDRAWN TWICE (2026-09-20). The first cut left the bubble OPEN at the
  // top-right to make room for a second spark, and an open outline under
  // `fill="none"` with a stray `Z` closed itself across the gap — a blob.
  // The second was closed but cramped: a full-height spark inside a
  // full-width bubble left no ground between them, so at 21px the two
  // outlines read as one texture.
  //
  // This one gives the bubble a SHALLOWER body and puts the spark slightly
  // off-centre, so there is clear ground on every side of it. A glyph is
  // read from its counters as much as its strokes.
  compose:
    "M3.4 3 L12.6 3 A1.7 1.7 0 0 1 14.3 4.7 L14.3 9.3 " +
    "A1.7 1.7 0 0 1 12.6 11 L6.6 11 L4 13.4 L4 11 L3.4 11 " +
    "A1.7 1.7 0 0 1 1.7 9.3 L1.7 4.7 A1.7 1.7 0 0 1 3.4 3 Z " +
    "M7.6 5.2 L8.3 6.6 L9.7 7.3 L8.3 8 L7.6 9.4 L6.9 8 L5.5 7.3 L6.9 6.6 Z",
  "geometry-network": "M8 1 A1 1 0 1 1 8 3 A1 1 0 1 1 8 1 M3 4 A1 1 0 1 1 3 6 A1 1 0 1 1 3 4 M13 4 A1 1 0 1 1 13 6 A1 1 0 1 1 13 4 M8 7 A1 1 0 1 1 8 9 A1 1 0 1 1 8 7 M3 10 A1 1 0 1 1 3 12 A1 1 0 1 1 3 10 M13 10 A1 1 0 1 1 13 12 A1 1 0 1 1 13 10 M8 13 A1 1 0 1 1 8 15 A1 1 0 1 1 8 13 M3.8 4.5 L7.2 2.5 M8.8 2.5 L12.2 4.5 M3 6 L3 10 M13 6 L13 10 M3.8 11.5 L7.2 13.5 M8.8 13.5 L12.2 11.5 M3.8 5.5 L7.2 7.5 M8.8 7.5 L12.2 5.5 M3.8 10.5 L7.2 8.5 M8.8 8.5 L12.2 10.5",
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
