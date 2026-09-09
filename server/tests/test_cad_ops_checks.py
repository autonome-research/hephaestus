# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``CheckOps``: project-check CRUD kinds, and the ``run_checks`` scopes.

Covers J-cli-startup-9 (a part-scope check run pays the full 3.3s sandbox
rebuild even when the part declares no checks at all — a case with provably
nothing to re-run), J-agent-results-9 (a project-scope report's ``part`` field
holds the *project* name), and J-agent-results-S5 (project-check snapshot refs
are minted under the part-snapshot kind, so a reader cannot tell a check
snapshot from a part script).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from hephaestus.testing.tools_fixture import Project, make_project


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    p = make_project(tmp_path / "proj")
    try:
        yield p
    finally:
        p.close()


def _spy_on_sandboxed_runs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Count real ``run_build`` invocations (the 3.3s sandbox floor, RC-7)."""
    import hephaestus.agent_bridge.cad_ops._base as base_module

    calls: list[str] = []
    original = base_module.run_build  # pyright: ignore[reportPrivateImportUsage]

    def spy(request: Any, **kwargs: Any) -> Any:
        calls.append(request.part)
        return original(request, **kwargs)

    monkeypatch.setattr(base_module, "run_build", spy)
    return calls


# ==========================================================================
# J-cli-startup-9: run_part_checks fast path for a part with no checks


class TestRunPartChecksFastPath:
    def test_a_part_with_no_checks_and_a_current_build_answers_from_the_record(
        self, project: Project, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``bracket`` declares no ``CHECKS`` at all. A current, unstale build
        already recorded that fact (an empty check map): re-running the
        sandbox to re-confirm "still declares none" is pure waste.
        """
        built = project.call("build_part", {"name": "bracket"})
        assert built["status"] == "ok"
        calls = _spy_on_sandboxed_runs(monkeypatch)
        report = project.cad.run_part_checks("bracket")
        assert report["status"] == "ok"
        assert report["checks"] == {}
        assert calls == [], (
            "a part with a current build and no declared checks must not spawn "
            f"the sandbox; the fast path was skipped (calls={calls})"
        )
        assert report["artifact_ref"] == built["artifact_ref"]

    def test_an_edit_that_adds_a_check_takes_the_full_path(
        self, project: Project, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The staleness guard: once the live script's inputs no longer match
        the recorded build, the fast path must not answer from a stale record.
        """
        project.call("build_part", {"name": "bracket"})
        read = project.call("read_part", {"name": "bracket"})
        project.call(
            "edit_part",
            {
                "name": "bracket",
                "expected_hash": read["content_hash"],
                "old_str": 'body.label = "bracket_body"',
                "new_str": (
                    'body.label = "bracket_body"\n\n'
                    'CHECKS = {\n    "nonzero": lambda m: m.volume("part") > 0.0,\n}'
                ),
            },
        )
        calls = _spy_on_sandboxed_runs(monkeypatch)
        report = project.cad.run_part_checks("bracket")
        assert calls, (
            "an edited part's checks must be re-evaluated, not answered from a stale record"
        )
        assert report["checks"]["nonzero"]["pass"] is True

    def test_a_part_with_a_non_empty_check_map_always_takes_the_full_path(
        self, project: Project, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The contract test that stops the optimisation creeping onto the
        non-empty case: ``widget`` declares ``wide_enough`` and its build is
        unchanged between the two runs below, yet BOTH must re-run the sandbox
        — an already-passing check silently answered from a stale record is a
        false verification signal, never a latency win worth taking.
        """
        project.call("build_part", {"name": "widget"})
        calls = _spy_on_sandboxed_runs(monkeypatch)
        first = project.cad.run_part_checks("widget")
        second = project.cad.run_part_checks("widget")
        assert len(calls) == 2, (
            f"expected two full runs for an unchanged non-empty check set, got {calls}"
        )
        assert first["checks"] and second["checks"]


# ==========================================================================
# J-agent-results-9: project-scope report's subject


class TestRunProjectChecksSubject:
    def test_project_scope_report_names_the_project_not_a_part(self, project: Project) -> None:
        project.build("widget", "bracket")
        report = project.cad.run_project_checks(None)
        assert report["scope"] == "project"
        # The record must not claim the project's own name is a part: either
        # there is no `part` key, or it is explicitly null.
        assert report.get("part") in (None,)
        assert report.get("project") == project.layout.manifest.name


# ==========================================================================
# J-agent-results-S5: project-check snapshot references carry the wrong kind


class TestCheckSnapshotKind:
    def test_created_check_snapshot_ref_is_not_the_part_snapshot_kind(
        self, project: Project
    ) -> None:
        created = project.call("create_project_check", {"name": "extra", "description": "x"})
        ref = created["snapshot_ref"]
        assert ":part-snapshot:" not in ref, (
            f"project-check snapshot {ref!r} must not be minted under the "
            "part kind — a reader holding it cannot tell a check snapshot "
            "from a part script"
        )

    def test_read_check_snapshot_ref_is_not_the_part_snapshot_kind(self, project: Project) -> None:
        project.call("create_project_check", {"name": "extra", "description": "x"})
        read = project.call("read_project_check", {"name": "extra"})
        assert ":part-snapshot:" not in read["snapshot_ref"]

    def test_edit_conflict_base_and_current_refs_share_a_kind(self, project: Project) -> None:
        """A stale-hash conflict's ``base_snapshot_ref`` (client-reconstructed
        from the expected hash) and ``current_snapshot_ref`` (server-minted)
        must carry the SAME kind, or a correct client reconstruction never
        matches the server's own reference.
        """
        created = project.call("create_project_check", {"name": "extra", "description": "x"})
        conflict = project.call(
            "edit_project_check",
            {
                "name": "extra",
                "expected_hash": "sha256:" + "0" * 64,
                "old_str": "x",
                "new_str": "y",
            },
        )
        assert conflict["status"] == "conflict"
        base_kind = conflict["base_snapshot_ref"].split(":")[1]
        current_kind = conflict["current_snapshot_ref"].split(":")[1]
        assert base_kind == current_kind == created["snapshot_ref"].split(":")[1]
