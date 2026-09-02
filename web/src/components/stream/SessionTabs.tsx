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
// The visible label is the first prompt this page sent, or (§7.1 C6, amended
// 2026-09-02) a noun phrase composed from server facts only — never a
// create-control label. The UUID stays on `title` / `data-session-id`. History
// omits prompts, so the first line is remembered on Send (`sessionPrompts.ts`).
//
// §4.1(h) C25 (amended 2026-09-02): `[data-stream-collapse]` is the strip's
// TRAILING item, after the §7.1(b) `+` — the former `streamHeader` band above
// this strip is struck, so in the steady state this strip is the one row of
// chrome above the transcript.

import { useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { copy } from "../../copy";
import type { ProfileCapability, SessionRow } from "../../api/sessions";
import type { ThreadTab } from "../../stream/thread";
import { originPart } from "../../stream/thread";
import { sessionPromptStore } from "../../stream/sessionPrompts";
import {
  applySessionDocumentTitle,
  sessionLabel,
  sessionTabMeta,
  sessionTitleAttr,
} from "../../stream/sessionTitle";
import { Button, Popover, TabBar } from "../../system";
import styles from "./Stream.module.css";

export interface SessionTabsProps {
  readonly tabs: readonly ThreadTab[];
  readonly sessions: readonly SessionRow[];
  readonly selected: string | null;
  readonly onSelect: (sessionId: string) => void;
  readonly bounded: boolean;
  /** The transcript `tabpanel` this list controls (#68). */
  readonly panelId?: string | undefined;
  /**
   * §7.1(b): the create affordance, as the strip's LAST ITEM rather than as a
   * band under it. The panel decides whether it renders at all; the strip only
   * decides where it sits. `undefined` is the state where the panel says no.
   */
  readonly create?: ReactNode;
  /**
   * §4.1(h) C25: the stream collapse affordance, as the strip's trailing item —
   * after the `+`, the strip's last interactive element in every state. The
   * shell owns the open/closed state; the strip only decides where the control
   * sits.
   */
  readonly collapse?: ReactNode;
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
  create,
  collapse,
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
    <div className={styles["tabs"]} data-session-strip="">
      {/* §7.1(a), amended 2026-09-01: THE HEADING DOES NOT RENDER, in any state.
          It was an `<h2>` over a list whose `aria-label` is the same string —
          the word "session" printed twice above a strip whose every row is one.
          `copy.stream.sessionsHeading` survives as that label below, so the
          landmark and the accessible name are unchanged; what is dropped is the
          visible duplicate, which §3.13 does not count as removing a name. */}
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
      {/* The strip's trailing row (§7.1(b), §4.1(h) C25): the `+`, then the
          collapse chevron as the strip's LAST interactive element in every
          state. Outside the `tablist`, because neither is a session and a
          roving tabindex over the tabs must not walk onto them. */}
      {(create === undefined || create === null) &&
      (collapse === undefined || collapse === null) ? null : (
        <div className={styles["tabsCreate"]}>
          {create}
          {collapse === undefined || collapse === null ? null : (
            <div className={styles["tabsCollapse"]}>{collapse}</div>
          )}
        </div>
      )}
    </div>
  );
}

export interface SessionCreateActionProps {
  readonly profiles: readonly ProfileCapability[];
  readonly part: string | null;
  readonly pending: boolean;
  readonly onCreate: (profile: "orchestrator" | "part", part: string | null) => void;
}

/**
 * §7.1(b): the two create affordances as ONE icon-only `+` at the end of the
 * session strip.
 *
 * The wording is not printed twice. `New session` and `Ask about <part>` are
 * the `+`'s two menu entries and the menu is drawn **only while open**; with no
 * part selected there is one entry, and the `+` activates it directly rather
 * than opening a one-item menu — a menu whose only job is to be dismissed is a
 * click that reports nothing.
 *
 * The hooks are unmoved: `[data-session-create]` addresses the new-session
 * action and `[data-session-ask]` the part-scoped one, wherever they live —
 * on the `+` itself in the one-entry case, on the entries in the two-entry one.
 * `data-create-profile` is unchanged and still names the profile the POST will
 * carry, so a gate that addressed either action by name still finds it.
 *
 * The capability list is decoration, not a gate: `POST /sessions` does not need
 * it, and a 500 on the document that reported a runtime fault leaves
 * `profiles = []`. Hiding the create then would kill the one §7A.2 affordance
 * with the read that reported the failure (#43).
 */
export function SessionCreateAction({
  profiles,
  part,
  pending,
  onCreate,
}: SessionCreateActionProps): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const orchestrator = profiles.find((row) => row.profile === "orchestrator");
  const partProfile = profiles.find((row) => row.profile === "part");
  const newSessionWhy =
    orchestrator === undefined
      ? copy.composer.createOrchestrator
      : copy.composer.profileWhat(
          orchestrator.profile,
          orchestrator.can_delegate,
          orchestrator.part_scoped,
        );
  const askWhy =
    part === null
      ? null
      : partProfile === undefined
        ? copy.composer.createPart(part)
        : copy.composer.profileWhat(
            partProfile.profile,
            partProfile.can_delegate,
            partProfile.part_scoped,
          );
  const disablement = pending
    ? ({ disabled: true as const, reason: copy.composer.sending } as const)
    : ({} as const);

  if (part === null) {
    return (
      <Button
        variant="quiet"
        icon="plus"
        iconLabel={copy.composer.createOrchestrator}
        title={newSessionWhy}
        onClick={() => {
          onCreate("orchestrator", null);
        }}
        data-session-create=""
        data-create-profile="orchestrator"
        {...disablement}
      />
    );
  }

  return (
    <div className={styles["tabsCreateAnchor"]}>
      <Button
        variant="quiet"
        icon="plus"
        iconLabel={copy.stream.createMenu}
        title={copy.stream.createMenu}
        expanded={open}
        onClick={() => {
          setOpen((was) => !was);
        }}
        data-session-create-menu=""
        {...disablement}
      />
      <Popover
        open={open}
        onClose={() => {
          setOpen(false);
        }}
        label={copy.stream.createMenu}
        variant="popover"
        className={styles["createMenu"]}
        data-session-create-open=""
      >
        <Button
          variant="quiet"
          title={newSessionWhy}
          onClick={() => {
            setOpen(false);
            onCreate("orchestrator", null);
          }}
          data-session-create=""
          data-create-profile="orchestrator"
          {...disablement}
        >
          {copy.composer.createOrchestrator}
        </Button>
        <Button
          variant="quiet"
          title={askWhy ?? ""}
          onClick={() => {
            setOpen(false);
            onCreate("part", part);
          }}
          data-session-ask=""
          data-create-profile="part"
          {...disablement}
        >
          {copy.composer.createPart(part)}
        </Button>
      </Popover>
    </div>
  );
}
