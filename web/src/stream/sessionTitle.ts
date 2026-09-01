// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// A session tab is a conversation, not a key (INTERFACE.md §7.1).
//
// The UUID is the session's identity and stays on `title` / `data-session-id`.
// The visible label is something the operator said or did: the first prompt
// line, the bound part, or "New session" plus when it started. A truncated
// UUID pair is indistinguishable; a part name is not.

import type { SessionRow } from "../api/sessions";
import { copy } from "../copy";
import { formatObservedAt } from "../system/format";
import { originPart, type ThreadTab } from "./thread";

const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface SessionTitleInput {
  readonly sessionId: string;
  readonly profile?: string | null;
  readonly part?: string | null;
  readonly kind?: string | null;
  readonly origin?: Readonly<Record<string, unknown>>;
  readonly createdAt?: number | null;
  /** First prompt line, when the page actually has the operator's words. */
  readonly firstPrompt?: string | null;
  readonly now?: Date;
}

function firstLine(text: string | null | undefined): string | null {
  if (text === null || text === undefined) return null;
  const line = text.trim().split(/\r?\n/, 1)[0]?.trim() ?? "";
  if (line === "" || UUID.test(line)) return null;
  return line;
}

function boundPart(input: SessionTitleInput): string | null {
  if (typeof input.part === "string" && input.part !== "") return input.part;
  return originPart(input.origin ?? {});
}

/**
 * The human label for one session tab. Never a UUID.
 *
 * Precedence is what the operator can recognise: their own words, then the
 * part they asked about, then the create affordance plus a time.
 */
export function sessionLabel(input: SessionTitleInput): string {
  const prompt = firstLine(input.firstPrompt);
  if (prompt !== null) return prompt;
  const part = boundPart(input);
  if (part !== null) return copy.composer.createPart(part);
  if (input.createdAt !== null && input.createdAt !== undefined) {
    return `${copy.composer.createOrchestrator} · ${formatObservedAt(input.createdAt, input.now)}`;
  }
  return copy.composer.createOrchestrator;
}

/** Tooltip / `title`: the UUID, plus the unlinked reason when that is a fact. */
export function sessionTitleAttr(
  sessionId: string,
  threadState: string | null | undefined,
): string {
  if (threadState === "unlinked") return `${sessionId} — ${copy.stream.unlinkedWhy}`;
  return sessionId;
}

/** A root is not a missing parent. The parent clause is omitted there. */
export function isSessionRoot(tab: Pick<ThreadTab, "parent_session_id" | "depth">): boolean {
  return tab.parent_session_id === null && tab.depth === 0;
}

/**
 * The muted word beside the label.
 *
 * An orchestrator root is a project session, not "no parent". Linked children
 * keep the server's profile / edge kind. The unlinked word is never the
 * visible subtitle — `data-thread-state` still carries it.
 */
export function sessionTabMeta(
  tab: ThreadTab,
  row: SessionRow | undefined,
): string | null {
  if (row?.profile === "orchestrator" || (row === undefined && isSessionRoot(tab))) {
    return copy.stream.projectSession;
  }
  if (row?.profile === "part" || row?.profile === "quick_edit") {
    return copy.stream.profile[row.profile];
  }
  if (row?.profile !== undefined && row.profile !== "") return row.profile;
  if (tab.kind === "quick_edit" || tab.kind === "delegation") {
    return copy.stream.edgeKind[tab.kind];
  }
  return tab.kind;
}

export function titleInputFor(
  sessionId: string,
  sessions: readonly SessionRow[],
  tabs: readonly ThreadTab[],
  now?: Date,
): SessionTitleInput {
  const row = sessions.find((item) => item.session_id === sessionId);
  const tab = tabs.find((item) => item.session_id === sessionId);
  return {
    sessionId,
    profile: row?.profile ?? null,
    part: row?.part ?? originPart(tab?.origin ?? {}),
    kind: tab?.kind ?? null,
    origin: tab?.origin ?? {},
    createdAt: tab?.created_at ?? null,
    ...(now === undefined ? {} : { now }),
  };
}

/** Human title for a session id, for copy that used to dump the UUID. */
export function titleForSession(
  sessionId: string,
  sessions: readonly SessionRow[],
  tabs: readonly ThreadTab[],
  now?: Date,
): string {
  return sessionLabel(titleInputFor(sessionId, sessions, tabs, now));
}
