// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `Button` — four variants and nothing else (INTERFACE.md §4.7).
//
//   primary    accent fill, AT MOST ONE PER SURFACE
//   secondary  the default
//   quiet      toolbar and row actions
//   toggle     `aria-pressed`, accent-quiet fill when on
//
// THE SHIPPED P1 THIS RETIRES. `panels.module.css` shipped five bordered-pill
// classes; `.toggle` is a `<button>` and `.state` is inert text, and their
// `border` declarations are **byte-identical**. The affordance was absent BY
// CONSTRUCTION — no amount of hovering distinguishes a control from a readout
// when the two are the same rectangle. §3.3's principle 3 is the rule and
// §3.10's border assignment is its mechanical form: a readout has a tinted fill
// and NO border (`Badge`, `Chip`); a control has a raised control surface and a
// `--border-control`, **and only a control may carry that border**.
//
// DISABLED REQUIRES A REASON, ENFORCED BY THE TYPE. §4.7: "a disabled control in
// this app must always be able to say why — which is the same rule §7A.8 applies
// to the composer and §22.7 to a refused export". The props are a discriminated
// union, so `disabled` without `reason` does not compile; there is no runtime
// check to forget and no lint to add. The reason is rendered as `title` **and**
// as an `aria-describedby` target, because a `title` is not reachable from the
// keyboard and a disabled control is exactly where a keyboard user is stuck.
//
// §3.13.6: every control clears a 24×24px hit area, achieved by padding rather
// than by font-size — the shipped 11px pill controls were ~18px tall.

import { useId, type ReactNode } from "react";
import { Icon, type IconId } from "./icons";
import { cx, dataProps, type DataAttributes } from "./dataAttrs";
import styles from "./Button.module.css";
import roles from "./type.module.css";

export const BUTTON_VARIANTS = ["primary", "secondary", "quiet", "toggle"] as const;
export type ButtonVariant = (typeof BUTTON_VARIANTS)[number];

/** The disabled half of the union: the reason is not optional when it applies. */
type Disablement =
  | { readonly disabled: true; readonly reason: string }
  | { readonly disabled?: false | undefined; readonly reason?: undefined };

export type ButtonProps = {
  readonly variant?: ButtonVariant | undefined;
  /** `toggle` only: drives `aria-pressed` and the accent-quiet fill. */
  readonly pressed?: boolean | undefined;
  readonly onClick?: (() => void) | undefined;
  readonly type?: "button" | "submit" | undefined;
  readonly icon?: IconId | undefined;
  /**
   * Present when the icon is the control's **only** label (§3.12): the button
   * then carries `aria-label` and the icon carries the label as its `role="img"`
   * name. Copy comes from `copy.ts` like every other human-facing string.
   */
  readonly iconLabel?: string | undefined;
  readonly title?: string | undefined;
  readonly className?: string | undefined;
  readonly children?: ReactNode;
} & Disablement &
  DataAttributes;

export function Button(props: ButtonProps): React.JSX.Element {
  const {
    variant = "secondary",
    pressed,
    onClick,
    type = "button",
    icon,
    iconLabel,
    title,
    className,
    children,
    disabled,
    reason,
  } = props;
  const reasonId = useId();
  const isDisabled = disabled === true;
  const labelled = iconLabel !== undefined && children === undefined;

  return (
    <>
      <button
        type={type}
        className={cx(styles["button"], roles["label"], className)}
        data-variant={variant}
        disabled={isDisabled}
        // A disabled control that cannot say why is indistinguishable from a
        // broken one. Both carriers are present: the pointer one and the AT one.
        {...(isDisabled ? { title: reason, "aria-describedby": reasonId } : { title })}
        {...(variant === "toggle" ? { "aria-pressed": pressed === true } : {})}
        {...(labelled ? { "aria-label": iconLabel } : {})}
        {...(onClick === undefined ? {} : { onClick })}
        {...dataProps(props)}
      >
        {icon === undefined ? null : <Icon id={icon} size={13} />}
        {children === undefined ? null : <span>{children}</span>}
      </button>
      {isDisabled ? (
        <span id={reasonId} className={styles["reason"]}>
          {reason}
        </span>
      ) : null}
    </>
  );
}
