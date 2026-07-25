"""Registry format, Merkle digest, pinning, and the ``heph registry`` verbs.

Covers the trust boundary itself: a registry is a directory whose entire content
tree hashes to one digest, that digest is pinned in ``hephaestus.toml``, and a
tree whose bytes no longer match refuses to load. Pinning is the only thing
standing between the model and arbitrary content, so the tamper paths — edited
byte, renamed file, added file, deleted file, edited manifest — are each asserted
rather than assumed to follow from "it's a hash".
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from hephaestus.core import cli_registry
from hephaestus.core.errors import ValidationError
from hephaestus.core.registry import (
    MANIFEST_FILENAME,
    RegistryIntegrityError,
    RegistryPin,
    RegistrySet,
    bundled_registries_root,
    load_registry,
    merkle_digest,
    parse_manifest,
    read_pins,
    tree_leaves,
    write_pins,
)

REPO = Path(__file__).resolve().parents[2]
REGISTRIES = REPO / "registries"

MANIFEST = """\
[registry]
name = "demo-skills"
kind = "skills"
version = "0.2.0"
license = "CC-BY-4.0"
description = "A two-page demo registry."

[[skills]]
name = "alpha"
file = "alpha.md"
summary = "The first page."

[[skills]]
name = "beta"
file = "pages/beta.md"
summary = "The second page."
"""


@pytest.fixture
def registry_root(tmp_path: Path) -> Path:
    root = tmp_path / "demo"
    (root / "pages").mkdir(parents=True)
    (root / MANIFEST_FILENAME).write_text(MANIFEST, encoding="utf-8")
    (root / "alpha.md").write_text("# alpha\n\nfirst page\n", encoding="utf-8")
    (root / "pages" / "beta.md").write_text("# beta\n\nsecond page\n", encoding="utf-8")
    return root


@pytest.fixture
def project(tmp_path: Path, registry_root: Path) -> Path:
    root = tmp_path / "proj"
    (root / "parts").mkdir(parents=True)
    (root / "globals.py").write_text("WALL = 2.0\n", encoding="utf-8")
    (root / "hephaestus.toml").write_text(
        f'name = "proj"\n\n[registries.skills]\npath = {json.dumps(str(registry_root))}\n',
        encoding="utf-8",
    )
    return root


# -- digest ----------------------------------------------------------------


def test_digest_is_stable_and_path_prefixed(registry_root: Path) -> None:
    first = merkle_digest(registry_root)
    assert first.startswith("sha256:")
    assert merkle_digest(registry_root) == first
    leaves = tree_leaves(registry_root)
    assert [rel for rel, _digest in leaves] == [
        "alpha.md",
        "pages/beta.md",
        "registry.toml",
    ]


def test_digest_ignores_dotfiles_and_pycache(registry_root: Path) -> None:
    before = merkle_digest(registry_root)
    (registry_root / ".DS_Store").write_bytes(b"junk")
    (registry_root / "__pycache__").mkdir()
    (registry_root / "__pycache__" / "x.pyc").write_bytes(b"\x00\x01")
    assert merkle_digest(registry_root) == before


def _edit_byte(root: Path) -> None:
    (root / "alpha.md").write_text("# alpha!\n", encoding="utf-8")


def _rename(root: Path) -> None:
    (root / "alpha.md").rename(root / "pages" / "alpha.md")


def _add(root: Path) -> None:
    (root / "gamma.md").write_text("extra\n", encoding="utf-8")


def _delete(root: Path) -> None:
    (root / "alpha.md").unlink()


def _edit_manifest(root: Path) -> None:
    (root / MANIFEST_FILENAME).write_text(MANIFEST.replace("0.2.0", "0.3.0"), encoding="utf-8")


@pytest.mark.parametrize(
    ("mutate", "label"),
    [
        (_edit_byte, "edited-byte"),
        (_rename, "renamed"),
        (_add, "added"),
        (_delete, "deleted"),
        (_edit_manifest, "edited-manifest"),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_every_tamper_class_changes_the_digest(
    registry_root: Path, mutate: Callable[[Path], None], label: str
) -> None:
    before = merkle_digest(registry_root)
    mutate(registry_root)
    assert merkle_digest(registry_root) != before, label


def test_a_moved_file_is_as_detectable_as_an_edited_one(tmp_path: Path) -> None:
    """Path is bound into the leaf, so swapping two files' contents is caught."""
    root = tmp_path / "swap"
    root.mkdir()
    (root / MANIFEST_FILENAME).write_text(MANIFEST, encoding="utf-8")
    (root / "a.md").write_text("AAA\n", encoding="utf-8")
    (root / "b.md").write_text("BBB\n", encoding="utf-8")
    before = merkle_digest(root)
    (root / "a.md").write_text("BBB\n", encoding="utf-8")
    (root / "b.md").write_text("AAA\n", encoding="utf-8")
    assert merkle_digest(root) != before


# -- load / verify ---------------------------------------------------------


def test_load_verifies_against_the_pin(registry_root: Path) -> None:
    digest = merkle_digest(registry_root)
    registry = load_registry(registry_root, expected_digest=digest)
    assert registry.pinned
    assert registry.kind == "skills"
    assert registry.manifest.version == "0.2.0"


def test_tampered_tree_refuses_to_load(registry_root: Path) -> None:
    digest = merkle_digest(registry_root)
    (registry_root / "alpha.md").write_text("# alpha\n\nINJECTED\n", encoding="utf-8")
    with pytest.raises(RegistryIntegrityError) as ei:
        load_registry(registry_root, expected_digest=digest)
    assert ei.value.reason == "registry_integrity"
    assert ei.value.expected == digest
    assert ei.value.actual != digest
    # The refusal names the deliberate re-pin path and nothing else.
    assert "heph registry update" in ei.value.message


def test_unpinned_load_reports_the_digest_but_verifies_nothing(registry_root: Path) -> None:
    registry = load_registry(registry_root)
    assert not registry.pinned
    assert registry.digest == merkle_digest(registry_root)


def test_registry_set_requires_pinning_when_asked(project: Path, registry_root: Path) -> None:
    with pytest.raises(RegistryIntegrityError):
        RegistrySet.open(project, fallback_to_bundled=False, require_pinned=True)
    pins = read_pins(project)
    pins["skills"] = RegistryPin(
        name="skills", path=str(registry_root), digest=merkle_digest(registry_root)
    )
    write_pins(project, pins)
    registries = RegistrySet.open(project, fallback_to_bundled=False, require_pinned=True)
    assert registries.skills.names() == ("alpha", "beta")


def test_manifest_errors_are_typed() -> None:
    with pytest.raises(ValidationError):
        parse_manifest("not = [toml")
    with pytest.raises(ValidationError):
        parse_manifest('[registry]\nname = "x"\nversion = "1"\nkind = "nonsense"\n')
    with pytest.raises(ValidationError):
        parse_manifest('[other]\nname = "x"\n')


# -- pin round-trip through hephaestus.toml --------------------------------


def test_pin_round_trip_preserves_the_rest_of_the_manifest(project: Path) -> None:
    manifest = project / "hephaestus.toml"
    manifest.write_text(
        'name = "proj"\nversion = "9.9"\n\n[params]\nwall = 3.0\n\n'
        '[registries.skills]\npath = "./old"\n',
        encoding="utf-8",
    )
    write_pins(
        project,
        {"skills": RegistryPin(name="skills", path="./new", digest="sha256:deadbeef")},
    )
    text = manifest.read_text(encoding="utf-8")
    assert 'version = "9.9"' in text
    assert "[params]" in text and "wall = 3.0" in text
    assert "./old" not in text
    pins = read_pins(project)
    assert pins["skills"].path == "./new"
    assert pins["skills"].digest == "sha256:deadbeef"


# -- the CLI verbs ---------------------------------------------------------


def _run(monkeypatch: pytest.MonkeyPatch, cwd: Path, *argv: str) -> int:
    monkeypatch.chdir(cwd)
    return cli_registry.main(["registry", *argv])


def test_cli_pin_update_verify_cycle(
    project: Path,
    registry_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Unpinned: verify fails closed (exit 1), naming the registry.
    assert _run(monkeypatch, project, "verify", "skills") == 1
    assert "unpinned" in capsys.readouterr().out

    assert _run(monkeypatch, project, "pin", "skills", "--json") == 0
    pinned = json.loads(capsys.readouterr().out)
    assert pinned["digest"] == merkle_digest(registry_root)
    assert _run(monkeypatch, project, "verify", "skills", "--json") == 0
    assert json.loads(capsys.readouterr().out)[0]["status"] == "ok"

    # Drift: verify fails, and pin refuses to silently re-pin.
    (registry_root / "alpha.md").write_text("# alpha\n\nchanged\n", encoding="utf-8")
    assert _run(monkeypatch, project, "verify", "skills", "--json") == 1
    record = json.loads(capsys.readouterr().out)[0]
    assert record["status"] == "drifted"
    assert record["expected_digest"] != record["digest"]

    assert _run(monkeypatch, project, "pin", "skills") == 1
    assert "registry_integrity" in capsys.readouterr().err

    # update is the one deliberate re-pin path.
    assert _run(monkeypatch, project, "update", "skills", "--json") == 0
    updated = json.loads(capsys.readouterr().out)[0]
    assert updated["changed"] is True
    assert updated["digest"] == merkle_digest(registry_root)
    assert _run(monkeypatch, project, "verify", "skills") == 0
    capsys.readouterr()


def test_cli_list_reports_status(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(monkeypatch, project, "list", "--json") == 0
    records = {r["name"]: r for r in json.loads(capsys.readouterr().out)}
    assert records["skills"]["status"] == "unpinned"
    assert records["skills"]["kind"] == "skills"
    assert records["skills"]["registry_name"] == "demo-skills"


def test_cli_unknown_registry_is_usage_error(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(monkeypatch, project, "verify", "nope") == 2
    assert "unknown registry" in capsys.readouterr().err


def test_cli_missing_tree_is_usage_error(
    project: Path,
    registry_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shutil.rmtree(registry_root)
    assert _run(monkeypatch, project, "update", "skills") == 2
    assert MANIFEST_FILENAME in capsys.readouterr().err


def test_registry_verbs_are_registered_on_the_engine_cli() -> None:
    from hephaestus.core.cli import build_parser

    args = build_parser().parse_args(["registry", "list", "--json"])
    assert args.command == "registry"
    assert args.registry_command == "list"


# -- the shipped registries ------------------------------------------------


def test_bundled_registries_load_and_are_discoverable() -> None:
    root = bundled_registries_root()
    assert root is not None and root == REGISTRIES
    for kind in ("skills", "parts", "materials"):
        registry = load_registry(root / kind)
        assert registry.kind == kind
        assert registry.manifest.license
        assert registry.digest.startswith("sha256:")
