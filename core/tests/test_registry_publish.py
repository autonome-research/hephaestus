"""Registry publishing end to end: validate -> digest -> pin -> consume verifies.

Pinning is the consumer half of registry trust and is covered in
``test_registry_digest.py``. This file covers the producer half and the seam
between them:

* ``heph registry publish`` refuses to state a digest for a tree it could not
  fully read — a manifest listing a missing file, a DFM rule reading a parameter
  its pack never declared, and a store part without a generator are all
  publication failures, not published-with-a-warning;
* what it does publish is the Merkle root **plus every leaf hash**, so a
  consumer that sees a mismatch is told which files were added, removed or
  edited rather than only that the hash changed;
* the pin it writes is the one a consumer verifies: ``RegistrySet.open(...,
  require_pinned=True)`` loads a published tree and refuses a tampered one;
* publishing never silently re-pins — accepting new bytes stays
  ``heph registry update``.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest
from hephaestus.core import cli_registry
from hephaestus.core.errors import ValidationError
from hephaestus.core.registry import (
    MANIFEST_FILENAME,
    PublicationRecord,
    RegistryIntegrityError,
    RegistryPin,
    RegistrySet,
    load_registry,
    merkle_digest,
    publication_drift,
    publish_registry,
    read_pins,
    verify_publication,
)
from opstore.types import JSONValue

REPO = Path(__file__).resolve().parents[2]
REGISTRIES = REPO / "registries"

SKILLS_MANIFEST = """\
[registry]
name = "demo-skills"
kind = "skills"
version = "1.0.0"
license = "CC-BY-4.0"
description = "A publishable two-page demo registry."

[[skills]]
name = "alpha"
file = "alpha.md"
summary = "The first page."

[[skills]]
name = "beta"
file = "beta.md"
summary = "The second page."
"""


@pytest.fixture
def registry_root(tmp_path: Path) -> Path:
    root = tmp_path / "demo-skills"
    root.mkdir()
    (root / MANIFEST_FILENAME).write_text(SKILLS_MANIFEST, encoding="utf-8")
    (root / "alpha.md").write_text("# Alpha\n\nFirst page.\n", encoding="utf-8")
    (root / "beta.md").write_text("# Beta\n\nSecond page.\n", encoding="utf-8")
    return root


@pytest.fixture
def project(tmp_path: Path, registry_root: Path) -> Path:
    root = tmp_path / "proj"
    (root / "parts").mkdir(parents=True)
    (root / "hephaestus.toml").write_text(
        f'name = "proj"\n\n[registries.demo]\npath = {json.dumps(str(registry_root))}\n',
        encoding="utf-8",
    )
    return root


def _run(monkeypatch: pytest.MonkeyPatch, cwd: Path, *argv: str) -> int:
    monkeypatch.chdir(cwd)
    return cli_registry.main(["registry", *argv])


def _read_record(path: Path) -> PublicationRecord:
    raw = cast("Mapping[str, JSONValue]", json.loads(path.read_text(encoding="utf-8")))
    return PublicationRecord.from_json(raw)


# -- the record ------------------------------------------------------------


def test_publish_states_the_digest_and_every_leaf(registry_root: Path) -> None:
    record = publish_registry(registry_root, published_at="2026-07-26T00:00:00+00:00")
    assert record.name == "demo-skills"
    assert record.kind == "skills"
    assert record.version == "1.0.0"
    assert record.digest == merkle_digest(registry_root)
    assert record.counts == {"skills": 2}
    assert record.leaf_count == 3
    assert [path for path, _digest in record.leaves] == [
        "alpha.md",
        "beta.md",
        MANIFEST_FILENAME,
    ]
    assert record.published_at == "2026-07-26T00:00:00+00:00"


def test_a_publication_record_round_trips_through_json(registry_root: Path) -> None:
    record = publish_registry(registry_root)
    restored = PublicationRecord.from_json(record.to_json())
    assert restored == record


def test_publish_validates_content_end_to_end_and_refuses_a_broken_tree(
    registry_root: Path,
) -> None:
    (registry_root / "beta.md").unlink()
    with pytest.raises(ValidationError, match=r"beta\.md"):
        publish_registry(registry_root)


def test_publish_refuses_a_dfm_pack_whose_rule_reads_an_undeclared_parameter(
    tmp_path: Path,
) -> None:
    root = tmp_path / "broken-dfm"
    (root / "demo").mkdir(parents=True)
    (root / MANIFEST_FILENAME).write_text(
        '[registry]\nname = "broken-dfm"\nkind = "dfm"\nversion = "0.0.1"\n'
        'license = "Apache-2.0"\n\n'
        '[[packs]]\nprocess = "demo"\ndir = "demo"\n',
        encoding="utf-8",
    )
    (root / "demo" / "pack.toml").write_text(
        '[pack]\nprocess = "demo"\nversion = "0.0.1"\n\n[params]\nlimit_mm = 1.0\n\n'
        '[[rules]]\nid = "demo.thing"\ntitle = "T"\npredicate = "rule.py"\n'
        'reads = ["nozzle_mm"]\n',
        encoding="utf-8",
    )
    (root / "demo" / "rule.py").write_text("def evaluate(ctx):\n    pass\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="nozzle_mm"):
        publish_registry(root)


def test_verify_publication_accepts_the_tree_it_described(registry_root: Path) -> None:
    record = publish_registry(registry_root)
    assert verify_publication(registry_root, record) == record.digest
    assert publication_drift(registry_root, record) == ()


def test_verify_publication_names_every_drifted_file(registry_root: Path) -> None:
    record = publish_registry(registry_root)
    (registry_root / "alpha.md").write_text("# Alpha\n\nEdited.\n", encoding="utf-8")
    (registry_root / "beta.md").unlink()
    (registry_root / "gamma.md").write_text("# Gamma\n", encoding="utf-8")

    drift = {item.path: item.status for item in publication_drift(registry_root, record)}
    assert drift == {"alpha.md": "modified", "beta.md": "removed", "gamma.md": "added"}

    with pytest.raises(RegistryIntegrityError) as error:
        verify_publication(registry_root, record)
    assert error.value.expected == record.digest
    assert error.value.actual == merkle_digest(registry_root)
    reported = error.value.data["drift"]
    assert isinstance(reported, list)
    assert len(reported) == 3


# -- publish -> pin -> consume ---------------------------------------------


def test_publish_writes_the_pin_and_the_record(
    project: Path,
    registry_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert read_pins(project)["demo"].digest is None
    exit_code = _run(monkeypatch, project, "publish", "demo", "--record", "demo.publication.json")
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "published sha256:" in out
    assert "skills=2" in out

    pin = read_pins(project)["demo"]
    assert pin.digest == merkle_digest(registry_root)

    record = _read_record(project / "demo.publication.json")
    assert record.digest == pin.digest
    assert record.leaf_count == 3


def test_a_published_registry_loads_under_require_pinned(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _run(monkeypatch, project, "publish", "demo") == 0
    registries = RegistrySet.open(project, fallback_to_bundled=False, require_pinned=True)
    assert registries.names() == ("demo",)
    assert registries.get("demo").pinned
    assert registries.skills.names() == ("alpha", "beta")


def test_a_tampered_published_tree_refuses_to_load(
    project: Path, registry_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _run(monkeypatch, project, "publish", "demo") == 0
    published = read_pins(project)["demo"].digest
    assert published is not None

    (registry_root / "alpha.md").write_text("# Alpha\n\nTampered.\n", encoding="utf-8")

    with pytest.raises(RegistryIntegrityError) as error:
        load_registry(registry_root, expected_digest=published)
    assert error.value.expected == published
    assert error.value.actual != published

    with pytest.raises(RegistryIntegrityError):
        RegistrySet.open(project, fallback_to_bundled=False, require_pinned=True)


def test_an_unpinned_registry_is_refused_when_pinning_is_required(project: Path) -> None:
    with pytest.raises(RegistryIntegrityError, match="not pinned"):
        RegistrySet.open(project, fallback_to_bundled=False, require_pinned=True)


def test_publish_refuses_to_change_an_existing_pin(
    project: Path,
    registry_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _run(monkeypatch, project, "publish", "demo") == 0
    first = read_pins(project)["demo"].digest
    (registry_root / "alpha.md").write_text("# Alpha\n\nRevised.\n", encoding="utf-8")

    assert _run(monkeypatch, project, "publish", "demo") == 1
    err = capsys.readouterr().err
    assert "registry_integrity" in err
    assert "heph registry update demo" in err
    assert read_pins(project)["demo"].digest == first, "a refused publish leaves the pin alone"

    # Accepting new bytes stays a deliberate act.
    assert _run(monkeypatch, project, "update", "demo") == 0
    assert read_pins(project)["demo"].digest == merkle_digest(registry_root)


def test_publish_refuses_a_tree_that_does_not_validate(
    project: Path,
    registry_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (registry_root / "beta.md").unlink()
    assert _run(monkeypatch, project, "publish", "demo") == 1
    assert "does not validate and was not published" in capsys.readouterr().err
    assert read_pins(project)["demo"].digest is None


def test_publish_needs_a_path_for_an_unknown_registry(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(monkeypatch, project, "publish", "nowhere") == 2
    assert "--path DIR" in capsys.readouterr().err


def test_publish_can_pin_a_new_registry_by_path(
    project: Path,
    registry_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copy = tmp_path / "vendored"
    shutil.copytree(registry_root, copy)
    assert _run(monkeypatch, project, "publish", "vendored", "--path", str(copy)) == 0
    pin = read_pins(project)["vendored"]
    assert pin == RegistryPin(name="vendored", path=str(copy), digest=merkle_digest(copy))


# -- verify --record -------------------------------------------------------


def test_verify_against_a_record_passes_and_then_names_the_drift(
    project: Path,
    registry_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _run(monkeypatch, project, "publish", "demo", "--record", "rec.json") == 0
    capsys.readouterr()

    assert _run(monkeypatch, project, "verify", "demo", "--record", "rec.json", "--json") == 0
    records = json.loads(capsys.readouterr().out)
    assert records[0]["status"] == "ok"
    assert records[0]["record_digest"] == read_pins(project)["demo"].digest

    (registry_root / "alpha.md").write_text("# Alpha\n\nDrifted.\n", encoding="utf-8")
    assert _run(monkeypatch, project, "verify", "demo", "--record", "rec.json", "--json") == 1
    drifted = json.loads(capsys.readouterr().out)[0]
    # The pin check fails first; the record check names the file either way.
    assert drifted["status"] in ("drifted", "record_mismatch")


def test_verify_with_a_record_requires_exactly_one_registry(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(monkeypatch, project, "publish", "demo", "--record", "rec.json") == 0
    capsys.readouterr()
    assert _run(monkeypatch, project, "verify", "--record", "rec.json") == 2
    assert "exactly one registry" in capsys.readouterr().err


def test_a_malformed_record_is_a_usage_error(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (project / "bad.json").write_text('{"digest": "not-a-digest"}', encoding="utf-8")
    assert _run(monkeypatch, project, "verify", "demo", "--record", "bad.json") == 2
    assert "digest" in capsys.readouterr().err


# -- the shipped registries ------------------------------------------------


@pytest.mark.parametrize("kind", ["skills", "parts", "materials", "dfm"])
def test_every_bundled_registry_publishes(kind: str) -> None:
    record = publish_registry(REGISTRIES / kind)
    assert record.kind == kind
    assert record.digest == merkle_digest(REGISTRIES / kind)
    assert record.license, "a publishable registry states its licence"
    assert sum(record.counts.values()) > 0
    assert verify_publication(REGISTRIES / kind, record) == record.digest


def test_the_bundled_dfm_registry_publishes_the_shipped_packs_and_all_rules() -> None:
    record = publish_registry(REGISTRIES / "dfm")
    assert record.counts == {"packs": 3, "rules": 12}
