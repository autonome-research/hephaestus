// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useLayoutEffect, useState, type RefObject } from "react";

export const FOLLOW_BOTTOM_PX = 32;
export interface ScrollMetrics {
  readonly scrollTop: number;
  readonly scrollHeight: number;
  readonly clientHeight: number;
}
export function scrolledAwayFromBottom(el: ScrollMetrics, threshold = FOLLOW_BOTTOM_PX): boolean {
  return el.scrollHeight - el.clientHeight - el.scrollTop > threshold;
}
export interface ReadingPosition {
  following: boolean;
  top: number;
  anchor: string | null;
  offset: number;
}
/** Project lifetime, like drafts. Presentation is not workspace URL state. */
export const sessionReading = new Map<string, ReadingPosition>();
export function readingPosition(session: string): ReadingPosition {
  let position = sessionReading.get(session);
  if (position === undefined) {
    position = { following: true, top: 0, anchor: null, offset: 0 };
    sessionReading.set(session, position);
  }
  return position;
}
export function pinToLatest(el: { scrollTop: number; scrollHeight: number }): void {
  el.scrollTop = el.scrollHeight;
}

/** Bind to actual content size, not event/row count. Text, images, result bodies,
 * disclosures and width changes can all resize the same stable row. */
export function bindReadingPosition(
  el: HTMLElement, position: ReadingPosition, changed: (following: boolean) => void,
): { restore: () => void; close: () => void } {
  let expectedTop = el.scrollTop;
  const rows = (): HTMLElement[] => [...el.querySelectorAll<HTMLElement>("[data-row-key]")];
  const relativeTop = (row: HTMLElement): number =>
    row.getBoundingClientRect().top - el.getBoundingClientRect().top - el.clientTop;
  const capture = (): void => {
    position.top = el.scrollTop;
    const anchor = rows().find(row => relativeTop(row) + row.getBoundingClientRect().height > 0);
    if (anchor !== undefined) {
      position.anchor = anchor.dataset["rowKey"] ?? null;
      position.offset = relativeTop(anchor);
    }
  };
  const restore = (): void => {
    if (position.following) pinToLatest(el);
    else {
      const anchor = rows().find(row => row.dataset["rowKey"] === position.anchor);
      el.scrollTop = anchor === undefined ? position.top
        : el.scrollTop + relativeTop(anchor) - position.offset;
    }
    expectedTop = el.scrollTop;
  };
  const onScroll = (): void => {
    // Browser-generated events from restoration must not detach following or
    // replace an anchor while its history is still loading.
    if (Math.abs(el.scrollTop - expectedTop) < 1) return;
    expectedTop = el.scrollTop;
    position.following = !scrolledAwayFromBottom(el);
    capture();
    changed(position.following);
  };
  const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(restore);
  const observe = (): void => {
    ro?.disconnect();
    ro?.observe(el);
    for (const child of el.children) ro?.observe(child);
    restore();
  };
  const mo = typeof MutationObserver === "undefined" ? null : new MutationObserver(observe);
  mo?.observe(el, { childList: true, characterData: true, subtree: true });
  el.addEventListener("scroll", onScroll, { passive: true });
  observe();
  changed(position.following);
  return { restore, close: () => {
    el.removeEventListener("scroll", onScroll);
    ro?.disconnect();
    mo?.disconnect();
  } };
}

export function useFollowScroll(
  scrollerRef: RefObject<HTMLElement | null>, sessionId: string | null, mounted: boolean,
): { readonly following: boolean; readonly jumpToLatest: () => void } {
  const [following, setFollowing] = useState(true);
  useLayoutEffect(() => {
    const el = scrollerRef.current;
    if (el === null || sessionId === null) return;
    return bindReadingPosition(el, readingPosition(sessionId), setFollowing).close;
  }, [scrollerRef, sessionId, mounted]);
  const jumpToLatest = useCallback(() => {
    if (sessionId === null) return;
    readingPosition(sessionId).following = true;
    setFollowing(true);
    if (scrollerRef.current !== null) pinToLatest(scrollerRef.current);
  }, [scrollerRef, sessionId]);
  return { following, jumpToLatest };
}
