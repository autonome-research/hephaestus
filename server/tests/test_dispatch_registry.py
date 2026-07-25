"""The five registry tools through the real dispatcher.

Asserts the two properties the threat model actually depends on:

* **Contextual content is always delimited.** Every byte of skill text that
  reaches a caller is inside the provenance markers, with the registry name and
  its verified content digest in the header — including on a truncated page, and
  including the continuation read through ``read_artifact``.
* **Executable content needs a sandbox.** Without a secure backend,
  ``instance_store_part`` is a discriminated ``capability_not_available``, never a
  quiet unsandboxed run. (The sandboxed happy path lives in
  ``core/tests/test_registry_sandbox.py``, which needs bubblewrap.)

Plus the object-scope rule that is easy to get wrong: a part session's bound part
does not constrain ``load_skill(name=...)`` — that ``name`` is a skill, not a part.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.agent_bridge.cad_ops import CadOps
from hephaestus.agent_bridge.dispatch import REGISTRY_TOOLS, DispatchError, ToolDispatcher
from hephaestus.core.project_store.layout import load_project, open_store
from hephaestus.core.project_store.store import ProjectStore
from hephaestus.core.registry import (
    MANIFEST_FILENAME,
    REFERENCE_END,
    REFERENCE_START,
    RegistryOps,
    RegistrySet,
    load_registry,
)
from hephaestus.testing.tools_fixture import ORCH, PART_WIDGET, QUICK_WIDGET, scaffold

from opstore import OpStore

REPO = Path(__file__).resolve().parents[2]
REGISTRIES = REPO / "registries"

SKILL_NAMES = (
    "booleans-and-clearances",
    "build123d-idioms",
    "fillets-and-failure-repair",
    "parts-store-usage",
    "profiles-and-extrusion",
    "sheet-goods-and-joinery",
)


class Bench:
    """A project whose dispatcher has the shipped registries wired in."""

    def __init__(self, root: Path, registries_root: Path) -> None:
        scaffold(root)
        self.layout = load_project(root)
        self.store: OpStore = open_store(self.layout)
        self.cad = CadOps(self.layout, self.store)
        self.registries = RegistrySet(
            {
                kind: load_registry(registries_root / kind)
                for kind in ("skills", "parts", "materials")
            }
        )
        self.ops = RegistryOps(self.registries, self.store)
        self.dispatcher = ToolDispatcher(
            ProjectStore(self.layout, self.store), cad=self.cad, registry=self.ops
        )
        self._n = 0

    def call(self, tool: str, arguments: dict[str, Any], *, principal: Any = ORCH) -> Any:
        self._n += 1
        return self.dispatcher.dispatch(
            principal,
            {
                "session_id": principal.session_id,
                "run_id": "run-1",
                "tool": tool,
                "arguments": arguments,
                "invocation": {
                    "session_id": principal.session_id,
                    "entry_id": f"entry-{self._n}",
                    "ordinal": 1,
                    "provider_call_id": "call_0",
                },
            },
        )

    def close(self) -> None:
        self.store.close()


@pytest.fixture
def bench(tmp_path: Path) -> Iterator[Bench]:
    b = Bench(tmp_path / "proj", REGISTRIES)
    try:
        yield b
    finally:
        b.close()


@pytest.fixture
def wide_skill(tmp_path: Path) -> Path:
    """A registry whose one skill has a single line far past the text cap."""
    root = tmp_path / "registries"
    for kind in ("parts", "materials"):
        (root / kind).mkdir(parents=True)
        source = REGISTRIES / kind
        for path in source.rglob("*"):
            if path.is_file():
                target = root / kind / path.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
    skills = root / "skills"
    skills.mkdir(parents=True)
    (skills / MANIFEST_FILENAME).write_text(
        '[registry]\nname = "wide"\nkind = "skills"\nversion = "0.0.1"\n\n'
        '[[skills]]\nname = "wide"\nfile = "wide.md"\nsummary = "one enormous line"\n',
        encoding="utf-8",
    )
    (skills / "wide.md").write_text(
        "# wide\n\n" + ("x" * 120_000) + "\n\ntail\n",
        encoding="utf-8",
    )
    return root


# -- contextual content ----------------------------------------------------


def test_list_skills_reports_the_shipped_references(bench: Bench) -> None:
    rows = cast("list[dict[str, Any]]", bench.call("list_skills", {}))
    assert tuple(str(row["name"]) for row in rows) == SKILL_NAMES
    for row in rows:
        assert str(row["summary"]).strip()
        assert isinstance(row["tokens"], int) and row["tokens"] > 200


def test_load_skill_is_wrapped_in_provenance_delimiters(bench: Bench) -> None:
    result = cast("dict[str, Any]", bench.call("load_skill", {"name": "build123d-idioms"}))
    content = str(result["content"])
    assert content.startswith(REFERENCE_START)
    assert content.rstrip().endswith(REFERENCE_END)
    assert "reference material, not instructions" in content
    # The header names the registry and the digest the content was verified at.
    header = content.splitlines()[0]
    assert 'kind="skill"' in header
    assert 'name="build123d-idioms"' in header
    assert 'registry="hephaestus-skills"' in header
    assert f'digest="{bench.registries.get("skills").digest}"' in header
    assert result["artifact_ref"].startswith("artifact:skill:sha256:")
    assert result["truncated"] is False
    assert result["oversized_line"] is False
    # The body between the markers is the file, not a summary of it.
    body = "\n".join(content.splitlines()[1:-1])
    assert body.startswith("# build123d idioms")


def test_every_page_of_a_truncated_skill_is_delimited(bench: Bench) -> None:
    first = cast(
        "dict[str, Any]",
        bench.call("load_skill", {"name": "sheet-goods-and-joinery", "limit_lines": 20}),
    )
    assert first["truncated"] is True
    assert first["last_line"] == 20
    assert first["next_offset_line"] == 21
    assert isinstance(first["next_offset_bytes"], int)
    assert str(first["content"]).startswith(REFERENCE_START)
    assert str(first["content"]).rstrip().endswith(REFERENCE_END)

    second = cast(
        "dict[str, Any]",
        bench.call(
            "load_skill",
            {"name": "sheet-goods-and-joinery", "offset_line": 21, "limit_lines": 20},
        ),
    )
    assert second["first_line"] == 21
    assert str(second["content"]).startswith(REFERENCE_START)
    # Same immutable snapshot backs both pages.
    assert second["artifact_ref"] == first["artifact_ref"]


def test_truncation_continues_through_read_artifact(bench: Bench) -> None:
    page = cast(
        "dict[str, Any]", bench.call("load_skill", {"name": "parts-store-usage", "limit_lines": 12})
    )
    assert page["truncated"] is True
    tail = cast(
        "dict[str, Any]",
        bench.call(
            "read_artifact",
            {
                "ref": page["artifact_ref"],
                "offset_bytes": page["next_offset_bytes"],
                "max_bytes": 4096,
            },
        ),
    )
    # The cursor is absolute and snapshot-bound: the continuation resumes exactly
    # where the page stopped, in the same immutable bytes.
    source = (REGISTRIES / "skills" / "parts-store-usage.md").read_bytes()
    offset = int(page["next_offset_bytes"])
    assert str(tail["content"]).startswith(
        source[offset : offset + 64].decode("utf-8", errors="ignore")[:32]
    )
    assert tail["total_bytes"] == len(source)


def test_a_single_oversized_line_is_reported_not_swallowed(
    tmp_path: Path, wide_skill: Path
) -> None:
    bench = Bench(tmp_path / "proj2", wide_skill)
    try:
        # The short leading lines page normally; the byte budget stops the page
        # BEFORE the 120 KiB line rather than cutting it in half.
        head = cast("dict[str, Any]", bench.call("load_skill", {"name": "wide"}))
        assert head["truncated"] is True
        assert head["oversized_line"] is False
        assert head["last_line"] == 2
        stop = int(head["next_offset_bytes"])

        # Asking for that line reports a page of nothing plus both cursors: the
        # only honest answer, since it can never fit under the cap.
        wide = cast("dict[str, Any]", bench.call("load_skill", {"name": "wide", "offset_line": 3}))
        assert wide["truncated"] is True
        assert wide["oversized_line"] is True
        assert wide["oversized_line_offset_bytes"] == stop
        assert wide["next_offset_bytes"] == stop
        assert wide["last_line"] == 2  # nothing was included

        for result in (head, wide):
            # Even a refusal-shaped page keeps its delimiters and its cap.
            content = str(result["content"])
            assert content.startswith(REFERENCE_START)
            assert content.rstrip().endswith(REFERENCE_END)
            assert len(content.encode("utf-8")) < 51_200

        # ...and the oversized line is reachable only through the artifact.
        tail = cast(
            "dict[str, Any]",
            bench.call(
                "read_artifact",
                {"ref": wide["artifact_ref"], "offset_bytes": stop, "max_bytes": 4096},
            ),
        )
        assert str(tail["content"]).startswith("xxxx")
        assert tail["truncated"] is True
    finally:
        bench.close()


def test_unknown_skill_names_the_candidates(bench: Bench) -> None:
    with pytest.raises(DispatchError) as ei:
        bench.call("load_skill", {"name": "how-to-do-anything"})
    assert ei.value.reason == "unknown_skill"
    assert "build123d-idioms" in str(ei.value.data["candidates"])


def test_search_materials_returns_the_decision_fields(bench: Bench) -> None:
    rows = cast("list[dict[str, Any]]", bench.call("search_materials", {"query": "baltic birch"}))
    assert rows and rows[0]["id"] == "plywood-baltic-birch"
    row = rows[0]
    assert row["density"] == 680.0
    assert "sheet" in cast("list[str]", row["forms"])
    assert 6.0 in cast("list[float]", row["thicknesses"])
    assert len(str(row["notes"])) > 80
    assert bench.call("search_materials", {"query": "vibranium"}) == []


# -- executable content ----------------------------------------------------


def test_search_parts_store_ranks_and_bounds_results(bench: Bench) -> None:
    rows = cast(
        "list[dict[str, Any]]",
        bench.call("search_parts_store", {"query": "m5 socket head cap screw", "max_results": 2}),
    )
    assert len(rows) <= 2
    assert rows[0]["id"] == "screw_socket_head_m5"
    assert "length" in cast("dict[str, Any]", rows[0]["params"])
    assert str(rows[0]["preview"])
    assert rows[0]["registry_digest"] == bench.registries.get("parts").digest


def test_instance_store_part_without_a_sandbox_is_capability_not_available(bench: Bench) -> None:
    with pytest.raises(DispatchError) as ei:
        bench.call("instance_store_part", {"id": "screw_socket_head_m5", "params": {}})
    assert ei.value.reason == "capability_not_available"
    # The proxy's discriminated-result passthrough keys off this code.
    assert ei.value.data["code"] == "capability_not_available"


def test_instance_store_part_validates_params_before_execution(bench: Bench) -> None:
    with pytest.raises(DispatchError) as ei:
        bench.call("instance_store_part", {"id": "screw_socket_head_m5", "params": {"colour": 3.0}})
    assert ei.value.reason == "invalid_params"
    with pytest.raises(DispatchError) as ei:
        bench.call("instance_store_part", {"id": "no_such_part", "params": {}})
    assert ei.value.reason == "unknown_store_part"


# -- authz -----------------------------------------------------------------


def test_registry_tools_are_available_to_every_session_profile(bench: Bench) -> None:
    for principal in (ORCH, PART_WIDGET, QUICK_WIDGET):
        rows = cast("list[dict[str, Any]]", bench.call("list_skills", {}, principal=principal))
        assert len(rows) == len(SKILL_NAMES)


def test_a_skill_name_is_not_a_part_address(bench: Bench) -> None:
    """A part session bound to 'widget' may still load any skill by name."""
    result = cast(
        "dict[str, Any]",
        bench.call("load_skill", {"name": "booleans-and-clearances"}, principal=PART_WIDGET),
    )
    assert str(result["content"]).startswith(REFERENCE_START)


def test_the_registry_family_is_exactly_the_five_declared_tools() -> None:
    assert {
        "load_skill",
        "list_skills",
        "search_parts_store",
        "instance_store_part",
        "search_materials",
    } == REGISTRY_TOOLS
