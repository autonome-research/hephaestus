// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `Chip` — the other readout (INTERFACE.md §4.7).
//
// "raised fill, **no border**, 3px radius, inert by contract — it renders a
// `<span>` and takes no `onClick`." The last clause is the interesting one: the
// component cannot be made interactive, so `DfmPanel.tsx`:225 — which rendered
// *"Automatic evaluation after each build: off"* as a chip in the panel's action
// corner, looking exactly like a settings toggle — is not expressible as a
// mistake here. §4.7's rule for that case is blunt: **when a layout has to be
// corrected by a caption, the layout is wrong.** The fact moved into the `Field`
// list where every other read-only fact lives, and the apologetic caption was
// deleted.
//
// §3.10's radius rule is the other half: pill REPORTS, 3px ACTS. A `Badge` is a
// pill because it is a status readout; a `Chip` is 3px because it sits in the
// grammar of the controls around it while carrying no affordance of its own.

import type { ReactNode } from "react";
import { cx, dataProps, type DataAttributes } from "./dataAttrs";
import styles from "./Chip.module.css";
import roles from "./type.module.css";

export type ChipProps = {
  /** `label` for a word, `code` for a ref, a hash, a reason code (§4.7). */
  readonly tone?: "label" | "code" | undefined;
  readonly title?: string | undefined;
  readonly className?: string | undefined;
  readonly children: ReactNode;
} & DataAttributes;

export function Chip(props: ChipProps): React.JSX.Element {
  const { tone = "label", title, className, children } = props;
  return (
    <span
      className={cx(styles["chip"], roles[tone === "code" ? "code" : "label"], className)}
      title={title}
      {...dataProps(props)}
    >
      {children}
    </span>
  );
}
