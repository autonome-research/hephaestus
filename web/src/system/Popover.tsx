// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `Popover` (INTERFACE.md §4.7, §3.13.4, §4.4).
//
// "Overlay surface, popover shadow, `max-width: 44ch`, anchored and flipped to
// stay in the viewport, focus trapped, `Escape` closes, focus restored to the
// opener. Carries `data-provenance-state` for §4.4's three shapes."
//
// ONE DEVIATION FROM §4.7's LAST CLAUSE, AND IT IS DELIBERATE. §4.7 says §4.4's
// explanatory sentences render "in `.body` at `--ink-muted` — **not** the current
// 3.10:1". §3.9 says `--ink-muted` is **forbidden on `--surface-overlay`**. A
// popover IS the overlay surface, so the two clauses collide. The refusal wins
// and the prose renders at `--ink-base`, because §3.9's own remedy for the
// forbidden pairing is "Use the base ink" and because §4.7's stated reason for
// naming a token at all was that the sentence "cannot itself be below the
// legibility floor" — which base ink satisfies more, not less. Recorded here
// rather than resolved silently; §3.9 and §4.7 need one word reconciled.
//
// FOCUS. The trap is a real one: focus moves into the panel on open, Tab cycles
// inside it, `Escape` closes, and the opener gets focus back. A popover that
// only *looks* modal strands a keyboard user behind it, which is the failure
// §3.13.4 names for the rail overlay ("cannot be dismissed at all").

import { useCallback, useEffect, useRef, type ReactNode } from "react";
import { cx, dataProps, type DataAttributes } from "./dataAttrs";
import styles from "./Popover.module.css";

const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

export type PopoverProps = {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly label: string;
  /** `dialog` for a modal (§4.7's ConflictDialog/TagDialog), `menu` for anchored. */
  readonly variant?: "popover" | "dialog" | undefined;
  readonly className?: string | undefined;
  readonly children: ReactNode;
} & DataAttributes;

export function Popover(props: PopoverProps): React.JSX.Element | null {
  const { open, onClose, label, variant = "popover", className, children } = props;
  const panelRef = useRef<HTMLDivElement | null>(null);
  const openerRef = useRef<Element | null>(null);

  const close = useCallback(() => {
    onClose();
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    openerRef.current = document.activeElement;
    const panel = panelRef.current;
    const first = panel?.querySelector<HTMLElement>(FOCUSABLE) ?? null;
    if (first !== null) first.focus();
    else panel?.focus();
    const opener = openerRef.current;
    return () => {
      // Restoring focus to the opener is the half of the pattern that is usually
      // missing: without it, dismissing a popover drops the caret at the top of
      // the document and a keyboard user has to walk back.
      if (opener instanceof HTMLElement && document.contains(opener)) opener.focus();
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        event.stopPropagation();
        close();
        return;
      }
      if (event.key !== "Tab") return;
      const panel = panelRef.current;
      if (panel === null) return;
      const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (first === undefined || last === undefined) return;
      const active = document.activeElement;
      const inItems = active instanceof HTMLElement && items.includes(active);
      // A click on the panel (`tabIndex={-1}`) or the scrim leaves
      // `activeElement` outside the focusable list. Wrapping only at the
      // first/last item lets Tab escape from that state (#84).
      if (event.shiftKey && (!inItems || active === first)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (!inItems || active === last)) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
    };
  }, [open, close]);

  if (!open) return null;

  return (
    <>
      <div className={styles["scrim"]} data-popover-scrim="" onClick={close} />
      <div
        ref={panelRef}
        className={cx(styles["panel"], className)}
        data-variant={variant}
        role={variant === "dialog" ? "dialog" : "group"}
        aria-modal={variant === "dialog"}
        aria-label={label}
        tabIndex={-1}
        {...dataProps(props)}
      >
        {children}
      </div>
    </>
  );
}
