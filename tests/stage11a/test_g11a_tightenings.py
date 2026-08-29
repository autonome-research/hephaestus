"""G11A clauses 8, 9, 18, 19, 20: the tightenings that ride with the record.

Four of the five change behaviour for trees that pass today, which is why each
is a clause rather than a footnote:

* clause 8 (``param_schema_drift``) makes the index read ``generator.py`` for
  the first time — a record could previously advertise a parameter the
  generator lacks and publish cleanly;
* clause 9 (``unlicensed_registry``) makes ``PUBLISHING.md:28``'s "publishing
  checks it is present" true, where ``opt_str`` had silently turned an absent
  license into ``""``;
* clause 18 (``duplicate_registry_kind``) converts ``_set.py``'s
  ``setdefault`` — a *silent drop* of the second registry of a kind — into a
  configuration error; and
* clauses 19-20 are the §7.2 publish-time scanners that make the operator's
  "REFERENCE, DO NOT VENDOR" decision mechanical rather than aspirational.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, cast

import pytest
from _g11a import LEGACY_PARTS, SHIPPED_PARTS, component_tree, index_of, motor_component
from hephaestus.core.registry import (
    BUNDLED_KINDS,
    MANIFEST_FILENAME,
    RegistryRefusal,
    RegistrySet,
    load_registry,
    parse_manifest,
    publish_registry,
)

# ==========================================================================
# clause 8 — param_schema_drift, both directions, index and publish


DRIFT_PARAMS: dict[str, Any] = {
    "body_length": {"type": "float", "default": 39.0, "min": 20.0, "max": 60.0},
    "shaft_length": {"type": "float", "default": 24.0, "min": 10.0, "max": 40.0},
}


def test_a_record_advertising_a_parameter_the_generator_lacks_is_refused(
    tmp_path: Path,
) -> None:
    root = component_tree(tmp_path / "tree", motor_component(), params=DRIFT_PARAMS)
    with pytest.raises(RegistryRefusal) as caught:
        index_of(root)
    assert caught.value.reason == "param_schema_drift"
    assert caught.value.detail["surplus"] == ["shaft_length"]
    assert "shaft_length" in caught.value.message


def test_a_record_omitting_a_parameter_the_generator_declares_is_refused(
    tmp_path: Path,
) -> None:
    root = component_tree(tmp_path / "tree", motor_component(), params={})
    with pytest.raises(RegistryRefusal) as caught:
        index_of(root)
    assert caught.value.reason == "param_schema_drift"
    assert caught.value.detail["shortfall"] == ["body_length"]


def test_param_schema_drift_also_refuses_publication(tmp_path: Path) -> None:
    root = component_tree(tmp_path / "tree", motor_component(), params=DRIFT_PARAMS)
    with pytest.raises(RegistryRefusal) as caught:
        publish_registry(root)
    assert caught.value.reason == "param_schema_drift"


#: The bundled ``parts`` tree's part count. Repointed 2026-08-29 by
#: PARTS_STORE.md's Named new work item 31, whose G11C half ("item 31 for the
#: completed packs", Gates sub-stage table) adds ``bearing_608``,
#: ``gear_module1_z20`` and ``stepper_nema17_frame`` to the six A shipped. The
#: clause this constant serves is unchanged — every shipped part still passes
#: the cross-check, the payload scanner and publication — so only the count
#: moved, and it is named once rather than repeated at each site.
SHIPPED_PART_COUNT = 9


def test_the_cross_check_holds_for_the_shipped_and_the_legacy_trees() -> None:
    """The negative control: a tightening that refuses shipped content is a bug."""
    assert len(index_of(SHIPPED_PARTS).ids()) == SHIPPED_PART_COUNT
    assert len(index_of(LEGACY_PARTS).ids()) == 2


# ==========================================================================
# clause 9 — unlicensed_registry


UNLICENSED = '[registry]\nname = "x"\nkind = "parts"\nversion = "0.0.1"\n'


def test_a_manifest_with_no_license_refuses_to_parse() -> None:
    with pytest.raises(RegistryRefusal) as caught:
        parse_manifest(UNLICENSED)
    assert caught.value.reason == "unlicensed_registry"


def test_an_empty_license_string_is_the_same_refusal() -> None:
    """The failure `opt_str` used to produce silently *was* the empty string."""
    with pytest.raises(RegistryRefusal) as caught:
        parse_manifest(UNLICENSED.replace("version", 'license = ""\nversion', 1))
    assert caught.value.reason == "unlicensed_registry"


def test_an_unlicensed_tree_neither_loads_nor_publishes(tmp_path: Path) -> None:
    root = component_tree(tmp_path / "tree", motor_component(), license_line=None)
    with pytest.raises(RegistryRefusal) as caught:
        load_registry(root)
    assert caught.value.reason == "unlicensed_registry"
    with pytest.raises(RegistryRefusal):
        publish_registry(root)


@pytest.mark.parametrize("kind", ["skills", "parts", "materials", "dfm"])
def test_every_shipped_registry_still_parses_unchanged(kind: str) -> None:
    registry = load_registry(SHIPPED_PARTS.parent / kind)
    assert registry.manifest.license, f"{kind} states its license"


# ==========================================================================
# clause 18 — duplicate_registry_kind


#: The unfederated kinds, in the words of the clause: every bundled kind outside
#: ``RegistrySet.FEDERATED_KINDS``. **PARTS_STORE.md G11A clause 18 was amended
#: 2026-08-29** to name these rather than ``parts``, and the amendment is written
#: out in the clause itself: §8's own second bullet scheduled merged federation
#: into G11C, C's clause 9 delivered it, so two ``parts`` trees now index
#: together and a colliding id is a per-id ``ambiguous_component_id``. The
#: refusal is *scoped*, not waived — ``skills``, ``materials`` and ``dfm`` each
#: still read one registry, so a second one really would be the silent drop §8
#: opens on. The ``parts`` half of the behaviour is
#: ``tests/stage11c/test_g11c_federation.py``.
UNFEDERATED_KINDS = ("skills", "materials", "dfm")

BUNDLED_TREES = SHIPPED_PARTS.parent


def _renamed_copy(source: Path, destination: Path, name: str) -> Path:
    """Copy a registry tree, giving the copy its own manifest ``name``.

    The clause says the refusal names **both** registries *and both roots*, and a
    plain ``copytree`` cannot evidence the first half: both copies would carry
    the source's manifest name, so a refusal that printed one name twice would
    satisfy a set-equality assertion. Two distinct names here, two distinct roots
    below, and the pair is then actually pinned.
    """
    shutil.copytree(source, destination)
    manifest = destination / MANIFEST_FILENAME
    text = manifest.read_text(encoding="utf-8")
    original = load_registry(source).name
    assert f'name = "{original}"' in text
    manifest.write_text(text.replace(f'name = "{original}"', f'name = "{name}"', 1), "utf-8")
    return destination


@pytest.mark.parametrize("kind", UNFEDERATED_KINDS)
def test_two_registries_of_an_unfederated_kind_refuse_naming_both_and_both_roots(
    kind: str, tmp_path: Path
) -> None:
    """Every unfederated kind, not a representative: the clause's subject is the
    whole complement of ``FEDERATED_KINDS``, and a kind omitted here is a kind
    whose silent drop nothing pins."""
    first_root = BUNDLED_TREES / kind
    second_root = _renamed_copy(first_root, tmp_path / f"vendor-{kind}", f"vendor-{kind}")
    with pytest.raises(RegistryRefusal) as caught:
        RegistrySet(
            {
                f"a-{kind}": load_registry(first_root),
                f"z-{kind}": load_registry(second_root),
            }
        )
    refusal = caught.value
    assert refusal.reason == "duplicate_registry_kind"
    assert refusal.detail["kind"] == kind

    # Both NAMES — distinct, because the copy was re-named on purpose.
    listed = refusal.detail["registries"]
    assert isinstance(listed, list)
    assert [str(name) for name in listed] == [f"hephaestus-{kind}", f"vendor-{kind}"]

    # Both ROOTS — the half that is always distinct, and the half an operator
    # acts on when two packs of a kind share a manifest name.
    roots = refusal.detail["roots"]
    assert isinstance(roots, list)
    assert [str(root) for root in roots] == [str(first_root), str(second_root)]
    assert len(set(roots)) == 2

    for fragment in (f"hephaestus-{kind}", f"vendor-{kind}", str(first_root), str(second_root)):
        assert fragment in refusal.message


def test_two_identically_named_registries_are_still_told_apart(tmp_path: Path) -> None:
    """The case the amendment's tightening is *for*: a fork, or a copy of the
    bundled tree, carrying the same manifest name. Naming the pair is useless
    here; naming the roots is the whole of what the operator can act on."""
    first_root = BUNDLED_TREES / "materials"
    second_root = tmp_path / "second-materials"
    shutil.copytree(first_root, second_root)
    with pytest.raises(RegistryRefusal) as caught:
        RegistrySet(
            {
                "a-materials": load_registry(first_root),
                "z-materials": load_registry(second_root),
            }
        )
    refusal = caught.value
    listed = [str(name) for name in cast("list[Any]", refusal.detail["registries"])]
    roots = [str(root) for root in cast("list[Any]", refusal.detail["roots"])]
    assert listed == ["hephaestus-materials", "hephaestus-materials"], "the names really do collide"
    assert roots == [str(first_root), str(second_root)]
    assert len(set(roots)) == 2, "and the roots still separate them"


def test_the_federated_kind_set_is_exactly_parts() -> None:
    """The clause's last half: federating a kind cannot silently retire this
    clause's subject, because the set the scoping keys on is pinned here.

    ``parts`` is in it — G11C clause 9's merge — and every kind this file
    parametrises is out of it. A later stage federating ``materials`` fails here
    and has to amend the clause, which is the intended cost.
    """
    assert set(RegistrySet.FEDERATED_KINDS) == {"parts"}
    assert set(UNFEDERATED_KINDS).isdisjoint(RegistrySet.FEDERATED_KINDS)
    assert set(UNFEDERATED_KINDS) | set(RegistrySet.FEDERATED_KINDS) == set(BUNDLED_KINDS)


def test_one_registry_per_kind_still_opens() -> None:
    registries = RegistrySet({"parts": load_registry(SHIPPED_PARTS)})
    assert registries.parts.ids()
    assert registries.by_kind("parts") is not None


@pytest.mark.parametrize("kind", UNFEDERATED_KINDS)
def test_one_registry_of_an_unfederated_kind_still_opens(kind: str) -> None:
    """The clause's own negative control, per kind: the refusal must not fire on
    the configuration every existing project actually has."""
    registries = RegistrySet({kind: load_registry(BUNDLED_TREES / kind)})
    assert registries.by_kind(kind) is not None


def test_the_refusal_is_deterministic_in_which_pair_it_names(tmp_path: Path) -> None:
    """Fail-closed is only useful if the report is stable: the pair is named in
    registry-key order, not in whatever order the mapping happened to iterate."""
    second = _renamed_copy(
        BUNDLED_TREES / "materials", tmp_path / "second-materials", "vendor-materials"
    )
    messages: set[str] = set()
    details: set[str] = set()
    for _ in range(3):
        with pytest.raises(RegistryRefusal) as caught:
            RegistrySet(
                {
                    "z-materials": load_registry(second),
                    "a-materials": load_registry(BUNDLED_TREES / "materials"),
                }
            )
        messages.add(caught.value.message)
        details.add(json.dumps(caught.value.detail, sort_keys=True))
    assert len(messages) == 1
    assert len(details) == 1
    # Registry-KEY order, not mapping-insertion order: `a-materials` is the
    # bundled tree and is named first even though it was inserted second.
    (detail,) = details
    assert detail.index("hephaestus-materials") < detail.index("vendor-materials")


# ==========================================================================
# clauses 19-20 — the §7.2 publish-time scanners


@pytest.mark.parametrize("payload", ["motor.pdf", "motor.step", "render.png"])
def test_a_vendored_payload_refuses_publication_naming_the_file(
    payload: str, tmp_path: Path
) -> None:
    root = component_tree(tmp_path / "tree", motor_component())
    (root / "stepper_nema17_frame" / payload).write_bytes(b"not source, not a record\n")
    with pytest.raises(RegistryRefusal) as caught:
        publish_registry(root)
    assert caught.value.reason == "vendored_third_party_payload"
    assert payload in caught.value.message


def test_every_vendored_payload_is_named_not_just_the_first(tmp_path: Path) -> None:
    root = component_tree(tmp_path / "tree", motor_component())
    for payload in ("motor.pdf", "motor.step", "render.png"):
        (root / "stepper_nema17_frame" / payload).write_bytes(b"x\n")
    with pytest.raises(RegistryRefusal) as caught:
        publish_registry(root)
    files = caught.value.detail["files"]
    assert isinstance(files, list)
    assert sorted(str(name) for name in files) == [
        "stepper_nema17_frame/motor.pdf",
        "stepper_nema17_frame/motor.step",
        "stepper_nema17_frame/render.png",
    ]


def test_prose_and_source_are_not_payloads(tmp_path: Path) -> None:
    """The negative control: a store tree keeps its README and its sources."""
    root = component_tree(tmp_path / "tree", motor_component())
    (root / "NOTES.md").write_text("# how this envelope was authored\n", encoding="utf-8")
    assert publish_registry(root).counts["components"] == 1


def test_the_shipped_and_legacy_trees_pass_the_payload_scanner() -> None:
    assert publish_registry(SHIPPED_PARTS).counts["parts"] == SHIPPED_PART_COUNT
    assert publish_registry(LEGACY_PARTS).counts["components"] == 0


def test_a_trademarked_component_id_refuses_publication(tmp_path: Path) -> None:
    root = component_tree(tmp_path / "tree", motor_component(), part_id="bearing_skf_6001")
    with pytest.raises(RegistryRefusal) as caught:
        publish_registry(root)
    assert caught.value.reason == "trademark_in_component_id"
    assert caught.value.detail["marks"] == ["skf"]
    assert "bearing_skf_6001" in caught.value.message


def test_a_generic_or_standard_derived_id_publishes(tmp_path: Path) -> None:
    root = component_tree(tmp_path / "tree", motor_component(), part_id="bearing_608")
    assert publish_registry(root).counts["components"] == 1


def test_the_trademark_scan_does_not_reach_legacy_parts(tmp_path: Path) -> None:
    """§7.2 draws the rule at *component* ids, and the scanner does the same.

    A legacy store part carries no record and no provenance claim, so widening
    the scan to it would refuse a tree this stage promised not to touch.
    """
    root = tmp_path / "legacy"
    shutil.copytree(LEGACY_PARTS, root)
    renamed = root / "legacy_skf_part"
    (root / "legacy_spacer").rename(renamed)
    manifest = (root / MANIFEST_FILENAME).read_text(encoding="utf-8")
    (root / MANIFEST_FILENAME).write_text(
        manifest.replace(
            'id = "legacy_spacer"\ndir = "legacy_spacer"',
            'id = "legacy_skf_part"\ndir = "legacy_skf_part"',
        ),
        encoding="utf-8",
    )
    import json

    meta_path = renamed / "part.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["id"] = "legacy_skf_part"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    assert publish_registry(root).counts["components"] == 0
