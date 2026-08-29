# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""The Gate G4 public fixture, materialized — one definition, three consumers.

``INTERFACE.md`` §14 / §19 item 16 make ``corpus/public_fixtures/workspace/`` the
project the browser gate opens. Three things need it and must agree byte for
byte about what "it" means: the transcript recorder
(``scripts/record_workspace_transcript.py``), the server-side Stage 4 pytests
(``tests/stage4/``), and the Playwright harness that runs a real
``heph serve --web`` for ``pnpm --dir web test:e2e``. This module is that one
definition; nothing else knows the fixture's layout, its session ids, or where
its goldens live.

**What "materialize" means, and why it is more than a copy.** A committed
fixture is a directory of sources. Three of §14's requirements are not sources:

* the **git history** the §13.1 dirty markers and the §2.9 log projection read —
  so materialization initialises a repository and makes one commit;
* the **transcript**, which is a persisted Pi session under ``.heph/sessions/``
  and therefore cannot live in the committed tree (``.heph/`` is ignored
  repo-wide, and its session header records an absolute ``cwd``) — so it is
  committed under ``transcript/`` and replayed into place, with ``cwd`` rewritten
  to the materialized root;
* the **session edges** of §2.8, which live in ``state.db`` — so they are
  committed as ``transcript/threads.json`` and written through
  :class:`~hephaestus.agent_bridge.session_edges.SessionEdgeStore`, the same
  writer the two production sites use. No second writer, no hand-built table.

Nothing here fabricates engine output: the transcript was produced by a real
sidecar against this project, and the edge rows carry the real selection id and
the real ``source_artifact_ref`` the recording resolved.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hephaestus.agent_bridge.app import repo_root
from hephaestus.agent_bridge.session_edges import SessionEdgeStore
from hephaestus.core.render.goldens import GoldenSpec
from hephaestus.core.render.offscreen import DEFAULT_HEIGHT, DEFAULT_WIDTH

__all__ = [
    "CONTEXT_GOLDEN_CASES",
    "CONTEXT_GOLDEN_DIR",
    "CURRENT_BUILD_REF",
    "EVENT_ARCHIVE",
    "EVENT_ARCHIVE_PROVENANCE",
    "GATE_PARTS",
    "ORCHESTRATOR_SESSION_ID",
    "QUICK_EDIT_SESSION_ID",
    "SECTION_GOLDEN_DIR",
    "SECTION_GOLDEN_SPEC",
    "SECTION_PLANE",
    "SECTION_VIEW",
    "SUBJECT_PART",
    "TAGGED_FACE",
    "WORKSPACE_FIXTURE",
    "Materialized",
    "fixture_source",
    "install_transcript",
    "materialize_workspace_fixture",
    "record_requirements",
    "record_transcript_edges",
    "resolve_context_case",
    "stage4_goldens",
]

#: The fixture directory name under ``corpus/public_fixtures/``.
WORKSPACE_FIXTURE = "workspace"

#: The part every G4 DOM/pixel clause is about.
SUBJECT_PART = "tread"

#: The parts the browser gate builds. ``kerf_card`` is deliberately absent: it
#: exists for G5.8's oversized legend and 90 boolean cuts are time G4 does not
#: need to spend (``corpus/public_fixtures/workspace/README.md``).
GATE_PARTS: tuple[str, ...] = ("tread", "riser")

#: The tag G5.4 joins back to its creating line; present in G4 only as a fact
#: the fixture carries.
TAGGED_FACE = "tread_top"

#: G4.7's plane and view. The offset is written the way the client writes it
#: (``web/src/viewport/section.ts::formatSectionPlane`` trims trailing zeros), so
#: the string the browser puts on ``data-section-plane`` and the string this
#: golden was baselined with are the same string.
SECTION_PLANE = "+X@0"
SECTION_VIEW = "iso"

#: The two session ids the committed transcript carries. They are FIXED, and
#: that is the point: §2.8 puts G4.11's archive over ``(session_id, ordinal)``
#: pairs, so a server-minted UUID would make the archive unmatchable.
ORCHESTRATOR_SESSION_ID = "sess-workspace-orchestrator"
QUICK_EDIT_SESSION_ID = "sess-workspace-quickedit"


def fixture_source() -> Path:
    """The committed fixture directory."""
    return repo_root() / "corpus" / "public_fixtures" / WORKSPACE_FIXTURE


def stage4_goldens() -> Path:
    """``tests/stage4/goldens`` — the Stage 4 golden families."""
    return repo_root() / "tests" / "stage4" / "goldens"


#: G4.11's archive: normalized **historical** events, one JSON object per line.
EVENT_ARCHIVE = "events/workspace.jsonl"
EVENT_ARCHIVE_PROVENANCE = "events/workspace.provenance.json"

#: G4.7's directory. A separate family from ``tests/render/goldens`` only in
#: *location*: it is produced by :func:`hephaestus.core.render.goldens.update_goldens`,
#: carries the same provenance sidecar, and re-baselines by the same policy.
SECTION_GOLDEN_DIR = "section"

#: G4.7's golden. Baselined at the **route's** render size, not the small golden
#: size: the browser cannot choose a size, so a 480x360 baseline would compare a
#: resampling rather than a render (§5.3 makes the browser a viewer of server
#: pixels).
SECTION_GOLDEN_SPEC = GoldenSpec(
    name="workspace_tread_section",
    fixture=WORKSPACE_FIXTURE,
    part=SUBJECT_PART,
    views=(SECTION_VIEW,),
    channel="section",
    section_plane=SECTION_PLANE,
    width=DEFAULT_WIDTH,
    height=DEFAULT_HEIGHT,
)


#: §7A.3's golden family: the composed context block, one file per case.
#:
#: "Goldened at ``tests/stage4/goldens/context/<case>.txt`` **so a change to
#: what the agent is told is a diff in a review rather than a change nobody can
#: see**". The block is the one artefact in this system that reaches a model's
#: context window without a human reading it first, which is the whole argument
#: for a committed text file over a substring assertion.
CONTEXT_GOLDEN_DIR = "context"

#: The stand-in for "the ref the operator pinned". §7A.3's ``artifact_ref`` is a
#: **server-minted id the client echoes back**, so neither the test nor the
#: rebaseline script may spell one: a hash typed into either would be a second
#: copy of a value the store owns, rotting the first time the fixture changed.
#: :func:`resolve_context_case` substitutes the fixture's own current build ref,
#: which is what a browser holding a pin actually sends.
CURRENT_BUILD_REF = "@current_build_ref"

#: One case per committed golden: ``(name, envelope)``.
#:
#: The envelopes are the **client's** side of §7A.3 — every member either §4.5
#: workspace state or a server-minted id echoed back — written exactly as a
#: browser would send them, so each golden is a diff of what a real workspace
#: state produces. They live here rather than in the test module because the
#: rebaseline script reads the same table: one definition of "the cases", so a
#: case added to one cannot go missing from the other.
CONTEXT_GOLDEN_CASES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("part_only", {"part": SUBJECT_PART}),
    (
        "pinned_workspace",
        {
            "part": SUBJECT_PART,
            "artifact_ref": CURRENT_BUILD_REF,
            "pin_mode": "pinned",
            "stage_tab": "viewport",
            "inspector_tab": "checks",
            "view": "iso",
            "explode_t": 0.5,
            "section_plane": SECTION_PLANE,
            "hidden_labels": ["cleat_left"],
            "focus": "geometry:tread_plate",
        },
    ),
)


def resolve_context_case(envelope: dict[str, Any], build_ref: str) -> dict[str, Any]:
    """:data:`CURRENT_BUILD_REF` → the ref the store actually minted."""
    if envelope.get("artifact_ref") != CURRENT_BUILD_REF:
        return envelope
    return {**envelope, "artifact_ref": build_ref}


@dataclass(frozen=True, slots=True)
class Materialized:
    """A materialized fixture and the facts a harness needs about it."""

    root: Path
    #: Session ids installed from ``transcript/`` and openable with
    #: ``POST /sessions {session_id, resume: true}``.
    sessions: tuple[str, ...]
    #: ``True`` when a git repository was initialised and committed.
    git: bool


def materialize_workspace_fixture(
    dest: Path,
    *,
    git: bool = True,
    transcript: bool = True,
) -> Materialized:
    """Copy the fixture to ``dest`` and make it the project the gate opens.

    ``dest`` must not exist. Returns the project root, which is ``dest`` itself.
    """
    source = fixture_source()
    if not source.is_dir():  # pragma: no cover - a broken checkout
        raise FileNotFoundError(f"fixture not found: {source}")
    shutil.copytree(source, dest)
    record_requirements(dest)
    installed: tuple[str, ...] = ()
    if transcript:
        installed = install_transcript(dest)
    if git:
        _init_repository(dest)
    return Materialized(root=dest, sessions=installed, git=git)


def record_requirements(root: Path) -> int:
    """Replay ``requirements.json`` through ``cad_ops.record_requirements``.

    ``VALIDATION.md`` §2 refuses ``build_part`` while a project's ledger is empty
    ("geometry may not precede requirements"), and the ledger lives in the
    opstore, so a committed project cannot carry one. The entries are committed
    instead and written here through the **production** writer, so the fixture
    can never hold a ledger shape the product does not produce. Every entry is
    ``source: "specified"`` with its quote, so none of them gates: a clarification
    prompt in the middle of a browser gate would be a hang, not a finding.
    """
    from hephaestus.agent_bridge.cad_ops import CadOps
    from hephaestus.core.project_store.layout import load_project, open_store

    manifest = root / "requirements.json"
    if not manifest.is_file():
        return 0
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    entries = [{key: value for key, value in entry.items()} for entry in payload.get("entries", [])]
    if not entries:
        return 0
    layout = load_project(root)
    store = open_store(layout)
    try:
        CadOps(layout, store).record_requirements(entries, op_id="workspace-fixture-requirements")
    finally:
        store.close()
    return len(entries)


def _init_repository(root: Path) -> None:
    """A real repository with one commit — §13.1's markers need a baseline.

    Identity is set on the repository, never globally: a fixture must not depend
    on (or alter) whatever the machine's git config happens to say.
    """
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}

    def run(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, text=True, env=env
        )

    run("init", "--initial-branch=main")
    run("config", "user.name", "Hephaestus Fixture")
    run("config", "user.email", "fixture@hephaestus.invalid")
    run("config", "commit.gpgsign", "false")
    run("add", "-A")
    run("commit", "-m", "workspace fixture: flat-pack stair tread kit")


def install_transcript(root: Path) -> tuple[str, ...]:
    """Replay ``transcript/`` into ``.heph/sessions/`` and record its edges.

    Returns the session ids installed. Absent transcript directory is not an
    error — a fixture materialized before the recorder has run is a project with
    no sessions, which is a state the workspace already renders by name.
    """
    staged = root / "transcript" / "sessions"
    if not staged.is_dir():
        return ()
    target = root / ".heph" / "sessions"
    target.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []
    for session_dir in sorted(staged.iterdir()):
        if not session_dir.is_dir():
            continue
        out = target / session_dir.name
        shutil.copytree(session_dir, out, dirs_exist_ok=True)
        for jsonl in out.glob("*.jsonl"):
            _rewrite_cwd(jsonl, root)
        installed.append(session_dir.name)
    record_transcript_edges(root)
    return tuple(installed)


def _rewrite_cwd(path: Path, root: Path) -> None:
    """Point a recorded session header at the project it now lives in.

    Pi's session file opens with a ``{"type": "session", …, "cwd": …}`` record
    naming the absolute directory the session was recorded in. That directory
    was a recorder's temporary path and does not exist here. Only that one key on
    that one record is rewritten; every message record is left exactly as the
    sidecar wrote it, because the messages are the transcript the archive is
    over.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return
    try:
        header: dict[str, Any] = json.loads(lines[0])
    except json.JSONDecodeError:  # pragma: no cover - not a Pi session file
        return
    if header.get("type") != "session" or "cwd" not in header:
        return
    header["cwd"] = str(root)
    lines[0] = json.dumps(header, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def record_transcript_edges(root: Path) -> int:
    """Write ``transcript/threads.json``'s rows through the production writer.

    §2.8's edge table lives in ``state.db``, so it cannot be committed. What is
    committed is the rows; they are written here through
    :class:`SessionEdgeStore` — the same class ``SessionService.spawn_quick_edit``
    and the delegation WAL write through — so the fixture can never carry a row
    shape the product does not produce.
    """
    manifest = root / "transcript" / "threads.json"
    if not manifest.is_file():
        return 0
    from hephaestus.core.project_store.layout import load_project, open_store

    rows = json.loads(manifest.read_text(encoding="utf-8"))
    store = open_store(load_project(root))
    written = 0
    try:
        edges = SessionEdgeStore(store.db)
        for row in rows["edges"]:
            edges.record(
                child_session_id=str(row["child_session_id"]),
                parent_session_id=str(row["parent_session_id"]),
                kind=str(row["kind"]),
                origin=dict(row.get("origin") or {}),
            )
            written += 1
    finally:
        store.close()
    return written
