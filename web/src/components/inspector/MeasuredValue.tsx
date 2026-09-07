// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The visible half of a `measured` value (INTERFACE.md §4.7, §6.3, §6.4).
//
// §4.7 carries a clause written AS A KNOWN DEFECT — "a reading surface never
// receives `JSON.stringify` output" — which names the Checks panel's measured
// row, explains that the actual information is buried inside JSON punctuation,
// and prescribes the shape: **the message renders as the row value, the code as
// a chip, and the raw object goes behind a disclosure.** The clause was written
// and the implementation never followed (J-web-stream-8), so this is that shape,
// in one place, because the Checks panel and the DFM panel had the identical
// defect one layer apart and fixing one would have left the other.
//
// THE MACHINE-READABLE HALF IS UNCHANGED. `<Fact>`'s `data-value` still carries
// `JSON.stringify(measured)` verbatim — that serialization is legitimate and is
// what the e2e's DOM-vs-JSON comparison, the archive matcher and the audit
// harness read. The defect was never that the value was serialized; it was that
// the same serialization was ALSO the human text.
//
// **Two components, not one, and the split is `heph/no-derived-fact`'s.** A
// single `<MeasuredValue source={…}>` would have to pass its `source` prop into
// `<Fact>`, and a computed attribution "cannot be reviewed or asserted on" — the
// lint rejects it, correctly. So the caller keeps its literal `<Fact source>` and
// this file supplies what goes *inside* it (`MeasuredText`) and what stands
// *beside* it (`MeasuredAside`): the code chip and the disclosure are outside the
// attributed value on purpose, since §4.7 is explicit that the code is never
// inside the sentence.
//
// Four shapes, and the last is honest about not being one:
//
//   scalar / numeric triple   `format.ts::formatValue` renders it, as today
//   error envelope            message + code chip + raw behind a disclosure
//   flat fact map             `key value` pairs, in the server's own order
//   anything else             one sentence + the disclosure, never stringified

import {
  formatValue,
  readErrorEnvelope,
  readFactMap,
  type ErrorEnvelope,
  type FactPair,
} from "../../system";
import { Chip } from "../../system";
import { copy } from "../../copy";
import styles from "./panels.module.css";

/** A measured value as the report carries it, serialized for `data-value`. */
export function measuredText(measured: unknown): string {
  return measured === undefined || measured === null ? "" : JSON.stringify(measured);
}

/**
 * Which of §4.7's four renderings a measured value takes.
 *
 * A pure function, decided once and handed to both halves, so the text and the
 * aside beside it can never disagree about what the value is.
 */
export type MeasuredShape =
  | { readonly kind: "scalar"; readonly text: string }
  | { readonly kind: "error"; readonly envelope: ErrorEnvelope }
  | { readonly kind: "facts"; readonly facts: readonly FactPair[] }
  | { readonly kind: "opaque" };

export function readMeasured(measured: unknown): MeasuredShape {
  const scalar = formatValue(measured);
  if (scalar !== null) return { kind: "scalar", text: scalar };
  const envelope = readErrorEnvelope(measured);
  if (envelope !== null) return { kind: "error", envelope };
  const facts = readFactMap(measured);
  if (facts !== null) return { kind: "facts", facts };
  return { kind: "opaque" };
}

/** The human text of a measured value — the `<Fact>`'s children. */
export function MeasuredText({ shape }: { readonly shape: MeasuredShape }): React.JSX.Element {
  switch (shape.kind) {
    case "scalar":
      return <>{shape.text}</>;
    case "error":
      // The MESSAGE is the row value. It is the sentence the engine already
      // composed — "unknown part 'lid' in selector 'lid/part'; known parts: …"
      // — and it used to sit about 120 characters into a JSON object rendered
      // at the same weight as a passing check's formatted number.
      return <>{shape.envelope.message}</>;
    case "facts":
      return (
        // Label/value pairs in the SERVER's order. A fact map's order is the
        // rule's, and re-sorting it here would be the client asserting a
        // ranking the engine did not report (§1).
        <span className={styles["measuredFacts"]} data-measured-facts="">
          {shape.facts.map((pair) => (
            <span key={pair.key} className={styles["measuredFact"]} data-measured-fact={pair.key}>
              <span className={styles["measuredFactKey"]}>{pair.key}</span>{" "}
              <span className={styles["measuredFactValue"]}>{pair.value}</span>
            </span>
          ))}
        </span>
      );
    case "opaque":
      // §4.4: a state that exists for a reason reads as designed; the same
      // state with its content missing reads as a bug. The disclosure beside
      // this sentence still carries every byte.
      return <>{copy.inspector.measuredUnreadable}</>;
  }
}

/**
 * What stands beside the attributed value: the code chip and the disclosure.
 *
 * Renders nothing for a scalar, which is the common case and needs neither.
 */
export function MeasuredAside({
  shape,
  raw,
}: {
  readonly shape: MeasuredShape;
  readonly raw: string;
}): React.JSX.Element | null {
  if (shape.kind === "scalar" || shape.kind === "facts") return null;
  return (
    <>
      {shape.kind === "error" ? (
        <>
          {" "}
          <Chip tone="code" data-measured-code={shape.envelope.code}>
            {shape.envelope.code}
          </Chip>
        </>
      ) : null}
      <details className={styles["measuredRaw"]} data-measured-raw="">
        <summary>{copy.inspector.measuredRaw}</summary>
        <pre className={styles["measuredRawBody"]}>{raw}</pre>
      </details>
    </>
  );
}
