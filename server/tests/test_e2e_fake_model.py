"""End-to-end Stage 2A: scripted fake model -> REAL Node sidecar -> Python core.

Every test here drives the *packaged* sidecar (``node agent/dist/main.js``, built
by ``pnpm --dir agent build``) through the private framed JSON-RPC bridge, with a
scripted OpenAI-compatible fake model
(:mod:`hephaestus.testing.fake_openai`) standing in for the
provider. Nothing is stubbed between the model and the CAD engine: tool calls
travel model -> Pi loop -> ToolProxy -> ``py.tool_dispatch`` -> ``hephaestus.core``
and back, and the normalized event stream is asserted on the Python side exactly
as a client would see it (the raw bridge is never surfaced).

Covered (mission Stage 2 / Gate G2 "cross-cutting" list):

* ``create_part`` -> ``write_part`` (CAS) -> ``build_part`` -> ``inspect_part``
  with images flowing back inline within the §5 budgets -> ``edit_part`` with a
  stale hash (conflict payload) and then a correct hash (applied);
* ``ask_user`` suspension answered by a scripted answerer, surfaced as the public
  ``question``/``answer`` events;
* cancellation mid-run: the run's own abort controller stops that run only, and
  exactly one durable terminal is recorded;
* supervisor ``kill -9`` -> in-flight run marked ``interrupted`` -> restart ->
  session **resume** completing a second prompt against the persisted transcript;
* the repair flow off the ``failure_fillet`` fixture: the build fails, the model
  reads the structured error, edits the script, and rebuilds clean.

Every scenario asserts zero orphan sidecar processes afterwards.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from hephaestus.agent_bridge.app import BridgeRuntime, repo_root
from hephaestus.agent_bridge.supervisor import build_minimal_env, pid_alive
from hephaestus.testing.fake_openai import FakeOpenAI, RequestInfo, start_fake_openai
from hephaestus.testing.projects import scaffold_project
from hephaestus.testing.sidecar import build_agent_dist
from hephaestus.testing.stream_assertions import (
    assert_stream_shape,
    events_of,
    last_tool_result,
    payload_of,
    text,
    tool_call,
)
from opstore.types import TerminalState

FIXTURES = repo_root() / "corpus" / "public_fixtures"
FAILURE_FILLET = FIXTURES / "failure_fillet"

#: A small buildable part the scripted model authors through write_part.
WIDGET_SCRIPT = """PARAMS = {
    "width": Param(40.0, min=10.0, max=80.0),
}

body = Box(p.width, 20.0, 6.0)
body.label = "widget_body"
part.geometry = body
part.description = "Scripted end-to-end widget"
"""


# --------------------------------------------------------------------------
# environment / fixtures


@pytest.fixture(scope="session")
def sidecar_dist() -> Path:
    """Build the real sidecar once per session; skip cleanly when Node is absent."""
    built = build_agent_dist()
    if built is None:
        pytest.skip("node/pnpm unavailable; the e2e bridge needs the packaged sidecar")
    return built[0]


def e2e_project(root: Path) -> Path:
    """The empty-but-real project the e2e scenarios author parts into."""
    return scaffold_project(
        root,
        name="e2e",
        globals_src="# Project-shared namespace for the e2e project.\nPARAMS = {}\n",
    )


class Harness:
    """A started :class:`BridgeRuntime` plus its scripted fake provider."""

    def __init__(self, project_root: Path, dist_main: Path) -> None:
        self.project_root = project_root
        self.fake: FakeOpenAI = start_fake_openai([])
        self.runtime = BridgeRuntime(
            project_root=project_root,
            providers=[self.fake.provider_spec()],
            dist_main=dist_main,
        )
        self.runtime.start()
        self.child_pids: list[int] = [self.runtime.child_pid]

    def track_child(self) -> None:
        self.child_pids.append(self.runtime.child_pid)

    def close(self) -> None:
        try:
            self.runtime.close()
        finally:
            self.fake.close()

    def assert_no_orphans(self) -> None:
        for pid in self.child_pids:
            assert not pid_alive(pid), f"sidecar pid {pid} outlived the supervisor"


@pytest.fixture
def harness(tmp_path: Path, sidecar_dist: Path) -> Iterator[Harness]:
    project = e2e_project(tmp_path / "proj")
    h = Harness(project, sidecar_dist)
    try:
        yield h
    finally:
        h.close()
        h.assert_no_orphans()


# --------------------------------------------------------------------------
# 1. the full tool loop: create -> write (CAS) -> build -> inspect -> edit


def test_full_tool_loop_with_images_and_cas(harness: Harness) -> None:
    seen: dict[str, Any] = {}

    def write_widget(info: RequestInfo) -> dict[str, Any]:
        created = last_tool_result(info)
        seen["created_hash"] = created["content_hash"]
        return tool_call(
            "write_part",
            {
                "name": "widget",
                "expected_hash": created["content_hash"],
                "script": WIDGET_SCRIPT,
            },
            "c1",
        )

    def build_widget(info: RequestInfo) -> dict[str, Any]:
        written = last_tool_result(info)
        assert written["applied"] is True
        seen["written_hash"] = written["content_hash"]
        return tool_call("build_part", {"name": "widget"}, "c2")

    def inspect_widget(info: RequestInfo) -> dict[str, Any]:
        built = last_tool_result(info)
        seen["build"] = built
        assert built["status"] == "ok", built
        return tool_call("inspect_part", {"name": "widget", "views": ["iso"]}, "c3")

    def edit_stale(info: RequestInfo) -> dict[str, Any]:
        inspected = last_tool_result(info)
        seen["inspect"] = inspected
        # The render reached the model inline (not as a "images unsupported" note).
        seen["image_in_context"] = "image_url" in info.body_text
        # Deliberately present the pre-write hash: the CAS must refuse.
        return tool_call(
            "edit_part",
            {
                "name": "widget",
                "expected_hash": seen["created_hash"],
                "old_str": "20.0",
                "new_str": "24.0",
            },
            "c4",
        )

    def edit_fresh(info: RequestInfo) -> dict[str, Any]:
        conflict = last_tool_result(info)
        seen["conflict"] = conflict
        assert conflict["applied"] is False
        current = conflict["conflict"]["current_hash"]
        return tool_call(
            "edit_part",
            {
                "name": "widget",
                "expected_hash": current,
                "old_str": "20.0",
                "new_str": "24.0",
            },
            "c5",
        )

    def finish(info: RequestInfo) -> dict[str, Any]:
        applied = last_tool_result(info)
        seen["applied"] = applied
        assert applied["applied"] is True
        return text("widget is 40 x 24 x 6")

    harness.fake.set_script(
        [
            tool_call("create_part", {"name": "widget", "template": "blank"}, "c0"),
            write_widget,
            build_widget,
            inspect_widget,
            edit_stale,
            edit_fresh,
            finish,
        ]
    )

    session_id = harness.runtime.create_session("orchestrator", session_id="e2e-main")
    result = harness.runtime.prompt(
        session_id, "author, build, inspect, and tweak the widget", timeout=600
    )

    assert result.status == "completed"
    assert_stream_shape(result)

    # -- the real engine did the work --------------------------------------
    script_path = harness.project_root / "parts" / "widget.py"
    assert script_path.exists()
    assert "24.0" in script_path.read_text(encoding="utf-8")
    assert seen["build"]["status"] == "ok"
    assert seen["build"]["current"] is True
    assert seen["build"]["artifact_ref"].startswith("artifact:")

    # -- images rode back inline within the §5 budgets ----------------------
    images = events_of(result, "image")
    assert images, "inspect_part must stream at least one image event"
    for image in images:
        payload = payload_of(image)
        assert payload["mimeType"] == "image/png"
        assert 0 < int(payload["bytes"]) <= 8 * 1024 * 1024
        assert isinstance(payload["data"], str) and payload["data"]
    assert seen["inspect"]["status"] == "ok"
    assert seen["inspect"]["render_artifact_refs"]
    assert seen["image_in_context"] is True, "the render must reach the model inline"
    # The model's *text* view of the result never carries base64 image bytes.
    assert all("data" not in img for img in seen["inspect"]["images"])

    # -- CAS: the stale hash produced a conflict payload, not a write -------
    assert seen["conflict"]["conflict"]["current_hash"] == seen["written_hash"]
    assert seen["applied"]["content_hash"] != seen["written_hash"]

    # -- the normalized stream is the public tool narrative -----------------
    called = [payload_of(ev)["name"] for ev in events_of(result, "tool_call")]
    assert called == [
        "create_part",
        "write_part",
        "build_part",
        "inspect_part",
        "edit_part",
        "edit_part",
    ]
    assert len(events_of(result, "tool_result")) == len(called)
    streamed = "".join(payload_of(ev)["text"] for ev in events_of(result, "text_delta"))
    assert "widget is 40 x 24 x 6" in streamed

    # -- exactly one durable, acknowledged terminal -------------------------
    terminal = harness.runtime.admission.get_terminal(result.run_id)
    assert terminal is not None
    assert terminal.state is TerminalState.COMPLETED
    assert result.terminal is not None and result.terminal["state"] == "completed"


# --------------------------------------------------------------------------
# 2. ask_user suspension + scripted answer


def test_ask_user_suspension_and_answer(harness: Harness) -> None:
    asked: list[dict[str, Any]] = []

    def answerer(params: dict[str, Any]) -> Any:
        asked.append(params)
        return "6 mm plywood"

    def after_answer(info: RequestInfo) -> dict[str, Any]:
        answer = last_tool_result(info)
        assert answer["selection"] == "6 mm plywood"
        return text("using 6 mm plywood")

    harness.fake.set_script(
        [
            tool_call(
                "ask_user",
                {
                    "question": "Which sheet stock?",
                    "options": ["6 mm plywood", "12 mm plywood"],
                    "allow_free_text": False,
                },
                "q0",
            ),
            after_answer,
        ]
    )

    session_id = harness.runtime.create_session("orchestrator", session_id="e2e-ask")
    result = harness.runtime.prompt(session_id, "pick a material", answerer=answerer, timeout=300)

    assert result.status == "completed"
    assert_stream_shape(result)

    # The suspension reached Python with the model's structured question…
    assert len(asked) == 1
    assert asked[0]["question"] == "Which sheet stock?"
    assert asked[0]["options"] == ["6 mm plywood", "12 mm plywood"]
    assert asked[0]["run_id"] == result.run_id

    # …and is public as a question/answer pair, in order, never coalesced.
    questions = events_of(result, "question")
    answers = events_of(result, "answer")
    assert len(questions) == 1 and len(answers) == 1
    assert payload_of(questions[0])["question"] == "Which sheet stock?"
    assert questions[0]["seq"] < answers[0]["seq"]
    assert payload_of(answers[0])["answer"] == {"selection": "6 mm plywood"}

    streamed = "".join(payload_of(ev)["text"] for ev in events_of(result, "text_delta"))
    assert "using 6 mm plywood" in streamed


# --------------------------------------------------------------------------
# 3. cancellation mid-run


def test_cancellation_mid_run(harness: Harness) -> None:
    harness.fake.set_script([{"kind": "stall"}])
    session_id = harness.runtime.create_session("orchestrator", session_id="e2e-cancel")
    run_id = harness.runtime.new_run_id()

    def cancel_soon() -> None:
        # Wait until the model request is actually in flight, then cancel.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not harness.fake.requests:
            time.sleep(0.05)
        time.sleep(0.2)
        harness.runtime.cancel(run_id)

    canceller = threading.Thread(target=cancel_soon, daemon=True)
    canceller.start()
    result = harness.runtime.prompt(session_id, "stall forever", run_id=run_id, timeout=120)
    canceller.join(timeout=5)

    assert result.run_id == run_id
    assert result.status == "cancelled"
    assert_stream_shape(result)
    assert result.terminal is not None and result.terminal["state"] == "cancelled"

    terminal = harness.runtime.admission.get_terminal(run_id)
    assert terminal is not None
    assert terminal.state is TerminalState.CANCELLED

    # The sidecar survives a cancelled run and still serves the next prompt.
    harness.fake.set_script([text("still here")])
    followup = harness.runtime.prompt(session_id, "are you alive?", timeout=120)
    assert followup.status == "completed"
    streamed = "".join(payload_of(ev)["text"] for ev in events_of(followup, "text_delta"))
    assert "still here" in streamed


# --------------------------------------------------------------------------
# 4. kill -9 the sidecar, restart, resume the session, finish a second prompt


def test_kill9_restart_and_session_resume(harness: Harness) -> None:
    harness.fake.set_script([text("first turn recorded")])
    session_id = harness.runtime.create_session("orchestrator", session_id="e2e-resume")
    first = harness.runtime.prompt(session_id, "remember the gusset is 4 mm", timeout=300)
    assert first.status == "completed"

    # A run that is in flight when the process dies must be marked interrupted.
    doomed_run = harness.runtime.new_run_id()
    harness.runtime.admission.admit_run(doomed_run)
    harness.runtime._sup.track_run(doomed_run)  # pyright: ignore[reportPrivateUsage]

    old_pid = harness.runtime.child_pid
    os.kill(old_pid, 9)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and pid_alive(old_pid):
        time.sleep(0.05)
    assert not pid_alive(old_pid)

    harness.runtime.restart()
    harness.track_child()
    assert harness.runtime.child_pid != old_pid

    interrupted = harness.runtime.admission.get_terminal(doomed_run)
    assert interrupted is not None
    assert interrupted.state is TerminalState.INTERRUPTED

    # Resume the persisted Pi transcript and complete a second prompt.
    harness.fake.set_script(
        [
            lambda info: text(
                "resumed:" + ("saw-gusset" if "gusset is 4 mm" in info.body_text else "no-history")
            )
        ]
    )
    # No hand-written resume (§2.8(6), 2026-09-03): the respawned sidecar has
    # forgotten the session, and `_call_for_session` re-adopts it from the
    # retained principal on this very prompt. A hand-call here would let the
    # test pass even if that re-adoption regressed.
    second = harness.runtime.prompt(session_id, "what was the gusset decision?", timeout=300)
    assert second.status == "completed"
    assert_stream_shape(second)
    streamed = "".join(payload_of(ev)["text"] for ev in events_of(second, "text_delta"))
    assert "resumed:saw-gusset" in streamed, streamed

    # Historical reads still normalize through the sidecar after the restart.
    page = harness.runtime.history_page(session_id)
    assert page["done"] is True
    replayed = [str(ev["kind"]) for ev in page["events"]]
    assert replayed.count("text_delta") >= 2


# --------------------------------------------------------------------------
# 5. repair flow off the failure_fillet fixture


def test_repair_flow_off_failure_fixture(harness: Harness) -> None:
    # Plant the public broken-fillet fixture in the project.
    broken = (FAILURE_FILLET / "parts" / "broken.py").read_text(encoding="utf-8")
    (harness.project_root / "parts" / "broken.py").write_text(broken, encoding="utf-8")

    seen: dict[str, Any] = {}

    def read_after_failure(info: RequestInfo) -> dict[str, Any]:
        failed = last_tool_result(info)
        seen["failed_build"] = failed
        assert failed["status"] == "error", failed
        # The canonical §8 error record reaches the model: the failing line, the
        # exception type, and the statement the build got through.
        assert failed["error"]["line"] == 9
        assert failed["error"]["type"] == "ValueError"
        assert failed["error"]["built_through"]["statement"] == "notched = plate - slot"
        return tool_call("read_part", {"name": "broken"}, "r1")

    def repair(info: RequestInfo) -> dict[str, Any]:
        source = last_tool_result(info)
        seen["read"] = source
        assert "radius=40.0" in source["script"]
        return tool_call(
            "edit_part",
            {
                "name": "broken",
                "expected_hash": source["content_hash"],
                "old_str": "radius=40.0",
                "new_str": "radius=2.0",
            },
            "r2",
        )

    def rebuild(info: RequestInfo) -> dict[str, Any]:
        edited = last_tool_result(info)
        assert edited["applied"] is True
        return tool_call("build_part", {"name": "broken"}, "r3")

    def report(info: RequestInfo) -> dict[str, Any]:
        rebuilt = last_tool_result(info)
        seen["repaired_build"] = rebuilt
        assert rebuilt["status"] == "ok", rebuilt
        return text("repaired: fillet radius reduced to 2.0")

    harness.fake.set_script(
        [
            tool_call("build_part", {"name": "broken"}, "r0"),
            read_after_failure,
            repair,
            rebuild,
            report,
        ]
    )

    session_id = harness.runtime.create_session("orchestrator", session_id="e2e-repair")
    result = harness.runtime.prompt(session_id, "the broken part fails; fix it", timeout=600)

    assert result.status == "completed"
    assert_stream_shape(result)
    assert seen["failed_build"]["status"] == "error"
    assert seen["failed_build"]["error"]["last_good_artifact_ref"]
    assert seen["repaired_build"]["status"] == "ok"
    assert seen["repaired_build"]["current"] is True
    assert "radius=2.0" in (harness.project_root / "parts" / "broken.py").read_text(
        encoding="utf-8"
    )

    called = [payload_of(ev)["name"] for ev in events_of(result, "tool_call")]
    assert called == ["build_part", "read_part", "edit_part", "build_part"]


# --------------------------------------------------------------------------
# 6. object scope + client queues (cross-cutting assertions on the same loop)


def test_part_session_scope_and_client_queue(harness: Harness) -> None:
    queue = harness.runtime.client_queue("cli")
    harness.fake.set_script(
        [
            # A part session is bound to 'widget': creating/addressing another
            # part must be refused by the Python authz layer, not by the model.
            tool_call("read_part", {"name": "other"}, "s0"),
            lambda info: text("denied:" + ("yes" if "scope_denied" in info.body_text else "no")),
        ]
    )
    session_id = harness.runtime.create_session("part", part="widget", session_id="e2e-scope")
    result = harness.runtime.prompt(session_id, "read the other part", timeout=300)

    assert result.status == "completed"
    assert_stream_shape(result)
    streamed = "".join(payload_of(ev)["text"] for ev in events_of(result, "text_delta"))
    assert "denied:yes" in streamed

    # The bounded per-client queue saw the same public events plus the terminal.
    drained = queue.drain()
    assert [ev.kind for ev in drained if ev.kind == "tool_call"]
    assert any(ev.kind == "terminal" for ev in drained)
    assert all(ev.run_id == result.run_id for ev in drained)
    harness.runtime.drop_client("cli")


# --------------------------------------------------------------------------
# 7. sidecar isolation: app-owned agent dir, minimal environment


def test_sidecar_agent_dir_is_app_owned(harness: Harness) -> None:
    """Pi's auth/model store lands under the project, never in the caller's cwd."""
    agent_dir = harness.project_root / ".heph" / "agent"
    assert agent_dir.is_dir()
    assert (agent_dir / "auth.json").exists()
    # The repository root (this process's cwd during the test run) stays clean.
    assert not (repo_root() / "auth.json").exists()

    # No auth_source was declared, so auth.json is the sidecar's own file — not a
    # link into ~/.pi or anywhere else — and it carries no credential record. A
    # `pi_native` provider therefore has nothing ambient to authenticate with.
    auth = agent_dir / "auth.json"
    assert not auth.is_symlink()
    stored = json.loads(auth.read_text(encoding="utf-8") or "{}")
    assert stored == {}


def test_declared_auth_source_is_linked_into_the_agent_dir(tmp_path: Path) -> None:
    """The other half of the isolation contract: opt-in linking, by symlink.

    Uses a synthetic auth.json under tmp — never the operator's real Pi login —
    and never starts the sidecar, so nothing here can make a network call.
    """
    source = tmp_path / "pi-auth.json"
    source.write_text(
        json.dumps({"openai-codex": {"type": "oauth", "access": "synthetic"}}), encoding="utf-8"
    )
    project = e2e_project(tmp_path / "linked")
    runtime = BridgeRuntime(
        project_root=project,
        providers=[{"id": "openai-codex", "kind": "pi_native", "models": [{"id": "gpt-5.6-sol"}]}],
        auth_source=source,
    )
    try:
        link = project / ".heph" / "agent" / "auth.json"
        assert link.is_symlink()
        assert link.resolve() == source.resolve()
    finally:
        runtime.close()


def test_minimal_env_drops_ambient_keys_and_keeps_app_settings() -> None:
    env = build_minimal_env(
        frozenset({"APPROVED_KEY"}),
        source={
            "PATH": "/usr/bin",
            "HOME": "/home/u",
            "APPROVED_KEY": "ok",
            "ANTHROPIC_API_KEY": "ambient-must-not-leak",
            "HEPHAESTUS_AGENT_DIR": "/hostile/dir",
        },
        extra={"HEPHAESTUS_AGENT_DIR": "/app/owned"},
    )
    assert env["PATH"] == "/usr/bin"
    assert env["APPROVED_KEY"] == "ok"
    assert "ANTHROPIC_API_KEY" not in env
    # The app-owned value wins over an ambient one of the same name.
    assert env["HEPHAESTUS_AGENT_DIR"] == "/app/owned"
