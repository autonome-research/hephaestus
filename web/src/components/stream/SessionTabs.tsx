// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// §7.1's session tabs: "an orchestrator, its delegated part sessions, and a part
// session's quick-edit children form a three-level tree rendered as an indented
// tab list with `data-thread-depth`. **The edge source is
// `GET /sessions/{id}/thread` — never inference.**"
//
// So the tree here is exactly the server's `nodes`, in the server's
// breadth-first order, at the server's `depth`. Nothing is sorted, nested, or
// inferred from a session's profile or its part name.
//
// `data-thread-state="unlinked"` is §2.8's honesty state. A root is not a
// missing parent — the unlinked word is not printed there. The attribute
// stays, and the UUID stays on `title` / `data-session-id`.
//
// A browser tab is a client, never a lease holder (§7.1). Selecting a tab
// changes `?s=` in the §4.5 route and nothing else — no lease is taken, no
// session is created, and the CLI's hold on a session is untouched.
//
// The widget is `TabBar`: roving tabindex, arrows, Home/End, Tab leaves the
// list. The transcript is the `tabpanel` this list controls (#68).
//
// The visible label is the first prompt this page sent, the bound part, or
// "New session". The UUID stays on `title` / `data-session-id`. History omits
// prompts, so the first line is remembered on Send (`sessionPrompts.ts`).

import { useEffect, useSyncExternalStore } from "react";
import { copy } from "../../copy";
import type { SessionRow } from "../../api/sessions";
import type { ThreadTab } from "../../stream/thread";
import { originPart } from "../../stream/thread";
import { sessionPromptStore } from "../../stream/sessionPrompts";
import {
  applySessionDocumentTitle,
  sessionLabel,
  sessionTabMeta,
  sessionTitleAttr,
} from "../../stream/sessionTitle";
import { TabBar } from "../../system";
import styles from "./Stream.module.css";

export interface SessionTabsProps {
  readonly tabs: readonly ThreadTab[];
  readonly sessions: readonly SessionRow[];
  readonly selected: string | null;
  readonly onSelect: (sessionId: string) => void;
  readonly bounded: boolean;
  /** The transcript `tabpanel` this list controls (#68). */
  readonly panelId?: string | undefined;
}

function labelFor(
  tab: ThreadTab,
  row: SessionRow | undefined,
  firstPrompt: string | null,
): string {
  return sessionLabel({
    sessionId: tab.session_id,
    profile: row?.profile ?? null,
    part: row?.part ?? null,
    kind: tab.kind,
    origin: tab.origin,
    createdAt: tab.created_at ?? null,
    firstPrompt,
  });
}

export function SessionTabs({
  tabs,
  sessions,
  selected,
  onSelect,
  bounded,
  panelId,
}: SessionTabsProps): React.JSX.Element {
  const byId = new Map(sessions.map((row) => [row.session_id, row]));
  const selectedId = selected ?? tabs[0]?.session_id ?? "";
  const firstPrompts = useSyncExternalStore(
    sessionPromptStore.subscribe,
    sessionPromptStore.getSnapshot,
    sessionPromptStore.getServerSnapshot,
  );
  const selectedTab = tabs.find((tab) => tab.session_id === selectedId);
  const selectedLabel =
    selectedTab === undefined
      ? null
      : labelFor(selectedTab, byId.get(selectedId), firstPrompts[selectedId] ?? null);

  useEffect(() => {
    applySessionDocumentTitle(selectedLabel);
    return () => {
      applySessionDocumentTitle(null);
    };
  }, [selectedLabel]);

  return (
    <div className={styles["tabs"]}>
      {/* A heading over a list of one is a label for something the reader can
          already see. It appears once there is a choice to make. */}
      {tabs.length > 1 ? (
        <h2 className={styles["tabsHeading"]}>{copy.stream.sessionsHeading}</h2>
      ) : null}
      {bounded ? <p className={styles["note"]}>{copy.stream.threadBounded}</p> : null}
      <TabBar
        attr="data-session-tab"
        panelId={panelId}
        layout="stack"
        className={styles["sessionTabs"]}
        label={copy.stream.sessionsHeading}
        selected={selectedId}
        onSelect={onSelect}
        tabs={tabs.map((tab) => {
          const row = byId.get(tab.session_id);
          const part = row?.part ?? originPart(tab.origin);
          const label = labelFor(tab, row, firstPrompts[tab.session_id] ?? null);
          const meta = sessionTabMeta(tab, row);
          return {
            id: tab.session_id,
            label,
            ariaLabel: label,
            title: sessionTitleAttr(tab.session_id, tab.thread_state),
            trailing:
              meta === null ? undefined : <span className={styles["tabMeta"]}>{meta}</span>,
            style: {
              paddingLeft: `calc(var(--space-2) + ${String(tab.depth)} * var(--space-4))`,
            },
            attrs: {
              "data-session-id": tab.session_id,
              "data-thread-depth": tab.depth,
              "data-thread-state": tab.thread_state,
              ...(tab.kind === null ? {} : { "data-thread-kind": tab.kind }),
              ...(part === null || part === undefined ? {} : { "data-part": part }),
            },
          };
        })}
      />
    </div>
  );
}
