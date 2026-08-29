# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""The shipped registry content itself: skills, parts-store generators, materials.

The load-bearing test here is the snippet extraction: **every ```python fence in
every skill is a real part script**, executed through the ordinary build pipeline,
and every CHECK it declares must pass on its own example. A reference that teaches
a check which fails on the code beside it is worse than no reference at all.

A ```python globals fence supplies the ``globals.py`` source for the fences after
it in the same file; ```text fences are illustrative and are not executed.

Also enforced: the contribution ban on naming bench corpus tasks (grep-level, per
`repo_conventions.md`), the store generators' fragment contract, and the metadata
each tool result is built from.
"""

from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.core.executor.runner import BuildRequest, run_build
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.registry import (
    MaterialsIndex,
    PartsIndex,
    SkillsIndex,
    instance_prefix,
    load_registry,
    parse_generator,
    render_fragment,
)

REPO = Path(__file__).resolve().parents[2]
REGISTRIES = REPO / "registries"
SKILLS = REGISTRIES / "skills"

#: The six references Stage 2 ships (mission Stage 2 / digest §7).
EXPECTED_SKILLS = (
    "booleans-and-clearances",
    "build123d-idioms",
    "fillets-and-failure-repair",
    "parts-store-usage",
    "profiles-and-extrusion",
    "sheet-goods-and-joinery",
)

#: Corpus task ids the public bench split declares if it is present in the tree;
#: otherwise the eight names fixed by STAGE2_DIGEST §8.
FALLBACK_TASK_IDS = (
    "bracket-101",
    "sheet-box",
    "cat-step",
    "store-hardware",
    "repair-fillet",
    "param-retune",
    "knob-loft",
    "enclosure-bosses",
)

_FENCE = re.compile(r"^```([^\n]*)\n(.*?)^```", re.S | re.M)


class Snippet:
    """One executable fence: its file, its ordinal, its script, its globals."""

    def __init__(self, path: Path, ordinal: int, script: str, globals_source: str | None) -> None:
        self.path = path
        self.ordinal = ordinal
        self.script = script
        self.globals_source = globals_source

    @property
    def id(self) -> str:
        return f"{self.path.stem}#{self.ordinal}"

    def __repr__(self) -> str:  # pragma: no cover - test ids only
        return self.id


def _snippets(path: Path) -> Iterator[Snippet]:
    globals_source: str | None = None
    ordinal = 0
    for info, body in _FENCE.findall(path.read_text(encoding="utf-8")):
        label = str(info).strip()
        if label == "python globals":
            globals_source = str(body)
            continue
        if label != "python":
            continue
        ordinal += 1
        yield Snippet(path, ordinal, str(body), globals_source)


def _all_snippets() -> list[Snippet]:
    return [snippet for path in sorted(SKILLS.glob("*.md")) for snippet in _snippets(path)]


ALL_SNIPPETS = _all_snippets()


def _corpus_task_ids() -> tuple[str, ...]:
    tasks = REPO / "corpus" / "tasks"
    ids: list[str] = []
    for manifest in sorted(tasks.glob("*/task.json")):
        document = cast("dict[str, Any]", json.loads(manifest.read_text(encoding="utf-8")))
        raw = document.get("id")
        ids.append(str(raw) if isinstance(raw, str) and raw else manifest.parent.name)
    return tuple(ids) if ids else FALLBACK_TASK_IDS


# -- inventory -------------------------------------------------------------


def test_the_six_skill_references_are_present_and_indexed() -> None:
    registry = load_registry(SKILLS)
    index = SkillsIndex(registry)
    assert index.names() == EXPECTED_SKILLS
    for row in index.listing():
        assert row["summary"], row["name"]
        assert isinstance(row["tokens"], int) and cast("int", row["tokens"]) > 200


def test_every_skill_is_a_substantial_reference() -> None:
    for name in EXPECTED_SKILLS:
        lines = (SKILLS / f"{name}.md").read_text(encoding="utf-8").splitlines()
        assert 100 <= len(lines) <= 400, f"{name}: {len(lines)} lines"
        assert lines[0].startswith("# ")


def test_skills_carry_executable_examples() -> None:
    per_file = {path.stem: 0 for path in SKILLS.glob("*.md")}
    for snippet in ALL_SNIPPETS:
        per_file[snippet.path.stem] += 1
    assert all(count >= 2 for count in per_file.values()), per_file


# -- the contribution ban on corpus task names -----------------------------


def test_no_skill_mentions_a_bench_corpus_task_by_name() -> None:
    """`repo_conventions.md`: registry content may not reference corpus tasks."""
    task_ids = _corpus_task_ids()
    assert len(task_ids) >= 8
    offences: list[str] = []
    for path in sorted(SKILLS.glob("*.md")):
        haystack = path.read_text(encoding="utf-8").lower()
        for task_id in task_ids:
            needle = task_id.lower()
            if needle in haystack or needle.replace("-", "_") in haystack:
                offences.append(f"{path.name}: {task_id}")
    assert not offences, offences


def test_no_registry_content_at_all_mentions_a_bench_corpus_task() -> None:
    task_ids = _corpus_task_ids()
    offences: list[str] = []
    for path in sorted(REGISTRIES.rglob("*")):
        if not path.is_file() or path.suffix not in {".md", ".toml", ".json", ".py"}:
            continue
        haystack = path.read_text(encoding="utf-8").lower()
        for task_id in task_ids:
            if task_id.lower() in haystack:
                offences.append(f"{path.relative_to(REGISTRIES)}: {task_id}")
    assert not offences, offences


# -- every snippet builds, and its own checks pass -------------------------


@pytest.mark.parametrize("snippet", ALL_SNIPPETS, ids=lambda s: s.id)
def test_skill_snippet_builds_and_its_checks_pass(snippet: Snippet) -> None:
    with tempfile.TemporaryDirectory() as scratch:
        build = run_build(
            BuildRequest(
                part=re.sub(r"\W", "_", snippet.id),
                script=snippet.script,
                globals_source=snippet.globals_source,
            ),
            backend=UnsafeLocalBackend(),
            out_dir=Path(scratch) / "out",
        )
    result = build.result
    if result.status != "ok":
        error = result.error
        detail = "unknown failure" if error is None else f"{error.type}: {error.message}"
        pytest.fail(f"{snippet.id} failed to build at line {getattr(error, 'line', '?')}: {detail}")
    failed = {name: check.measured for name, check in result.checks.items() if not check.passed}
    assert not failed, f"{snippet.id} declares checks that fail on its own example: {failed}"


# -- parts store -----------------------------------------------------------


def test_parts_store_indexes_the_shipped_generators() -> None:
    """Repointed 2026-08-29 (PARTS_STORE.md Named new work item 31, G11C half).

    The list grew by the three mechanism components the component store ships —
    a bearing, a gear blank and a motor frame — beside the six fastener
    envelopes it started from. What this test pins is unchanged: the whole
    manifest indexes, sorted, and search finds the right row.
    """
    index = PartsIndex(load_registry(REGISTRIES / "parts"))
    assert index.ids() == (
        "bearing_608",
        "gear_module1_z20",
        "heatset_insert_m3",
        "heatset_insert_m4",
        "heatset_insert_m5",
        "screw_socket_head_m3",
        "screw_socket_head_m4",
        "screw_socket_head_m5",
        "stepper_nema17_frame",
    )
    hits = index.search("m5 socket head screw", 5)
    assert hits and hits[0]["id"] == "screw_socket_head_m5"
    assert index.search("heat set insert m3", 3)[0]["id"] == "heatset_insert_m3"
    assert index.search("hovercraft", 5) == []


def test_every_generator_satisfies_the_fragment_contract() -> None:
    """Repointed 2026-08-29 by ``PARTS_STORE.md`` §4's decision, cited here.

    This used to assert that *every* generator declares at least one parameter,
    which was true of the six fastener envelopes and is not a contract. §4
    settles the discrete-axis question the other way — "**Decision: no enum
    parameter kind. Series are separate part ids.**" — so a component whose
    every dimension is fixed by its designation (a 608 bearing, a module-1
    20-tooth gear) has no continuous parameter to declare, by the spec's own
    choice rather than by omission. A ``computed`` mass additionally *requires*
    that: §5 checks the declared value against the built envelope, so a
    parameter that moved the volume would make the record uncheckable.

    The contract itself is unweakened and now asserted unconditionally: the
    generator's ``PARAMS`` and the record's ``params`` are the same set, in both
    directions, so search results and instancing cannot disagree about what is
    tunable. What is dropped is only the claim that the set is non-empty, and
    the family that legitimately has parameters is still checked for them.
    """
    index = PartsIndex(load_registry(REGISTRIES / "parts"))
    parameterised: list[str] = []
    for part_id in index.ids():
        part = index.get(part_id)
        generator = parse_generator(part.read_script(), source=str(part.script_path))
        assert generator.root_name.startswith("_"), part_id
        # Declared params and the metadata schema agree, so search results and
        # instancing cannot disagree about what is tunable.
        assert set(generator.param_names) == set(part.params), part_id
        if generator.param_names:
            parameterised.append(part_id)
    # Every fastener envelope is parameterised over its standard's length or
    # clearance range, which is what §4 asks a generator to do where a
    # continuous axis exists.
    assert {pid for pid in parameterised if pid.startswith(("screw_", "heatset_"))} == {
        pid for pid in index.ids() if pid.startswith(("screw_", "heatset_"))
    }


def test_fragment_placement_is_deterministic_and_collision_free() -> None:
    index = PartsIndex(load_registry(REGISTRIES / "parts"))
    part = index.get("screw_socket_head_m5")
    generator = parse_generator(part.read_script(), source=str(part.script_path))
    here = render_fragment(generator, part, {"length": 16.0}, {"x": 10.0, "y": 0.0, "z": 4.0})
    again = render_fragment(generator, part, {"length": 16.0}, {"x": 10.0, "y": 0.0, "z": 4.0})
    there = render_fragment(generator, part, {"length": 16.0}, {"x": -10.0, "y": 0.0, "z": 4.0})
    assert here == again
    assert here != there
    # Two instances of the same generator never collide on a module-scope name.
    assert instance_prefix(part.id, {"length": 16.0}, {"x": 10.0}) != instance_prefix(
        part.id, {"length": 16.0}, {"x": -10.0}
    )
    # The fragment is an instance, not a part: it publishes nothing itself (the
    # header comment names part.geometry only to say what YOU should do with it).
    statements = [line for line in here.splitlines() if line and not line.startswith("#")]
    assert not any(line.startswith("part.") for line in statements)
    assert "Pos(10.0, 0.0, 4.0)" in here
    assert part.digest in here and part.registry in here


# -- materials -------------------------------------------------------------


def test_materials_records_carry_what_a_design_decision_needs() -> None:
    index = MaterialsIndex(load_registry(REGISTRIES / "materials"))
    assert index.ids() == ("al-6061", "petg", "pla", "plywood-baltic-birch")
    by_id = {row["id"]: row for row in index.search("plywood pla petg aluminium")}
    assert set(by_id) == set(index.ids())
    assert by_id["plywood-baltic-birch"]["density"] == 680.0
    assert by_id["pla"]["density"] == 1240.0
    assert by_id["petg"]["density"] == 1270.0
    assert by_id["al-6061"]["density"] == 2700.0
    plywood = by_id["plywood-baltic-birch"]
    assert cast("list[float]", plywood["thicknesses"]) == [3.0, 6.0, 12.0, 18.0]
    assert "sheet" in cast("list[str]", plywood["forms"])
    for row in by_id.values():
        assert len(str(row["notes"])) > 80, row["id"]


def test_materials_search_ranks_the_obvious_match_first() -> None:
    index = MaterialsIndex(load_registry(REGISTRIES / "materials"))
    assert index.search("baltic birch plywood")[0]["id"] == "plywood-baltic-birch"
    assert index.search("6061 aluminium")[0]["id"] == "al-6061"
    assert index.search("unobtainium") == []
