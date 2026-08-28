# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Record the Gate G4 fixture transcript, its event archive, and its goldens.

``INTERFACE.md`` §14 makes three things fixture requirements that are *recorded*
rather than authored: a **committed >250-event normalized transcript with at
least one quick-edit child** (G4.9, G4.10, G4.11), the **normalized-event
archive golden** over that transcript's `(session_id, ordinal)` identities
(§2.8), and a **server-rendered section golden** for G4.7 (§5.3). This script
produces all three from one run against
``corpus/public_fixtures/workspace/``.

Run it from the repository root::

    uv run python scripts/record_workspace_transcript.py

RECORDED, NOT AUTHORED — and the distinction is the point. Every claim the Stage
4 gate makes about a reopened transcript is a claim about **what the sidecar's
own normalizer emits**: that a failed tool call reopens as ``isError: true``
(§19 item 13), that a historical ``image`` payload keeps ``{mimeType}`` and no
bytes, that identity restarts at 0 per session, and that >250 events really do
page. A hand-typed transcript would test the author's belief about all four.
This script drives the **real** Node sidecar against a **real** project through
the **real** ``BridgeRuntime``, with a scripted model standing in only for the
provider, and writes down what came back.

WHAT IS SCRIPTED AND WHAT IS REAL. The fake provider decides which tool the
agent calls next and what prose it writes. Everything else is the product:
``build_part`` really builds, ``run_dfm`` really evaluates the shipped
``laser_cut`` pack, ``edit_part`` really refuses a stale hash, and the session
file is the one Pi wrote.

RE-RECORDING IS ITS OWN CHANGE. The outputs are committed; re-recording carries
the normalization or fixture change that caused it, on the same churn policy the
render goldens use (``verification.md`` Tier 2, ``heph goldens --update``).

THE SESSION IDS ARE FIXED ON PURPOSE. §2.8 puts G4.11's archive over
``(session_id, ordinal)`` pairs. A server-minted UUID would make every archived
identity unmatchable on the next run, so the transcript is recorded under the
two names ``hephaestus.testing.workspace_fixture`` declares and reopened under
the same two.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent

#: Filler turns exist because §2.8 forbids a page-size knob: "multi-page" is a
#: property of the transcript's LENGTH, so the fixture has to be genuinely long.
#: Each filler turn is one cheap tool call plus its result — two normalized
#: events — so the count below clears 250 with the rich prompt's contribution to
#: spare, and page 2 is non-empty rather than a single stray event.
FILLER_TURNS = 130

#: How many filler turns ride inside one `prompt` call. Every turn is a model
#: round trip either way; batching them keeps the number of *bridge* round trips
#: (admission, WAL, lease heartbeat) proportionate to a real session.
TURNS_PER_PROMPT = 26


def main() -> int:
    from hephaestus.testing.sidecar import build_agent_dist
    from hephaestus.testing.workspace_fixture import fixture_source

    if not fixture_source().is_dir():
        print(f"fixture missing: {fixture_source()}", file=sys.stderr)
        return 2
    built = build_agent_dist()
    if built is None:
        print("node/pnpm unavailable: the recorder needs the packaged sidecar", file=sys.stderr)
        return 2
    scratch = Path(tempfile.mkdtemp(prefix="heph-g4-record-"))
    try:
        record(scratch / "workspace", built[0])
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print("done.")
    return 0


def record(project_root: Path, dist_main: Path) -> None:
    from hephaestus.agent_bridge.app import BridgeRuntime
    from hephaestus.http.runtime import WorkspaceRuntime
    from hephaestus.testing.fake_openai import start_fake_openai
    from hephaestus.testing.workspace_fixture import (
        ORCHESTRATOR_SESSION_ID,
        QUICK_EDIT_SESSION_ID,
        SUBJECT_PART,
        materialize_workspace_fixture,
    )

    print(f"materializing the fixture at {project_root}")
    materialize_workspace_fixture(project_root, git=False, transcript=False)

    # The SAME wiring `heph serve --web` uses (`http/serve.py::_attach_agent`):
    # one store, one CadOps, one dispatcher, injected into the bridge. Recording
    # through a second, differently-configured stack would produce a transcript
    # the served workspace could not have produced — most visibly, a default
    # `BridgeRuntime` runs the unsafe-local backend, which refuses to execute
    # registry DFM content at all, so the recorded `run_dfm` would be a sandbox
    # refusal rather than the pack's findings.
    workspace = WorkspaceRuntime.open(project_root, token="record", serve_mode=True)
    fake = start_fake_openai([])
    runtime = BridgeRuntime(
        project_root=project_root,
        providers=[fake.provider_spec()],
        dist_main=dist_main,
        store=workspace.store,
        project_store=workspace.project_store,
        cad=workspace.cad,
        dispatcher=workspace.dispatcher,
    )
    runtime.start()
    try:
        orchestrator = runtime.create_session("orchestrator", session_id=ORCHESTRATOR_SESSION_ID)
        drive_opening_turn(runtime, fake, orchestrator)
        drive_filler(runtime, fake, orchestrator)
        child = runtime.create_session(
            "quick_edit", part=SUBJECT_PART, session_id=QUICK_EDIT_SESSION_ID
        )
        drive_quick_edit(runtime, fake, child)
        pages = collect_history(runtime, orchestrator)
        child_pages = collect_history(runtime, child)
    finally:
        runtime.close()
        fake.close()
        workspace.close()

    total = sum(len(page["events"]) for page in pages)
    print(f"orchestrator: {len(pages)} page(s), {total} normalized events")
    if total <= 250:
        raise SystemExit(
            f"transcript is {total} events: §14 requires more than 250 so the history "
            f"route genuinely pages. Raise FILLER_TURNS."
        )
    stage_transcript(project_root)
    write_threads(project_root)
    write_archive(pages, child_pages, orchestrator, child)
    write_section_golden()


# ---------------------------------------------------------------------------
# the scripted session
# ---------------------------------------------------------------------------


def drive_opening_turn(runtime: Any, fake: Any, session_id: str) -> None:
    """One realistic working turn: read, build, look, check, run DFM, edit, miss.

    It is the turn every chip assertion is about, so it deliberately contains
    three shapes a shorter turn would not reach:

    * a call that returns an **image** (``inspect_part``) — §7.3's reopened image
      placeholder needs something to be a placeholder for;
    * a call that returns a **discriminated refusal** (``edit_part`` on a stale
      hash) — a CAS conflict is a *result*, ``isError: false``, and §9.3's
      conflict payload is what a chip renders for it;
    * a call that genuinely **fails** (``inspect_part`` on the riser, which the
      agent has not built yet) — the only shape that produces ``isError: true``,
      which is the whole reason §19 item 13 exists. The *unbuilt-part* refusal is
      chosen over a missing-part one because the missing-part message names an
      absolute path, and a committed archive must not carry the recorder's
      temporary directory: it would differ on every re-recording and turn the
      churn policy into noise.
    """
    from hephaestus.testing.stream_assertions import last_tool_result, text, tool_call
    from hephaestus.testing.workspace_fixture import SUBJECT_PART

    seen: dict[str, Any] = {}

    def after_read(info: Any) -> dict[str, Any]:
        seen["read"] = last_tool_result(info)
        return tool_call("build_part", {"name": SUBJECT_PART}, "c-build")

    def after_build(info: Any) -> dict[str, Any]:
        built = last_tool_result(info)
        seen["build"] = built
        return tool_call("inspect_part", {"name": SUBJECT_PART, "views": ["iso"]}, "c-inspect")

    def after_inspect(info: Any) -> dict[str, Any]:
        seen["inspect"] = last_tool_result(info)
        return tool_call("run_checks", {"name": SUBJECT_PART}, "c-checks")

    def after_checks(info: Any) -> dict[str, Any]:
        seen["checks"] = last_tool_result(info)
        return tool_call("run_dfm", {"name": SUBJECT_PART}, "c-dfm")

    def after_dfm(info: Any) -> dict[str, Any]:
        seen["dfm"] = last_tool_result(info)
        # A deliberately stale hash: the CAS refuses and the chip reopens as
        # `error`. `expected_hash` is a hash of nothing, which is exactly the
        # shape a model that lost track of the file presents.
        return tool_call(
            "edit_part",
            {
                "name": SUBJECT_PART,
                "expected_hash": "sha256:" + "0" * 64,
                "old_str": "notch_radius",
                "new_str": "corner_radius",
            },
            "c-edit",
        )

    def after_edit(info: Any) -> dict[str, Any]:
        seen["edit"] = last_tool_result(info)
        # A call that genuinely FAILS at the protocol level. The stale-hash
        # `edit_part` above is not one: a CAS conflict is a *discriminated
        # result* (`applied: false` + a conflict record), which §2.4 keeps at 200
        # and which the sidecar reports with `isError: false` — correctly, since
        # the tool answered. Without a real failure the archive could not
        # exercise §19 item 13's `isError` branch at all.
        return tool_call("inspect_part", {"name": "riser", "views": ["iso"]}, "c-missing")

    def after_missing(info: Any) -> dict[str, Any]:
        seen["missing"] = last_tool_result(info)
        return text(
            "The tread builds. Three laser_cut rules are violated: the drain bore is "
            "below the minimum cut feature, the notch corners are tighter than the beam "
            "radius, and 5.5 mm is not a stocked sheet thickness."
        )

    fake.set_script(
        [
            tool_call("read_part", {"name": SUBJECT_PART}, "c-read"),
            after_read,
            after_build,
            after_inspect,
            after_checks,
            after_dfm,
            after_edit,
            after_missing,
        ]
    )
    result = runtime.prompt(
        session_id, "Open the tread and tell me what is wrong with it for laser cutting."
    )
    fake.raise_script_error()
    print(f"  opening turn: {result.status}, {len(result.events)} live events")
    for name in ("read", "build", "inspect", "checks", "dfm", "edit", "missing"):
        outcome = seen.get(name)
        summary = "MISSING" if outcome is None else json.dumps(outcome)[:220]
        print(f"    {name}: {summary}")
    if seen.get("edit", {}).get("applied") is not False:
        raise SystemExit("the stale-hash edit_part was expected to report a CAS conflict")
    if "_text" not in seen.get("missing", {}):
        raise SystemExit(
            "inspect_part on the unbuilt riser was expected to FAIL; without a failed "
            "tool call the archive cannot exercise §7.2's isError branch"
        )


def drive_filler(runtime: Any, fake: Any, session_id: str) -> None:
    """Length, honestly come by: real tool calls whose results are small.

    ``list_project_checks`` is chosen because it takes no arguments, touches no
    geometry and returns a short document — so a 130-turn transcript is a
    transcript, not a 500 KB fixture.
    """
    from hephaestus.testing.stream_assertions import text, tool_call

    done = 0
    batch = 0
    while done < FILLER_TURNS:
        count = min(TURNS_PER_PROMPT, FILLER_TURNS - done)
        script: list[Any] = [
            tool_call("list_project_checks", {}, f"c-scan-{done + i}") for i in range(count)
        ]
        script.append(text(f"Check sweep {batch + 1} complete; the check set is unchanged."))
        fake.set_script(script)
        runtime.prompt(session_id, f"Re-read the project's check set (sweep {batch + 1}).")
        fake.raise_script_error()
        done += count
        batch += 1
    print(f"  filler: {done} tool turns across {batch} prompts")


def drive_quick_edit(runtime: Any, fake: Any, session_id: str) -> None:
    """The child session a quick edit spawns: short, scoped, and its own file."""
    from hephaestus.testing.stream_assertions import last_tool_result, text, tool_call
    from hephaestus.testing.workspace_fixture import SUBJECT_PART

    def after_read(info: Any) -> dict[str, Any]:
        last_tool_result(info)
        return text(
            "The notch corners are rounded 0.3 mm. Widening them to 0.5 mm clears the "
            "beam-radius rule without moving the notch."
        )

    fake.set_script([tool_call("read_part", {"name": SUBJECT_PART}, "c-child-read"), after_read])
    runtime.prompt(session_id, "Only the notch corners: what would clear the radius rule?")
    fake.raise_script_error()
    print("  quick-edit child recorded")


def collect_history(runtime: Any, session_id: str) -> list[dict[str, Any]]:
    """Every page of one session's history, cursor forwarded verbatim (§2.8)."""
    pages: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        page = runtime.history_page(session_id, cursor)
        pages.append(page)
        if page.get("done") or page.get("cursor") is None:
            return pages
        cursor = str(page["cursor"])


# ---------------------------------------------------------------------------
# the committed outputs
# ---------------------------------------------------------------------------


def stage_transcript(project_root: Path) -> None:
    """Copy the sidecar's own session files into the committed fixture.

    ``.heph/`` is ignored repo-wide, so the transcript is committed one level up
    under ``transcript/sessions/`` and replayed back into ``.heph/sessions/`` by
    :func:`hephaestus.testing.workspace_fixture.install_transcript`.
    """
    from hephaestus.testing.workspace_fixture import fixture_source

    source = project_root / ".heph" / "sessions"
    target = fixture_source() / "transcript" / "sessions"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for session_dir in sorted(source.iterdir()):
        if not session_dir.is_dir():
            continue
        shutil.copytree(session_dir, target / session_dir.name)
        size = sum(f.stat().st_size for f in (target / session_dir.name).glob("*"))
        print(f"  staged {session_dir.name} ({size} bytes)")


def write_threads(project_root: Path) -> None:
    """``transcript/threads.json`` — §2.8's edge, over REAL engine values.

    ``SessionService.spawn_quick_edit`` is the production writer and it needs a
    concrete ``SelectionResolver``, which is Stage 5 work (§19 item 8). What is
    available today, and what the row must not fake, is the *content*: the
    ``source_artifact_ref`` is the tread's built artifact and the ``selection_id``
    is an entry in the selection table that artifact's own bundle published. The
    row is written into ``state.db`` through :class:`SessionEdgeStore` — the
    production writer's own class — at materialization time.
    """
    from hephaestus.core.render.bundle import resolve_selection
    from hephaestus.http.runtime import WorkspaceRuntime
    from hephaestus.testing.workspace_fixture import (
        ORCHESTRATOR_SESSION_ID,
        QUICK_EDIT_SESSION_ID,
        SUBJECT_PART,
        TAGGED_FACE,
        fixture_source,
    )

    runtime = WorkspaceRuntime.open(project_root, token="record", serve_mode=False)
    try:
        current = runtime.cad.current_build(SUBJECT_PART)
        if current is None or current.artifact_ref is None:
            raise SystemExit(
                "the tread has no current build; the scripted session's build_part turn "
                "did not publish, so there is no artifact for the edge to name"
            )
        published = runtime.cad.publish_gltf(current.artifact_ref)
        resolution = resolve_selection(runtime.store, published.bundle_ref)
        tagged = next(
            (i for i, entry in resolution.entries.items() if entry.tag == TAGGED_FACE),
            None,
        )
        if tagged is None:
            raise SystemExit(
                f"the {TAGGED_FACE!r} tag is not in the tread's selection table; the "
                f"quick-edit edge would have to invent a selection id"
            )
        origin = {
            "part": SUBJECT_PART,
            "source_artifact_ref": resolution.source_artifact_ref,
            "selection_id": tagged,
            "provenance": {"state": "tagged", "tag": TAGGED_FACE},
            # §12.5's `selection-crop` kind is named new work; a crop is a named
            # absence here rather than a fabricated ref.
            "crop_artifact_ref": None,
        }
    finally:
        runtime.close()

    payload = {
        "note": (
            "Session edges for the workspace fixture (INTERFACE.md §2.8). Replayed into "
            "state.db by hephaestus.testing.workspace_fixture.record_transcript_edges, "
            "through the same SessionEdgeStore the two production writers use."
        ),
        "edges": [
            {
                "child_session_id": QUICK_EDIT_SESSION_ID,
                "parent_session_id": ORCHESTRATOR_SESSION_ID,
                "kind": "quick_edit",
                "origin": origin,
            }
        ],
    }
    path = fixture_source() / "transcript" / "threads.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"  {path.relative_to(REPO)} (selection_id {origin['selection_id']})")


def write_archive(
    pages: list[dict[str, Any]],
    child_pages: list[dict[str, Any]],
    session_id: str,
    child_session_id: str,
) -> None:
    """``tests/stage4/goldens/events/workspace.jsonl`` — G4.11's archive.

    One JSON object per normalized historical event, in page order, each carrying
    the **historical** identity ``<session_id>@<ordinal>``. Live identities are
    deliberately absent: §2.8 settles that the archive is over the pair a
    *reopened* transcript emits, and archiving ``(run_id, seq)`` would have
    archived identities the reopened panel never produces.
    """
    from hephaestus.http.event_identity import historical_event_id
    from hephaestus.testing.workspace_fixture import (
        EVENT_ARCHIVE,
        EVENT_ARCHIVE_PROVENANCE,
        stage4_goldens,
    )

    def rows(all_pages: list[dict[str, Any]], sid: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for index, page in enumerate(all_pages):
            for event in page["events"]:
                record: dict[str, Any] = {
                    "event_id": historical_event_id(sid, int(event["seq"])),
                    "session_id": sid,
                    "page": index,
                    "seq": int(event["seq"]),
                    "kind": event["kind"],
                }
                if "tool_call_id" in event:
                    record["tool_call_id"] = event["tool_call_id"]
                if "payload" in event:
                    record["payload"] = event["payload"]
                out.append(record)
        return out

    archive = rows(pages, session_id) + rows(child_pages, child_session_id)
    path = stage4_goldens() / EVENT_ARCHIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in archive:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    agent_pkg = json.loads((REPO / "agent" / "package.json").read_text(encoding="utf-8"))
    provenance = {
        "archive": EVENT_ARCHIVE,
        "fixture": "corpus/public_fixtures/workspace",
        "recorded_by": "scripts/record_workspace_transcript.py",
        "identity_namespace": "historical (session_id, ordinal) — INTERFACE.md §2.8",
        "normalizers": [
            "agent/src/session/history.ts::normalizeEntries",
            "agent/src/session/history.ts::pageHistory",
            "agent/src/session/live.ts::wireEvent",
        ],
        "sidecar_package": f"{agent_pkg['name']}@{agent_pkg['version']}",
        "sessions": {
            session_id: {"pages": len(pages), "events": sum(len(p["events"]) for p in pages)},
            child_session_id: {
                "pages": len(child_pages),
                "events": sum(len(p["events"]) for p in child_pages),
            },
        },
        "churn_policy": (
            "A re-baseline is its own PR carrying the normalization or fixture change "
            "that caused it (INTERFACE.md §2.8, verification.md Tier 2)."
        ),
    }
    sidecar = stage4_goldens() / EVENT_ARCHIVE_PROVENANCE
    sidecar.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"  {path.relative_to(REPO)} ({len(archive)} events)")
    print(f"  {sidecar.relative_to(REPO)}")


def write_section_golden() -> None:
    """G4.7's golden, through ``update_goldens`` — one generator, one sidecar.

    ``force=True`` because this script writes the transcript first and therefore
    always runs on a dirty tree; the dirty-tree refusal it bypasses guards
    ``heph goldens --update``'s interactive path, and the churn policy it exists
    to enforce is stated in the provenance sidecar and honoured by committing the
    golden with the change that motivated it.
    """
    from hephaestus.core.render.goldens import update_goldens
    from hephaestus.testing.workspace_fixture import (
        SECTION_GOLDEN_DIR,
        SECTION_GOLDEN_SPEC,
        stage4_goldens,
    )

    out = stage4_goldens() / SECTION_GOLDEN_DIR
    written = update_goldens(out_dir=out, repo_root=REPO, specs=(SECTION_GOLDEN_SPEC,), force=True)
    for path in written:
        print(f"  {path.relative_to(REPO)}")


if __name__ == "__main__":
    sys.exit(main())
