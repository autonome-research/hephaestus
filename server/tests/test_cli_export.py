# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``heph export list`` / ``heph export unpin`` and the admission guard (§19.40).

``INTERFACE.md`` §19.40 and §22.6, under Stage 10A / Gate G10A, whose last clause
is *"``heph export list`` and ``heph export unpin BLOB`` exist and are
exercised"*. Two things are asserted here that a smoke test would not be:

* **the unpin actually releases the artifact for GC.** Not "the pin row is gone"
  — the blob leaves ``gc.reachable()`` and a real ``gc.collect()`` pass then
  deletes its bytes, which is the property §22.6's whole retention argument rests
  on. The same test asserts the *source build* stays reachable, because the
  export's ``gc.link`` is what protects it and an unpin that took the build with
  it would be a different, much worse operation than the one advertised.
* **the admission guard has production callers.** §22.6's CORRECTION records that
  ``GcCollector.admission_guard()`` had **zero**, so "exports pin unboundedly and
  nothing currently refuses on the strength of it". These tests drive a store
  whose quota is already exceeded and assert that a build and an export both
  refuse with the engine's own ``protected_quota_exceeded``, carrying the
  ``GcUsage`` numbers §22.7's table requires — through the CLI, through the tool
  dispatcher, and onto the §2.4 wire mapping.

The quota is exercised by *lowering the quota*, never by writing gigabytes: the
guard's condition is ``protected_bytes > quota_bytes`` and a store reopened with
``quota_bytes=0`` over a project that has built once satisfies it exactly, in the
same way the opstore's own ``test_protected_quota_exceeded_and_admission_guard``
does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.cad_ops import CadOps
from hephaestus.agent_bridge.cad_ops._base import CadOpError
from hephaestus.agent_bridge.cad_ops.export_history import EXPORTS_DIR, export_records
from hephaestus.core.cli import main
from hephaestus.core.project_store.layout import ProjectLayout, load_project, open_store
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.retention import DefaultProtectedRoots
from hephaestus.http.errors import refusal_for, status_for_reason
from hephaestus.testing.tools_fixture import Project, make_project, scaffold
from opstore.errors import ProtectedQuotaExceededError
from opstore.types import StoreConfig

from opstore import STATE_DB_NAME, OpStore


@dataclass(frozen=True)
class Exported:
    """A project with one committed export, and its store closed.

    Closed because both verbs open the project's store themselves — that is what
    a CLI does — and the test's own assertions reopen it afterwards.
    """

    root: Path
    blob: str
    rel_path: str


def _reopen(root: Path, *, config: StoreConfig | None = None) -> tuple[ProjectLayout, OpStore]:
    """The project's store, optionally under a different quota.

    Mirrors ``layout.open_store``'s protected-roots wiring rather than calling it,
    because that helper takes no ``StoreConfig`` and the quota is the subject of
    half these tests. The default policy — current bundle, last failure record,
    live projection pointers — is the same object it would have installed.
    """
    layout = load_project(root)
    if config is None:
        return layout, open_store(layout)
    roots = DefaultProtectedRoots(layout)
    store = OpStore.open(layout.store_root, config, protected_roots=roots)
    roots.bind(store)
    return layout, store


@pytest.fixture
def exported(tmp_path: Path) -> Exported:
    """``widget`` built and exported once as STEP."""
    project: Project = make_project(tmp_path / "proj")
    try:
        project.build("widget")
        raw = project.call("export_part", {"name": "widget", "format": "step"})
        result = cast("dict[str, Any]", raw)
        hashes = cast("dict[str, str]", result["export_hashes"])
        rel_path, blob = next(iter(hashes.items()))
        root = project.root
    finally:
        project.close()
    return Exported(root=root, blob=blob, rel_path=rel_path)


def _run(root: Path, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.chdir(root)
    return main(list(argv))


# ==========================================================================
# heph export list


def _table_exists(store: OpStore) -> bool:
    row = store.db.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'tp_exports'"
    ).fetchone()
    return row is not None


def test_neither_verb_creates_the_write_ahead_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """ "Nothing has ever been exported" is a fact about the project, not a failure.

    A project that has never *constructed* ``CadOps`` has no ``tp_exports`` at
    all (``CadOps.__init__`` is the one caller of ``ensure_exports_table``), and
    neither verb may create it: a read verb that takes a DDL write on
    ``state.db`` would be unsafe to run against a store another process is using.
    ``unpin`` does construct ``CadOps`` — §19.40 names ``unpin_export`` as the
    operation it is over — so its refusal has to come *first*, and this asserts
    that ordering rather than trusting it.
    """
    root = tmp_path / "proj"
    scaffold(root)
    layout = load_project(root)
    store = open_store(layout)
    try:
        assert not _table_exists(store)
    finally:
        store.close()

    assert _run(root, monkeypatch, "export", "list") == 0
    assert capsys.readouterr().out.strip() == "no exports recorded"

    digest = "sha256:" + "0" * 64
    assert _run(root, monkeypatch, "export", "unpin", digest) == 2
    assert "is not an output of any committed export" in capsys.readouterr().err

    _, after = _reopen(root)
    try:
        assert not _table_exists(after), "an export verb created the write-ahead table"
    finally:
        after.close()


def test_list_names_the_file_its_blob_and_its_pin(
    exported: Exported, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The human form carries everything ``unpin`` needs, in one copyable line."""
    assert _run(exported.root, monkeypatch, "export", "list") == 0
    out = capsys.readouterr().out
    assert "widget" in out
    assert "step" in out
    assert "as_built" in out
    # The whole blob, not an abbreviation: this line is what an operator pastes
    # into `heph export unpin`.
    assert exported.blob in out
    assert f"{EXPORTS_DIR}/{exported.rel_path}" in out
    assert "pinned" in out
    assert "1 export(s), 1 file(s)" in out
    assert "heph export unpin BLOB" in out
    # §19.40's other half, made visible where the remedy is: the quota numbers.
    assert "protected of" in out


def test_list_json_reports_every_output_with_its_pin_and_reachability(
    exported: Exported, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(exported.root, monkeypatch, "export", "list", "--json") == 0
    document = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
    assert document["status"] == "ok"
    assert document["part"] is None
    rows = cast("list[dict[str, Any]]", document["exports"])
    assert len(rows) == 1
    row = rows[0]
    assert row["part"] == "widget"
    assert row["format"] == "step"
    assert row["state"] == "COMMITTED"
    assert row["source_artifact_ref"].startswith("artifact:build:")
    outputs = cast("list[dict[str, Any]]", row["outputs"])
    assert len(outputs) == 1
    assert outputs[0]["blob"] == exported.blob
    assert outputs[0]["path"] == exported.rel_path
    assert outputs[0]["bytes"] > 0
    assert outputs[0]["pinned"] is True
    assert outputs[0]["reachable"] is True
    assert row["total_bytes"] == outputs[0]["bytes"]
    assert document["total_bytes"] == outputs[0]["bytes"]
    assert document["pinned_bytes"] == outputs[0]["bytes"]
    assert set(cast("dict[str, int]", document["usage"])) == {
        "total_bytes",
        "protected_bytes",
        "quota_bytes",
    }


def test_list_filters_by_part_and_says_so_in_the_document(
    exported: Exported, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(exported.root, monkeypatch, "export", "list", "bracket", "--json") == 0
    document = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
    assert document["part"] == "bracket"
    assert document["exports"] == []
    assert document["total_bytes"] == 0


def test_list_outside_a_project_refuses_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The engine CLI's own no-project refusal, unchanged.

    ``find_project_root`` raises ``ValidationError``, which
    ``hephaestus.core.cli.main`` reports as ``error (validation_error)`` and
    exit **1** — the same answer ``heph assembly`` and ``heph joints`` give
    outside a project. Pinned rather than "fixed": ``cli.py``'s module docstring
    reads "2 usage (bad arguments, **no project**, unknown part)", so the
    docstring and the behaviour disagree *for every verb in the CLI*, and
    changing one verb's answer would make that inconsistency worse rather than
    better. Reported in this item's notes for whoever owns that sentence.
    """
    outside = tmp_path / "not-a-project"
    outside.mkdir()
    assert _run(outside, monkeypatch, "export", "list") == 1
    assert "no hephaestus.toml found" in capsys.readouterr().err


# ==========================================================================
# heph export unpin


def test_unpin_releases_the_artifact_for_gc(
    exported: Exported, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The acceptance evidence of §19.40, end to end.

    Before: pinned, reachable, and so is the build it came from (G10A's own
    clause). After: unpinned, unreachable, and a real GC pass deletes the bytes —
    while the source build blob, which the export's ``gc.link`` was protecting,
    stays reachable because the part's current pointer protects it in its own
    right. That second half is the difference between "unpin" and "delete the
    build", and nothing else in the suite distinguishes them.
    """
    layout, store = _reopen(exported.root)
    try:
        (record,) = export_records(store)
        source_blob = record.source_artifact_ref.split(":", 2)[2]
        assert exported.blob in store.gc.pins()
        assert exported.blob in store.gc.reachable()
        assert source_blob in store.gc.reachable()
    finally:
        store.close()

    assert _run(exported.root, monkeypatch, "export", "unpin", exported.blob) == 0
    out = capsys.readouterr().out
    assert f"unpinned {exported.blob}" in out
    assert "now collectable" in out

    # Retention horizons zeroed so the pass is observable now; the *reachability*
    # assertions above and below are horizon-independent and are the real claim.
    _, swept = _reopen(exported.root, config=StoreConfig(retention_s=0.0, preview_retention_s=0.0))
    try:
        assert exported.blob not in swept.gc.pins()
        assert exported.blob not in swept.gc.reachable()
        assert source_blob in swept.gc.reachable()
        report = swept.gc.collect()
        collected = {candidate.ref for candidate in report.candidates}
        assert exported.blob in collected
        assert not swept.blobs.has(exported.blob)
        assert swept.blobs.has(source_blob)
    finally:
        swept.close()
    assert layout.root == exported.root


def test_unpin_json_reports_the_row_it_named_and_the_usage_after(
    exported: Exported, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(exported.root, monkeypatch, "export", "unpin", exported.blob, "--json") == 0
    document = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
    assert document["status"] == "ok"
    assert document["blob"] == exported.blob
    assert document["was_pinned"] is True
    assert document["pinned"] is False
    assert document["reachable"] is False
    assert document["bytes"] > 0
    rows = cast("list[dict[str, Any]]", document["exports"])
    assert rows == [{"op_id": rows[0]["op_id"], "part": "widget", "path": exported.rel_path}]
    assert cast("dict[str, int]", document["usage"])["quota_bytes"] > 0


def test_unpin_is_idempotent_and_says_which_time_this_is(
    exported: Exported, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A second unpin is not an error; it is the same end state, stated honestly."""
    assert _run(exported.root, monkeypatch, "export", "unpin", exported.blob) == 0
    capsys.readouterr()
    assert _run(exported.root, monkeypatch, "export", "unpin", exported.blob) == 0
    out = capsys.readouterr().out
    assert "was already unpinned" in out


def test_unpin_accepts_the_bare_digest_a_reader_copies(
    exported: Exported, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    digest = exported.blob.removeprefix("sha256:")
    assert _run(exported.root, monkeypatch, "export", "unpin", digest, "--json") == 0
    document = cast("dict[str, Any]", json.loads(capsys.readouterr().out))
    assert document["blob"] == exported.blob


def test_unpin_refuses_a_blob_no_committed_export_names(
    exported: Exported, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The authorization is the WAL row, exactly as it is for the byte route.

    A ``heph export unpin`` that accepted any hash would be a general unpin verb
    over the whole store, and §22.6's decision is about *exports*. The blob used
    here is genuinely stored — it is the source build — so the refusal is about
    what named it, not about whether it exists.
    """
    _, store = _reopen(exported.root)
    try:
        (record,) = export_records(store)
        source_blob = record.source_artifact_ref.split(":", 2)[2]
    finally:
        store.close()

    assert _run(exported.root, monkeypatch, "export", "unpin", source_blob) == 2
    captured = capsys.readouterr()
    assert "is not an output of any committed export" in captured.err
    assert "heph export list" in captured.err

    _, after = _reopen(exported.root)
    try:
        assert source_blob in after.gc.reachable()
    finally:
        after.close()


def test_unpin_refuses_a_string_that_is_not_a_blob(
    exported: Exported, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(exported.root, monkeypatch, "export", "unpin", "widget-1.step") == 2
    assert "is not an export blob" in capsys.readouterr().err


# ==========================================================================
# §22.6 / §19.40 — the admission guard now has production callers


def test_the_guard_refuses_a_build_before_it_executes(exported: Exported) -> None:
    """``Publisher.freeze_inputs`` is the one seam every production build passes."""
    layout, store = _reopen(exported.root, config=StoreConfig(quota_bytes=0))
    try:
        with pytest.raises(ProtectedQuotaExceededError) as caught:
            Publisher(layout, store).freeze_inputs("widget")
    finally:
        store.close()
    assert caught.value.code == "protected_quota_exceeded"
    usage = caught.value.usage
    assert usage is not None
    assert usage["quota_bytes"] == 0
    assert usage["protected_bytes"] > 0


def test_the_guard_refuses_an_export_with_the_engines_own_reason(exported: Exported) -> None:
    """§22.7's table row, now reachable: the reason verbatim, with ``GcUsage``."""
    layout, store = _reopen(exported.root, config=StoreConfig(quota_bytes=0))
    try:
        with pytest.raises(CadOpError) as caught:
            CadOps(layout, store).export_part(
                "widget", "stl", artifact_ref=None, target=None, layout="as_built", op_id="over"
            )
    finally:
        store.close()
    assert caught.value.reason == "protected_quota_exceeded"
    usage = cast("dict[str, int]", caught.value.data["usage"])
    assert usage["quota_bytes"] == 0
    assert usage["protected_bytes"] > 0


def test_a_committed_export_still_replays_over_quota(exported: Exported) -> None:
    """The guard refuses *production*, never a replay.

    §22.2's key contract says a repeated key yields the recorded result. Refusing
    the replay would spend the retention obligation twice and reclaim nothing —
    the bytes and the pin already exist — so the guard sits after the WAL row is
    resolved rather than before it.
    """
    layout, store = _reopen(exported.root)
    try:
        (record,) = export_records(store)
        op_id = record.op_id
    finally:
        store.close()

    layout, store = _reopen(exported.root, config=StoreConfig(quota_bytes=0))
    try:
        replayed = CadOps(layout, store).export_part(
            "widget", "step", artifact_ref=None, target=None, layout="as_built", op_id=op_id
        )
    finally:
        store.close()
    assert replayed["replayed"] is True
    assert exported.blob in cast("dict[str, str]", replayed["export_hashes"]).values()


def test_the_quota_refusal_maps_to_507_with_its_numbers() -> None:
    """§2.4's envelope for a reason §2.4's table predates (§22.7 carries it).

    Not a 429: waiting changes nothing. The remedy is ``heph export unpin`` or a
    larger quota, and the operator cannot choose between them without the three
    numbers the body carries.
    """
    assert status_for_reason("protected_quota_exceeded") == 507
    refusal = refusal_for(
        ProtectedQuotaExceededError(
            "protected+pinned bytes 9 exceed quota 4; raise the quota or unpin data",
            usage={"total_bytes": 9, "protected_bytes": 9, "quota_bytes": 4},
        )
    )
    assert refusal.status == 507
    assert refusal.reason == "protected_quota_exceeded"
    body = refusal.body()
    assert body["reason"] == "protected_quota_exceeded"
    assert body["usage"] == {"total_bytes": 9, "protected_bytes": 9, "quota_bytes": 4}
    # The engine's message, not a rewrite of it (§22.6).
    assert "raise the quota or unpin data" in str(body["message"])


def test_the_store_root_is_where_the_verbs_looked(exported: Exported) -> None:
    """Guards the fixture itself: these tests would pass vacuously on an empty store."""
    _, store = _reopen(exported.root)
    try:
        assert (store.root / STATE_DB_NAME).is_file()
        assert len(export_records(store)) == 1
    finally:
        store.close()
