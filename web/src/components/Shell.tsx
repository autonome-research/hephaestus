// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The shell (INTERFACE.md §4.1): HEADER over RAIL | STAGE | STREAM.
//
// The STREAM is "a full-height peer column, collapsible but not hidden by
// default. Giving the agent a column rather than a bottom drawer is the
// 'collaborator, not console' claim cashed out in layout."
//
// Width supplies capacity, never conversation intent. Parts overlays below1280;
// an open conversation stays a peer down to843. Explicit Hide leaves a horizontal
// S2-backed return control; its activation reveals without writing a task.
// Conversation evidence and S1 reading/disclosures outlive this panel's mount.

import { useCallback, useEffect, useLayoutEffect, useRef, type CSSProperties } from "react";
import { flushSync } from "react-dom";
import { useProjectRefresh } from "../api/projectRefresh";
import { useProject } from "../api/queries";
import { copy } from "../copy";
import { useWorkspace } from "../state/react";
import { shellStore, streamSizing } from "../state/shell";
import { Button, useBreakpoint } from "../system";
import { ConversationReturn } from "./stream/ConversationReturn";
import { bindOverlayScrollTree } from "../system/overlayScroll";
import roles from "../system/type.module.css";
import { Header } from "./Header";
import { RefusalBanner } from "./RefusalBanner";
import { GitDirtyPanel } from "./rail/GitDirty";
import { ProjectTree } from "./rail/ProjectTree";
import { ProvidersPanel } from "./ProvidersPanel";
import { VersionList } from "./rail/VersionList";
import { Stage } from "./stage/Stage";
import { StreamPanel } from "./stream/StreamPanel";
import styles from "./Shell.module.css";

/** Captured pointer events stay local to the seam; no document drag listeners. */
export function StreamResize({
  sizing,
  viewportWidth,
}: {
  readonly sizing: ReturnType<typeof streamSizing>;
  readonly viewportWidth: number;
}): React.JSX.Element {
  const drag = useRef<{ element: HTMLDivElement; id: number; x: number; width: number } | null>(null);
  const finish = useCallback(() => {
    const active = drag.current;
    drag.current = null;
    if (active?.element.hasPointerCapture(active.id)) active.element.releasePointerCapture(active.id);
  }, []);

  // Also end capture on collapse/unmount, viewport changes, and window deactivation.
  useLayoutEffect(() => finish, [finish, viewportWidth]);
  useEffect(() => {
    window.addEventListener("blur", finish);
    return () => window.removeEventListener("blur", finish);
  }, [finish]);

  return (
    <div
      className={styles["streamResize"]}
      role="separator"
      aria-label={copy.stream.resize}
      aria-orientation="vertical"
      aria-controls="chat-column"
      aria-valuemin={sizing.min}
      aria-valuemax={sizing.max}
      aria-valuenow={sizing.width}
      aria-valuetext={copy.stream.width(sizing.width)}
      tabIndex={0}
      data-stream-resize=""
      onPointerDown={(event) => {
        if (!event.isPrimary || event.button !== 0 || drag.current !== null) return;
        event.preventDefault();
        event.currentTarget.focus();
        event.currentTarget.setPointerCapture(event.pointerId);
        drag.current = { element: event.currentTarget, id: event.pointerId, x: event.clientX, width: sizing.width };
      }}
      onPointerMove={(event) => {
        const active = drag.current;
        if (active === null || active.id !== event.pointerId) return;
        shellStore.setStreamWidth(active.width + active.x - event.clientX);
      }}
      onPointerUp={(event) => { if (drag.current?.id === event.pointerId) finish(); }}
      onPointerCancel={(event) => { if (drag.current?.id === event.pointerId) finish(); }}
      onLostPointerCapture={(event) => { if (drag.current?.id === event.pointerId) finish(); }}
      onKeyDown={(event) => {
        const step = event.shiftKey ? 40 : 10;
        const next = event.key === "Home" ? sizing.min
          : event.key === "End" ? sizing.max
          : event.key === "ArrowLeft" ? sizing.width + step
          : event.key === "ArrowRight" ? sizing.width - step : null;
        if (next === null) return;
        event.preventDefault();
        finish();
        shellStore.setStreamWidth(next);
      }}
    />
  );
}

export function Shell(): React.JSX.Element {
  // §7A.11 lives at project lifetime, not Stream column mount (#92).
  useProjectRefresh();
  const shell = useBreakpoint();
  const sizing = streamSizing(shell);
  // §4.1: when the pin is not the current build "the header is visibly marked
  // and every panel below inherits that marking".
  //
  // THIS ATTRIBUTE IS NOT THE INHERITANCE, and the comment that said it was is
  // the whole of J-web-viewport-9. It is a MECHANISM for one — a hook a panel
  // could style against — and for the workspace's whole life no panel did: a
  // grep found six hits, three comments, two mints and CSS scoped to the header
  // chip itself. The clause is discharged in words instead, by
  // `components/PinSplitMarker.tsx`, which marks the STAGE and the INSPECTOR
  // with what each is showing while the two axes disagree. The attribute stays
  // as the machine-readable half and now has human-readable consumers.
  const pinMode = useWorkspace((s) => s.pin_mode);
  // `GET /project` is the read every other panel presupposes. When *it* is
  // refused, saying which refusal it was beats N empty panels (§2.4).
  const project = useProject();
  const railRef = useRef<HTMLElement | null>(null);

  /**
   * Hand focus back to the control that opened the overlay (§3.13.4).
   *
   * Addressed through its `data-*` selector rather than a ref threaded through
   * `Header`: the toggle is rendered by `Header` and only exists in one band, so
   * a ref would have to be optional at every hop, and the attribute is the same
   * contract the e2e reads.
   */
  const focusRailToggle = (): void => {
    document.querySelector<HTMLElement>("[data-rail-toggle]")?.focus();
  };

  const railOverlayOpen = shell.railOverlay && shell.railOpen;

  const skipTo = (destination: "stage" | "composer"): void => {
    // Focus destinations are not workspace routes. Reveal before focusing,
    // including when the existing conversation is currently unmounted.
    flushSync(() => {
      if (railOverlayOpen) shellStore.setRailOpen(false);
      if (destination === "composer") shellStore.setStreamOpen(true);
    });
    const target = destination === "composer"
      ? document.querySelector<HTMLElement>("[data-composer-input]:not(:disabled)") ?? document.querySelector<HTMLElement>("#composer")
      : document.querySelector<HTMLElement>("#stage") ?? document.querySelector<HTMLElement>("[data-stage-focus]");
    target?.focus({ preventScroll: true });
    target?.scrollIntoView({ block: "nearest", inline: "nearest" });
  };

  // Overlay scroll cues (#115 leftover). Native thumbs are hidden globally so
  // they take no layout; this binds the 2px paint-only cue on every
  // `[data-overlay-scroll]` that mounts — rail, well, Results, stage.
  useLayoutEffect(() => bindOverlayScrollTree(document), []);

  // §3.13.4: the overlay closes on Escape and hands focus back to its opener.
  // A surface that covers a third of the stage and cannot be dismissed from the
  // keyboard is the defect (b) names, said the other way round.
  useEffect(() => {
    if (!railOverlayOpen) return;
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        event.preventDefault();
        shellStore.setRailOpen(false);
        focusRailToggle();
      }
      if (event.key === "Tab") {
        const controls = [...railRef.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
        ) ?? []].filter(el => el.getClientRects().length > 0);
        const first = controls[0];
        const last = controls.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    railRef.current?.querySelector<HTMLElement>("button, [tabindex]")?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [railOverlayOpen]);

  return (
    <div className={styles["shell"]} data-pin-mode={pinMode}>
      <nav className={styles["skip"]} aria-label={copy.skip.links} {...(railOverlayOpen ? { inert: "" } : {})}>
        <a className={roles["label"]} href="#stage" data-skip="stage"
          onClick={event => { event.preventDefault(); skipTo("stage"); }}>
          {copy.skip.stage}
        </a>
        <a className={roles["label"]} href="#composer" data-skip="composer"
          onClick={event => { event.preventDefault(); skipTo("composer"); }}>
          {copy.skip.composer}
        </a>
      </nav>
      <Header
        railToggle={
          shell.railOverlay ? (
            <Button
              variant="quiet"
              icon="sidebar"
              iconLabel={shell.railOpen ? copy.rail.close : copy.rail.open}
              onClick={() => {
                shellStore.setRailOpen(!shell.railOpen);
              }}
              aria-expanded={railOverlayOpen}
              aria-controls="parts-navigation"
              data-rail-toggle=""
            ><span aria-hidden="true">{copy.rail.partsHeading}</span><span className={styles["srOnly"]}>{shell.railOpen ? copy.rail.close : copy.rail.open}</span></Button>
          ) : undefined
        }
      />
      <RefusalBanner
        error={project.error}
        onRetry={() => {
          void project.refetch();
        }}
      />
      <div
        className={styles["body"]}
        style={{ "--stream-width": `${String(sizing.width)}px` } as CSSProperties}
        data-stream={shell.streamOpen ? "open" : "collapsed"}
        data-rail={shell.railOverlay ? (shell.railOpen ? "overlay" : "hidden") : "column"}
        data-band={shell.band}
      >
        {railOverlayOpen ? (
          <div
            className={styles["scrim"]}
            data-rail-scrim=""
            onClick={() => {
              shellStore.setRailOpen(false);
              focusRailToggle();
            }}
          />
        ) : null}

        <nav
          ref={railRef}
          className={styles["rail"]}
          aria-label={copy.rail.title}
          id="parts-navigation"
          data-overlay-scroll=""
        >
          {shell.railOverlay ? (
            <div className={styles["railHead"]}>
              <Button
                variant="quiet"
                icon="close"
                iconLabel={copy.rail.close}
                onClick={() => {
                  shellStore.setRailOpen(false);
                  focusRailToggle();
                }}
                data-rail-close=""
              />
            </div>
          ) : null}
          <ProjectTree />
          <GitDirtyPanel />
          <VersionList />
          {/*
            §4.2's amended panel inventory (§23): `ProvidersPanel` sits on the
            rail beside the project's other configuration, because "which model
            is attached" is a project-level fact like the working tree and the
            version list — not a property of whatever part is selected.

            §23.0's success condition is what its placement has to serve: the
            operator must be able to go from a refusing session route to a
            running turn without leaving the page, so the panel is *on* the page
            rather than behind a settings route the empty state links to.
          */}
          <ProvidersPanel
            onAttached={() => {
              shellStore.setRailOpen(false);
              shellStore.setStreamOpen(true);
              // Let the newly expanded agent column mount before moving
              // keyboard focus. Never create a session or send a turn here.
              requestAnimationFrame(() => {
                document.querySelector<HTMLElement>(
                  '[data-composer-input]:not(:disabled), [data-create-profile="orchestrator"]:not(:disabled)',
                )?.focus();
              });
            }}
          />
        </nav>

        <main className={styles["stage"]} data-stage-focus="" tabIndex={-1} {...(railOverlayOpen ? { inert: "" } : {})}>
          <Stage />
        </main>

        {shell.streamOpen && !railOverlayOpen ? <StreamResize sizing={sizing} viewportWidth={shell.viewportWidth} /> : null}

        <aside className={styles["stream"]} id="chat-column" aria-label={copy.stream.title} {...(railOverlayOpen ? { inert: "" } : {})}>
          {shell.streamOpen ? (
            /* §4.1(h), amended 2026-09-02 (C25): the eyebrow band is struck AS
               A BAND. The collapse control renders as the trailing item of the
               session tab strip inside `StreamPanel`, keeping its hook and its
               `iconLabel` name; the `aside` keeps `copy.stream.title` as its
               `aria-label` above. In the steady state exactly one row of chrome
               renders above the transcript — the strip itself. */
            <StreamPanel />
          ) : (
            <ConversationReturn onOpen={(questionId) => {
              flushSync(() => shellStore.setStreamOpen(true));
              // Return to the same live question if one is actually addressable;
              // otherwise retain S1's session reading anchor and focus composer.
              const question = questionId === null ? null : document.querySelector<HTMLElement>(`[data-question-id="${CSS.escape(questionId)}"]`);
              if (question) {
                question.scrollIntoView({ block: "nearest" });
                question.focus();
              } else skipTo("composer");
            }} />
          )}
        </aside>
      </div>
    </div>
  );
}
