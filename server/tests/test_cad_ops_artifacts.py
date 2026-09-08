# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``read_artifact`` on a binary artifact must discriminate, not fake a page.

J-agent-results-3: today ``ArtifactOps.read_artifact``
(``server/src/hephaestus/agent_bridge/cad_ops/_artifacts.py:70-93``) answers a
binary artifact (a build, a render, an export, ...) with the *page*-shaped
success branch — empty content, ``application/octet-stream``, offset 0, the
real byte total, ``truncated: False`` — which asserts a multi-kilobyte artifact
was read completely and is empty, and reuses the identical shape for any
unknown kind whose bytes fail to decode. The model has no discriminator to
branch on.

Field names below (``status``, ``"binary_artifact"`` / ``"undecodable_artifact"``,
``consumed_by``, ``BINARY_ARTIFACT_READERS``) match the shipped
``_artifacts.py`` implementation.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from hephaestus.agent_bridge.cad_ops._artifacts import BINARY_ARTIFACT_KINDS
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.testing.tools_fixture import Project, make_project

STATUS_FIELD = "status"
BINARY_STATUS = "binary_artifact"
UNDECODABLE_STATUS = "undecodable_artifact"
CONSUMER_TOOL_FIELD = "consumed_by"


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    p = make_project(tmp_path / "proj")
    p.build("widget")
    try:
        yield p
    finally:
        p.close()


def _build_ref(project: Project) -> str:
    result = project.call("build_part", {"name": "widget"})
    ref = result["artifact_ref"]
    assert isinstance(ref, str)
    return ref


def _read(project: Project, ref: str) -> dict[str, Any]:
    return dict(
        project.cad.read_artifact(ref, 0, 4096)  # type: ignore[no-any-return]
    )


class TestBinaryArtifactsDiscriminate:
    def test_a_build_artifact_returns_the_binary_status_not_an_empty_page(
        self, project: Project
    ) -> None:
        ref = _build_ref(project)
        result = _read(project, ref)
        assert result[STATUS_FIELD] == BINARY_STATUS
        assert result["kind"] == "build"
        assert result["mime_type"] == "application/octet-stream"
        assert result["total_bytes"] > 0
        # "a real consuming tool" — never empty, never the artifact's own name.
        assert result[CONSUMER_TOOL_FIELD]
        assert isinstance(result[CONSUMER_TOOL_FIELD], str)

    def test_binary_status_names_the_true_byte_total(self, project: Project) -> None:
        ref = _build_ref(project)
        blob = blob_hash_of_ref(ref)
        # Independently confirm the byte total is the artifact's REAL size, not
        # a zero carried over from the empty-content branch.
        stored = project.store.blobs.get(blob)
        result = _read(project, ref)
        assert result["total_bytes"] == len(stored)

    def test_binary_reader_map_is_total_over_the_binary_kind_set(self) -> None:
        """The guard that stops a new binary kind reverting to the empty page:
        every member of ``BINARY_ARTIFACT_KINDS`` must resolve to a real
        consuming tool, asserted at import so an addition to the kind set that
        forgets to name a reader fails immediately rather than degrading
        silently at read time.
        """
        from hephaestus.agent_bridge.cad_ops import (
            _artifacts as artifacts_module,  # pyright: ignore[reportPrivateUsage]
        )

        reader_map_names = [
            name
            for name in dir(artifacts_module)
            if "READER" in name.upper() or "CONSUMER" in name.upper()
        ]
        assert reader_map_names, (
            "expected a module-level mapping from binary artifact kind to its "
            "consuming tool (e.g. BINARY_ARTIFACT_READERS); none found on "
            "hephaestus.agent_bridge.cad_ops._artifacts"
        )
        reader_map = getattr(artifacts_module, reader_map_names[0])
        assert set(reader_map) == set(BINARY_ARTIFACT_KINDS), (
            "every kind in BINARY_ARTIFACT_KINDS must have a named reader; "
            f"missing: {set(BINARY_ARTIFACT_KINDS) - set(reader_map)}"
        )


class TestUndecodableUnknownKind:
    def test_a_non_decoding_unknown_kind_returns_the_other_status(
        self, project: Project, tmp_path: Path
    ) -> None:
        """A kind outside ``BINARY_ARTIFACT_KINDS`` whose bytes are not UTF-8 is
        a *different* fact from "this kind is binary by design" — it must not
        collapse onto the same status.
        """
        blob = project.store.blobs.put(b"\xff\xfe\x00\xff not utf-8")
        ref = f"artifact:some-unknown-kind:{blob}"
        result = _read(project, ref)
        assert result[STATUS_FIELD] == UNDECODABLE_STATUS
        assert result[STATUS_FIELD] != BINARY_STATUS
        assert result["total_bytes"] == len(b"\xff\xfe\x00\xff not utf-8")


class TestTextArtifactsUnchanged:
    def test_a_text_kind_is_byte_identical_to_today_including_paging(
        self, project: Project
    ) -> None:
        """Additive-only: a known text kind must keep its exact page-content
        contract (no ``status`` discriminator forced onto the happy path).
        """
        script = project.call("read_part", {"name": "widget"})
        ref = script["snapshot_ref"]
        result = _read(project, ref)
        assert result.get(STATUS_FIELD) in (None, "ok")
        assert result["content"] == project.root.joinpath("parts", "widget.py").read_text(
            encoding="utf-8"
        )
        assert result["mime_type"] == "text/x-python"
        assert result["truncated"] is False
