// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `Panel` / `PanelHeader` / `PanelBody` (INTERFACE.md §4.7).
//
// "Grid `auto minmax(0,1fr)`, `min-height: 0`; header at `--pad-panel-header`
// with a `--border` bottom, title in `.title` — **the app's first heading level
// anywhere** — optional `.eyebrow`, right-aligned actions; body at
// `--pad-panel`, `overflow: auto`, stacked at `--gap-group`."
//
// *Retires:* no heading level in the product, and every panel declaring its own
// padding and disagreeing. The measurement behind that: across `web/src/**/*.css`
// there were 91 `font-size` declarations, 65 of them at 11px, one `lg` (a `›`
// chevron) and one `xl` (the no-token screen). **The workspace had no heading
// anywhere.** A panel title at `.title` (15/600) is the first one.
//
// THE BODY OWNS THE COLUMN GRID. §4.7: "All `DataTable`s inside one panel share
// one grid via `subgrid`, so columns align down the whole drawer." The three
// tracks are declared once on `PanelBody`; `DataTable` and `Field` opt into them
// with `grid-template-columns: subgrid`. That is what retires "a 200px table
// floating in a 1490px panel with the Properties value column visibly jogging
// between two groups that each compute their own `max-content`".

import type { ReactNode } from "react";
import { cx, dataProps, type DataAttributes } from "./dataAttrs";
import styles from "./Panel.module.css";
import roles from "./type.module.css";

export type PanelProps = {
  readonly as?: "section" | "div" | "aside" | "nav" | undefined;
  readonly label?: string | undefined;
  readonly className?: string | undefined;
  readonly children: ReactNode;
} & DataAttributes;

export function Panel(props: PanelProps): React.JSX.Element {
  const { as = "section", label, className, children } = props;
  const Tag = as;
  return (
    <Tag
      className={cx(styles["panel"], className)}
      {...(label === undefined ? {} : { "aria-label": label })}
      {...dataProps(props)}
    >
      {children}
    </Tag>
  );
}

export interface PanelHeaderProps {
  /** The app's first heading level. Rendered in `.title` (§4.7). */
  readonly title: ReactNode;
  /** An `.eyebrow` above the title — a section name, never a sentence. */
  readonly eyebrow?: ReactNode | undefined;
  /** Right-aligned actions; `Button`s, never bare `<button>`s. */
  readonly actions?: ReactNode | undefined;
  /** `h2` in the rail, `h3` in the inspector drawer — the caller owns depth. */
  readonly level?: 1 | 2 | 3 | undefined;
  readonly className?: string | undefined;
}

export function PanelHeader({
  title,
  eyebrow,
  actions,
  level = 2,
  className,
}: PanelHeaderProps): React.JSX.Element {
  const Heading = (level === 1 ? "h1" : level === 2 ? "h2" : "h3") as "h1" | "h2" | "h3";
  return (
    <div className={cx(styles["header"], className)}>
      <div className={styles["headingBlock"]}>
        {eyebrow === undefined ? null : (
          <span className={cx(styles["eyebrow"], roles["eyebrow"])}>{eyebrow}</span>
        )}
        <Heading className={cx(styles["title"], roles["title"])}>{title}</Heading>
      </div>
      {actions === undefined ? null : <div className={styles["actions"]}>{actions}</div>}
    </div>
  );
}

export interface PanelBodyProps {
  readonly className?: string | undefined;
  readonly children: ReactNode;
}

export function PanelBody({ className, children }: PanelBodyProps): React.JSX.Element {
  return <div className={cx(styles["body"], className)}>{children}</div>;
}

/**
 * A named group inside a body, with an `.eyebrow` over it.
 *
 * §4.7 gives the eyebrow a job — "section eyebrows above a group" — and this is
 * the only way to spend it, so the 11px tightening has exactly one site.
 */
export function PanelSection({
  eyebrow,
  children,
}: {
  readonly eyebrow: ReactNode;
  readonly children: ReactNode;
}): React.JSX.Element {
  return (
    <div className={styles["section"]}>
      <span className={cx(styles["eyebrow"], roles["eyebrow"])}>{eyebrow}</span>
      {children}
    </div>
  );
}

/**
 * A sentence in a panel: base ink, `.body`, **not italic** (§3.9, §4.7).
 *
 * The shipped `.note`/`.absent` pair was `--ink-3` at 11px italic, measuring
 * 3.10:1 — below the legibility floor in four files at once. Italic-grey-and-
 * smaller is the universal signal for *footnote*, and applying it to a panel's
 * primary content tells the reader the panel is broken.
 */
export function PanelNote({
  children,
  className,
  ...rest
}: { readonly children: ReactNode; readonly className?: string | undefined } & DataAttributes): React.JSX.Element {
  return (
    <p className={cx(styles["note"], roles["body"], className)} {...dataProps(rest)}>
      {children}
    </p>
  );
}
