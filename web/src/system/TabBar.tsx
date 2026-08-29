// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `TabBar` (INTERFACE.md §4.7, §3.13.4).
//
// "`role="tablist"`, roving tabindex, arrows, Home/End. Selected state is
// `box-shadow: inset 0 -2px 0 var(--accent)` — **not** a border, so the bar does
// not reflow on selection. Emits `data-{attr}`, preserving `[data-stage-tab]`
// and `[data-inspector-tab]` verbatim for the e2e."
//
// *Retires:* three tab bars hand-rolled with three paddings and no keyboard
// pattern. The shipped bars set `role="tab"` and `aria-selected` and then left
// every tab in the tab order with no arrow-key movement, which is the half of
// the pattern that makes `role="tablist"` mean anything to a screen reader.
//
// THE ATTRIBUTE NAME IS A PROP, and it is how the migration criterion is met:
// the Stage passes `attr="data-stage-tab"`, the Inspector passes
// `attr="data-inspector-tab"`, the Stream passes `attr="data-session-tab"`, and
// every selector the gate suite already reads survives verbatim on an element
// this primitive now owns.

import { useRef, type ReactNode } from "react";
import { cx, type DataAttributes } from "./dataAttrs";
import styles from "./TabBar.module.css";
import roles from "./type.module.css";

export interface TabSpec<Id extends string> {
  readonly id: Id;
  readonly label: ReactNode;
  /** A marker beside the label — §13.1's dirty dot on the Script tab. */
  readonly trailing?: ReactNode | undefined;
  /** Addressing attributes for this tab, forwarded verbatim. */
  readonly attrs?: DataAttributes | undefined;
}

export interface TabBarProps<Id extends string> {
  /** The `data-*` name each tab carries its id under (`data-stage-tab`, …). */
  readonly attr: `data-${string}`;
  readonly tabs: readonly TabSpec<Id>[];
  readonly selected: Id;
  readonly onSelect: (id: Id) => void;
  readonly label: string;
  readonly className?: string | undefined;
}

export function TabBar<Id extends string>({
  attr,
  tabs,
  selected,
  onSelect,
  label,
  className,
}: TabBarProps<Id>): React.JSX.Element {
  const listRef = useRef<HTMLDivElement | null>(null);

  /**
   * The roving-tabindex keyboard contract: exactly one tab is in the tab order,
   * and arrows move both the focus and the selection. Home/End go to the ends.
   * Moving focus without moving selection is the other legal pattern; this one
   * is chosen because the tab IS workspace state (§4.5) and a focused-but-
   * unselected tab would put a second, invisible cursor in the URL's way.
   */
  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>): void => {
    const index = tabs.findIndex((tab) => tab.id === selected);
    if (index === -1) return;
    let next = -1;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") next = (index + 1) % tabs.length;
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      next = (index - 1 + tabs.length) % tabs.length;
    } else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    if (next === -1) return;
    event.preventDefault();
    const target = tabs[next];
    if (target === undefined) return;
    onSelect(target.id);
    listRef.current?.querySelector<HTMLButtonElement>(`[${attr}="${target.id}"]`)?.focus();
  };

  return (
    <div
      ref={listRef}
      className={cx(styles["bar"], className)}
      role="tablist"
      aria-label={label}
      onKeyDown={onKeyDown}
    >
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={tab.id === selected}
          tabIndex={tab.id === selected ? 0 : -1}
          className={cx(styles["tab"], roles["label"])}
          {...{ [attr]: tab.id }}
          {...(tab.attrs ?? {})}
          onClick={() => {
            onSelect(tab.id);
          }}
        >
          <span>{tab.label}</span>
          {tab.trailing ?? null}
        </button>
      ))}
    </div>
  );
}
