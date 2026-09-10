// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `ChecksPanel` — the check report's badges (INTERFACE.md §6.3, §4.7).
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
// THE P0 THIS FILE SHIPPED, AND HOW IT IS NOW UNREPRESENTABLE. Line 59 used to
// write `data-badge` onto the `<li>` while `panels.module.css` selected
// `.badge[data-badge=…]` one element down, so `pass`, `fail` and `error`
// computed to the same colour, the same border and `::before { content: none }`
// — label-only status encoding at 11px in the panel whose entire job is "did my
// part pass". The `<Badge>` primitive emits the attribute **on the element it
// styles** and no call site can write it (§3.4, `heph/system-owns-status`).
//
// THE SELECTOR IS PRESERVED VERBATIM. `dom.spec.ts` reads `data-check` and
// `data-badge` **off the same node**, so `data-check` moves onto the badge
// rather than the badge's attribute moving onto the row. §3.14: "If a primitive
// cannot carry a selector, change the primitive, not the test."
//
// The vocabulary is closed at four and **`not_run` renders as its own visible
// state with the words "not run"**: §6.3 makes "silence never reads as a pass" a
// UI obligation, not only a tool one. `not_run` has no producer in the public
// clean-room fixture, so §3.14 puts its distinctness assertion in a COMPONENT
// test rather than in Playwright, where it would have nothing to render.

import type { ChecksDocument } from "../../api/types";
import { useChecks } from "../../api/queries";
import { copy } from "../../copy";
import {
  Badge,
  DataTable,
  EmptyState,
  Panel,
  PanelBody,
  PanelHeader,
  PanelNote,
  type BadgeStatus,
} from "../../system";
import { Fact } from "../Fact";
import { MeasuredAside, MeasuredText, measuredText, readMeasured } from "./MeasuredValue";
import { RefusalBanner } from "../RefusalBanner";
import { useWorkspace } from "../../state/react";
import styles from "./panels.module.css";

/** §6.3's four badge values are a subset of §4.7's six. The map is total. */
const BADGE_STATUS: Readonly<Record<string, BadgeStatus>> = {
  pass: "pass",
  fail: "fail",
  error: "error",
  not_run: "not_run",
};

export interface ChecksViewProps {
  readonly checks: ChecksDocument;
}

export function ChecksView({ checks }: ChecksViewProps): React.JSX.Element {
  // Order supplied verdicts for attention; never re-evaluate measured values.
  const priority = { error: 0, fail: 1, not_run: 2, pass: 3 };
  const names = Object.keys(checks.badges).sort((a, b) =>
    priority[checks.badges[a] ?? "not_run"] - priority[checks.badges[b] ?? "not_run"] || a.localeCompare(b));

  return (
    <Panel label={copy.checks.heading} data-panel="checks">
      <PanelHeader title={copy.checks.heading} level={3} />
      <PanelBody>
        {names.length > 0 ? <p data-checks-summary="">{(["error", "fail", "not_run", "pass"] as const)
          .filter(status => names.some(name => checks.badges[name] === status))
          .map(status => `${names.filter(name => checks.badges[name] === status).length} ${copy.checks.badge[status]}`).join(" · ")}</p> : null}
        {names.length === 0 ? (
          <EmptyState icon="check" title={copy.checks.emptyTitle} body={copy.checks.empty} />
        ) : (
          <ul className={styles["list"]}>
            {names.map((name) => {
              const badge = checks.badges[name] ?? "not_run";
              const result = checks.report.checks[name];
              return (
                <li key={name} className={styles["row"]}>
                  <Badge status={BADGE_STATUS[badge] ?? "not_run"} data-check={name}>
                    <Fact source="checks.badges[]" value={badge}>
                      {copy.checks.badge[badge]}
                    </Fact>
                  </Badge>
                  <span className={styles["rowValue"]}>
                    <span className={styles["name"]}>{name}</span>{" "}
                    {result === undefined ? (
                      <span className={styles["why"]}>{copy.checks.badgeExplain[badge]}</span>
                    ) : (
                      <span className={styles["muted"]}>
                        {copy.checks.measured}:{" "}
                        {/* §4.7: the message is the row value, the code is a
                            chip, the raw object is behind a disclosure — never
                            `JSON.stringify` at the weight of a formatted
                            measurement (J-web-stream-8). The `<Fact>` keeps its
                            literal source and its verbatim `data-value`; only
                            the glyphs inside it moved. */}
                        <Fact
                          source="checks.report.checks[].measured"
                          value={measuredText(result.measured)}
                          className={styles["mono"]}
                        >
                          <MeasuredText shape={readMeasured(result.measured)} />
                        </Fact>
                        <MeasuredAside
                          shape={readMeasured(result.measured)}
                          raw={measuredText(result.measured)}
                        />
                      </span>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        )}

        <PanelNote>{copy.checks.scope}</PanelNote>

        <details data-checks-provenance=""><summary>{copy.dfm.provenance}</summary>
        <DataTable
          rows={[
            {
              key: "bundle",
              label: copy.checks.bundle,
              value: (
                <Fact
                  source="checks.report.check_bundle_ref"
                  value={checks.report.check_bundle_ref}
                  mono
                />
              ),
            },
            {
              key: "generation",
              label: copy.checks.generation,
              value: (
                <Fact
                  source="checks.report.check_set_generation"
                  value={checks.report.check_set_generation}
                />
              ),
            },
          ]}
        />
        </details>
      </PanelBody>
    </Panel>
  );
}

export function ChecksPanel(): React.JSX.Element {
  const part = useWorkspace((s) => s.part);
  const checks = useChecks(part);

  if (part === null) {
    return <EmptyState icon="cube" title={copy.inspector.noPartTitle} body={copy.inspector.selectPart} />;
  }
  // A refused run is an answer with a name, and the panel shows the name. An
  // empty badge list under a spinner would read as "this project has no checks".
  if (checks.error !== null) return <RefusalBanner error={checks.error} />;
  if (checks.data === undefined) {
    return <PanelNote>{copy.absent.loading}</PanelNote>;
  }
  return <ChecksView checks={checks.data} />;
}
