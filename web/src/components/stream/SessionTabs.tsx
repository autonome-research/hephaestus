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
// The selected human title stays in the header; the full server-shaped tree
// lives in the compact switcher. Both reuse TabBar's keyboard navigation.
//
// The visible label is the first prompt this page sent, or (§7.1 C6, amended
// 2026-09-02) a noun phrase composed from server facts only — never a
// create-control label. The UUID stays on `title` / `data-session-id`. History
// omits prompts, so the first line is remembered on Send (`sessionPrompts.ts`).
//
// §4.1(h) C25 (amended 2026-09-20): the strip is the one row of chrome above
// the transcript, and it carries the column's two edge controls — the §7.1(b)
// `+` that opens a conversation at its leading edge, and the `X` that closes
// the whole column at its trailing one. The former `streamHeader` band above
// this strip is struck.

import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
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
   * The create affordance at the leading edge of the conversation header.
   * The panel decides whether it renders at all; the strip only places it.
   */
  readonly create?: ReactNode;
  /**
   * The Agent column's close, as the strip's TRAILING item (2026-09-20).
   *
   * Not the struck in-column chevron returning: that one hid the column and
   * left a docked strip to come back through. This is an `X` on the row that
   * already opens conversations, so the row reads open-left / close-right, and
   * the way BACK is the header's own control — which is always drawn, because
   * the header never goes away.
   */
  readonly close?: ReactNode;
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
  close,
}: SessionTabsProps): React.JSX.Element {
  const [switchOpen, setSwitchOpen] = useState(false);
  const stripRef = useRef<HTMLDivElement>(null);
  const hadOpen = useRef(false);
  const byId = new Map(sessions.map((row) => [row.session_id, row]));
  const selectedId = selected ?? tabs[0]?.session_id ?? "";
  useEffect(() => {
    if (switchOpen) {
      hadOpen.current = true;
      stripRef.current?.querySelector<HTMLElement>('[data-session-option][aria-selected="true"]')?.focus();
    } else if (hadOpen.current) {
      hadOpen.current = false;
      stripRef.current?.querySelector<HTMLElement>("[data-session-switch]")?.focus();
    }
  }, [switchOpen, selectedId]);
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

  const choices = tabs.map((tab) => {
    const row = byId.get(tab.session_id);
    const part = row?.part ?? originPart(tab.origin);
    const firstPrompt = firstPrompts[tab.session_id] ?? null;
    const label = labelFor(tab, row, firstPrompt);
    const kind = sessionTabMeta(tab, row, firstPrompt);
    // A prompt title must not erase the bound part. Fallback labels already name it.
    const meta = part != null && firstPrompt !== null
      ? [part, kind].filter(Boolean).join(" · ") : kind;
    return {
      id: tab.session_id,
      label,
      ariaLabel: meta === null ? label : `${label} — ${meta}`,
      title: sessionTitleAttr(tab.session_id, tab.thread_state),
      trailing: meta === null ? undefined : <span className={styles["tabMeta"]}>{meta}</span>,
      style: { paddingLeft: `calc(var(--space-2) + ${String(tab.depth)} * var(--space-4))` },
      attrs: {
        "data-session-id": tab.session_id,
        "data-thread-depth": tab.depth,
        "data-thread-state": tab.thread_state,
        ...(tab.kind === null ? {} : { "data-thread-kind": tab.kind }),
        ...(part == null ? {} : { "data-part": part }),
      },
    };
  });

  return (
    <div ref={stripRef} className={styles["tabs"]} data-session-strip="">
      <div className={styles["tabsCreate"]}>{create}</div>
      <div className={styles["selectedSession"]}>
      <TabBar
        attr="data-session-tab"
        panelId={panelId}
        layout="stack"
        className={styles["selectedSession"]}
        label={copy.stream.sessionsHeading}
        selected={selectedId}
        onSelect={() => {
          // The title may be replaced on selection; restore focus to the stable switch control.
          stripRef.current?.querySelector<HTMLElement>("[data-session-switch]")?.focus();
          setSwitchOpen(true);
        }}
        tabs={choices.filter((choice) => choice.id === selectedId).map((choice) => ({
          ...choice,
          trailing: <span aria-hidden="true" className={styles["titleChevron"]} />,
          expanded: switchOpen,
          style: { paddingLeft: "var(--space-2)" },
          attrs: { ...choice.attrs, "data-session-switch": "" },
        }))}
      />
      <span className={styles["srOnly"]} data-conversation-scope="">
        {selectedTab ? (byId.get(selectedId)?.part ?? originPart(selectedTab.origin)) != null
          ? `Part: ${byId.get(selectedId)?.part ?? originPart(selectedTab.origin)}`
          : byId.get(selectedId)?.profile === "orchestrator" ? "Project scope" : "Scope unavailable"
          : "No conversation selected"}
      </span>
      </div>
      {close == null ? null : <div className={styles["tabsClose"]}>{close}</div>}
      <Popover
        open={switchOpen}
        onClose={() => setSwitchOpen(false)}
        label={copy.stream.switchSession}
        className={styles["sessionMenu"]}
        data-session-switch-open=""
      >
        {bounded ? <p className={styles["note"]}>{copy.stream.threadBounded}</p> : null}
        <TabBar
          attr="data-session-option"
          layout="stack"
          className={styles["sessionTabs"]}
          label={copy.stream.sessionsHeading}
          selected={selectedId}
          onSelect={onSelect}
          // Roving keyboard selection keeps the list available for subsequent
          // arrows/Home/End. Only explicit click/Enter/Space dismisses it.
          onActivate={() => setSwitchOpen(false)}
          tabs={choices}
        />
        <Button variant="quiet" onClick={() => setSwitchOpen(false)}>
          {copy.stream.switchDone}
        </Button>
      </Popover>
    </div>
  );
}

export interface SessionCreateActionProps {
  readonly profiles: readonly ProfileCapability[];
  readonly part: string | null;
  readonly pending: boolean;
  readonly onCreate: (profile: "orchestrator" | "part", part: string | null) => void;
  /**
   * Why the create cannot act, when it cannot — a runtime fault or
   * `agent_unavailable`. The control still MOUNTS in those states (§4.7, #43):
   * the strip's leading `+` is the column's fixed landmark, and a header whose
   * only content is the control that dismisses it is the furniture §0.2b
   * measured. `null` while the create can act.
   */
  readonly blockedReason?: string | null | undefined;
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
  blockedReason = null,
}: SessionCreateActionProps): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const orchestrator = profiles.find((row) => row.profile === "orchestrator");
  const newSessionWhy =
    orchestrator === undefined
      ? copy.composer.createOrchestrator
      : copy.composer.profileWhat(
          orchestrator.profile,
          orchestrator.can_delegate,
          orchestrator.part_scoped,
        );
  // A blocked runtime outranks a pending POST: with no runtime there is nothing
  // for the POST to be pending on, and the operator needs the cause that tells
  // them what to do next, not the one that tells them to wait.
  const disablement = blockedReason !== null
    ? ({ disabled: true as const, reason: blockedReason } as const)
    : pending
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
