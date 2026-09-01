// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `Input` — text, textarea, slider (INTERFACE.md §4.7).
//
// "Invalid state carries a message row in words, never colour alone. The
// slider's numeric readout is `.data`, right-aligned, and **editable** — a
// slider whose value cannot be typed is not a parameter control (§10). Bounds
// come from `PARAMS` and render as `Field`s, never invented."
//
// The editable readout is the substantive clause and the shipped `ExplodeSlider`
// is the case: it renders `t.toFixed(2)` as inert text, so a reader who wants
// exactly 0.60 has to drag for it. `Slider` therefore pairs the range with a
// number input over the same value, and both write through one `onChange`.
//
// WHAT THE SLIDER'S NUMBER IS NOT. §1 exempts screen-space quantities by name
// and forbids rendering them as facts: `explode_t` is the position of a control,
// so the readout is deliberately NOT a `<Fact>` and carries no `data-source`.
// The primitive cannot mint one either — that is `<Fact>`'s exclusive right
// (§4.6, and `heph/no-derived-fact` enforces it).

import { useId, type ReactNode } from "react";
import { cx, dataProps, type DataAttributes } from "./dataAttrs";
import styles from "./Input.module.css";
import roles from "./type.module.css";

interface FieldFrame {
  readonly label: string;
  /** `true` hides the label visually; it stays in the accessibility tree. */
  readonly hideLabel?: boolean | undefined;
  /** A refusal in WORDS. Colour is never the carrier (§3.13.2). */
  readonly invalid?: string | undefined;
  readonly className?: string | undefined;
}

export type TextInputProps = FieldFrame & {
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly placeholder?: string | undefined;
  readonly disabled?: boolean | undefined;
  readonly multiline?: boolean | undefined;
  readonly rows?: number | undefined;
  readonly onFocus?: (() => void) | undefined;
  readonly onBlur?: (() => void) | undefined;
  /**
   * Keys, for the one control where the keyboard is the primary affordance.
   *
   * The composer (§7A) is a conversation, and a conversation held entirely by
   * reaching for a Send button is not one. The primitive stays dumb about which
   * key means what — the binding is the call site's decision, because a
   * `multiline` field that swallowed Enter everywhere would break the two
   * places this primitive is a genuine paragraph editor.
   */
  readonly onKeyDown?: ((event: React.KeyboardEvent<HTMLTextAreaElement>) => void) | undefined;
  /**
   * The §23.3 password discipline, and it is three properties rather than one.
   *
   * "…the key goes into a `type="password"` field with `autocomplete="off"` and
   * **no `name`** a password manager would save under a misleading identity."
   * A provider key saved by a browser under the identity of a loopback page is
   * a credential filed in the wrong place forever, so the field carries no
   * `name` at all — this primitive never emits one, for any input.
   *
   * `spellCheck` is off for the same family of reasons a password field turns
   * it off: a spellchecker is another consumer of the value.
   */
  readonly secret?: boolean | undefined;
} & DataAttributes;

export function TextInput(props: TextInputProps): React.JSX.Element {
  const {
    label,
    hideLabel,
    invalid,
    className,
    value,
    onChange,
    placeholder,
    disabled,
    multiline,
    rows = 3,
    secret,
    onFocus,
    onBlur,
    onKeyDown,
  } = props;
  const id = useId();
  const messageId = `${id}-message`;
  const shared = {
    id,
    className: cx(styles["input"], roles["body"]),
    value,
    disabled: disabled === true,
    "aria-invalid": invalid !== undefined,
    ...(invalid === undefined ? {} : { "aria-describedby": messageId }),
    ...(placeholder === undefined ? {} : { placeholder }),
    ...dataProps(props),
  };

  return (
    <div className={cx(styles["field"], className)}>
      <label
        htmlFor={id}
        className={cx(hideLabel === true ? styles["hidden"] : styles["label"], roles["label"])}
      >
        {label}
      </label>
      {multiline === true ? (
        <textarea
          {...shared}
          rows={rows}
          {...(onFocus === undefined ? {} : { onFocus })}
          {...(onBlur === undefined ? {} : { onBlur })}
          {...(onKeyDown === undefined ? {} : { onKeyDown })}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      ) : (
        <input
          {...shared}
          type={secret === true ? "password" : "text"}
          // §23.3's three properties on the key field. Written as literal JSX
          // props so the set is visible at a glance rather than hidden in a
          // conditional spread. NOTE for anyone asserting on rendered markup:
          // React 18's `renderToStaticMarkup` emits `autoComplete` in its JSX
          // casing (it lowercases `spellCheck` but not this one), while the
          // browser DOM carries the lowercase attribute a password manager
          // reads. The unit test compares case-insensitively for that reason,
          // and the e2e reads the real attribute off the real element.
          autoComplete={secret === true ? "off" : undefined}
          autoCorrect={secret === true ? "off" : undefined}
          spellCheck={secret === true ? false : undefined}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      )}
      {invalid === undefined ? null : (
        <p id={messageId} className={cx(styles["invalid"], roles["body"])}>
          {invalid}
        </p>
      )}
    </div>
  );
}

export type SliderProps = FieldFrame & {
  readonly value: number;
  readonly min: number;
  readonly max: number;
  readonly step: number;
  readonly onChange: (value: number) => void;
  /**
   * Fires on range release (pointer/key up), not during drag. §10's PARAMS
   * rebuild is "debounced 300 ms **on release**, not during drag"; explode
   * still writes on every `onChange`.
   */
  readonly onRelease?: ((value: number) => void) | undefined;
  /** Digits the editable readout shows. Presentation, never a rounding of data. */
  readonly precision?: number | undefined;
  /**
   * §10 / G5.3: PARAMS sliders must **not** clamp. A typed out-of-bounds
   * value is sent so the server can reject it. Explode (`0..1`) still clamps
   * — that is a screen-space quantity, not a parameter.
   */
  readonly clamp?: boolean | undefined;
  readonly disabled?: boolean | undefined;
  readonly trailing?: ReactNode | undefined;
} & DataAttributes;

export function Slider(props: SliderProps): React.JSX.Element {
  const {
    label,
    hideLabel,
    invalid,
    className,
    value,
    min,
    max,
    step,
    onChange,
    onRelease,
    precision = 2,
    clamp = true,
    disabled,
    trailing,
  } = props;
  const id = useId();
  const messageId = `${id}-message`;

  const parse = (raw: string): number | null => {
    const next = Number(raw);
    if (!Number.isFinite(next)) return null;
    return clamp === true ? Math.min(max, Math.max(min, next)) : next;
  };

  const commit = (raw: string): void => {
    const next = parse(raw);
    if (next === null) return;
    onChange(next);
  };

  const release = (raw: string): void => {
    const next = parse(raw);
    if (next === null) return;
    onRelease?.(next);
  };

  return (
    <div className={cx(styles["slider"], className)}>
      <label
        htmlFor={id}
        className={cx(hideLabel === true ? styles["hidden"] : styles["label"], roles["label"])}
      >
        {label}
      </label>
      <input
        id={id}
        type="range"
        className={styles["range"]}
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled === true}
        aria-invalid={invalid !== undefined}
        {...(invalid === undefined ? {} : { "aria-describedby": messageId })}
        onChange={(event) => {
          commit(event.target.value);
        }}
        onPointerUp={(event) => {
          release(event.currentTarget.value);
        }}
        onKeyUp={(event) => {
          release(event.currentTarget.value);
        }}
        {...dataProps(props)}
      />
      {/* §4.7: the readout is editable. A slider whose value cannot be typed is
          not a parameter control. §10: the number input is how G5.3 types an
          out-of-bounds value; min/max stay off it when `clamp` is false. */}
      <input
        type="number"
        className={cx(styles["readout"], roles["data"])}
        aria-label={label}
        {...(clamp === true ? { min, max } : {})}
        step={step}
        value={Number.isFinite(value) ? value.toFixed(precision) : ""}
        disabled={disabled === true}
        onChange={(event) => {
          commit(event.target.value);
          release(event.target.value);
        }}
      />
      {trailing ?? null}
      {invalid === undefined ? null : (
        <p id={messageId} className={cx(styles["invalid"], roles["body"])}>
          {invalid}
        </p>
      )}
    </div>
  );
}

export type SelectProps = FieldFrame & {
  readonly value: string;
  readonly options: readonly string[];
  readonly onChange: (value: string) => void;
} & DataAttributes;

export function Select(props: SelectProps): React.JSX.Element {
  const { label, hideLabel, className, value, options, onChange } = props;
  const id = useId();
  return (
    <div className={cx(styles["field"], styles["inline"], className)}>
      <label
        htmlFor={id}
        className={cx(hideLabel === true ? styles["hidden"] : styles["label"], roles["label"])}
      >
        {label}
      </label>
      <select
        id={id}
        className={cx(styles["select"], roles["data"])}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        {...dataProps(props)}
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </div>
  );
}
