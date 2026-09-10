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

/** What a scroll event means for the follow state. */
export type FollowMove = "follow" | "unfollow" | "repin" | "hold";

/**
 * Read one scroll event: did the OPERATOR leave the newest row?
 *
 * A scroll event is not evidence of a scroll. A transcript settles after its
 * first paint — an image decodes, a font swaps, a markdown block reflows — and
 * the growth alone moves the viewport's relation to the end; Chrome's scroll
 * anchoring then fires `scroll` with nobody touching the wheel. Reading that as
 * "the operator scrolled up" detached a followed transcript from its own
 * output, which is the opposite of the behaviour this module exists for, and it
 * happened exactly when output was arriving fastest.
 *
 * So the signal is the viewport MOVING UP (`scrollTop` decreasing), not the
 * distance from the end. Content that grew under a pinned viewport leaves
 * `scrollTop` where it was and is re-pinned; the operator dragging upward
 * lowers it and detaches. `previousTop` is the last position this hook saw,
 * not the last one it set, so a nudge inside the slack still counts as the
 * operator's.
 */
export function readFollowMove(
  previousTop: number,
  following: boolean,
  el: ScrollMetrics,
  threshold = FOLLOW_BOTTOM_PX,
): FollowMove {
  const away = scrolledAwayFromBottom(el, threshold);
  if (!away) return following ? "hold" : "follow";
  if (!following) return "hold";
  return el.scrollTop < previousTop ? "unfollow" : "repin";
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
    const move = readFollowMove(expectedTop, position.following, el);
    // Browser-generated events from exact restoration must not detach following
    // or replace an anchor while its history is still loading. Paint-only growth
    // can leave the same top newly away from the end, so its repin still runs.
    if (Math.abs(el.scrollTop - expectedTop) < 1 && move !== "repin") return;
    if (move === "repin") {
      // Paint-only growth and browser anchoring are not operator intent. Keep a
      // followed transcript at its real end, even when no row was added.
      pinToLatest(el);
      expectedTop = el.scrollTop;
      return;
    }
    expectedTop = el.scrollTop;
    if (move === "follow") position.following = true;
    else if (move === "unfollow") position.following = false;
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
