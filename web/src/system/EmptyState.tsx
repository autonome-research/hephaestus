// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `EmptyState` (INTERFACE.md §4.7, §3.3 principle 5).
//
// "Centred column, `max-width: 44ch`, sprite icon, `.title` heading, `.body`
// prose in the base ink and **not italic**, optional `Button`."
//
// *Retires the shipped P2:* italic-grey-and-smaller is the universal signal for
// *footnote*, and applying it to a panel's primary content tells the reader the
// panel is broken — exactly the failure `Stage.tsx`'s own comment says it is
// avoiding ("a state that exists for a reason reads as designed; the same state
// with its content missing reads as a bug"). The prose achieved it; the styling
// defeated it. The shipped value was `--ink-3` on `--ground-1` at **3.10:1**,
// 11px, italic, in four files plus every `.note`.
//
// §3.3's principle 5 is why this primitive exists at all rather than a
// paragraph: "The agent is a peer surface, and its emptiness must look designed…
// Every state — refusal, absence, 'no runtime attached' — is a first-class
// composed state with a shape, an icon, a heading, and where an action exists, a
// button." A peer column whose entire content is two italic 12px sentences at
// 3.10:1 contradicts the layout claim.
//
// SECOND RULE, and it is a real one: **a shared cause is detected once** (§4.7).
// `WORKING TREE` and `VERSIONS` shipped the *identical* sentence in adjacent
// rail sections above ~1000px of void. One `EmptyState` spans both and the
// sentence is printed once — which is why this component takes a `body` that may
// be a node, and why the rail composes it around two sections rather than inside
// each.

import type { ReactNode } from "react";
import { Icon, type IconId } from "./icons";
import { cx, dataProps, type DataAttributes } from "./dataAttrs";
import styles from "./EmptyState.module.css";
import roles from "./type.module.css";

export type EmptyStateProps = {
  readonly icon: IconId;
  readonly title: ReactNode;
  /**
   * The prose. **Optional**, and the container is not rendered without it.
   *
   * §4.7 asks for prose because the shipped absences were bare grey sentences
   * with no shape; it does not ask for a second copy of the heading. Where the
   * title already IS the whole fact — `No artifact pinned` under a body reading
   * "No artifact is pinned, so there is no geometry to show." — the sentence is
   * not prose, it is the heading again in a smaller ink, and the reader pays for
   * it in the middle of an empty viewport.
   */
  readonly body?: ReactNode | undefined;
  /** A `Button`, where an action actually exists. Never a decorative one. */
  readonly action?: ReactNode | undefined;
  /** `panel` centres in a region; `inline` sits in the flow of a rail section. */
  readonly density?: "panel" | "inline" | undefined;
  readonly className?: string | undefined;
} & DataAttributes;

export function EmptyState(props: EmptyStateProps): React.JSX.Element {
  const { icon, title, body, action, density = "panel", className } = props;
  return (
    <div
      className={cx(styles["empty"], className)}
      data-density={density}
      {...dataProps(props)}
    >
      <Icon id={icon} size={22} className={styles["icon"]} />
      <p className={cx(styles["title"], roles["title"])}>{title}</p>
      {body === undefined ? null : (
        <div className={cx(styles["body"], roles["body"])}>{body}</div>
      )}
      {action === undefined ? null : <div className={styles["action"]}>{action}</div>}
    </div>
  );
}
