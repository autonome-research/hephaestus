// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The project-lifetime half of §7A.11 (#92).
//
// `refreshAfterTurn` itself is unchanged: refetch the enumerated keys, never
// merge a tool payload, never move the pin. What this module owns is *when*
// that runs for a turn this tab did not originate.
//
// The Stream column used to be the only listener. Two holes followed:
//
// 1. `useStream` drops every frame whose `session_id` is not the selected tab,
//    so a `delegate_part_agent(delivery="follow_up")` child writes from a
//    session nobody subscribed to, and `keys.parts()` / `keys.gitStatus()` stay
//    stale after the child's terminal.
// 2. `Shell` unmounts `StreamPanel` when the column is collapsed — including
//    the 1024–1279px band §4.1 names as not an edge case — so a collapsed
//    Stream has no refresh at all.
//
// The observer hangs at project lifetime, subscribes to every session the tab
// bar already enumerates (the flat list plus the selected thread), and treats
// a `terminal` on any of those sessions as a turn on this project.

import { useEffect, useMemo, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchSessions, fetchThread } from "./sessions";
import { workspaceToken } from "./token";
import { useWorkspace } from "../state/react";
import { eventsUrl, StreamSocket } from "../stream/socket";
import { processGone, runtimeFaultOf } from "../stream/runtimeFault";
import { refreshAfterTurn } from "./refresh";

const SESSIONS_STALE_MS = 5_000;

/**
 * The session ids a project-scoped observer must hear.
 *
 * `listed` is `GET /sessions`. `thread` is the tab bar's walk of the selected
 * session — delegated children land there before a later list refresh.
 */
export function collectSessionIds(
  listed: readonly string[],
  thread: readonly string[],
): readonly string[] {
  return [...new Set([...listed, ...thread])].sort();
}

/** Subscribe to every session this project already enumerates; refresh on terminal. */
export function useProjectRefresh(): void {
  const client = useQueryClient();
  const part = useWorkspace((s) => s.part);
  const selected = useWorkspace((s) => s.session);
  const sessions = useQuery({
    queryKey: ["sessions"],
    queryFn: fetchSessions,
    staleTime: SESSIONS_STALE_MS,
    retry: false,
  });
  const thread = useQuery({
    queryKey: ["thread", selected],
    queryFn: () => fetchThread(selected ?? ""),
    enabled: selected !== null,
    retry: false,
    staleTime: SESSIONS_STALE_MS,
  });

  const sessionIds = useMemo(() => {
    const listed = (sessions.data?.sessions ?? []).map((row) => row.session_id);
    const nodes = (thread.data?.nodes ?? []).map((node) => node.session_id);
    return collectSessionIds(listed, nodes);
  }, [sessions.data, thread.data]);

  const sessionKey = sessionIds.join("\0");
  const partRef = useRef(part);
  useEffect(() => {
    partRef.current = part;
  }, [part]);

  useEffect(() => {
    if (sessionIds.length === 0) return;
    const token = workspaceToken();
    if (token === null) return;
    const lead = sessionIds[0];
    if (lead === undefined) return;
    const socket = new StreamSocket(
      { sessionId: lead, sessionIds, token },
      {
        onFrame: (frame) => {
          const sid = frame.session_id;
          if (sid !== null && !sessionIds.includes(sid)) return;
          if (frame.kind === "tool_result") {
            // A delegated child is minted before it writes. Refresh the
            // inventory so the next subscribe includes it — still a refetch
            // of enumerated keys, never a merge of the tool payload.
            void client.invalidateQueries({ queryKey: ["sessions"] });
            if (selected !== null) {
              void client.invalidateQueries({ queryKey: ["thread", selected] });
            }
          }
          if (frame.kind !== "terminal") return;
          refreshAfterTurn(client, partRef.current);
        },
        onStatus: () => undefined,
        onResync: () => undefined,
        cursor: () => null,
      },
    );
    socket.open(eventsUrl(window.location));
    return () => {
      socket.close();
    };
  }, [sessionKey, sessionIds, client, selected]);

  // Sidecar death produces neither a terminal nor a prompt response. The
  // Stream column already handles this when it is mounted (#59); this copy
  // covers the collapsed band, where that column is a 44px strip.
  const fault = runtimeFaultOf(sessions.error);
  const refreshedFault = useRef<ReturnType<typeof runtimeFaultOf>>(null);
  useEffect(() => {
    if (fault === null || !processGone(fault)) {
      refreshedFault.current = null;
      return;
    }
    if (refreshedFault.current === fault) return;
    refreshedFault.current = fault;
    refreshAfterTurn(client, part);
  }, [fault, client, part]);
}
