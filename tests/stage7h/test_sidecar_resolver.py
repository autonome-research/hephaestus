# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""The sidecar resolution policy and its integrity check, in isolation.

Fast unit coverage of :mod:`hephaestus.agent_bridge.sidecar`. The wheel lanes in
:mod:`test_packaged_sidecar` prove the policy holds for a real installation;
these prove each *branch* of it behaves, including the ones a healthy
installation never takes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hephaestus.agent_bridge.sidecar import (
    MANIFEST_NAME,
    MINIMUM_NODE,
    NodeVersionError,
    SidecarIntegrityError,
    SidecarMissingError,
    resolve_sidecar,
    verify_sidecar,
    write_manifest,
)


def _sidecar_tree(root: Path) -> Path:
    """A minimal, valid sidecar tree with both entry points."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "main.js").write_text("console.log('main');\n", encoding="utf-8")
    (root / "workflows").mkdir()
    (root / "workflows" / "runner.js").write_text("console.log('runner');\n", encoding="utf-8")
    (root / "chunk-AAAA.js").write_text("export const x = 1;\n", encoding="utf-8")
    write_manifest(root, version="9.9.9")
    return root


def test_a_freshly_manifested_tree_verifies(tmp_path: Path) -> None:
    root = _sidecar_tree(tmp_path / "sc")
    manifest = verify_sidecar(root)
    assert manifest.version == "9.9.9"
    assert manifest.entrypoints == {"main": "main.js", "runner": "workflows/runner.js"}
    # The manifest covers every shipped file, not just the entry points.
    assert set(manifest.entries) == {"main.js", "workflows/runner.js", "chunk-AAAA.js"}


def test_a_mutated_byte_fails_closed(tmp_path: Path) -> None:
    """The tamper case G7H names explicitly."""
    root = _sidecar_tree(tmp_path / "sc")
    target = root / "chunk-AAAA.js"
    target.write_text("export const x = 2;  // tampered\n", encoding="utf-8")
    with pytest.raises(SidecarIntegrityError, match="does not match its manifest digest"):
        verify_sidecar(root)


def test_a_deleted_file_fails_closed(tmp_path: Path) -> None:
    root = _sidecar_tree(tmp_path / "sc")
    (root / "chunk-AAAA.js").unlink()
    with pytest.raises(SidecarIntegrityError, match="missing 1 manifested file"):
        verify_sidecar(root)


def test_a_planted_file_fails_closed(tmp_path: Path) -> None:
    """Verification is bidirectional — an *added* module is tampering too.

    The bundle is a chunk graph. A file the manifest never listed is reachable
    the moment an existing chunk names it, so "every manifested file is intact"
    is not on its own a safe statement.
    """
    root = _sidecar_tree(tmp_path / "sc")
    (root / "chunk-EVIL.js").write_text("process.exit(0);\n", encoding="utf-8")
    with pytest.raises(SidecarIntegrityError, match="absent from its manifest"):
        verify_sidecar(root)


def test_a_missing_manifest_fails_closed(tmp_path: Path) -> None:
    root = _sidecar_tree(tmp_path / "sc")
    (root / MANIFEST_NAME).unlink()
    with pytest.raises(SidecarIntegrityError, match=f"no {MANIFEST_NAME}"):
        verify_sidecar(root)


def test_a_manifest_with_a_foreign_algorithm_is_refused(tmp_path: Path) -> None:
    """A manifest may not choose its own (weaker) hash."""
    root = _sidecar_tree(tmp_path / "sc")
    manifest_path = root / MANIFEST_NAME
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    doc["algorithm"] = "md5"
    manifest_path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(SidecarIntegrityError, match="unsupported algorithm"):
        verify_sidecar(root)


def test_a_manifest_missing_an_entrypoint_is_refused(tmp_path: Path) -> None:
    root = _sidecar_tree(tmp_path / "sc")
    manifest_path = root / MANIFEST_NAME
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    del doc["entrypoints"]["runner"]
    manifest_path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(SidecarIntegrityError, match="no runner entrypoint"):
        verify_sidecar(root)


def test_the_override_branch_wins_and_is_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _sidecar_tree(tmp_path / "sc")
    monkeypatch.setenv("HEPHAESTUS_SIDECAR", str(root))
    resolution = resolve_sidecar()
    assert resolution.source == "override"
    assert resolution.root == root.resolve()
    assert resolution.main == root.resolve() / "main.js"
    assert resolution.runner == root.resolve() / "workflows" / "runner.js"


def test_an_override_naming_nothing_refuses_rather_than_falling_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A named override that does not exist is an error, never a silent demotion.

    If a pinned override could quietly fall through to the packaged sidecar, a
    CI lane that meant to test artifact X would pass while testing artifact Y.
    """
    monkeypatch.setenv("HEPHAESTUS_SIDECAR", str(tmp_path / "nowhere"))
    with pytest.raises(SidecarMissingError, match="names no sidecar directory"):
        resolve_sidecar()


def test_an_override_that_fails_integrity_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _sidecar_tree(tmp_path / "sc")
    (root / "main.js").write_text("console.log('swapped');\n", encoding="utf-8")
    monkeypatch.setenv("HEPHAESTUS_SIDECAR", str(root))
    with pytest.raises(SidecarIntegrityError):
        resolve_sidecar()


def test_the_repo_resolves_a_verified_sidecar() -> None:
    """In this source checkout, resolution succeeds and integrity holds.

    Which branch wins depends on whether the tree has been staged into
    `hephaestus.agent_bridge` (editable installs see the packaged copy); both are
    legitimate here. What must never happen is an unverified resolution.
    """
    resolution = resolve_sidecar()
    assert resolution.source in {"packaged", "development"}
    assert resolution.main.is_file()
    assert resolution.runner.is_file()
    verify_sidecar(resolution.root)


def test_the_node_check_rejects_a_too_old_runtime_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`repo_conventions.md` requires an *explicit* startup compatibility check.

    Before Stage 7H the bridge only checked that some `node` existed, so an old
    runtime surfaced as an unexplained child crash on modern syntax rather than
    a message naming the required version.

    The gate is on the Node found *on PATH* — the case it exists for.
    """
    from hephaestus.agent_bridge import sidecar as sidecar_mod

    fake = tmp_path / "node"
    fake.write_text("#!/bin/sh\necho v20.11.1\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.delenv("HEPHAESTUS_NODE", raising=False)
    monkeypatch.setattr(sidecar_mod.shutil, "which", lambda _name: str(fake))
    with pytest.raises(NodeVersionError, match="older than the required"):
        sidecar_mod.node_executable()


def test_the_node_check_accepts_the_supported_floor_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hephaestus.agent_bridge import sidecar as sidecar_mod

    major, minor = MINIMUM_NODE
    fake = tmp_path / "node"
    fake.write_text(f"#!/bin/sh\necho v{major}.{minor}.0\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.delenv("HEPHAESTUS_NODE", raising=False)
    monkeypatch.setattr(sidecar_mod.shutil, "which", lambda _name: str(fake))
    assert sidecar_mod.node_executable() == str(fake)


def test_an_explicit_node_override_is_honoured_verbatim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """$HEPHAESTUS_NODE means "spawn exactly this", version gate included.

    It is not a hint about where Node lives. The bridge's own test harness
    points it at a *Python* interpreter to run a scripted fake sidecar with no
    Node in the picture at all (see
    ``server/tests/test_supervisor.py::test_bridge_runtime_replays_its_own_configure_payload_on_every_child``),
    and `heph agent` has always honoured it that way. Version-gating an
    explicitly named interpreter would break that standing contract while
    protecting nobody — the operator naming a binary has already decided.
    """
    import sys

    from hephaestus.agent_bridge.sidecar import node_executable

    # A Python interpreter reports "3.13.x", which the gate would reject.
    monkeypatch.setenv("HEPHAESTUS_NODE", sys.executable)
    assert node_executable() == sys.executable


def test_an_absent_node_names_the_required_version(monkeypatch: pytest.MonkeyPatch) -> None:
    from hephaestus.agent_bridge import sidecar as sidecar_mod

    monkeypatch.delenv("HEPHAESTUS_NODE", raising=False)
    monkeypatch.setattr(sidecar_mod.shutil, "which", lambda _name: None)
    with pytest.raises(NodeVersionError, match=r">=22\.19"):
        sidecar_mod.node_executable()


def test_write_manifest_refuses_a_tree_with_no_entrypoint(tmp_path: Path) -> None:
    """The producer will not mint a manifest for something unspawnable."""
    root = tmp_path / "sc"
    root.mkdir()
    (root / "chunk-AAAA.js").write_text("export const x = 1;\n", encoding="utf-8")
    with pytest.raises(SidecarMissingError, match="no main entry"):
        write_manifest(root, version="0.0.0")
