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

import {
  createContext,
  useCallback,
  useContext,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Icon } from "./icons";
import { cx, dataProps, type DataAttributes } from "./dataAttrs";
import styles from "./TreeRow.module.css";
import roles from "./type.module.css";

/**
 * The tree's tab stop is a focus-holder, not a selection. A disclosure-only
 * tree has no `aria-selected="true"` row; it still needs exactly one
 * `tabIndex={0}` (issue 102). Selected, when present, wins; otherwise the first
 * visible row holds the stop. Arrow keys move the holder with focus.
 */
type TreeFocus = {
  readonly holderId: string | null;
  readonly claim: (id: string, selected: boolean) => void;
  readonly release: (id: string) => void;
  readonly moveHolder: (id: string) => void;
};

const TreeFocusContext = createContext<TreeFocus | null>(null);

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
  const rows = useRef(new Map<string, { selected: boolean; order: number }>());
  const order = useRef(0);
  const [holderId, setHolderId] = useState<string | null>(null);

  const reconcile = useCallback((): void => {
    let first: string | null = null;
    let firstOrder = Infinity;
    let selected: string | null = null;
    for (const [id, info] of rows.current) {
      if (info.order < firstOrder) {
        firstOrder = info.order;
        first = id;
      }
      if (info.selected) selected = id;
    }
    const next = selected ?? first;
    setHolderId((current) => (current === next ? current : next));
  }, []);

  const claim = useCallback(
    (id: string, selected: boolean): void => {
      const existing = rows.current.get(id);
      if (existing === undefined) {
        rows.current.set(id, { selected, order: order.current });
        order.current += 1;
      } else {
        rows.current.set(id, { selected, order: existing.order });
      }
      reconcile();
    },
    [reconcile],
  );

  const release = useCallback(
    (id: string): void => {
      rows.current.delete(id);
      reconcile();
    },
    [reconcile],
  );

  const moveHolder = useCallback((id: string): void => {
    if (rows.current.has(id)) setHolderId(id);
  }, []);

  const focus = useMemo(
    (): TreeFocus => ({ holderId, claim, release, moveHolder }),
    [holderId, claim, release, moveHolder],
  );

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
    const target = items[next];
    const nextId = target?.getAttribute("data-tree-focus");
    if (nextId !== null && nextId !== undefined) moveHolder(nextId);
    target?.focus();
  };

  return (
    <TreeFocusContext.Provider value={focus}>
      <ul
        ref={ref}
        className={cx(styles["tree"], className)}
        role="tree"
        aria-label={label}
        onKeyDown={onKeyDown}
      >
        {children}
      </ul>
    </TreeFocusContext.Provider>
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
  const focusId = useId();
  const treeFocus = useContext(TreeFocusContext);
  const claim = treeFocus?.claim;
  const release = treeFocus?.release;
  useLayoutEffect(() => {
    if (claim === undefined || release === undefined) return;
    claim(focusId, selected);
    return () => {
      release(focusId);
    };
  }, [claim, release, focusId, selected]);
  const tabIndex =
    treeFocus === null ? (selected ? 0 : -1) : treeFocus.holderId === focusId ? 0 : -1;
  const select = (): void => {
    onSelect?.();
  };
  return (
    <li
      className={cx(styles["node"], className)}
      role="treeitem"
      aria-selected={selected}
      tabIndex={tabIndex}
      data-tree-focus={focusId}
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
