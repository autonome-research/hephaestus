// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Overlay scroll cues (#115 leftover, INTERFACE.md §3.10).
//
// A classic OS track still eats layout after `scrollbar-width: thin`: on this
// box that property reserved the 10px OS scrollbar (11px on the parts rail,
// 10px on Results at 1280×800) and won over the 2px `::-webkit-scrollbar`
// rule. Overlay means the scroller's layout width equals its content box.
//
// Native thumbs are hidden (`scrollbar-width: none`, `scrollbar-gutter: auto`).
// Overflow stays reachable. The position cue is a 1–2px absolutely positioned
// strip (`[data-overlay-scroll]::after`) that is not in the flow.

/** The overlay cue is 2px (`--space-0`). A classic track is ~10–15px. */
export const OVERLAY_SCROLL_CUE_PX = 2;

/** A reserved gutter at or above this is a classic OS track, not an overlay. */
export const CLASSIC_SCROLLBAR_GUTTER_PX = 8;

export interface ReservedGutter {
  readonly inline: number;
  readonly block: number;
}

/**
 * Layout reserved for a classic scrollbar: offset box minus content box minus
 * borders. Overlay / `scrollbar-width: none` yields 0. `thin` on a
 * classic-track OS yields ~10px.
 */
export function reservedScrollbarGutter(el: HTMLElement): ReservedGutter {
  const cs = getComputedStyle(el);
  const bl = Number.parseFloat(cs.borderLeftWidth) || 0;
  const br = Number.parseFloat(cs.borderRightWidth) || 0;
  const bt = Number.parseFloat(cs.borderTopWidth) || 0;
  const bb = Number.parseFloat(cs.borderBottomWidth) || 0;
  return {
    inline: Math.max(0, Math.round(el.offsetWidth - el.clientWidth - bl - br)),
    block: Math.max(0, Math.round(el.offsetHeight - el.clientHeight - bt - bb)),
  };
}

export interface OverlayThumb {
  readonly offset: number;
  readonly size: number;
}

/**
 * Thumb along one axis, in the scroller's visible client box. `null` when
 * content fits — no cue, because there is nothing to cue.
 */
export function overlayThumbAlong(
  scroll: number,
  client: number,
  content: number,
  cuePx = OVERLAY_SCROLL_CUE_PX,
): OverlayThumb | null {
  if (content <= client || client <= 0) return null;
  const size = Math.max(cuePx, (client / content) * client);
  const range = content - client;
  const max = Math.max(0, client - size);
  const offset = range === 0 ? 0 : (scroll / range) * max;
  return { offset, size };
}

/** Write the cue custom properties. `top` includes `scrollTop` so the
 * absolutely-positioned `::after` (a descendant of the scroller) stays in
 * the visible box as the content moves. */
export function syncOverlayScrollCue(el: HTMLElement): void {
  const y = overlayThumbAlong(el.scrollTop, el.clientHeight, el.scrollHeight);
  if (y === null) {
    el.style.setProperty("--overlay-scroll-height", "0px");
    el.style.setProperty("--overlay-scroll-top", "0px");
    return;
  }
  el.style.setProperty("--overlay-scroll-top", `${String(el.scrollTop + y.offset)}px`);
  el.style.setProperty("--overlay-scroll-height", `${String(y.size)}px`);
}

export function bindOverlayScrollCue(el: HTMLElement): () => void {
  const sync = (): void => {
    syncOverlayScrollCue(el);
  };
  const watch = (node: Element): void => {
    ro?.observe(node);
  };
  sync();
  el.addEventListener("scroll", sync, { passive: true });
  const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(sync);
  ro?.observe(el);
  for (const child of el.children) watch(child);
  // Content in the rail / Results arrives after mount (queries). The scroller's
  // own box does not resize; scrollHeight does. Watch the tree so the cue
  // appears when overflow begins.
  const mo = typeof MutationObserver === "undefined" ? null : new MutationObserver(() => {
    for (const child of el.children) watch(child);
    sync();
  });
  mo?.observe(el, { childList: true, subtree: true });
  return () => {
    el.removeEventListener("scroll", sync);
    ro?.disconnect();
    mo?.disconnect();
  };
}

/**
 * Keep overlay cues bound on every `[data-overlay-scroll]` under `root`.
 * Stream scroll mounts only while a session is selected; a one-shot query
 * would miss it.
 */
export function bindOverlayScrollTree(root: ParentNode): () => void {
  const attached = new Map<HTMLElement, () => void>();
  const scan = (): void => {
    const nodes = root.querySelectorAll<HTMLElement>("[data-overlay-scroll]");
    const seen = new Set<HTMLElement>();
    for (const el of nodes) {
      seen.add(el);
      if (!attached.has(el)) attached.set(el, bindOverlayScrollCue(el));
    }
    for (const [el, stop] of attached) {
      if (seen.has(el)) continue;
      stop();
      attached.delete(el);
    }
  };
  scan();
  const mo = typeof MutationObserver === "undefined" ? null : new MutationObserver(scan);
  const target = root instanceof Document ? root.body : (root as Element);
  mo?.observe(target, { childList: true, subtree: true });
  return () => {
    mo?.disconnect();
    for (const stop of attached.values()) stop();
    attached.clear();
  };
}
