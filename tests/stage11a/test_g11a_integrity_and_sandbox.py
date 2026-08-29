"""G11A clauses 21-22: tamper refusal and runtime sandbox denial, on components.

G6 recorded both properties against a **DFM** tree. They are re-asserted here
against *component* content because "the registry stack refuses a tampered tree"
and "a tampered component tree refuses" are different claims once the tree
carries a validated record and a provenance block: a reader who assumes the
first covers the second is assuming exactly the coverage gap this clause exists
to close.

Clause 22 is the sandbox denial, and it is sited at the generator's **body**
region deliberately. Its interface-region form is unreachable: §2.1's parse-time
rule refuses file IO before the tree can be *indexed*, hence before it can be
published or pinned, so there would be nothing to run. G11B clause 11 asserts
that half. Deleting this clause because the interface form is unreachable would
have dropped the only component-tree re-assertion of G6's governing evidence; it
is re-sited, not weakened.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from _g11a import DATASHEET, component_tree, motor_component, requires_bwrap
from hephaestus.core.registry import (
    RegistryError,
    RegistryIntegrityError,
    RegistryOps,
    RegistrySet,
    load_registry,
    merkle_digest,
    publication_drift,
    publish_registry,
)

from opstore import OpStore


@pytest.fixture
def store(tmp_path: Path) -> Iterator[OpStore]:
    opened = OpStore.create(tmp_path / "store")
    try:
        yield opened
    finally:
        opened.close()


@pytest.fixture
def component_registry(tmp_path: Path) -> Path:
    """A published, pinnable one-component tree."""
    root = component_tree(
        tmp_path / "component-parts",
        motor_component(
            datasheet=DATASHEET,
            mass={"value_g": 280.0, "source": "datasheet"},
        ),
    )
    publish_registry(root)
    return root


# ==========================================================================
# clause 21 — tamper refusal against component content


@pytest.mark.parametrize("target", ["generator.py", "part.json"])
def test_a_one_byte_edit_makes_the_pinned_tree_refuse_to_load(
    target: str, component_registry: Path
) -> None:
    pinned = merkle_digest(component_registry)
    path = component_registry / "stepper_nema17_frame" / target
    path.write_bytes(path.read_bytes() + b" \n")
    assert merkle_digest(component_registry) != pinned, "the tamper must move the hash"

    with pytest.raises(RegistryIntegrityError) as refusal:
        load_registry(component_registry, expected_digest=pinned)
    assert refusal.value.expected == pinned
    assert refusal.value.actual == merkle_digest(component_registry)
    # The typed pair rides in `data` so a caller reports which tree drifted.
    assert refusal.value.data["expected_digest"] == pinned


@pytest.mark.parametrize("target", ["generator.py", "part.json"])
def test_the_refusal_happens_before_any_content_is_read_for_use(
    target: str, component_registry: Path
) -> None:
    """Verify-on-load is the only place integrity is enforced, and it is
    enforced *first*: a tampered record never reaches the component parser."""
    pinned = merkle_digest(component_registry)
    path = component_registry / "stepper_nema17_frame" / target
    path.write_text("this is not valid content at all\n", encoding="utf-8")
    with pytest.raises(RegistryIntegrityError):
        load_registry(component_registry, expected_digest=pinned)


def test_publication_drift_names_the_modified_file_and_the_added_one(
    component_registry: Path,
) -> None:
    record = publish_registry(component_registry)
    generator = component_registry / "stepper_nema17_frame" / "generator.py"
    generator.write_text(generator.read_text(encoding="utf-8") + "# tampered\n", encoding="utf-8")
    (component_registry / "stepper_nema17_frame" / "extra.md").write_text(
        "# smuggled in\n", encoding="utf-8"
    )
    drift = {item.path: item.status for item in publication_drift(component_registry, record)}
    assert drift == {
        "stepper_nema17_frame/generator.py": "modified",
        "stepper_nema17_frame/extra.md": "added",
    }


def test_a_tampered_component_tree_refuses_to_open_the_registry_set(
    tmp_path: Path, component_registry: Path
) -> None:
    """The end-to-end shape: not "the digest moved" in a helper — the set the
    tools are built on refuses to open at all."""
    pinned = merkle_digest(component_registry)
    meta = component_registry / "stepper_nema17_frame" / "part.json"
    meta.write_text(
        meta.read_text(encoding="utf-8").replace('"value_g": 280.0', '"value_g": 180.0'),
        encoding="utf-8",
    )
    with pytest.raises(RegistryIntegrityError):
        RegistrySet({"parts": load_registry(component_registry, expected_digest=pinned)})


# ==========================================================================
# clause 22 — runtime sandbox denial, body region, component tree


#: The body region reaches the sandbox; `open` is not in the injected namespace
#: at all, and the sandbox has no bind to read from even if it were.
HOSTILE_BODY_GENERATOR = (
    "# --- hephaestus-store: params ---\n"
    'PARAMS = {\n    "body_length": Param(39.0, min=20.0, max=60.0),\n}\n'
    "# --- hephaestus-store: bind ---\n"
    "_body_length = p.body_length\n"
    "# --- hephaestus-store: body ---\n"
    '_leak = open("/etc/passwd").read()\n'
    "_motor = Box(42.3, 42.3, _body_length)\n"
    "part.geometry = _motor\n"
    # Item 11 (G11B) makes the record's declared interface set and the region's
    # emitted set equal at INDEX time, so this fixture needs a region matching
    # `motor_component()` or it stops publishing — and clause 22 would then be
    # testing an unpublishable tree, which the guard below exists to catch. The
    # denial still happens at `open`, which runs long before the region does.
    "# --- hephaestus-store: interface ---\n"
    'tag(_motor.faces().filter_by(GeomType.PLANE).sort_by(SortBy.AREA)[-1], "mount_face")\n'
    'tag(_motor.faces().filter_by(GeomType.PLANE).sort_by(SortBy.AREA)[0], "shaft")\n'
)


@pytest.fixture
def hostile_component(tmp_path: Path) -> Path:
    """A published *and pinned* component tree whose body reads a file.

    Published and pinned matters: by every measure the registry stack has, this
    generator is trusted content. It is still executed under the sandbox.
    """
    root = component_tree(
        tmp_path / "hostile-parts",
        motor_component(),
        generator=HOSTILE_BODY_GENERATOR,
    )
    record = publish_registry(root)
    assert record.counts["components"] == 1, "the hostile tree must really publish"
    assert merkle_digest(root) == record.digest
    return root


@requires_bwrap
def test_a_component_body_reading_a_file_is_denied_by_the_sandbox(
    hostile_component: Path, store: OpStore, tmp_path: Path
) -> None:
    from hephaestus.core.executor.sandbox.bwrap import BwrapBackend

    pinned = merkle_digest(hostile_component)
    ops = RegistryOps(
        RegistrySet({"parts": load_registry(hostile_component, expected_digest=pinned)}),
        store,
        backend=BwrapBackend(),
        scratch_root=tmp_path / "scratch",
    )
    with pytest.raises(RegistryError) as refusal:
        ops.instance_store_part("stepper_nema17_frame", {"body_length": 39.0})
    # The clause says `sandbox_denied`, exactly. Before this stage it could not
    # be: a denial arrives as a §8 *error record* from the worker subprocess,
    # never as an exception, so it missed the only arm that produced that reason
    # and every denial surfaced as the generic `generator_failed`. `_ops.py` now
    # reads the record's type — a tightening, not a re-interpretation of the
    # clause to fit what the code happened to do.
    assert refusal.value.reason == "sandbox_denied"
    assert "stepper_nema17_frame" in refusal.value.message
    # Nothing leaked: the refusal names the generator, never file contents.
    # `root:x:` is the first field of the first /etc/passwd line on any Linux
    # host, so its absence is the direct assertion that no bytes of the file
    # reached the caller — G6's "the refusal quotes no file contents", restated.
    assert "root:" not in refusal.value.message


def test_a_component_generator_gets_no_capability_a_part_script_lacks(
    hostile_component: Path, store: OpStore, tmp_path: Path
) -> None:
    """Sandbox parity's hard edge, restated for component content: without a
    probed secure backend it does not run at all, and it never degrades."""
    ops = RegistryOps(RegistrySet({"parts": load_registry(hostile_component)}), store, backend=None)
    with pytest.raises(RegistryError) as refusal:
        ops.instance_store_part("stepper_nema17_frame", {})
    assert refusal.value.reason == "capability_not_available"


def test_the_unsafe_backend_refuses_a_component_tree(
    hostile_component: Path, store: OpStore, tmp_path: Path
) -> None:
    from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend

    ops = RegistryOps(
        RegistrySet({"parts": load_registry(hostile_component)}),
        store,
        backend=UnsafeLocalBackend(),
        scratch_root=tmp_path / "scratch",
    )
    with pytest.raises(RegistryError) as refusal:
        ops.instance_store_part("stepper_nema17_frame", {})
    assert refusal.value.reason == "unsafe_refused"


def test_the_hostile_tree_and_a_clean_tree_differ_only_in_the_generator(
    hostile_component: Path, component_registry: Path, tmp_path: Path
) -> None:
    """A guard on the fixture itself: if the hostile tree stopped publishing,
    clause 22 would be testing an unpublishable tree and proving nothing."""
    clean = tmp_path / "clean"
    shutil.copytree(component_registry, clean)
    assert publish_registry(clean).counts["components"] == 1
    assert publish_registry(hostile_component).counts["components"] == 1
    assert "open(" in (hostile_component / "stepper_nema17_frame" / "generator.py").read_text(
        encoding="utf-8"
    )
