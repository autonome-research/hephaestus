// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The composer's context envelope, built from §4.5 state (INTERFACE.md §7A.3).
//
// A pure module, and pure for a reason: the sharpest constraint in §7A is that
// **the client sends references and never facts**, and a rule that lives inside
// a component is a rule nobody can test. Everything here is a projection of
// state this client already owns — §4.5's closed workspace record and
// `state/visibility.ts`'s hidden set — into the closed member set the server
// admits. There is no read, no fetch, and nowhere to put a number.
//
// **Every member is opt-out** (§7A.3): "the default envelope is exactly the
// workspace state visible at submit time; every member is opt-out, rendered as a
// removable chip row above the textarea, so the operator sees the references
// before sending and can drop any of them." `chipsFor` produces that row and
// `envelopeFor` honours the drops.
//
// **No chip is a fact.** §7A.10: "no chip carries a `data-source`, because no
// chip is a fact (§4.6); a chip that ever renders a measured value is a
// `heph/no-derived-fact` failure". The chips render §4.5 state, which is
// navigation, not fact — the same exemption §1 grants the grid readout — so
// nothing here goes through `<Fact>` and nothing here carries a source.
//
// THE ONE COUNT THAT IS NOT A FACT, said out loud because it looks like one.
// The `hidden_labels` chip renders `data-context-count`, a count of *labels the
// operator has toggled off*. That is a count of the client's own control state,
// not a measurement of the model: it says how many toggles are set and never
// how many solids are visible. §7A.3 draws exactly that line and the server's
// composed block draws it again in words.

// AMENDED 2026-09-01 (§0.2b, §7A.3(a)-(e)). The envelope's *content* rules
// above are unchanged in every particular — the closed field list, the three
// stated WHYs, the "references, never facts" tightening. What is added is
// `summaryFor`, the pure projection behind the composer's **resting one-line
// summary**: the same members, in a fixed drawn order, with the remainder
// counted rather than drawn. It re-words nothing and computes nothing; the only
// arithmetic is `+N`, a count of the client's own envelope members and not a
// measurement of anything in the model (the same line §7A.3 already draws for
// `hidden_labels`).

// AMENDED 2026-09-02 (§0.2c, C22). `addViewOnLine` is the pure half of "Add
// current view surfaces where the gap is visible": the one moment the
// affordance matters on the RESTING line is when a selection exists in
// workspace state and the envelope carries neither `view` nor `selection` —
// the gap the operator would otherwise have to open the disclosure to see.
// The negative halves live here too, as the same predicate returning false:
// members already in the envelope, no selection, or the disclosure open (the
// form's copy of the control is showing). Activation is the component's job
// and does exactly what the form's copy does — it adds members to the `added`
// set, computing nothing (§1).

import type { ContextEnvelope, ContextMember } from "../api/sessions";
import type { WorkspaceState } from "../state/workspace";

/**
 * One chip in the row above the textarea.
 *
 * `value` is what the chip displays and `count` is the alternative rendering for
 * a member that is a set rather than a scalar — §7A.10's DOM contract carries
 * `data-context-value` on the first and `data-context-count` on the second.
 */
export interface ContextChip {
  readonly key: ContextMember;
  readonly value: string | null;
  readonly count: number | null;
}

/** The order chips render in. Fixed, so the row does not reshuffle as state changes. */
export const CHIP_ORDER: readonly ContextMember[] = [
  "part",
  "artifact_ref",
  "selection",
  "stage_tab",
  "inspector_tab",
  "view",
  "explode_t",
  "section_plane",
  "hidden_labels",
  "focus",
];

/**
 * The chips a given workspace state offers, in :data:`CHIP_ORDER`.
 *
 * A member with nothing to say produces no chip: an unpinned workspace has no
 * `artifact_ref`, an unexploded one has no `explode_t`. The two navigation
 * tabs are always offered because they are always set — they say which panel
 * the operator is reading, which is context a question about "this" needs.
 *
 * `pin_mode` has no chip of its own on purpose. It is not independently
 * droppable: it qualifies `artifact_ref` ("pinned" versus "following current")
 * and a chip row that let the operator drop the qualifier while keeping the ref
 * would offer them a way to make the block say something less true.
 */
export function chipsFor(state: WorkspaceState, hiddenLabels: readonly string[]): ContextChip[] {
  const chips: ContextChip[] = [];
  const push = (key: ContextMember, value: string | null, count: number | null = null): void => {
    chips.push({ key, value, count });
  };
  for (const key of CHIP_ORDER) {
    switch (key) {
      case "part":
        if (state.part !== null) push("part", state.part);
        break;
      case "artifact_ref":
        if (state.artifact_ref !== null) push("artifact_ref", state.artifact_ref);
        break;
      case "selection":
        if (state.selection !== null) push("selection", state.selection.selection_id);
        break;
      case "stage_tab":
        push("stage_tab", state.stage_tab);
        break;
      case "inspector_tab":
        push("inspector_tab", state.inspector_tab);
        break;
      case "view":
        push("view", state.view);
        break;
      case "explode_t":
        if (state.explode_t > 0) push("explode_t", String(state.explode_t));
        break;
      case "section_plane":
        if (state.section_plane !== null) push("section_plane", state.section_plane);
        break;
      case "hidden_labels":
        if (hiddenLabels.length > 0) push("hidden_labels", null, hiddenLabels.length);
        break;
      case "focus":
        if (state.focus !== null) push("focus", state.focus);
        break;
      // `pin_mode` is deliberately not a chip; see the docstring.
      case "pin_mode":
        break;
    }
  }
  return chips;
}

/**
 * The envelope to send, with `dropped` members omitted.
 *
 * Returns `null` — §7A.3's blank canvas, "and the server composes nothing" —
 * when nothing survives that names a reference. A workspace with a tab selected
 * and no part, no pin and no selection is a blank canvas whatever its tabs say,
 * so an envelope carrying only navigation tokens is collapsed here rather than
 * sent for the server to collapse. (The server collapses it too; agreeing costs
 * one condition and means the wire shows what the model gets.)
 *
 * `added` is the explicit "Add current view" set (issue #13). `view` alone
 * never names a reference; once the operator adds it, it does.
 */
export function envelopeFor(
  state: WorkspaceState,
  hiddenLabels: readonly string[],
  dropped: ReadonlySet<ContextMember>,
  added: ReadonlySet<ContextMember> = new Set(),
): ContextEnvelope | null {
  const kept = (key: ContextMember): boolean => !dropped.has(key);
  const envelope: {
    -readonly [K in keyof ContextEnvelope]: ContextEnvelope[K];
  } = {};

  if (kept("part") && state.part !== null) envelope.part = state.part;
  if (kept("artifact_ref") && state.artifact_ref !== null) {
    envelope.artifact_ref = state.artifact_ref;
    // The qualifier travels with the ref it qualifies, never alone.
    envelope.pin_mode = state.pin_mode;
  }
  if (kept("selection") && state.selection !== null) {
    // The IDS, submitted. The server resolves them through §12.3 against the
    // pinned ref; a selection that does not resolve is `stale_selection` and is
    // never quietly dropped, and never a fallback to current geometry (§15.3).
    envelope.selection = {
      selection_id: state.selection.selection_id,
      bundle_ref: state.selection.bundle_ref,
    };
  }
  if (kept("stage_tab")) envelope.stage_tab = state.stage_tab;
  if (kept("inspector_tab")) envelope.inspector_tab = state.inspector_tab;
  if (kept("view")) envelope.view = state.view;
  if (kept("explode_t") && state.explode_t > 0) {
    // The PARAMETER. §1 already puts `offset · t` in this client's scene graph;
    // a displacement here would be the browser asserting a measurement.
    envelope.explode_t = state.explode_t;
  }
  if (kept("section_plane") && state.section_plane !== null) {
    envelope.section_plane = state.section_plane;
  }
  if (kept("hidden_labels") && hiddenLabels.length > 0) {
    // The TOGGLES, in the geometry-entry label namespace `GET /parts/{part}/build`
    // gives this client — never a claim about what is on screen. Sorted so the
    // envelope is a function of the set rather than of toggle order, which
    // keeps the composed block deterministic (§7A.3).
    envelope.hidden_labels = [...hiddenLabels].sort();
  }
  if (kept("focus") && state.focus !== null) envelope.focus = state.focus;

  // `view` is always present as navigation, but it does not *name* a
  // reference on its own — a workspace with only a camera token is still
  // the blank canvas. An explicit "Add current view" (issue #13) is the
  // operator saying the view *is* the reference, so it counts then.
  const namesAReference =
    envelope.part !== undefined ||
    envelope.artifact_ref !== undefined ||
    envelope.selection !== undefined ||
    envelope.hidden_labels !== undefined ||
    envelope.section_plane !== undefined ||
    envelope.focus !== undefined ||
    (added.has("view") && envelope.view !== undefined);
  return namesAReference ? envelope : null;
}

// ---------------------------------------------------------------------------
// §7A.3 (C22) — "Add current view" on the resting line
// ---------------------------------------------------------------------------

/**
 * Whether `[data-context-add-view]` renders on the RESTING summary line
 * (§7A.3, amended 2026-09-02 (§0.2c, C22)).
 *
 * True exactly when the gap the affordance exists to close is visible: a
 * selection exists in workspace state, and the envelope carries **neither**
 * `view` nor `selection`. False — the clause's stated negative halves — when
 * the members are already in the envelope, when no selection exists, or while
 * the disclosure is open, because the form's own copy of the control is
 * showing then and two live copies of one affordance is the same control
 * twice.
 *
 * A projection, not a policy: it reads the envelope this form would POST and
 * the client's own disclosure flag, and computes nothing (§1). The (d)
 * testables are untouched — `data-context-keys` still names exactly what
 * would be sent, before and after the add.
 */
export function addViewOnLine(
  envelope: ContextEnvelope | null,
  hasSelection: boolean,
  disclosed: boolean,
): boolean {
  if (disclosed) return false;
  if (!hasSelection) return false;
  const viewAbsent = envelope === null || envelope.view === undefined;
  const selectionAbsent = envelope === null || envelope.selection === undefined;
  return viewAbsent && selectionAbsent;
}

// ---------------------------------------------------------------------------
// §7A.3(a)-(e) — the resting summary line
// ---------------------------------------------------------------------------

/**
 * The order the resting line names members in (§7A.3(a)).
 *
 * `part`, `artifact_ref`, the `stage_tab`/`inspector_tab` pair and `view` are
 * **drawn**; everything after `view` is **counted** into `+N`. `pin_mode` is
 * absent for the same reason it has no chip: it is not an independently
 * addressable member, it qualifies `artifact_ref` and travels with it.
 */
export const SUMMARY_ORDER: readonly ContextMember[] = [
  "part",
  "artifact_ref",
  "stage_tab",
  "inspector_tab",
  "view",
  "selection",
  "explode_t",
  "section_plane",
  "hidden_labels",
  "focus",
];

/** The members the line draws in full; the rest are counted (§7A.3(a)). */
const DRAWN: ReadonlySet<ContextMember> = new Set<ContextMember>([
  "part",
  "artifact_ref",
  "stage_tab",
  "inspector_tab",
  "view",
]);

/**
 * One drawn token on the resting line.
 *
 * `text` is the value **as the envelope carries it**; abbreviation is the
 * component's job, because `formatRef` is a rendering and this module is the
 * decision. `abbreviate` says which tokens §4.1(a)'s ref shortening applies to.
 */
export interface SummaryToken {
  /** The member that produced it. The stage/inspector pair is keyed `stage_tab`. */
  readonly key: ContextMember;
  readonly text: string;
  readonly abbreviate: boolean;
}

/**
 * What the resting line says, and what `data-context-keys` publishes.
 *
 * `keys` is **the envelope's own member keys**, in :data:`SUMMARY_ORDER`, with
 * `pin_mode` folded into the `artifact_ref` it qualifies. §7A.3(d)'s testable is
 * that this list, the envelope `POST /prompt` would send, and the chips'
 * `data-context-key` set once the disclosure is open all name the same members.
 */
export interface ContextSummary {
  readonly keys: readonly ContextMember[];
  readonly tokens: readonly SummaryToken[];
  /** Members present in the envelope but past `view` in the drawn order. */
  readonly remaining: number;
  /**
   * Members the operator excluded (§7A.3(e)).
   *
   * An exclusion is a fact about what is being sent — "the agent will not be
   * told about the selection" — so it stays visible on the resting line rather
   * than taking the quiet path the implied envelope gets.
   */
  readonly removed: readonly ContextMember[];
}

/**
 * The resting line for one envelope, plus the exclusions that shaped it.
 *
 * `offered` is `chipsFor`'s complete enumeration: a member the workspace could
 * have carried. A member in `offered` and in `dropped` was excluded, and §7A.3(e)
 * says the line says so.
 */
export function summaryFor(
  envelope: ContextEnvelope | null,
  offered: readonly ContextChip[],
  dropped: ReadonlySet<ContextMember>,
): ContextSummary {
  const present = (key: ContextMember): boolean =>
    envelope !== null && envelope[key] !== undefined;
  const keys = SUMMARY_ORDER.filter(present);

  const tokens: SummaryToken[] = [];
  if (present("part")) tokens.push({ key: "part", text: String(envelope?.part), abbreviate: false });
  if (present("artifact_ref")) {
    tokens.push({ key: "artifact_ref", text: String(envelope?.artifact_ref), abbreviate: true });
  }
  // ONE token for the two navigation tabs (§7A.3(a)): "the `stage_tab` /
  // `inspector_tab` pair as one `stage/inspector` pair". Either half can be
  // dropped on its own, so the pair degrades to whichever half survives rather
  // than printing a placeholder for a member the envelope does not carry.
  const stage = present("stage_tab") ? String(envelope?.stage_tab) : null;
  const inspector = present("inspector_tab") ? String(envelope?.inspector_tab) : null;
  if (stage !== null || inspector !== null) {
    tokens.push({
      key: stage !== null ? "stage_tab" : "inspector_tab",
      text: stage !== null && inspector !== null ? `${stage}/${inspector}` : (stage ?? inspector ?? ""),
      abbreviate: false,
    });
  }
  if (present("view")) tokens.push({ key: "view", text: String(envelope?.view), abbreviate: false });

  const remaining = keys.filter((key) => !DRAWN.has(key)).length;
  const offeredKeys = new Set(offered.map((chip) => chip.key));
  const removed = SUMMARY_ORDER.filter((key) => offeredKeys.has(key) && dropped.has(key));

  return { keys, tokens, remaining, removed };
}
