"""G0B adapter clause: immutable check-bundle provenance.

Architecture §3.4: a project-check run snapshots the complete, lexically
ordered authorized ``checks/*.py`` set into one immutable content-addressed
bundle; CheckReport carries generation, ``check_bundle_ref``, and per-file
hashes. A concurrent or later edit belongs wholly to another generation —
frozen bundle contents come from CAS blobs, never the live filesystem, and
an old bundle ref keeps resolving byte-identically forever.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from _adapter_helpers import make_project
from hephaestus.core.checks.engine import (
    BUNDLE_REF_PREFIX,
    CheckSet,
    run_bundle,
)
from hephaestus.core.project_store.layout import ProjectLayout, open_store

from opstore import OpStore, sha256_bytes

FIT_V1 = "CHECKS = {'fits': lambda m: True}\n"
FIT_V2 = "CHECKS = {'fits': lambda m: True, 'sealed': lambda m: True}\n"
SPACING = "CHECKS = {'spaced': lambda m: True}\n"


@pytest.fixture
def layout(tmp_path: Path) -> ProjectLayout:
    layout = make_project(tmp_path / "proj")
    layout.checks_dir.mkdir(exist_ok=True)
    return layout


@pytest.fixture
def store(layout: ProjectLayout) -> Iterator[OpStore]:
    handle = open_store(layout)
    yield handle
    handle.close()


class TestBundleProvenance:
    def test_report_carries_generation_bundle_ref_and_file_hashes(
        self, layout: ProjectLayout, store: OpStore
    ) -> None:
        (layout.checks_dir / "fit.py").write_text(FIT_V1, encoding="utf-8")
        (layout.checks_dir / "spacing.py").write_text(SPACING, encoding="utf-8")
        check_set = CheckSet(layout.checks_dir, store)
        report = check_set.run({}, part="proj")
        assert report.check_bundle_ref.startswith(BUNDLE_REF_PREFIX)
        assert report.file_hashes == {
            "fit.py": sha256_bytes(FIT_V1.encode()),
            "spacing.py": sha256_bytes(SPACING.encode()),
        }
        # The bundle manifest is a durable lexically-ordered snapshot.
        bundle_blob = report.check_bundle_ref.removeprefix(BUNDLE_REF_PREFIX)
        manifest = json.loads(store.blobs.get(bundle_blob).decode("utf-8"))
        assert [f["path"] for f in manifest["files"]] == ["fit.py", "spacing.py"]
        assert {f["path"]: f["hash"] for f in manifest["files"]} == dict(report.file_hashes)
        # Check names are reported per-file in lexical order.
        assert sorted(report.checks) == ["fit:fits", "spacing:spaced"]

    def test_frozen_bundle_executes_from_cas_not_the_live_tree(
        self, layout: ProjectLayout, store: OpStore
    ) -> None:
        (layout.checks_dir / "fit.py").write_text(FIT_V1, encoding="utf-8")
        check_set = CheckSet(layout.checks_dir, store)
        bundle = check_set.capture()
        # A direct filesystem edit lands after capture...
        (layout.checks_dir / "fit.py").write_text(
            "CHECKS = {'fits': lambda m: False}\n", encoding="utf-8"
        )
        # ...but execution sees wholly the frozen generation.
        assert bundle.contents == {"fit.py": FIT_V1}
        report = run_bundle(bundle, {}, part="proj")
        assert report.checks["fit:fits"].passed
        assert report.check_set_generation == bundle.state.generation
        assert report.check_bundle_ref == bundle.state.bundle_ref

    def test_cooperative_edit_advances_generation_and_keeps_old_bundle(
        self, layout: ProjectLayout, store: OpStore
    ) -> None:
        (layout.checks_dir / "fit.py").write_text(FIT_V1, encoding="utf-8")
        check_set = CheckSet(layout.checks_dir, store)
        old_state = check_set.current()
        old_bundle_blob = old_state.bundle
        old_manifest_bytes = store.blobs.get(old_bundle_blob)

        new_state = check_set.write_check("fit.py", FIT_V2, op_id="edit-1")
        assert new_state.generation == old_state.generation + 1
        assert new_state.origin == "cooperative"
        assert new_state.files["fit.py"] == sha256_bytes(FIT_V2.encode())
        assert new_state.bundle != old_bundle_blob
        # Immutability: the superseded bundle ref resolves byte-identically.
        assert store.blobs.get(old_bundle_blob) == old_manifest_bytes
        old_manifest = json.loads(old_manifest_bytes.decode("utf-8"))
        assert {f["path"]: f["hash"] for f in old_manifest["files"]} == dict(old_state.files)
        # And the old generation's file *content* is still CAS-resolvable.
        assert store.blobs.get(old_state.files["fit.py"]) == FIT_V1.encode()

    def test_edits_belong_wholly_to_one_generation(
        self, layout: ProjectLayout, store: OpStore
    ) -> None:
        (layout.checks_dir / "fit.py").write_text(FIT_V1, encoding="utf-8")
        check_set = CheckSet(layout.checks_dir, store)
        before = check_set.capture()
        check_set.write_check("fit.py", FIT_V2, op_id="edit-1")
        after = check_set.capture()
        # No mixed in-flight state: each bundle is wholly old or wholly new.
        assert before.contents == {"fit.py": FIT_V1}
        assert after.contents == {"fit.py": FIT_V2}
        assert after.state.generation == before.state.generation + 1

    def test_external_direct_write_reconciles_into_one_external_import_generation(
        self, layout: ProjectLayout, store: OpStore
    ) -> None:
        (layout.checks_dir / "fit.py").write_text(FIT_V1, encoding="utf-8")
        check_set = CheckSet(layout.checks_dir, store)
        settled = check_set.current()
        # A stable third-party filesystem change with no matching WAL...
        (layout.checks_dir / "fit.py").write_text(FIT_V2, encoding="utf-8")
        reconciled = check_set.current()
        # ...becomes exactly one new external_import generation.
        assert reconciled.generation == settled.generation + 1
        assert reconciled.origin == "external_import"
        assert reconciled.files["fit.py"] == sha256_bytes(FIT_V2.encode())
        # And stays settled on the next acquisition (exactly one, not per-read).
        assert check_set.current() == reconciled
