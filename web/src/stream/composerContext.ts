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
