# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G6: registry trust — content-hash pinning and sandbox parity.

Gate clause: *"a registry-integrity test (tampered registry tree fails the hash
check and refuses to load; a store part attempting file IO is denied by the
sandbox)"*, over the Stage 6 publishing story: publish computes the digest,
consume verifies it (mission_plan.md Stage 6; architecture.md §3.6, §7.2).

Both halves are asserted end to end:

* a project pinned to a published DFM registry runs its rules; edit one byte of
  a **rule predicate** — the executable half — and the same project refuses to
  load the registry at all, naming the drifted file, so a tampered rule can
  never be the thing that says the design is fine;
* a store part whose generator opens a file is denied by the same sandbox a part
  script runs under, through the real ``instance_store_part`` tool, and the
  refusal quotes no file contents.

The unit-level publish/pin coverage is ``core/tests/test_registry_publish.py``
and ``core/tests/test_registry_sandbox.py``; this module is the gate evidence.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from _g6 import REPO, make_g6_project, requires_bwrap
from hephaestus.agent_bridge.dispatch import DispatchError
from hephaestus.core import cli_registry
from hephaestus.core.registry import (
    MANIFEST_FILENAME,
    RegistryIntegrityError,
    RegistrySet,
    merkle_digest,
    publication_drift,
    publish_registry,
    read_pins,
)

#: The rule predicate the tamper edits: executable registry content, not prose.
TAMPERED_LEAF = "laser_cut/min_feature_vs_kerf.py"

HOSTILE_MANIFEST = """\
[registry]
name = "hostile-parts"
kind = "parts"
version = "0.0.1"
license = "Apache-2.0"

[[parts]]
id = "reads_a_file"
dir = "reads_a_file"
"""

#: A generator that reaches for the filesystem instead of making geometry.
HOSTILE_GENERATOR = """\
# --- hephaestus-store: params ---
PARAMS = {
    "size": Param(10.0, min=1.0, max=50.0),
}
# --- hephaestus-store: bind ---
_size = p.size
# --- hephaestus-store: body ---
_leak = open("/etc/passwd").read()
_solid = Box(_size, _size, _size)
part.geometry = _solid
"""


def _pin(root: Path, name: str, tree: Path) -> None:
    """Append a ``[registries.<name>]`` entry pointing at ``tree``."""
    manifest = root / "hephaestus.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + f"\n[registries.{name}]\npath = {json.dumps(str(tree))}\n",
        encoding="utf-8",
    )


def _publish(root: Path, name: str, monkeypatch: pytest.MonkeyPatch) -> int:
    """``heph registry publish <name>``: compute the digest and write the pin."""
    monkeypatch.chdir(root)
    return cli_registry.main(["registry", "publish", name, "--record", f"{name}.publication.json"])


@pytest.fixture
def dfm_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Path, Path]]:
    """A project pinned to its own published copy of the shipped DFM registry."""
    tree = tmp_path / "dfm-registry"
    shutil.copytree(REPO / "registries" / "dfm", tree)
    root = tmp_path / "proj"
    root.mkdir(parents=True)
    (root / "parts").mkdir()
    (root / "checks").mkdir()
    (root / "hephaestus.toml").write_text('[project]\nname = "g6"\n', encoding="utf-8")
    (root / "globals.py").write_text("PARAMS = {}\n", encoding="utf-8")
    _pin(root, "dfm", tree)
    assert _publish(root, "dfm", monkeypatch) == 0
    assert read_pins(root)["dfm"].digest == merkle_digest(tree)
    yield root, tree


# ==========================================================================
# publish computes the digest; consume verifies it


def test_a_published_registry_loads_and_serves_its_packs(dfm_project: tuple[Path, Path]) -> None:
    root, tree = dfm_project
    registries = RegistrySet.open(root)
    assert set(registries.dfm.processes()) >= {"laser_cut", "fdm"}
    pack = registries.dfm.get("laser_cut")
    # The pack states the digest of the bytes it came from — the pinned one.
    assert pack.digest == merkle_digest(tree)
    assert (tree / TAMPERED_LEAF).is_file(), "the tamper target must be a real predicate"


def test_a_tampered_predicate_fails_the_hash_check_and_refuses_to_load(
    dfm_project: tuple[Path, Path],
) -> None:
    root, tree = dfm_project
    before = merkle_digest(tree)
    predicate = tree / TAMPERED_LEAF
    predicate.write_text(
        predicate.read_text(encoding="utf-8").replace(
            "def evaluate(ctx", "def evaluate(ctx  # tampered", 1
        ),
        encoding="utf-8",
    )
    assert merkle_digest(tree) != before, "the tamper must change the tree hash"

    with pytest.raises(RegistryIntegrityError) as refusal:
        RegistrySet.open(root)
    assert refusal.value.expected == before
    assert refusal.value.actual == merkle_digest(tree)


def test_the_refusal_names_the_file_that_drifted(dfm_project: tuple[Path, Path]) -> None:
    """A consumer is told *which* bytes changed, not only that the hash moved."""
    _root, tree = dfm_project
    record = publish_registry(tree)
    (tree / TAMPERED_LEAF).write_text("def evaluate(ctx):\n    return None\n", encoding="utf-8")
    (tree / "extra.py").write_text("# smuggled in\n", encoding="utf-8")

    drift = {item.path: item.status for item in publication_drift(tree, record)}
    assert drift == {TAMPERED_LEAF: "modified", "extra.py": "added"}


def test_a_tampered_registry_stops_run_dfm_before_any_rule_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: the tool the model calls refuses, it does not report "clean"."""
    tree = tmp_path / "dfm-registry"
    shutil.copytree(REPO / "registries" / "dfm", tree)
    root = tmp_path / "proj"
    project = make_g6_project(root, ("vent_panel",), secure=False)
    try:
        _pin(root, "dfm", tree)
        assert _publish(root, "dfm", monkeypatch) == 0
        project.build("vent_panel")
        (tree / MANIFEST_FILENAME).write_text(
            (tree / MANIFEST_FILENAME).read_text(encoding="utf-8") + "\n# tampered\n",
            encoding="utf-8",
        )
        with pytest.raises((RegistryIntegrityError, DispatchError)) as refusal:
            project.call("run_dfm", {"name": "vent_panel"})
        assert "hash" in str(refusal.value).lower() or "digest" in str(refusal.value).lower()
    finally:
        project.close()


# ==========================================================================
# sandbox parity: registry content has no capability a part script lacks


@requires_bwrap
def test_a_store_part_that_opens_a_file_is_denied_by_the_sandbox(tmp_path: Path) -> None:
    tree = tmp_path / "hostile-parts"
    (tree / "reads_a_file").mkdir(parents=True)
    (tree / MANIFEST_FILENAME).write_text(HOSTILE_MANIFEST, encoding="utf-8")
    (tree / "reads_a_file" / "generator.py").write_text(HOSTILE_GENERATOR, encoding="utf-8")
    (tree / "reads_a_file" / "part.json").write_text(
        json.dumps(
            {
                "id": "reads_a_file",
                "name": "reads_a_file",
                "params": {"size": {"default": 10.0}},
            }
        ),
        encoding="utf-8",
    )

    # Published and pinned by digest: the generator is trusted content by every
    # measure the registry stack has — and is still executed under the sandbox.
    record = publish_registry(tree)
    project = make_g6_project(
        tmp_path / "proj",
        (),
        secure=True,
        wire_registry=True,
        manifest_extra=(
            f'\n[registries.parts]\npath = {json.dumps(str(tree))}\ndigest = "{record.digest}"\n'
        ),
    )
    try:
        with pytest.raises(DispatchError) as refusal:
            project.call("instance_store_part", {"id": "reads_a_file", "params": {"size": 10.0}})
    finally:
        project.close()

    assert refusal.value.reason in {"generator_failed", "sandbox_denied"}
    assert "reads_a_file" in str(refusal.value)
    # Nothing leaked: the refusal reports a denial, never file contents.
    assert "root:" not in str(refusal.value)


def test_an_unpinned_registry_is_refused_when_pinning_is_required(
    dfm_project: tuple[Path, Path],
) -> None:
    """``require_pinned`` is the serving runtime's "every byte was accepted"."""
    root, tree = dfm_project
    manifest = root / "hephaestus.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(f'digest = "{merkle_digest(tree)}"\n', ""),
        encoding="utf-8",
    )
    assert read_pins(root)["dfm"].digest is None
    RegistrySet.open(root)  # unpinned is allowed by default…
    with pytest.raises(RegistryIntegrityError):  # …and refused when required.
        RegistrySet.open(root, require_pinned=True)
