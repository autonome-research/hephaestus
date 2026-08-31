// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `TreeRow` and `Tree` (INTERFACE.md §4.7, §3.13.4).
//
// "`role="treeitem"`, `aria-expanded`, `aria-selected`, 26px, indent by depth,
// disclosure chevrons from the sprite, selected marked with an inset accent
// rule. The §13.1 dirty marker is a `Badge` variant carrying an `aria-label`,
// **never a bare coloured dot**."
//
// *Retires:* colour-only dirty markers; a tree with no keyboard navigation. The
// shipped rail set `role="tree"`/`role="treeitem"` and then handled no key at
// all, which is an ARIA role claiming a keyboard contract the code did not
// implement — worse than no role, because a screen-reader user is told to expect
// arrows that do nothing.
//
// `Tree` owns the arrow-key contract because it is the only party that can see
// the rows: Up/Down move between visible rows, Right expands (or descends),
// Left collapses (or ascends), Home/End go to the ends. The rows themselves are
// a flat, ordered list with a `depth`, which is what the rail already has.

import { useRef, type ReactNode } from "react";
import { Icon } from "./icons";
import { cx, dataProps, type DataAttributes } from "./dataAttrs";
import styles from "./TreeRow.module.css";
import roles from "./type.module.css";

export interface TreeProps {
  readonly label: string;
  readonly className?: string | undefined;
  readonly children: ReactNode;
}

/**
 * The `role="tree"` container and the arrow-key handler.
 *
 * Navigation is over `[role="treeitem"]` elements in DOM order, which is the
 * visible order: a collapsed node's children are not rendered, so they are not
 * reachable, which is exactly the tree pattern's requirement.
 */
export function Tree({ label, className, children }: TreeProps): React.JSX.Element {
  const ref = useRef<HTMLUListElement | null>(null);

  const onKeyDown = (event: React.KeyboardEvent<HTMLUListElement>): void => {
    const root = ref.current;
    if (root === null) return;
    const items = Array.from(root.querySelectorAll<HTMLElement>('[role="treeitem"]'));
    const active = document.activeElement;
    const index = items.findIndex((item) => item === active || item.contains(active));
    if (index === -1) return;
    const current = items[index];
    let next = -1;
    switch (event.key) {
      case "ArrowDown":
        next = Math.min(index + 1, items.length - 1);
        break;
      case "ArrowUp":
        next = Math.max(index - 1, 0);
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = items.length - 1;
        break;
      case "ArrowRight":
        if (current?.getAttribute("aria-expanded") === "false") {
          current.querySelector<HTMLElement>("[data-tree-toggle]")?.click();
          event.preventDefault();
          return;
        }
        next = Math.min(index + 1, items.length - 1);
        break;
      case "ArrowLeft":
        if (current?.getAttribute("aria-expanded") === "true") {
          current.querySelector<HTMLElement>("[data-tree-toggle]")?.click();
          event.preventDefault();
          return;
        }
        next = Math.max(index - 1, 0);
        break;
      default:
        return;
    }
    event.preventDefault();
    items[next]?.focus();
  };

  return (
    <ul
      ref={ref}
      className={cx(styles["tree"], className)}
      role="tree"
      aria-label={label}
      onKeyDown={onKeyDown}
    >
      {children}
    </ul>
  );
}

export type TreeRowProps = {
  readonly depth: 0 | 1 | 2;
  readonly selected: boolean;
  /** `undefined` for a leaf; a boolean makes the row a disclosure. */
  readonly expanded?: boolean | undefined;
  readonly onSelect?: (() => void) | undefined;
  readonly onToggle?: (() => void) | undefined;
  readonly label: ReactNode;
  /** A marker or a count at the row's right edge. A `Badge`, never a bare dot. */
  readonly trailing?: ReactNode | undefined;
  /** Nested `<ul role="group">` content for an expanded node. */
  readonly children?: ReactNode;
  readonly className?: string | undefined;
} & DataAttributes;

export function TreeRow(props: TreeRowProps): React.JSX.Element {
  const { depth, selected, expanded, onSelect, onToggle, label, trailing, children, className } =
    props;
  /**
   * Pointerdown already selected; ignore the click that follows so a
   * non-idempotent `onSelect` (section expand) does not toggle twice.
   * A test that only dispatches `click` still selects — `armed` stays false.
   */
  const armed = useRef(false);
  const select = (): void => {
    onSelect?.();
  };
  return (
    <li
      className={cx(styles["node"], className)}
      role="treeitem"
      aria-selected={selected}
      tabIndex={selected ? 0 : -1}
      {...(expanded === undefined ? {} : { "aria-expanded": expanded })}
      {...dataProps(props)}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        if (event.currentTarget !== event.target) return;
        event.preventDefault();
        select();
      }}
    >
      {/*
        Selection lives on the row, not the `li`. Nested geometry rows sit in
        a `role="group"` *beside* this div, so a click on a child does not
        bubble through it. Pointerdown selects immediately so a mousedown that
        focuses an unselected `tabIndex={-1}` treeitem cannot remount the row
        before mouseup and drop the click.
      */}
      <div
        className={cx(styles["row"], roles["label"])}
        style={{ paddingLeft: `calc(var(--space-2) + ${String(depth)} * var(--space-4))` }}
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          armed.current = true;
          select();
        }}
        onClick={() => {
          if (armed.current) {
            armed.current = false;
            return;
          }
          select();
        }}
      >
        {expanded === undefined ? (
          <span className={styles["spacer"]} aria-hidden="true" />
        ) : (
          <span
            className={styles["twisty"]}
            data-tree-toggle=""
            aria-hidden="true"
            onPointerDown={(event) => {
              event.stopPropagation();
              if (event.button !== 0) return;
              armed.current = true;
              onToggle?.();
            }}
            onClick={(event) => {
              event.stopPropagation();
              if (armed.current) {
                armed.current = false;
                return;
              }
              onToggle?.();
            }}
          >
            <Icon id={expanded ? "chevron-down" : "chevron-right"} size={12} />
          </span>
        )}
        <span className={styles["label"]}>{label}</span>
        {trailing === undefined ? null : <span className={styles["trailing"]}>{trailing}</span>}
      </div>
      {children}
    </li>
  );
}

/** The `role="group"` a node's children live in. */
export function TreeGroup({ children }: { readonly children: ReactNode }): React.JSX.Element {
  return (
    <ul className={styles["group"]} role="group">
      {children}
    </ul>
  );
}
