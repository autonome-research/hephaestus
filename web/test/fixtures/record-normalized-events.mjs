// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Recorder for `normalized-events.json` — the fixture the stream component tests
// run against (INTERFACE.md §7, §8, §14).
//
// WHY A RECORDER AND NOT A HAND-WRITTEN FIXTURE. Every claim these tests make is
// a claim about **what the engine emits**: that a historical `tool_result`
// carries `isError` (§7.2's NEW WORK, landed in `agent/src/session/history.ts`),
// that a historical `image` payload is `{mimeType}` with no bytes, that a
// historical event's identity is `(session_id, ordinal)` while a live one's is
// `(run_id, seq)`, and that a >250-event transcript really does page. A fixture
// typed by hand would test the fixture author's belief about all four. This
// script runs the sidecar's own `normalizeEntries` / `pageHistory` /
// `normalizeLiveEvent` / `wireEvent` and writes down what they produced.
//
// HOW TO RE-RECORD:
//
//     pnpm --dir agent build
//     node web/test/fixtures/record-normalized-events.mjs
//
// The output is committed. Re-recording is its own change, carrying the
// normalization change that caused it — the same churn policy the render
// goldens and §2.8's event archive use. This fixture is **not** that archive:
// `tests/stage4/goldens/events/` is the G4.11 golden family over a real project
// and is server-side; this is a browser-side component fixture, and the two are
// separate on purpose (§14: "no browser-rendered golden family is created").
//
// The Pi entry shapes below are read structurally by `history.ts`'s own boundary
// adapter (`PiMessage` and friends), which is the same reading a persisted
// session file gets. Nothing here imports Pi.

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..", "..", "..");
const agentDist = join(repo, "agent", "dist", "session");

const { pageHistory, HISTORY_PAGE_SIZE } = await import(join(agentDist, "history.js"));
const { normalizeLiveEvent, wireEvent } = await import(join(agentDist, "live.js"));

const SESSION_ID = "sess-workspace-orchestrator";
const CHILD_SESSION_ID = "sess-workspace-quickedit";
const RUN_ID = "run-a1b2c3d4e5f6";

let entryOrdinal = 0;
const entry = (message) => ({
  id: `entry-${String(entryOrdinal++).padStart(4, "0")}`,
  type: "message",
  message,
});
const compaction = () => ({
  id: `entry-${String(entryOrdinal++).padStart(4, "0")}`,
  type: "compaction",
});

const assistant = (...content) => entry({ role: "assistant", content });
const text = (value) => ({ type: "text", text: value });
const thinking = (value) => ({ type: "thinking", thinking: value });
const toolCall = (id, name, args) => ({ type: "toolCall", id, name, arguments: args });
const toolResult = (toolCallId, toolName, content, isError) =>
  entry(
    isError === undefined
      ? { role: "toolResult", toolCallId, toolName, content }
      : { role: "toolResult", toolCallId, toolName, content, isError },
  );
const json = (value) => text(JSON.stringify(value));
const image = (mimeType) => ({ type: "image", mimeType, data: "aGVsbG8=" });

// ---------------------------------------------------------------------------
// the recorded session
// ---------------------------------------------------------------------------
//
// It exercises, in order, every branch the components have to render:
//
//  * a user prompt (omitted by normalization — the §8 absence);
//  * assistant text and a thinking block;
//  * `build_part` succeeding, with `isError: false` on the entry;
//  * `inspect_part` returning an image (history keeps `{mimeType}` only);
//  * `edit_part` FAILING with `isError: true`;
//  * a legacy `run_checks` entry with **no** `isError` field whose envelope says
//    `{"status": "error"}` — the §7.2 fallback branch;
//  * a legacy entry with neither signal and an unparseable body — the `unknown`
//    status and the degraded `data-field-state="unparsed"` chip at once;
//  * an `ask_user` call and its result — §7.3's reopened widget;
//  * a compaction (audit);
//  * enough filler to push the transcript past `HISTORY_PAGE_SIZE`.

const entries = [
  entry({ role: "user", content: "Add a 2 mm fillet to the top edge." }),
  assistant(text("Building the part first so the edge exists to fillet.")),
  assistant(thinking("The tread face is tagged, so the edge is addressable.")),
  assistant(toolCall("call-build-1", "build_part", { name: "bracket" })),
  toolResult(
    "call-build-1",
    "build_part",
    [
      json({
        status: "ok",
        artifact_ref: "art:build:0f1e2d3c",
        project_snapshot_ref: "art:snapshot:99aa88bb",
        geometry_count: 3,
        metrics: { volume_mm3: 12045.5 },
      }),
    ],
    false,
  ),
  assistant(toolCall("call-inspect-1", "inspect_part", { name: "bracket", views: ["iso"] })),
  toolResult(
    "call-inspect-1",
    "inspect_part",
    [
      json({
        status: "ok",
        source_artifact_ref: "art:build:0f1e2d3c",
        views: [{ view: "iso", bundle_ref: "art:bundle:aa11" }],
      }),
      image("image/png"),
    ],
    false,
  ),
  assistant(toolCall("call-edit-1", "edit_part", { name: "bracket", find: "x", replace: "y" })),
  toolResult(
    "call-edit-1",
    "edit_part",
    [json({ status: "error", code: "no_match", message: "find text not present" })],
    true,
  ),
  // Legacy entry: no `isError` field at all. §7.2's second source — the
  // serialized envelope's `status` — has to recover the failure.
  assistant(toolCall("call-checks-1", "run_checks", { name: "bracket" })),
  toolResult("call-checks-1", "run_checks", [
    json({ status: "error", code: "check_failed", message: "wall thickness below minimum" }),
  ]),
  // Legacy entry with neither signal AND an unreadable body: `isError` is `null`
  // (status `unknown`) and the chip degrades to zero `data-field` nodes.
  assistant(toolCall("call-legacy-1", "measure", { a: "f1", b: "f2" })),
  toolResult("call-legacy-1", "measure", [text("distance: 12.5 mm")]),
  assistant(
    toolCall("call-ask-1", "ask_user", {
      question: "Which edge should the fillet follow?",
      options: [
        { label: "Top outer edge", consequence: "Softens the visible rim; adds 0.4 g." },
        { label: "Inner bore edge", consequence: "Eases assembly; removes 0.2 g." },
        "Neither",
      ],
    }),
  ),
  toolResult(
    "call-ask-1",
    "ask_user",
    [json({ status: "ok", selection: "Top outer edge", recorded: ["REQ-fillet"] })],
    false,
  ),
  compaction(),
];

// Filler past the page size, so paging is exercised for real rather than by a
// page-size knob the route does not have (§2.8).
const FILLER = HISTORY_PAGE_SIZE + 40;
for (let i = 0; i < FILLER; i += 1) {
  entries.push(assistant(text(`step ${String(i)}`)));
}

// ---------------------------------------------------------------------------
// history pages, through the sidecar's own pager
// ---------------------------------------------------------------------------

const pages = [];
let cursor;
for (;;) {
  const page = pageHistory(entries, SESSION_ID, cursor === undefined ? {} : { cursor });
  pages.push({
    status: "ok",
    session_id: SESSION_ID,
    events: page.events.map(wireEvent),
    cursor: page.cursor,
    done: page.done,
  });
  if (page.done || page.cursor === null) break;
  cursor = page.cursor;
}

// A second, tiny session standing in for the quick-edit child a thread carries.
const childEntries = [
  assistant(text("Filleting the selected edge only.")),
  assistant(toolCall("call-child-1", "edit_part", { name: "bracket" })),
  toolResult("call-child-1", "edit_part", [json({ status: "ok", content_hash: "sha256:beef" })], false),
];
const childPage = pageHistory(childEntries, CHILD_SESSION_ID, {});

// ---------------------------------------------------------------------------
// live frames, through the sidecar's own live normalizer
// ---------------------------------------------------------------------------

let seq = 0;
const nextSeq = () => seq++;
const liveEvents = [
  { type: "message_update", assistantMessageEvent: { type: "text_delta", delta: "Rebuilding " } },
  { type: "message_update", assistantMessageEvent: { type: "text_delta", delta: "the bracket." } },
  { type: "message_update", assistantMessageEvent: { type: "thinking_delta", delta: "The fillet " } },
  { type: "message_update", assistantMessageEvent: { type: "thinking_delta", delta: "radius fits." } },
  {
    type: "tool_execution_start",
    toolCallId: "live-call-1",
    toolName: "build_part",
    args: { name: "bracket" },
  },
  { type: "tool_execution_update", toolCallId: "live-call-1", toolName: "build_part" },
  {
    type: "tool_execution_end",
    toolCallId: "live-call-1",
    toolName: "build_part",
    isError: false,
    result: {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            status: "ok",
            artifact_ref: "art:build:cafe1234",
            project_snapshot_ref: "art:snapshot:99aa88bb",
            geometry_count: 3,
          }),
        },
        { type: "image", mimeType: "image/png", data: "aGVsbG8=" },
      ],
    },
  },
];

const liveFrames = [];
for (const event of liveEvents) {
  for (const normalized of normalizeLiveEvent(event, RUN_ID, nextSeq)) {
    liveFrames.push({ ...wireEvent(normalized), session_id: SESSION_ID });
  }
}

// The two synthetic events `main.ts` mints around the `py.ask_user` suspension.
// They are not produced by any normalizer — that is precisely §2.7's point — so
// they are recorded here in the shape `main.ts` emits, with the same
// `q-<runId>-<n>` id it mints.
const questionId = `q-${RUN_ID}-0`;
liveFrames.push({
  run_id: RUN_ID,
  seq: nextSeq(),
  kind: "question",
  session_id: SESSION_ID,
  payload: {
    question_id: questionId,
    question: "Keep the 2 mm fillet or widen it?",
    options: [
      { label: "Keep 2 mm", consequence: "No mass change; matches the drawing." },
      { label: "Widen to 3 mm", consequence: "Removes 0.6 g and softens the rim." },
    ],
  },
});
liveFrames.push({
  run_id: RUN_ID,
  seq: nextSeq(),
  kind: "answer",
  session_id: SESSION_ID,
  payload: { question_id: questionId, answer: "Keep 2 mm" },
});
// The pump's terminal (`agent_bridge/events.py`): seq 2**62 so terminals sort
// last, and the backpressure path's id prefix, which is the only place that
// reason reaches the event stream.
liveFrames.push({
  run_id: RUN_ID,
  seq: 2 ** 62,
  kind: "terminal",
  session_id: SESSION_ID,
  payload: { state: "completed", terminal_id: `terminal:${RUN_ID}` },
});

const packageJson = JSON.parse(readFileSync(join(repo, "agent", "package.json"), "utf8"));

const fixture = {
  provenance: {
    recorded_by: "web/test/fixtures/record-normalized-events.mjs",
    normalizers: [
      "agent/src/session/history.ts::normalizeEntries",
      "agent/src/session/history.ts::pageHistory",
      "agent/src/session/live.ts::normalizeLiveEvent",
      "agent/src/session/live.ts::wireEvent",
    ],
    sidecar_package: `${packageJson.name}@${packageJson.version}`,
    history_page_size: HISTORY_PAGE_SIZE,
    note: "Re-recording is its own change, carrying the normalization change that caused it.",
  },
  session_id: SESSION_ID,
  child_session_id: CHILD_SESSION_ID,
  run_id: RUN_ID,
  pages,
  child_page: {
    status: "ok",
    session_id: CHILD_SESSION_ID,
    events: childPage.events.map(wireEvent),
    cursor: childPage.cursor,
    done: childPage.done,
  },
  live_frames: liveFrames,
};

writeFileSync(join(here, "normalized-events.json"), `${JSON.stringify(fixture, null, 2)}\n`, "utf8");
process.stdout.write(
  `recorded ${String(pages.length)} pages, ` +
    `${String(pages.reduce((n, p) => n + p.events.length, 0))} historical events, ` +
    `${String(liveFrames.length)} live frames\n`,
);
