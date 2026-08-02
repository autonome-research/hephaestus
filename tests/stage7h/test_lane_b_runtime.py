# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G7H lane (b): the three runtime clauses, run against the INSTALLED wheel.

Lane (b)'s gate sentence is a chain: core build/check through the secure
executor -> packaged-sidecar integrity/native-addon audit -> **Python-backed
JobStore initialization** -> **`heph agent` fake-model** -> **MCP smoke**. The
integrity and audit links live in ``test_packaged_sidecar.py``; the three in
bold live here, and all three are asserted through subprocesses of the venv the
wheels were installed into.

Running them from the repository instead would prove the *source tree* works —
which no user installs. Each one has a specific way of being wrong in a wheel
and right in a checkout:

* the JobStore reaches ``opstore``, a separately built distribution, and its
  slot budget is read from a JSON file that had to become package data;
* the agent path spawns the packaged sidecar, which only exists inside the
  installed distribution;
* ``heph serve --mcp`` is a console script whose server imports the whole
  contract surface, and it is the transport a third-party MCP client uses.

The fake model is scripted (`hephaestus.testing.fake_openai`), so no network and
no credential is involved anywhere in this file.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from _wheel import clean_env, json_in_venv, venv_script

pytestmark = pytest.mark.slow


# --------------------------------------------------------------------------
# Python-backed JobStore initialization


def test_the_jobstore_initializes_from_the_installed_wheel(
    installed_venv: Path, tmp_path: Path
) -> None:
    """Create a store, write, read back, and reopen it in a second process.

    The reopen matters: a JobStore that only works in the process that created
    it would still pass a single-process smoke, and the workflows runner's whole
    purpose is surviving a restart.
    """
    root = tmp_path / "store"
    program = f"""
import json
from pathlib import Path
from hephaestus.agent_bridge.admission import bridge_store_config, BRIDGE_RUN_SLOTS
from hephaestus.agent_bridge.jobstore import JobStore
from opstore import OpStore

root = Path({str(root)!r})
config = bridge_store_config()
store = OpStore.create(root, config) if not root.exists() else OpStore.open(root, config)
try:
    js = JobStore(store.db)
    js.put("jobs", "j1", {{"status": "RUNNING"}})
    seen = js.get("jobs", "j1")
finally:
    store.close()
print(json.dumps({{"slots": BRIDGE_RUN_SLOTS, "value": seen, "created": root.is_dir()}}))
"""
    first = json_in_venv(installed_venv, program)
    assert isinstance(first, dict)
    assert first["value"] == {"status": "RUNNING"}
    assert first["created"] is True
    # The 16-slot budget comes from schemas/bridge_limits.json, which is package
    # data in the wheel; a wrong-but-plausible default would show up here.
    assert first["slots"] == 16

    second = json_in_venv(installed_venv, program)
    assert isinstance(second, dict)
    assert second["value"] == {"status": "RUNNING"}, "the durable row did not survive reopen"


# --------------------------------------------------------------------------
# `heph agent` against the scripted fake model


@pytest.mark.skipif(shutil.which("node") is None, reason="lane (b) needs Node")
def test_a_scripted_model_drives_a_session_through_the_packaged_sidecar(
    installed_venv: Path, tmp_path: Path
) -> None:
    """A full prompt round trip: fake provider -> packaged sidecar -> events.

    ``BridgeRuntime`` is constructed with **no** ``dist_main=``, so it resolves
    the sidecar exactly the way `heph agent` does. The assertion on
    ``sidecar.source`` is what ties this to the gate: a completed prompt through
    a *development* sidecar would prove nothing about the wheel.
    """
    workdir = tmp_path / "agent"
    program = f"""
import json
from pathlib import Path
from hephaestus.agent_bridge.app import BridgeRuntime
from hephaestus.testing.fake_openai import start_fake_openai
from hephaestus.testing.projects import scaffold_project
from hephaestus.testing.stream_assertions import text

project = scaffold_project(Path({str(workdir)!r}), name="lane_b",
                           globals_src="PARAMS = {{}}\\n")
fake = start_fake_openai([text("the fake model answered")])
runtime = BridgeRuntime(project_root=project, providers=[fake.provider_spec()])
runtime.start()
try:
    session = runtime.create_session("orchestrator", session_id="lane-b")
    result = runtime.prompt(session, "say something", timeout=300)
    resolution = runtime.sidecar
    print(json.dumps({{
        "status": result.status,
        "source": None if resolution is None else resolution.source,
        "root": None if resolution is None else str(resolution.root),
    }}))
finally:
    runtime.close()
    fake.close()
"""
    payload = json_in_venv(installed_venv, program, env=clean_env(installed_venv))
    assert isinstance(payload, dict)
    assert payload["status"] == "completed", payload
    assert payload["source"] == "packaged", (
        f"the session ran through the {payload['source']} sidecar at {payload['root']}"
    )


# --------------------------------------------------------------------------
# MCP smoke over stdio


def test_heph_serve_mcp_speaks_the_protocol_over_stdio(
    installed_venv: Path, tmp_path: Path
) -> None:
    """Initialize + ``tools/list`` against the installed console script.

    Hand-rolled newline-delimited JSON-RPC rather than the SDK: the point is
    that a client with no Hephaestus code drives the installed server, and the
    smallest possible client is the most honest one. The heavier Stage-3 flows
    (create -> build -> inspect -> export) run in ``tests/stage3``; this is the
    packaging smoke, so it asserts the surface exists and is well formed.
    """
    project = tmp_path / "proj"
    project.mkdir()
    (project / "hephaestus.toml").write_text('[project]\nname = "smoke"\n')
    (project / "parts").mkdir()

    proc = subprocess.Popen(
        [str(venv_script(installed_venv, "heph")), "serve", "--mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(project),
        env=clean_env(installed_venv),
    )
    try:
        assert proc.stdin is not None and proc.stdout is not None

        def send(message: dict[str, object]) -> None:
            assert proc.stdin is not None
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()

        def receive() -> dict[str, object]:
            assert proc.stdout is not None
            while True:
                line = proc.stdout.readline()
                assert line, "the server closed stdout before answering"
                decoded = json.loads(line)
                assert isinstance(decoded, dict)
                if "id" in decoded:
                    return decoded

        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "g7h-smoke", "version": "0"},
                },
            }
        )
        initialized = receive()
        assert "result" in initialized, initialized
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        listed = receive()
        result = listed.get("result")
        assert isinstance(result, dict), listed
        tools = result.get("tools")
        assert isinstance(tools, list) and tools, listed
        names = {tool["name"] for tool in tools if isinstance(tool, dict)}
        assert {"build_part", "inspect_part", "write_part"} <= names, sorted(names)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            proc.kill()


def test_the_installed_serve_verb_exists_without_node(installed_venv: Path) -> None:
    """``heph serve --help`` must register even where no Node exists: the MCP
    server is Python, and only *agent* features need the sidecar."""
    proc = subprocess.run(
        [str(venv_script(installed_venv, "heph")), "serve", "--help"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(installed_venv),
        env={
            "PATH": str(venv_script(installed_venv, "").parent),
            "HOME": os.environ.get("HOME", ""),
        },
    )
    assert proc.returncode == 0, proc.stderr
    assert "--mcp" in proc.stdout
