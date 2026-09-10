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
  //: The last position this hook OBSERVED, which is what makes a decrease
  //: attributable to the operator rather than to the content settling.
  const lastTopRef = useRef(0);

  const setFollow = (next: boolean): void => {
    followingRef.current = next;
    setFollowing(next);
  };

  const jumpToLatest = useCallback(() => {
    const el = scrollerRef.current;
    if (el === null) return;
    setFollow(true);
    pinToLatest(el);
    lastTopRef.current = el.scrollTop;
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
    lastTopRef.current = el.scrollTop;
  }, [sessionId, rowCount, scrollerRef]);

  useLayoutEffect(() => {
    const el = scrollerRef.current;
    if (el === null) return;
    const onScroll = (): void => {
      const move = readFollowMove(lastTopRef.current, followingRef.current, el);
      if (move === "repin") {
        // The content grew under a pinned viewport: stay with the newest row
        // rather than reading the growth as the operator leaving it.
        pinToLatest(el);
        lastTopRef.current = el.scrollTop;
        return;
      }
      lastTopRef.current = el.scrollTop;
      if (move === "follow") setFollow(true);
      else if (move === "unfollow") setFollow(false);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      el.removeEventListener("scroll", onScroll);
    };
  }, [scrollerRef, sessionId]);

  return { following, jumpToLatest };
}
