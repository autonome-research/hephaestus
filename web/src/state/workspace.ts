// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The workspace state module (INTERFACE.md §4.5) — closed record, one pin
// authority, URL-serializable.
//
// §3 chose "one module over `useSyncExternalStore`, no state library" for two
// reasons this file has to actually deliver: **the pin must have exactly one
// authority**, and the record must be URL-serializable, "which is a flat
// record, not a reducer ceremony". Zustand/Redux were rejected as a dependency
// whose only output is a store this small; per-component `useState` was rejected
// because it cannot hold a single pin authority.
//
// THE PIN AUTHORITY, stated as the rule the types enforce.
// §4.5's TIGHTENING (binds G5.6): `artifact_ref` is first-class, sticky
// workspace state, and "publishing a new build **never** advances a pin whose
// `pin_mode` is `"pinned"`". So `artifact_ref` and `pin_mode` are *not*
// writable through `update()` — the patch type excludes them and the method
// throws if a non-TypeScript caller passes one anyway. There are exactly three
// doors:
//
//   hold(ref)            an explicit user act: pin_mode := "pinned"
//   followCurrent(ref)   the explicit header action (§4.5): pin_mode := "current"
//   observeCurrent(ref)  the server said what `current` is — a NO-OP while held
//
// `observeCurrent` is the only path a server response may take to the pin, and
// it is the one that must not fire while held. A workspace that auto-refreshed
// to latest would silently fall back to current geometry, which
// `architecture.md` §4.4 forbids outright.

/** §5.5: the `STANDARD_VIEWS` vocabulary of `core/render/cameras.py`. */
export const STANDARD_VIEWS = ["iso", "+X", "-X", "+Y", "-Y", "+Z", "-Z", "front"] as const;
export type StandardView = (typeof STANDARD_VIEWS)[number];

/** §5.5: the free-orbit grammar the same module parses, `az<deg>_el<deg>`. */
const VIEW_GRAMMAR = /^az(-?\d+(?:\.\d+)?)_el(-?\d+(?:\.\d+)?)$/;

export const CHANNEL_OVERLAYS = ["none", "section"] as const;
export type ChannelOverlay = (typeof CHANNEL_OVERLAYS)[number];

/**
 * Stage tabs. `viewport` / `script` / `diff` are §4.5's original closed set.
 * `timeline` and `results` are the part views issue #4 adds so Script /
 * Timeline / Results are first-class switches on the same tablist. `results`
 * here reuses `ResultsPanel`. When this tab is selected the inspector does
 * not also mount Results — that was the duplicate list/metrics after #6.
 */
export const STAGE_TABS = ["viewport", "script", "timeline", "results", "diff"] as const;
export type StageTab = (typeof STAGE_TABS)[number];

/**
 * §4.2's panel inventory, plus §22.7's `export` tab and the sourcing tab
 * issue #12 adds.
 *
 * §22.7 put export in the Inspector so it inherits the pin. That tab stays:
 * history, drawings, documents, and the two-step download live there. Issue
 * #12 adds a seventh tab, `sourcing`, for the BOM readout that is only the
 * manufacturing fields the part already declares — and it also puts a simple
 * Export + BOM control in header chrome next to the pin, so egress is not
 * only a buried inspector tab. The chrome still sends
 * `WorkspaceState.artifact_ref` verbatim (§22.5).
 */
export const INSPECTOR_TABS = [
  "results",
  "properties",
  "provenance",
  "checks",
  "dfm",
  "export",
  "sourcing",
] as const;
export type InspectorTab = (typeof INSPECTOR_TABS)[number];

/**
 * Inspector tabs the drawer may show for a given stage tab.
 *
 * When the stage is already Results, the Results inspector tab is omitted so
 * the same `ResultsPanel` is not mounted twice. Every other inspector tab
 * stays; the e2e still addresses them with `[data-inspector-tab]`.
 */
export function inspectorTabsFor(stage: StageTab): readonly InspectorTab[] {
  return stage === "results" ? INSPECTOR_TABS.filter((tab) => tab !== "results") : INSPECTOR_TABS;
}

/**
 * The inspector panel that actually mounts.
 *
 * A URL that carries `tab=results&itab=results` (the defaults stacked) must
 * not render two geometry lists. Properties is the next tab in the closed
 * inventory and is already a statement about the pinned artifact.
 */
export function effectiveInspectorTab(stage: StageTab, tab: InspectorTab): InspectorTab {
  return stage === "results" && tab === "results" ? "properties" : tab;
}

export const PIN_MODES = ["current", "pinned"] as const;
export type PinMode = (typeof PIN_MODES)[number];

/** §12.1: a selection is the server's answer, carried whole. */
export interface WorkspaceSelection {
  readonly selection_id: string;
  readonly kind: string;
  readonly bundle_ref: string;
}

/** §11: two server-validated selections, never a client-computed distance. */
export interface WorkspaceMeasure {
  readonly a?: string;
  readonly b?: string;
}

/** §4.5's closed record. Every field is here; nothing else is workspace state. */
export interface WorkspaceState {
  readonly part: string | null;
  readonly artifact_ref: string | null;
  readonly pin_mode: PinMode;
  readonly view: string;
  readonly channel_overlay: ChannelOverlay;
  readonly explode_t: number;
  readonly section_plane: string | null;
  readonly selection: WorkspaceSelection | null;
  readonly measure: WorkspaceMeasure | null;
  readonly stage_tab: StageTab;
  readonly inspector_tab: InspectorTab;
  readonly focus: string | null;
  readonly session: string | null;
}

/** Everything `update()` may write: the record minus the pin's two fields. */
export type WorkspacePatch = Partial<Omit<WorkspaceState, "artifact_ref" | "pin_mode">>;

export const DEFAULT_STATE: WorkspaceState = {
  part: null,
  artifact_ref: null,
  pin_mode: "current",
  view: "iso",
  channel_overlay: "none",
  explode_t: 0,
  section_plane: null,
  selection: null,
  measure: null,
  stage_tab: "viewport",
  inspector_tab: "results",
  focus: null,
  session: null,
};

/** The two fields only the pin doors may write. */
const PIN_FIELDS: readonly string[] = ["artifact_ref", "pin_mode"];

// ---------------------------------------------------------------------------
// vocabulary guards — closed, and a rejected value falls back rather than
// widening the vocabulary. A URL is user input.
// ---------------------------------------------------------------------------

export function isView(value: string): boolean {
  return (STANDARD_VIEWS as readonly string[]).includes(value) || VIEW_GRAMMAR.test(value);
}

function oneOf<T extends string>(values: readonly T[], raw: string | null, fallback: T): T {
  return raw !== null && (values as readonly string[]).includes(raw) ? (raw as T) : fallback;
}

/** §5.2: `explode_t` is `0..1`; the client applies `offset · t` and nothing else. */
export function clampExplode(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.round(Math.min(1, Math.max(0, value)) * 10000) / 10000;
}

/** §12.4/§5.3: `"[+-]AXIS@OFFSET"`, the only section-plane spelling. */
const SECTION_PLANE = /^[+-][XYZ]@-?\d+(?:\.\d+)?$/;

// ---------------------------------------------------------------------------
// URL serialization (§4.5)
// ---------------------------------------------------------------------------
//
// `/#/p/{part}?ref=…&view=iso&t=0.0&sec=…&sel=…&tab=viewport&s=…`
//
// The emission rule is closed and total: **every non-null field is emitted, in a
// fixed order; a null field is omitted.** That reproduces §4.5's example shape
// exactly, and it makes `decode(encode(s)) === s` a real round-trip rather than
// a round-trip modulo whatever the encoder felt like dropping — which is what
// the vitest asserts.

const SELECTION_SEPARATOR = "|";

function formatExplode(value: number): string {
  return Number.isInteger(value) ? value.toFixed(1) : String(value);
}

function encodeSelection(selection: WorkspaceSelection): string {
  return [selection.selection_id, selection.kind, selection.bundle_ref].join(SELECTION_SEPARATOR);
}

function decodeSelection(raw: string): WorkspaceSelection | null {
  const parts = raw.split(SELECTION_SEPARATOR);
  if (parts.length !== 3) return null;
  const [selection_id, kind, bundle_ref] = parts as [string, string, string];
  if (selection_id === "" || kind === "" || bundle_ref === "") return null;
  return { selection_id, kind, bundle_ref };
}

/** The workspace state as a location hash, leading `#` included. */
export function encodeWorkspaceUrl(state: WorkspaceState): string {
  const query = new URLSearchParams();
  if (state.artifact_ref !== null) query.set("ref", state.artifact_ref);
  query.set("pin", state.pin_mode);
  query.set("view", state.view);
  query.set("t", formatExplode(state.explode_t));
  query.set("ov", state.channel_overlay);
  if (state.section_plane !== null) query.set("sec", state.section_plane);
  if (state.selection !== null) query.set("sel", encodeSelection(state.selection));
  if (state.measure !== null) {
    query.set("m", "1");
    if (state.measure.a !== undefined) query.set("ma", state.measure.a);
    if (state.measure.b !== undefined) query.set("mb", state.measure.b);
  }
  query.set("tab", state.stage_tab);
  query.set("itab", state.inspector_tab);
  if (state.focus !== null) query.set("focus", state.focus);
  if (state.session !== null) query.set("s", state.session);
  const path = state.part === null ? "/" : `/p/${encodeURIComponent(state.part)}`;
  return `#${path}?${query.toString()}`;
}

/** A location hash back to workspace state. Unknown values fall back closed. */
export function decodeWorkspaceUrl(hash: string): WorkspaceState {
  const raw = hash.startsWith("#") ? hash.slice(1) : hash;
  const split = raw.indexOf("?");
  const path = split === -1 ? raw : raw.slice(0, split);
  const query = new URLSearchParams(split === -1 ? "" : raw.slice(split + 1));

  let part: string | null = null;
  if (path.startsWith("/p/")) {
    const segment = path.slice(3);
    if (segment !== "") part = decodeURIComponent(segment);
  }

  const view = query.get("view");
  const section = query.get("sec");
  const selection = query.get("sel");
  const measurePresent = query.get("m") !== null;
  const measureA = query.get("ma");
  const measureB = query.get("mb");

  const measure: WorkspaceMeasure | null = measurePresent
    ? {
        ...(measureA !== null ? { a: measureA } : {}),
        ...(measureB !== null ? { b: measureB } : {}),
      }
    : null;

  return {
    part,
    artifact_ref: query.get("ref"),
    pin_mode: oneOf(PIN_MODES, query.get("pin"), DEFAULT_STATE.pin_mode),
    view: view !== null && isView(view) ? view : DEFAULT_STATE.view,
    channel_overlay: oneOf(CHANNEL_OVERLAYS, query.get("ov"), DEFAULT_STATE.channel_overlay),
    explode_t: clampExplode(Number(query.get("t") ?? DEFAULT_STATE.explode_t)),
    section_plane: section !== null && SECTION_PLANE.test(section) ? section : null,
    selection: selection === null ? null : decodeSelection(selection),
    measure,
    stage_tab: oneOf(STAGE_TABS, query.get("tab"), DEFAULT_STATE.stage_tab),
    inspector_tab: oneOf(INSPECTOR_TABS, query.get("itab"), DEFAULT_STATE.inspector_tab),
    focus: query.get("focus"),
    session: query.get("s"),
  };
}

// ---------------------------------------------------------------------------
// the store
// ---------------------------------------------------------------------------

export class PinAuthorityError extends Error {}

/**
 * The one workspace store. `useSyncExternalStore`-shaped by construction:
 * `subscribe` returns an unsubscribe, `getSnapshot` returns a stable reference
 * that changes identity only when the state changes.
 */
export class WorkspaceStore {
  private state: WorkspaceState;
  private readonly listeners = new Set<() => void>();

  constructor(initial: WorkspaceState = DEFAULT_STATE) {
    this.state = initial;
    this.subscribe = this.subscribe.bind(this);
    this.getSnapshot = this.getSnapshot.bind(this);
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  getSnapshot(): WorkspaceState {
    return this.state;
  }

  /** Every field except the pin's two. Throws rather than silently dropping. */
  update(patch: WorkspacePatch): void {
    for (const key of Object.keys(patch)) {
      if (PIN_FIELDS.includes(key)) {
        throw new PinAuthorityError(
          `${key} is written only by hold()/followCurrent()/observeCurrent() ` +
            "— INTERFACE.md §4.5 gives the pin exactly one authority.",
        );
      }
    }
    const next: WorkspaceState = { ...this.state, ...patch };
    this.commit(
      patch.explode_t === undefined ? next : { ...next, explode_t: clampExplode(patch.explode_t) },
    );
  }

  /** An explicit user act: hold this artifact, whatever `current` becomes. */
  hold(ref: string): void {
    this.commit({ ...this.state, artifact_ref: ref, pin_mode: "pinned" });
  }

  /**
   * §4.5's "Follow current" — the one-click action that states what it discards.
   * The discard is real and happens here: a selection, crop, or measurement was
   * taken against the held artifact and does not transfer to another one.
   */
  followCurrent(currentRef: string | null): void {
    this.commit({
      ...this.state,
      artifact_ref: currentRef,
      pin_mode: "current",
      selection: null,
      measure: null,
    });
  }

  /**
   * The server said what `current` is. **A no-op while held** — this is the one
   * place a published build could have advanced a pin, and §4.5 forbids it.
   */
  observeCurrent(currentRef: string | null): void {
    if (this.state.pin_mode === "pinned") return;
    if (this.state.artifact_ref === currentRef) return;
    this.commit({ ...this.state, artifact_ref: currentRef });
  }

  /** Adopt a whole state — a browser back/forward, or a hydrated URL. */
  reset(state: WorkspaceState): void {
    this.commit(state);
  }

  private commit(next: WorkspaceState): void {
    if (sameState(this.state, next)) return;
    this.state = next;
    for (const listener of [...this.listeners]) listener();
  }
}

function sameSelection(a: WorkspaceSelection | null, b: WorkspaceSelection | null): boolean {
  if (a === null || b === null) return a === b;
  return a.selection_id === b.selection_id && a.kind === b.kind && a.bundle_ref === b.bundle_ref;
}

function sameMeasure(a: WorkspaceMeasure | null, b: WorkspaceMeasure | null): boolean {
  if (a === null || b === null) return a === b;
  return a.a === b.a && a.b === b.b;
}

/** Structural equality over the closed record, so no-op writes do not notify. */
export function sameState(a: WorkspaceState, b: WorkspaceState): boolean {
  return (
    a.part === b.part &&
    a.artifact_ref === b.artifact_ref &&
    a.pin_mode === b.pin_mode &&
    a.view === b.view &&
    a.channel_overlay === b.channel_overlay &&
    a.explode_t === b.explode_t &&
    a.section_plane === b.section_plane &&
    a.stage_tab === b.stage_tab &&
    a.inspector_tab === b.inspector_tab &&
    a.focus === b.focus &&
    a.session === b.session &&
    sameSelection(a.selection, b.selection) &&
    sameMeasure(a.measure, b.measure)
  );
}
