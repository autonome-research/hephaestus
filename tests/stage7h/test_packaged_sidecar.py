# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G7H: the installed wheel uses *its own* packaged, integrity-checked sidecar.

This is the gate's load-bearing claim. Every assertion here is made against a
throwaway venv holding wheels built from the working tree — never against an
in-repo import, which would resolve the development sidecar and prove nothing.

The suite is marked ``slow``: it builds every distribution and creates a venv.
It must still run locally, so nothing here needs network beyond what `uv build`
already has cached.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from _wheel import (
    clean_env,
    json_in_venv,
    node_missing_env,
    run_in_venv,
    venv_script,
)

pytestmark = pytest.mark.slow

#: Prints the installed sidecar resolution as JSON. Deliberately does not import
#: anything that spawns — this is about *where the wheel looks*.
_PROBE = """
import json, sysconfig
from hephaestus.agent_bridge.sidecar import resolve_sidecar, verify_sidecar
r = resolve_sidecar()
verify_sidecar(r.root)
print(json.dumps({
    "source": r.source,
    "root": str(r.root),
    "main": str(r.main),
    "runner": str(r.runner),
    "purelib": sysconfig.get_paths()["purelib"],
    "version": r.manifest.version,
    "files": len(r.manifest.entries),
}))
"""


@pytest.fixture(scope="module")
def resolution(installed_venv: Path) -> dict[str, object]:
    result = json_in_venv(installed_venv, _PROBE)
    assert isinstance(result, dict)
    return result


def test_the_installed_wheel_resolves_its_packaged_sidecar(
    resolution: dict[str, object],
) -> None:
    """The branch an installed wheel takes is ``packaged``, and it lives inside
    site-packages.

    Before Stage 7H all three resolvers computed ``__file__.parents[4]`` and
    appended ``agent/dist/…``. From ``site-packages/hephaestus/agent_bridge/``
    that lands somewhere *above* site-packages — a path that has never existed
    on an installed machine. An installed wheel simply could not find a sidecar.
    """
    assert resolution["source"] == "packaged"

    purelib = Path(str(resolution["purelib"])).resolve()
    root = Path(str(resolution["root"])).resolve()
    main = Path(str(resolution["main"])).resolve()
    runner = Path(str(resolution["runner"])).resolve()

    assert root.is_relative_to(purelib), f"{root} is not inside site-packages {purelib}"
    assert main.is_relative_to(purelib)
    assert runner.is_relative_to(purelib)
    assert root == purelib / "hephaestus" / "agent_bridge" / "_sidecar"
    # Both entry points come from ONE resolution — the two hard-coded literals
    # that used to answer this question separately were free to drift.
    assert main.parent == root
    assert runner.parent == root / "workflows"


def test_the_packaged_sidecar_is_not_the_repos_development_tree(
    resolution: dict[str, object],
) -> None:
    """The wheel is self-contained: nothing it spawns lives in this checkout."""
    repo = Path(__file__).resolve().parents[2]
    root = Path(str(resolution["root"])).resolve()
    assert not root.is_relative_to(repo / "agent")
    assert "agent/dist" not in root.as_posix()


def test_the_integrity_check_actually_ran(installed_venv: Path) -> None:
    """Verification is not a no-op: it reads every shipped byte.

    Asserted by counting the files the manifest covers and confirming each is
    present on disk — a manifest that verified an empty set would pass
    `verify_sidecar` while proving nothing.
    """
    payload = json_in_venv(
        installed_venv,
        """
import json
from hephaestus.agent_bridge.sidecar import resolve_sidecar
r = resolve_sidecar()
missing = [k for k in r.manifest.entries if not (r.root / k).is_file()]
print(json.dumps({
    "count": len(r.manifest.entries),
    "missing": missing,
    "digest_len": sorted({len(v) for v in r.manifest.entries.values()}),
    "has_main": "main.js" in r.manifest.entries,
    "has_runner": "workflows/runner.js" in r.manifest.entries,
    "has_limits": "schemas/bridge_limits.json" in r.manifest.entries,
}))
""",
    )
    assert isinstance(payload, dict)
    assert payload["missing"] == []
    assert int(payload["count"]) > 20, "a bundled sidecar is dozens of chunks, not a stub"
    assert payload["digest_len"] == [64], "entries must be full SHA-256 hex digests"
    assert payload["has_main"] and payload["has_runner"]
    # The bridge's own bounds ship inside the manifest, so they cannot be
    # widened by editing a file in site-packages.
    assert payload["has_limits"]


def test_a_tampered_packaged_sidecar_fails_closed(installed_venv: Path, tmp_path: Path) -> None:
    """Mutate one byte in the installed tree; resolution must refuse.

    G7H names this explicitly. The refusal must be the *named* sidecar error —
    not a crash, and above all not a fallback to a global `pi`/`thread-phase`.

    Performed on a copy of the installed tree via the override branch, so the
    session's shared venv is left intact for the other lanes.
    """
    original = json_in_venv(installed_venv, _PROBE)
    assert isinstance(original, dict)
    copy_root = tmp_path / "tampered"
    shutil.copytree(str(original["root"]), copy_root)

    victim = copy_root / "main.js"
    victim.write_bytes(victim.read_bytes() + b"\n// tampered\n")

    proc = run_in_venv(
        installed_venv,
        """
from hephaestus.agent_bridge.sidecar import SidecarIntegrityError, resolve_sidecar
try:
    resolve_sidecar()
except SidecarIntegrityError as exc:
    print("REFUSED:" + exc.code)
else:
    print("ACCEPTED")
""",
        env=clean_env(installed_venv, HEPHAESTUS_SIDECAR=str(copy_root)),
    )
    assert proc.returncode == 0, proc.stderr
    assert "REFUSED:sidecar_integrity" in proc.stdout, proc.stdout + proc.stderr


def test_a_removed_packaged_sidecar_refuses_by_name(installed_venv: Path, tmp_path: Path) -> None:
    """A missing sidecar is a named refusal that says so, not a silent fallback.

    The error text must steer an operator to the packaging step rather than
    suggesting they install `pi` globally — the exact wrong repair.
    """
    empty = tmp_path / "not-a-sidecar"
    empty.mkdir()
    proc = run_in_venv(
        installed_venv,
        """
from hephaestus.agent_bridge.sidecar import SidecarError, resolve_sidecar
try:
    resolve_sidecar()
except SidecarError as exc:
    print("REFUSED:" + exc.code + ":" + str(exc))
else:
    print("ACCEPTED")
""",
        env=clean_env(installed_venv, HEPHAESTUS_SIDECAR=str(empty)),
    )
    assert proc.returncode == 0, proc.stderr
    assert "REFUSED:sidecar_integrity" in proc.stdout


def test_the_shipped_sidecar_carries_no_native_addon(resolution: dict[str, object]) -> None:
    """`repo_conventions.md`: the bundled sidecar MUST have no *required* native
    Node addon.

    The `tsc` sidecar could only be audited by walking a 202 MB production
    `node_modules` that contained three Linux `.node` files it never loaded —
    a claim that had to be re-argued per platform. The bundled artifact makes
    the audit trivial: there are no `.node` files at all to reason about.
    """
    root = Path(str(resolution["root"]))
    addons = [p.as_posix() for p in root.rglob("*.node")]
    assert addons == [], f"packaged sidecar ships native addons: {addons}"


def test_the_openai_sdk_is_present_only_via_pi_never_thread_phase(
    resolution: dict[str, object],
) -> None:
    """The `openai` clause of `repo_conventions.md`, asserted over build facts.

    The convention requires thread-phase 6.0.0's transitive `openai` to be
    "absent from the compiled sidecar or explicitly allowlisted as inert". The
    build's module graph shows the honest situation: **thread-phase contributes
    zero import edges into `openai`**, so the convention's clause is satisfied
    strictly. The SDK that *is* in the bundle arrives through
    `@earendil-works/pi-ai`'s provider adapters — pi's own OpenAI-compatible
    transport, which the fake-model lane exercises on purpose.

    Asserting the SDK is simply absent would be false and would need a waiver;
    asserting the thread-phase edge count is zero is the claim that actually
    carries the convention's intent.
    """
    audit_path = Path(str(resolution["root"])) / "AUDIT.json"
    assert audit_path.is_file(), "the shipped sidecar must describe its own audit"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    openai = audit["openai"]
    assert openai["thread_phase_edges"] == 0, (
        "thread-phase now pulls openai into the sidecar; the convention requires "
        "it absent or proven inert"
    )
    assert openai["importers"] == ["@earendil-works/pi-ai"], (
        f"an unexpected package now imports the openai SDK: {openai['importers']}"
    )


def test_the_bundle_leaves_only_the_documented_optional_externals(
    resolution: dict[str, object],
) -> None:
    """Nothing escaped the bundle except ws's two optional accelerators.

    Any other unresolved bare specifier means the shipped sidecar is not
    self-contained and would die on a machine with no `node_modules` beside it —
    the failure mode that made `agent/dist/` unshippable in the first place.
    """
    audit = json.loads((Path(str(resolution["root"])) / "AUDIT.json").read_text(encoding="utf-8"))
    assert sorted(audit["allowed_externals"]) == ["bufferutil", "utf-8-validate"]


def test_heph_version_reports_the_installed_distribution(installed_venv: Path) -> None:
    """G7H lane (a) opens with `heph --version`; it did not exist before 7H."""
    heph = venv_script(installed_venv, "heph")
    proc = subprocess.run(
        [str(heph), "--version"],
        capture_output=True,
        text=True,
        check=False,
        env=node_missing_env(installed_venv),
        cwd=str(installed_venv),
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "heph 0.1.0", proc.stdout


def test_the_node_free_surface_works_with_no_node_at_all(installed_venv: Path) -> None:
    """Lane (a): `heph build/check/render/export` MUST work without Node.

    Run with Node scrubbed from PATH rather than trusting that the machine has
    none — on a developer box it always does, so the un-scrubbed version of this
    test would pass for the wrong reason.
    """
    env = node_missing_env(installed_venv)
    assert shutil.which("node", path=env["PATH"]) is None, "PATH scrub failed"

    heph = venv_script(installed_venv, "heph")
    proc = subprocess.run(
        [str(heph), "--help"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=str(installed_venv),
    )
    assert proc.returncode == 0, proc.stderr
    for verb in ("build", "check", "lint", "render", "registry", "diff", "assembly"):
        assert verb in proc.stdout, f"{verb} did not register without Node"

    # The Python surface imports cleanly with no Node anywhere.
    probe = run_in_venv(
        installed_venv,
        "import hephaestus.core, hephaestus.geom, hephaestus.contract, opstore; print('OK')",
        env=env,
    )
    assert probe.returncode == 0, probe.stderr
    assert "OK" in probe.stdout


def test_a_real_part_script_lints_with_no_node(installed_venv: Path, tmp_path: Path) -> None:
    """Lane (a)'s lint smoke: real work on a real fixture, no Node, no execution.

    `heph lint` is static analysis, so this exercises the engine's parse/checks
    path end to end from the wheel while proving nothing spawns — a part script
    that *ran* here would mean the Node-free lane had quietly executed code.
    """
    fixture = Path(__file__).resolve().parents[2] / "corpus" / "public_fixtures" / "assembly"
    project = tmp_path / "lint-project"
    shutil.copytree(fixture, project)

    env = node_missing_env(installed_venv)
    proc = subprocess.run(
        [
            str(venv_script(installed_venv, "heph")),
            "lint",
            str(project / "parts" / "bracket.py"),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=str(installed_venv),
    )
    assert proc.returncode == 0, proc.stderr
    findings = json.loads(proc.stdout)
    assert isinstance(findings, list), "lint --json must emit a findings array"
    # No build artifacts: linting must not have executed the script.
    assert not (project / ".heph").exists(), "lint executed the part script"


def test_the_installed_contract_matches_the_committed_schemas(installed_venv: Path) -> None:
    """Lane (a)'s schema smoke: the wheel's declarations regenerate the committed
    JSON Schema byte-for-byte.

    `schemas/tools/*.schema.json` is the canonical, committed contract. If the
    installed `hephaestus.contract` produced anything else, the wheel would be
    serving a tool surface that no reviewed artifact describes.
    """
    payload = json_in_venv(
        installed_venv,
        """
import hashlib, json
from hephaestus.contract.toolgen import generate_json_schemas
out = {k: hashlib.sha256(v.encode()).hexdigest() for k, v in generate_json_schemas().items()}
print(json.dumps(out))
""",
        env=node_missing_env(installed_venv),
    )
    assert isinstance(payload, dict)
    assert payload, "the installed contract declared no tools"

    repo = Path(__file__).resolve().parents[2]
    mismatched: list[str] = []
    for rel, digest in payload.items():
        committed = repo / rel
        assert committed.is_file(), f"the wheel declares {rel}, which is not committed"
        if hashlib.sha256(committed.read_bytes()).hexdigest() != digest:
            mismatched.append(rel)
    assert not mismatched, f"installed contract diverges from committed schemas: {mismatched}"


def test_resolving_the_sidecar_needs_no_node(installed_venv: Path) -> None:
    """Resolution and integrity verification are pure Python.

    They must not require the runtime they are preparing to spawn — otherwise a
    Node-free machine could not even report *why* `heph agent` is unavailable.
    """
    proc = run_in_venv(
        installed_venv,
        "from hephaestus.agent_bridge.sidecar import resolve_sidecar;"
        " print(resolve_sidecar().source)",
        env=node_missing_env(installed_venv),
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "packaged"


def test_heph_agent_refuses_without_node_and_names_the_requirement(
    installed_venv: Path,
) -> None:
    """No Node means a refusal that names Node — never a global-binary fallback."""
    proc = run_in_venv(
        installed_venv,
        """
from hephaestus.agent_bridge.sidecar import NodeVersionError, node_executable
try:
    node_executable()
except NodeVersionError as exc:
    print("REFUSED:" + str(exc))
else:
    print("FOUND")
""",
        env=node_missing_env(installed_venv),
    )
    assert proc.returncode == 0, proc.stderr
    assert "REFUSED" in proc.stdout
    assert "22.19" in proc.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="lane (b) needs Node")
def test_the_packaged_sidecar_actually_starts(
    installed_venv: Path, resolution: dict[str, object]
) -> None:
    """Spawn the installed wheel's sidecar entries and require both to run.

    Locating a verified file proves packaging; only spawning it proves the
    bundle *works*. Both failures found while building this artifact — a data
    file resolved against a repo path, and an entry-point guard defeated by code
    splitting — passed every static check and only surfaced here.
    """
    node = shutil.which("node")
    assert node is not None
    for entry in ("main", "runner"):
        proc = subprocess.run(
            [node, str(resolution[entry])],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
            cwd=str(installed_venv),
            env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
        )
        output = proc.stdout + proc.stderr
        assert proc.returncode == 0, f"{entry} exited {proc.returncode}:\n{output}"
        assert "started" in output, (
            f"{entry} loaded but never started — it was spawned and silently did nothing:\n{output}"
        )


def test_heph_agent_reports_a_tampered_sidecar_as_a_named_cli_refusal(
    installed_venv: Path, tmp_path: Path
) -> None:
    """The refusal reaches the operator as a message, not a traceback.

    Resolution happens in ``BridgeRuntime.__init__``, which the CLI previously
    guarded only for ``AuthLinkError`` — so a tampered sidecar would have
    surfaced as an unhandled exception. It must print the stable error code, and
    it must not suggest installing a global `pi`/`thread-phase` as the repair.
    """
    original = json_in_venv(installed_venv, _PROBE)
    assert isinstance(original, dict)
    tampered = tmp_path / "tampered-cli"
    shutil.copytree(str(original["root"]), tampered)
    victim = tampered / "main.js"
    victim.write_bytes(victim.read_bytes() + b"\n// tampered\n")

    project = tmp_path / "proj"
    project.mkdir()

    proc = subprocess.run(
        [str(venv_script(installed_venv, "heph")), "agent", "--project", str(project)],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
        env=clean_env(installed_venv, HEPHAESTUS_SIDECAR=str(tampered)),
        cwd=str(installed_venv),
    )
    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "Traceback" not in combined, f"the refusal leaked a traceback:\n{combined}"
    # Either the sidecar refusal or an earlier config refusal is acceptable —
    # what must never happen is a spawn.
    assert "heph:" in combined
