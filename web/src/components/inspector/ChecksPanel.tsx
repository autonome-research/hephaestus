// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `ChecksPanel` — the check report's badges (INTERFACE.md §6.3).
//
// §6.3's TIGHTENING (binds G4.4): "The web client never runs checks."
// `GET /parts/{part}/checks` serializes the `CheckReport` through the same
// function `heph check --json` uses, and the e2e compares browser DOM badges
// against a subprocess `heph check --json`. One serializer, two callers.
//
// The badge is therefore **read, never derived**. `badges` is the server's own
// reading of the same report (`core/checks/report.py::badge`), and the mapping it
// encodes is an engine decision this panel must not re-make: a check whose
// `measured` carries an `error` (a predicate that raised) or an `unverifiable`
// (a bounded measurement the wall-clock ceiling cut short) badges `error`, never
// `fail` — a verdict the engine explicitly declined to give must not become one
// here. §1's closed list names "check verdicts" among the things the client may
// not compute, and a `result.pass ? "pass" : "fail"` in this file would be
// exactly that.
//
// The vocabulary is closed at four and **`not_run` renders as its own visible
// state with the words "not run"**: §6.3 makes "silence never reads as a pass" a
// UI obligation, not only a tool one. A `not_run` row has no report entry to
// show, and the panel says what is not known rather than showing a blank
// measurement.

import type { ChecksDocument } from "../../api/types";
import { useChecks } from "../../api/queries";
import { copy } from "../../copy";
import { Fact } from "../Fact";
import { RefusalBanner } from "../RefusalBanner";
import { useWorkspace } from "../../state/react";
import styles from "./panels.module.css";

/** A measured value as the report carries it, serialized for display. */
function measuredText(measured: unknown): string {
  return measured === undefined ? "" : JSON.stringify(measured);
}

export interface ChecksViewProps {
  readonly checks: ChecksDocument;
}

export function ChecksView({ checks }: ChecksViewProps): React.JSX.Element {
  const names = Object.keys(checks.badges).sort();

  return (
    <section className={styles["panel"]} aria-label={copy.checks.heading} data-panel="checks">
      <h3 className={styles["heading"]}>{copy.checks.heading}</h3>

      {names.length === 0 ? (
        <p className={styles["absent"]}>{copy.checks.empty}</p>
      ) : (
        <ul className={styles["list"]}>
          {names.map((name) => {
            const badge = checks.badges[name] ?? "not_run";
            const result = checks.report.checks[name];
            return (
              <li key={name} className={styles["row"]} data-check={name} data-badge={badge}>
                <Fact source="checks.badges[]" value={badge} className={styles["badge"]}>
                  {copy.checks.badge[badge]}
                </Fact>
                <span className={styles["rowValue"]}>
                  <span className={styles["mono"]}>{name}</span>
                  {result === undefined ? (
                    <span className={styles["why"]}> {copy.checks.badgeExplain[badge]}</span>
                  ) : (
                    <span className={styles["dim"]}>
                      {" "}
                      {copy.checks.measured}:{" "}
                      <Fact
                        source="checks.report.checks[].measured"
                        value={measuredText(result.measured)}
                        className={styles["mono"]}
                      />
                    </span>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      )}

      <p className={styles["note"]}>{copy.checks.scope}</p>

      <dl className={styles["pairs"]}>
        <div className={styles["pairRow"]}>
          <dt>{copy.checks.bundle}</dt>
          <dd>
            <Fact
              source="checks.report.check_bundle_ref"
              value={checks.report.check_bundle_ref}
              className={styles["mono"]}
              mono
            />
          </dd>
        </div>
        <div className={styles["pairRow"]}>
          <dt>{copy.checks.generation}</dt>
          <dd>
            <Fact
              source="checks.report.check_set_generation"
              value={checks.report.check_set_generation}
            />
          </dd>
        </div>
      </dl>
    </section>
  );
}

export function ChecksPanel(): React.JSX.Element {
  const part = useWorkspace((s) => s.part);
  const checks = useChecks(part);

  if (part === null) return <p className={styles["absent"]}>{copy.inspector.selectPart}</p>;
  // A refused run is an answer with a name, and the panel shows the name. An
  // empty badge list under a spinner would read as "this project has no checks".
  if (checks.error !== null) {
    return (
      <div className={styles["panel"]}>
        <RefusalBanner error={checks.error} />
      </div>
    );
  }
  if (checks.data === undefined) return <p className={styles["absent"]}>{copy.absent.loading}</p>;
  return <ChecksView checks={checks.data} />;
}
