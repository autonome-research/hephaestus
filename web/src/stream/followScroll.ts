// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Follow the newest transcript row — until the operator scrolls up.
//
// The well is a conversation, not a log viewer that yanks the viewport. Pin
// to the newest row while the operator is at the bottom; stop the moment they
// scroll up. A surface that steals the thing being read is worse than one that
// never moves. Opening a session lands on the newest turn. When detached, one
// control returns to latest. No new event kind: the effect keys on row count.

import { useCallback, useLayoutEffect, useRef, useState, type RefObject } from "react";

/** How far from the end still counts as "at the bottom". */
export const FOLLOW_BOTTOM_PX = 32;

export type FollowCause = "rows" | "open" | "jump";

export interface ScrollMetrics {
  readonly scrollTop: number;
  readonly scrollHeight: number;
  readonly clientHeight: number;
}

/** True when the operator has left the newest row. */
export function scrolledAwayFromBottom(
  el: ScrollMetrics,
  threshold = FOLLOW_BOTTOM_PX,
): boolean {
  return el.scrollHeight - el.clientHeight - el.scrollTop > threshold;
}

/**
 * Whether the scroller should pin to the newest row for this cause.
 *
 * New rows follow only while attached. Opening a session and the jump
 * control always pin — those are the operator asking for latest.
 */
export function shouldStickToLatest(following: boolean, cause: FollowCause): boolean {
  return cause !== "rows" || following;
}

export function pinToLatest(el: { scrollTop: number; scrollHeight: number }): void {
  el.scrollTop = el.scrollHeight;
}

/**
 * Follow-vs-detach for the transcript scroller.
 *
 * `sessionId` changing is an open; `rowCount` changing is new output. The
 * scroll listener is the only detach signal.
 */
export function useFollowScroll(
  scrollerRef: RefObject<HTMLElement | null>,
  sessionId: string | null,
  rowCount: number,
): { readonly following: boolean; readonly jumpToLatest: () => void } {
  const [following, setFollowing] = useState(true);
  const followingRef = useRef(true);
  const sessionRef = useRef(sessionId);

  const setFollow = (next: boolean): void => {
    followingRef.current = next;
    setFollowing(next);
  };

  const jumpToLatest = useCallback(() => {
    const el = scrollerRef.current;
    if (el === null) return;
    setFollow(true);
    pinToLatest(el);
  }, [scrollerRef]);

  useLayoutEffect(() => {
    const el = scrollerRef.current;
    if (el === null) return;
    const opened = sessionRef.current !== sessionId;
    sessionRef.current = sessionId;
    const cause: FollowCause = opened ? "open" : "rows";
    if (!shouldStickToLatest(followingRef.current, cause)) return;
    if (opened) setFollow(true);
    pinToLatest(el);
  }, [sessionId, rowCount, scrollerRef]);

  useLayoutEffect(() => {
    const el = scrollerRef.current;
    if (el === null) return;
    const onScroll = (): void => {
      const away = scrolledAwayFromBottom(el);
      if (away === !followingRef.current) return;
      setFollow(!away);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      el.removeEventListener("scroll", onScroll);
    };
  }, [scrollerRef, sessionId]);

  return { following, jumpToLatest };
}
