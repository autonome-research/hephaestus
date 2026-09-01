// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `Badge` — the readout primitive, and the P0 bug fix (INTERFACE.md §4.7).
//
// THE SHIPPED DEFECT THIS MAKES UNREPRESENTABLE. `ChecksPanel.tsx`:59 wrote
// `data-badge` onto the `<li>` while `panels.module.css` selected
// `.badge[data-badge=…]` on the element one level down, and `Fact.tsx` had no
// `data-badge` prop — so nothing matched and `pass`, `fail` and `error` computed
// to the same colour, the same border and `::before { content: none }`. That is
// label-only status encoding at 11px in the panel whose entire job is "did my
// part pass". `DfmPanel.tsx`:132 did it correctly two files over, which is the
// proof it was a slip and not a position.
//
// §3.4's ownership rule is the fix: **a primitive owns its `data-*` contract**.
// This component emits the attribute ON THE ELEMENT IT STYLES. A call site
// cannot put the attribute one element away from its selector because a call
// site never writes the attribute at all. Tailwind would have made the same bug
// identically representable; a component library ships an accordion, not this.
//
// THREE VOCABULARIES, THREE ATTRIBUTES, ONE RECIPE. The workspace has three
// closed status vocabularies that predate this file and that the e2e reads by
// name — `data-badge` (§6.3's check badges), `data-severity` (§6.4's DFM
// findings), `data-chip-status` (§7.2's tool chips). They are NOT merged: each
// keeps its own closed value set, and each gets its own exported component so a
// value from one vocabulary cannot be passed where another is expected. All
// three live in this file with `Badge.module.css` beside them, which is exactly
// what `heph/system-owns-status` (§3.14) checks: the attribute and the CSS that
// selects it are in the same directory, always.
//
// EVERY BADGE RENDERS ICON **+** WORD (§3.12, §3.13.2). Colour is never the
// carrier; it reinforces a carrier that already exists. Each status maps to its
// OWN icon id — §3.14's component test asserts the distinctness, and the map
// below is what makes it true rather than the test hoping it is.
//
// The fill is REQUIRED, not optional (§4.7): "a 1px hairline in an accent hue at
// 11px is not a status signal at arm's length". Badges therefore carry a tinted
// status fill and NO border — `not_run` alone takes a dashed `--border-strong`,
// so an absence reads as an absence.

import type { ReactNode } from "react";
import { Icon, type IconId } from "./icons";
import { cx, dataProps, type DataAttributes } from "./dataAttrs";
import styles from "./Badge.module.css";
import roles from "./type.module.css";

/** §6.3's closed check-badge vocabulary, plus §4.7's two non-check readouts. */
export const BADGE_STATUSES = ["pass", "fail", "error", "not_run", "info", "dirty"] as const;
export type BadgeStatus = (typeof BADGE_STATUSES)[number];

/** §6.4's closed finding-severity vocabulary. */
export const SEVERITIES = ["error", "warning", "info"] as const;
export type Severity = (typeof SEVERITIES)[number];

/** §7.2's closed tool-chip vocabulary, `unknown` included by name. */
export const CHIP_STATUSES = ["running", "ok", "error", "unknown"] as const;
export type ChipStatus = (typeof CHIP_STATUSES)[number];

/**
 * One icon id per `Badge` status — SIX ids for six statuses, none shared.
 *
 * §3.14: "two statuses may not share an icon id, so `info` and `dirty` take
 * different ids rather than both taking `dot`". `dirty` (git) and `error`
 * (runtime/artifact fault) also take different hues — brass vs amber — so a
 * dirty tree and a sidecar death cannot scan as one alarm (#81, §13.1).
 */
export const BADGE_ICONS: Readonly<Record<BadgeStatus, IconId>> = {
  pass: "check",
  fail: "cross",
  error: "alert",
  not_run: "dash",
  info: "info",
  dirty: "dot",
};

export const SEVERITY_ICONS: Readonly<Record<Severity, IconId>> = {
  error: "cross",
  warning: "alert",
  info: "info",
};

export const CHIP_ICONS: Readonly<Record<ChipStatus, IconId>> = {
  running: "dot",
  ok: "check",
  error: "cross",
  unknown: "dash",
};

/**
 * What every badge shares. The icon is chosen by the vocabulary, not passed.
 *
 * `DataAttributes` is the ADDRESSING half of §3.4's ownership rule: the badge
 * mints `data-badge`/`data-severity`/`data-chip-status` and no call site may,
 * but `data-check` — the name G4.4's e2e reads *off the same node* as the badge
 * — is the caller's namespace. §3.14's migration criterion is that every
 * selector survives verbatim, and `[data-check]` carrying `data-badge` is
 * exactly the pairing `dom.spec.ts` asserts. Putting `data-check` on the badge
 * satisfies both: the styled element carries the status, and the selector the
 * gate reads is unchanged.
 */
interface BadgeShellProps {
  /** The word. Never optional — §3.12 refuses an icon that replaces a word. */
  readonly children: ReactNode;
  readonly title?: string | undefined;
  readonly className?: string | undefined;
}

function shellClass(className: string | undefined): string {
  return cx(styles["badge"], roles["label"], className);
}

/** §6.3's check badge. Emits `data-badge` on the styled element, always. */
export function Badge(
  props: { readonly status: BadgeStatus } & BadgeShellProps & DataAttributes,
): React.JSX.Element {
  const { status, children, title, className } = props;
  return (
    <span className={shellClass(className)} data-badge={status} title={title} {...dataProps(props)}>
      <Icon id={BADGE_ICONS[status]} size={12} />
      <span>{children}</span>
    </span>
  );
}

/** §6.4's finding severity. Emits `data-severity` on the styled element. */
export function SeverityBadge(
  props: { readonly severity: Severity } & BadgeShellProps & DataAttributes,
): React.JSX.Element {
  const { severity, children, title, className } = props;
  return (
    <span
      className={shellClass(className)}
      data-severity={severity}
      title={title}
      {...dataProps(props)}
    >
      <Icon id={SEVERITY_ICONS[severity]} size={12} />
      <span>{children}</span>
    </span>
  );
}

/** §7.2's tool-chip status. Emits `data-chip-status` on the styled element. */
export function StatusBadge(
  props: { readonly status: ChipStatus } & BadgeShellProps & DataAttributes,
): React.JSX.Element {
  const { status, children, title, className } = props;
  return (
    <span
      className={shellClass(className)}
      data-chip-status={status}
      title={title}
      {...dataProps(props)}
    >
      <Icon id={CHIP_ICONS[status]} size={12} />
      <span>{children}</span>
    </span>
  );
}
