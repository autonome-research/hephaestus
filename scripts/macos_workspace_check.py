# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Milestone-only native server/browser lifecycle and fresh later-stage collector."""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import signal
import subprocess
import threading

from macos_milestone_smoke import ROOT, StageFailure
from macos_workspace import document


def run_browser_client(smoke, argv, directory):
    """Own Node separately: abrupt group-kill transport cannot reap detached Chrome.

    TERM is delivered to the live child first so Playwright can close its browser
    process group. Missing final browser ownership is a refusal, never absence.
    """
    from hephaestus.core.executor.sandbox.oci import RUNTIME_ENV

    state = {"launch_pending": True, "pid": None, "reaped": False}
    owner = directory / "client-owner.json"
    document(owner, state)
    process = reader = None
    acknowledged = False
    errors = []
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=RUNTIME_ENV,
            start_new_session=True,
            cwd=ROOT,
        )
        document(owner, {**state, "launch_pending": False, "pid": process.pid})
        acknowledged = True

        def capture():
            try:
                total = 0
                with (directory / "client.log").open("xb") as stream:
                    while chunk := process.stdout.read(4096):
                        total += len(chunk)
                        if total > 128 * 1024:
                            raise StageFailure("browser client log overflow")
                        stream.write(chunk)
            except BaseException as exc:
                errors.append(f"browser log capture failed: {type(exc).__name__}")
                process.terminate()

        reader = threading.Thread(target=capture, name="browser-log", daemon=True)
        reader.start()
        smoke.report["browser_command"] = {
            "argv": list(argv),
            "timeout_seconds": 480,
            "output_limit_bytes": 128 * 1024,
        }
        smoke.save()
        code = process.wait(timeout=480)
        if code:
            raise StageFailure("browser client failed; see browser/browser.json")
    finally:
        old = {sig: signal.signal(sig, signal.SIG_IGN) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
                    errors.append("forced client death; retain unresolved browser ownership")
            if reader is not None and reader.ident is not None:
                reader.join(timeout=5)
                if reader.is_alive():
                    errors.append("unreaped browser log reader")
            if process is not None:
                process.stdout.close()
                state.update(
                    launch_pending=not acknowledged,
                    pid=process.pid,
                    reaped=True,
                    returncode=process.returncode,
                    errors=errors,
                )
                # Failed acknowledgement never becomes settled merely because
                # this cleanup observed a dead client; Chrome may be detached.
                document(owner, state)
            if errors:
                raise StageFailure("; ".join(errors))
        finally:
            for sig, handler in old.items():
                signal.signal(sig, handler)


def diagnostic_requirements():
    """Authored test input, not a claim about an operator's real design brief."""
    request = (
        "Local diagnostic fixture: two disjoint centered cuboids, 4 x 5 x 6 mm at the origin "
        "and 2 x 3 x 7 mm translated 12 mm along X. Exactly two sealed solids, "
        "162 mm3 total volume; the Z=0 section has two faces and 26 mm2 area."
    )
    return {
        "request": request,
        "entries": [
            {"id": "R1", "text": request, "source": "specified", "quote": request},
        ],
    }


def browser(smoke, renderer_image):
    directory = smoke.directory / "browser"
    directory.mkdir(mode=0o700)
    project = smoke.directory / "project"
    state = directory / "server"
    document(directory / "requirements.json", diagnostic_requirements())
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "TMPDIR", "LANG"}}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    read_fd, write_fd = os.pipe()
    process = None
    errors = []
    reader = None
    ownership = {"launch_pending": True, "pid": None, "reaped": False}
    document(directory / "server-owner.json", ownership)
    try:
        process = subprocess.Popen(
            [
                str(ROOT / ".venv/bin/python"),
                str(ROOT / "scripts/macos_workspace.py"),
                "--project",
                str(project),
                "--state-dir",
                str(state),
                "--executor-image",
                smoke.report["executor_image_ref"],
                "--renderer-image",
                renderer_image,
                "--wall-seconds",
                "600",
                "--requirements",
                str(directory / "requirements.json"),
                "--ready-fd",
                str(write_fd),
            ],
            cwd=ROOT,
            env=env,
            pass_fds=(write_fd,),
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        ownership.update(launch_pending=False, pid=process.pid)
        document(directory / "server-owner.json", ownership)
        os.close(write_fd)
        write_fd = -1

        def capture():
            total = 0
            with (directory / "server.log").open("xb") as stream:
                while True:
                    chunk = process.stdout.read(4096)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 128 * 1024:
                        errors.append("server log overflow")
                        process.terminate()
                        break
                    stream.write(chunk)

        reader = threading.Thread(target=capture, name="workspace-log", daemon=True)
        reader.start()
        with selectors.DefaultSelector() as selector:
            selector.register(read_fd, selectors.EVENT_READ)
            if not selector.select(180):
                raise StageFailure("workspace readiness timed out")
            raw = os.read(read_fd, 8192)
        if not raw.endswith(b"\n"):
            raise StageFailure("workspace did not produce complete readiness")
        ready = json.loads(raw)
        if ready["pid"] != process.pid:
            raise StageFailure("workspace owner mismatch")
        document(directory / "ready.json", ready)  # token path, never token
        node = __import__("shutil").which("node")
        if node is None:
            raise StageFailure("Node unavailable for pinned Playwright")
        run_browser_client(
            smoke,
            (
                node,
                str(ROOT / "web/e2e/macos-workspace.mjs"),
                str(directory / "ready.json"),
                str(directory),
            ),
            directory,
        )
        evidence = json.loads((directory / "browser.json").read_text())
        if evidence["passed"] is not True or evidence["cleanup_passed"] is not True:
            raise StageFailure("browser acceptance or cleanup failed")
        smoke.report["browser_evidence"] = evidence
    finally:
        old = {sig: signal.signal(sig, signal.SIG_IGN) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            os.close(read_fd)
            if write_fd != -1:
                os.close(write_fd)
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
                    errors.append("server forced termination; ownership unresolved")
                ownership.update(reaped=True, returncode=process.returncode)
                document(directory / "server-owner.json", ownership)
                if reader is not None:
                    reader.join(timeout=5)
                    if reader.is_alive():
                        errors.append("server log reader not reaped")
                process.stdout.close()
                if process.returncode not in (0, 128 + signal.SIGTERM):
                    errors.append("server failed")
                if not (state / "workspace.json").is_file():
                    errors.append("workspace cleanup evidence missing")
                else:
                    final = json.loads((state / "workspace.json").read_text())
                    if final.get("cleanup_passed") is not True:
                        errors.append("workspace owned cleanup failed")
                    smoke.report["workspace_evidence"] = final
                if (project / ".heph/serve.json").exists():
                    errors.append("serve record remains")
                # Positive inventory, not a failed kill(0) interpreted as absence.
                _, raw = smoke.command(("/bin/ps", "-axo", "pid=,pgid="))
                live = {int(word) for word in raw.split()}
                browser_report = directory / "browser.json"
                if browser_report.exists():
                    b = json.loads(browser_report.read_text())
                    browser_owner = json.loads((directory / "browser-owner.json").read_text())
                    client_owner = json.loads((directory / "client-owner.json").read_text())
                    if (
                        b.get("cleanup_passed") is not True
                        or b.get("browser_pid") in live
                        or browser_owner.get("launch_pending") is not False
                        or browser_owner.get("closed") is not True
                        or browser_owner.get("pid") != b.get("browser_pid")
                        or client_owner.get("launch_pending") is not False
                        or client_owner.get("reaped") is not True
                        or client_owner.get("pid") in live
                        or client_owner.get("errors")
                    ):
                        errors.append("browser cleanup uncertain")
                else:
                    errors.append("browser cleanup evidence missing")
                if process.pid in live:
                    errors.append("server process/group remains")
            if errors:
                smoke.report["workspace_cleanup_passed"] = False
                raise StageFailure("; ".join(errors))
            smoke.report["workspace_cleanup_passed"] = True
        finally:
            for sig, handler in old.items():
                signal.signal(sig, handler)
            smoke.save()
    # Independently bind the actual browser plate to kernel/worker provenance.
    from hephaestus.core.project_store.layout import load_project, open_store
    from hephaestus.core.project_store.store import blob_hash_of_ref
    from hephaestus.core.render.bundle import resolve_selection
    from hephaestus.core.render.glb_gate import validate_linked_glb

    with open_store(load_project(project)) as store:
        browser_glb = smoke.report["browser_evidence"]["glb"]
        glb_data = (directory / "browser.glb").read_bytes()
        resolution = resolve_selection(
            store, browser_glb["bundle"], expected_source_artifact_ref=browser_glb["source"]
        )
        validation = validate_linked_glb(
            glb_data,
            source_ref=browser_glb["source"],
            bundle_ref=browser_glb["bundle"],
            selection_table_ref=resolution.selection_table_ref,
            entries={str(k): v.to_json() for k, v in resolution.entries.items()},
        )
        from macos_renderer_live import require_fixture_faces

        require_fixture_faces(validation, resolution.entries)
        if hashlib.sha256(glb_data).hexdigest() != browser_glb["sha256"]:
            raise StageFailure("browser GLB stored bytes mismatch")
        pick = smoke.report["browser_evidence"]["pick"]
        entry = resolution.entries[pick["selection_id"]]
        if entry.kind != "face" or entry.solid_index != pick["hint"]["mesh_index"]:
            raise StageFailure("actual browser hit/table resolution mismatch")
        document(directory / "linked-glb-validation.json", validation)
        section = smoke.report["browser_evidence"]["section"]
        blob = blob_hash_of_ref(section["ref"])
        data = store.blobs.get(blob)
        if hashlib.sha256(data).hexdigest() != section["displayed"]["sha256"]:
            raise StageFailure("browser plate stored bytes mismatch")
        records = [json.loads(store.blobs.get(t)) for s, t in store.gc.links() if s == blob]
        provenance = next(p for p in records if p.get("kind") == "render_provenance")
        if (
            provenance["section"]["faces"] != 2
            or abs(provenance["section"]["area_mm2"] - 26) > 1e-8
            or provenance["source_artifact_ref"] != section["source"]
            or provenance["executor_identity"]
            != smoke.report["workspace_evidence"]["executor_identity"]
            or provenance["renderer_identity"]
            != smoke.report["workspace_evidence"]["renderer_identity"]
        ):
            raise StageFailure("browser kernel section/provenance mismatch")
        document(directory / "section-provenance.json", provenance)
    smoke.report["screenshots"] = ["browser/viewport.png", "browser/section-workspace.png"]
    smoke.check(
        "browser",
        "passed",
        "native Chrome authenticated workspace, actual GLB/scene/raycast, "
        "resolved selection and kernel-linked section plate; owned cleanup",
    )


def later_stages(smoke):
    from macos_prepare_renderer import prepare
    from macos_probe_executor import resolve_image
    from macos_renderer_check import RendererSmoke, live

    renderer = RendererSmoke(smoke.directory / "renderer", smoke.wheelhouse)
    renderer.docker = smoke.docker
    try:
        renderer.native_dependencies()
        image = resolve_image(renderer, prepare(renderer), role="renderer")
        smoke.report["renderer_image_ref"] = image
        live(renderer, image, smoke)
        for name in ("rgb", "selection_masks", "kernel_section", "linked_glb"):
            smoke.report["checks"][name] = renderer.report["checks"][name]
        smoke.report["render_integration"] = renderer.report["render_integration"]
        smoke.save()
        browser(smoke, image)
    finally:
        renderer.cleanup()
        smoke.report["renderer_cleanup_passed"] = (
            renderer.report.get("renderer_cleanup_passed") is True
            and renderer.report["checks"]["cleanup"]["status"] == "passed"
        )
        if smoke.report["renderer_cleanup_passed"] is not True:
            raise StageFailure("renderer stage cleanup incomplete")
