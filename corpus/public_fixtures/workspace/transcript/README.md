<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# `transcript/` — the committed session history (G4.9, G4.10, G4.11)

`INTERFACE.md` §14 makes "a committed >250-event normalized transcript with at
least one quick-edit child" a fixture requirement. This is it.

| Path | What it is |
|---|---|
| `sessions/sess-workspace-orchestrator/*.jsonl` | the parent session, as the sidecar wrote it |
| `sessions/sess-workspace-quickedit/*.jsonl` | the quick-edit child |
| `threads.json` | the §2.8 `tp_session_edges` row linking the two |

Recorded by `scripts/record_workspace_transcript.py` against a **real** sidecar,
a **real** `BridgeRuntime` wired exactly as `heph serve --web` wires it, and a
scripted provider. Re-recording is its own change and carries the normalization
or fixture change that caused it.

## Three things that are load-bearing

**The session ids are fixed.** §2.8 puts G4.11's archive over
`(session_id, ordinal)` pairs. A server-minted UUID would change the session
half every run and the archive would record identities the reopened transcript
can never re-emit. So the transcript is recorded under two fixed names and
reopened under the same two, through
`POST /sessions {session_id, resume: true}`.

**These are Pi session files, and nothing outside the sidecar parses them.**
They are copied into `.heph/sessions/` and handed back to the sidecar, which
reads them with its own reader. The one edit made on the way in is the header
record's `cwd`, which named the recorder's temporary directory; every message
record is byte-for-byte what was written. `STAGE2_DIGEST` §2's rule — nothing
outside the sidecar parses Pi JSONL — is respected: the materializer rewrites a
single declared key on a single record and never interprets a message.

**The edge is a row, not a table.** `tp_session_edges` lives in `state.db`,
which is inside the ignored `.heph/`, so it cannot be committed. `threads.json`
carries the row and
`hephaestus.testing.workspace_fixture.record_transcript_edges` writes it through
`SessionEdgeStore` — the same class `SessionService.spawn_quick_edit` and the
delegation WAL write through. Its `source_artifact_ref` and `selection_id` are
real: they come from the selection table the recorded build's own bundle
published, resolved against the `tread_top` tag.

## What the recorded session contains

One realistic working turn — `read_part`, `build_part`, `inspect_part` (which
returns an **image**, so §7.3's metadata-only historical placeholder has
something to render), `run_checks`, `run_dfm` (three real `laser_cut`
violations), and an `edit_part` that **fails** on a stale `expected_hash` — then
130 cheap `list_project_checks` turns whose only job is length, because §2.8
forbids a page-size knob and "multi-page" is therefore a property of the
transcript itself.

The failing `edit_part` is not decoration. Without a tool call that genuinely
failed, the archive could not exercise the `isError` normalization §19 item 13
added, and a reopened transcript that renders a failed call as `ok` would pass
every other assertion.

## Deviation found while recording, stated here because it bounds a §7.2 claim

§7.2 pins the parse as total: "every dispatched tool result serializes as a
**single canonical-JSON text block** — which it does today". That holds for a
**successful** dispatch. A tool *error* comes back as a plain sentence
(`invalid_part: part 'tread' has no current successful build to inspect`), not
as JSON, so a chip over a refused call takes §7.2's own named failure branch:
zero `data-field` nodes, `data-field-state="unparsed"`, and the reason visible.
That branch exists precisely for this and the panel already implements it; what
is not true is the unqualified "the parse is total". Recorded rather than
silently relied on.
