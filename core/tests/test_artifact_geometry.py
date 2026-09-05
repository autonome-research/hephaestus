"""Reloaded-BRep measurement sources (§7) — the honest empty index, and the
real published-artifact namespace ``measure``, ``heph check`` and project-scope
``run_checks`` were missing before the B-1 fix (audit 2026-09-04).

``part_only_source``/``artifact_source`` stay exactly what they are: the
honest fallback for an artifact with no recorded bundle, admitting only
``"part"``. ``published_artifact_source`` is the constructor B-1 adds beside
it — the same machinery :class:`~hephaestus.core.assembly.AnchorResolver`
already uses for constraint anchors, promoted to
:mod:`hephaestus.core.executor.published_geometry` so ``measure``,
``heph check`` and project-scope ``run_checks`` can build the identical
addressable view instead of the hardcoded-empty one. Real build throughout
(not synthetic ``GeometryIndex`` fixtures): the point is whether a *reloaded*
published artifact resolves a tag to a face, a label to its solid and an
unrecorded selector to a named refusal, which a hand-built index could not
prove.
"""

# Mirror of the kernel executionEnvironment relaxations for untyped
# build123d / OCP surfaces (root pyproject [tool.pyright]); everything else strict.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from _assembly_project import build_part
from hephaestus.core.addressing import GeometryIndex, namespace, resolve
from hephaestus.core.errors import AddressingError
from hephaestus.core.executor.artifact_geometry import (
    artifact_source,
    load_brep_shape,
    part_only_source,
)
from hephaestus.core.executor.published_geometry import addressable_namespace
from hephaestus.core.executor.tags import TagPlacement
from hephaestus.core.project_store.layout import ProjectLayout, open_store
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.types import BuildResult
from opstore.types import JSONValue

from opstore import OpStore

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def box_brep_bytes(tmp_path: Path) -> bytes:
    # OCP ships no stubs; this is the same untyped writer the worker uses.
    from build123d import Box
    from OCP.BRepTools import (  # pyright: ignore[reportMissingTypeStubs]
        BRepTools,  # pyright: ignore[reportUnknownVariableType, reportAttributeAccessIssue]
    )

    shape = Box(10.0, 5.0, 2.0)
    path = tmp_path / "box.brep"
    assert BRepTools.Write_s(shape.wrapped, str(path))  # pyright: ignore[reportUnknownMemberType]
    return path.read_bytes()


class TestArtifactSource:
    """``part_only_source``/``artifact_source`` — the honest no-bundle fallback.

    Unchanged by B-1 (fix item 1: "Keep ``part_only_source`` as the honest
    fallback when no bundle exists; stop making it the default for anything
    that has one."). These pin that it stays exactly this restrictive for the
    case it is still correct for.
    """

    def test_roundtrip_preserves_geometry(self, tmp_path: Path) -> None:
        data = box_brep_bytes(tmp_path)
        shape = load_brep_shape(data, scratch_dir=tmp_path / "scratch")
        volume = getattr(shape, "volume", None)
        assert volume == pytest.approx(100.0, abs=1e-6)

    def test_part_selector_resolves_to_the_loaded_shape(self, tmp_path: Path) -> None:
        data = box_brep_bytes(tmp_path)
        source = artifact_source(data, scratch_dir=tmp_path / "scratch")
        resolution = resolve("part", source.index)
        assert resolution.kind == "part"
        picked = source.shape(resolution)
        assert getattr(picked, "volume", None) == pytest.approx(100.0, abs=1e-6)

    def test_non_part_selectors_raise_addressing_error(self, tmp_path: Path) -> None:
        data = box_brep_bytes(tmp_path)
        source = artifact_source(data, scratch_dir=tmp_path)
        with pytest.raises(AddressingError):
            resolve("top_face", source.index)

    def test_part_only_index_is_empty(self, tmp_path: Path) -> None:
        data = box_brep_bytes(tmp_path)
        source = part_only_source(load_brep_shape(data))
        assert source.index.labels == ()
        assert dict(source.index.bindings) == {}
        assert source.index.tags == frozenset()


# --------------------------------------------------------------------------
# published_artifact_source — the B-1 fix: the real §7 namespace of a
# published build, not a hardcoded-empty one.

#: The B-1 ledger's own reproduction (``docs/audit-2026-09-04-broken.md``
#: lines 145-146): a labeled, tagged box. ``body`` is bound to the whole
#: compound and explicitly relabeled ``"wb"`` — so ``"wb"`` (label) and
#: ``"body"`` (binding) name the SAME node under two different selector
#: rules, which is exactly the case the audit's refusal-parity table cites.
WB_SCRIPT = (
    "body = Box(40, 20, 6)\n"
    'body.label = "wb"\n'
    'tag(body.faces().sort_by(Axis.Z)[-1], "top_face")\n'
    "part.geometry = body\n"
)


@pytest.fixture
def published_w(tmp_path: Path) -> Iterator[tuple[ProjectLayout, OpStore, Publisher]]:
    """A real published build of ``WB_SCRIPT`` as part ``"w"``."""
    from test_project_store_helpers import make_project

    layout = make_project(tmp_path / "proj", parts={"w": WB_SCRIPT})
    store = open_store(layout)
    publisher = Publisher(layout, store)
    build_part(publisher, layout, "w")
    yield layout, store, publisher
    store.close()


def _bundle_inputs(
    layout: ProjectLayout, store: OpStore, publisher: Publisher, part: str = "w"
) -> tuple[bytes, dict[str, JSONValue], BuildResult]:
    """The raw ingredients ``published_artifact_source`` is built from.

    Exactly what publication already recorded — the artifact bytes, the
    bundle's ``geometry_index`` and the ``BuildResult`` — with no reach into
    :class:`~hephaestus.core.assembly.AnchorResolver`'s private helpers, so
    this proves the *published record* carries what B-1 says it does,
    independent of the (already correct) constraint-anchor code path.
    """
    result = publisher.current_result(part)
    assert result is not None and result.artifact_ref is not None
    bundle = publisher.current_bundle(part)
    assert bundle is not None
    data = store.blobs.get(blob_hash_of_ref(result.artifact_ref))
    return data, dict(bundle), result


class TestPublishedArtifactSource:
    """``published_artifact_source`` resolves the full §7 grammar (B-1 fix item 1).

    The bundle already holds ``geometry_index: {"bindings": {"body": 1},
    "labels": ["wb"], "tags": ["top_face"]}`` (ledger reproduction) — this was
    NOT true of ``artifact_source``, which was exactly the bug: it built an
    empty index regardless of what the bundle recorded.
    """

    def test_tag_resolves_to_the_tagged_face(
        self, published_w: tuple[ProjectLayout, OpStore, Publisher], tmp_path: Path
    ) -> None:
        from hephaestus.core.executor.artifact_geometry import published_artifact_source

        layout, store, publisher = published_w
        data, bundle, result = _bundle_inputs(layout, store, publisher)
        shape = load_brep_shape(data, scratch_dir=tmp_path / "scratch")
        source = published_artifact_source(
            shape,
            index=_index_of(bundle, result),
            placements=_placements_of(result, store),
            result=result,
        )
        resolution = resolve("top_face", source.index)
        assert resolution.kind == "tag"
        face = cast("Any", source.shape(resolution))
        box = face.bounding_box()
        # A face of the box: flat in exactly one axis. The tagged face is the
        # top (highest Z), so its bounding box has zero Z-extent — the ledger's
        # own expected value, ``bbox == [40, 20, 0]``.
        assert pytest.approx((40.0, 20.0, 0.0), abs=1e-6) == (box.size.X, box.size.Y, box.size.Z)

    def test_label_resolves_to_its_solid(
        self, published_w: tuple[ProjectLayout, OpStore, Publisher], tmp_path: Path
    ) -> None:
        from hephaestus.core.executor.artifact_geometry import published_artifact_source

        layout, store, publisher = published_w
        data, bundle, result = _bundle_inputs(layout, store, publisher)
        shape = load_brep_shape(data, scratch_dir=tmp_path / "scratch")
        source = published_artifact_source(
            shape,
            index=_index_of(bundle, result),
            placements=_placements_of(result, store),
            result=result,
        )
        resolution = resolve("wb", source.index)
        assert resolution.kind == "label"
        solid = source.shape(resolution)
        assert getattr(solid, "volume", None) == pytest.approx(40.0 * 20.0 * 6.0, abs=1e-6)

    def test_part_resolves_to_the_whole_compound(
        self, published_w: tuple[ProjectLayout, OpStore, Publisher], tmp_path: Path
    ) -> None:
        from hephaestus.core.executor.artifact_geometry import published_artifact_source

        layout, store, publisher = published_w
        data, bundle, result = _bundle_inputs(layout, store, publisher)
        shape = load_brep_shape(data, scratch_dir=tmp_path / "scratch")
        source = published_artifact_source(
            shape,
            index=_index_of(bundle, result),
            placements=_placements_of(result, store),
            result=result,
        )
        resolution = resolve("part", source.index)
        assert resolution.kind == "part"
        whole = source.shape(resolution)
        assert getattr(whole, "volume", None) == pytest.approx(40.0 * 20.0 * 6.0, abs=1e-6)

    def test_binding_whose_label_diverged_is_a_named_refusal_not_a_blind_one(
        self, published_w: tuple[ProjectLayout, OpStore, Publisher], tmp_path: Path
    ) -> None:
        """``"body"`` is a real, recorded binding (§7 rule 4 matches it) — the
        bug this pins is that it must refuse as ``UnresolvableAnchorError``
        (a NAMED reason, same as :class:`~hephaestus.core.assembly.AnchorResolver`
        already gives constraint anchors), never as an ``AddressingError`` with
        an EMPTY candidate set the way today's hardcoded-empty index does.

        It does not resolve to geometry for a *general* reason, not a special
        case of this script: publication records label runs (§8) and tag
        placements (§5.3) beside a build's artifact bytes, and no
        binding-to-solid mapping at all, so ``kind="binding"`` is structurally
        unanswerable here — every binding refuses this way, not only one whose
        node was relabelled. ``body``'s label happens to have been overridden
        to ``"wb"`` (§5.1 label-fill only default-fills a binding's label when
        none was set), which is why *this* node is still addressable at all,
        but only by that label under rule 3, never by the binding name under
        rule 4. Confirmed against the unmodified, already-shipped
        ``AnchorResolver``/``PartGeometry`` mechanism this constructor is
        promoted from: it raises this exact error for this exact selector
        today, and the ``"byte-for-byte"`` fix (item 2) must not change that.
        """
        from hephaestus.core.assembly import UnresolvableAnchorError
        from hephaestus.core.executor.artifact_geometry import published_artifact_source

        layout, store, publisher = published_w
        data, bundle, result = _bundle_inputs(layout, store, publisher)
        index = _index_of(bundle, result)
        assert index.bindings.get("body") == 1  # the binding really is recorded
        resolution = resolve("body", index)  # resolves — §7 rule 4 matches
        assert resolution.kind == "binding"
        shape = load_brep_shape(data, scratch_dir=tmp_path / "scratch")
        source = published_artifact_source(
            shape, index=index, placements=_placements_of(result, store), result=result
        )
        with pytest.raises(UnresolvableAnchorError) as excinfo:
            source.shape(resolution)
        assert excinfo.value.reason == "unaddressable_anchor"

    def test_unknown_selector_lists_the_real_namespace_not_an_empty_one(
        self, published_w: tuple[ProjectLayout, OpStore, Publisher], tmp_path: Path
    ) -> None:
        """The empty-selector branch (``addressing.py``) lists
        ``namespace(index)[:5]`` — with this bundle's real index that is
        ``wb``, ``top_face`` and ``body`` (plus ``"part"``), not the ``()``
        today's hardcoded-empty ``GeometryIndex`` produces for the identical
        artifact. That empty tuple — not a refusal by itself, but the PROOF
        the index carried nothing to list — is what the audit's reproduction
        observed for every non-``"part"`` selector.
        """
        from hephaestus.core.executor.artifact_geometry import published_artifact_source

        layout, store, publisher = published_w
        data, bundle, result = _bundle_inputs(layout, store, publisher)
        shape = load_brep_shape(data, scratch_dir=tmp_path / "scratch")
        source = published_artifact_source(
            shape,
            index=_index_of(bundle, result),
            placements=_placements_of(result, store),
            result=result,
        )
        assert set(namespace(source.index)) >= {"wb", "top_face", "body", "part"}
        with pytest.raises(AddressingError) as excinfo:
            resolve("", source.index)
        assert set(excinfo.value.candidates) >= {"wb", "top_face", "body"}


def _index_of(bundle: dict[str, JSONValue], result: BuildResult) -> GeometryIndex:
    """The bundle's recorded §7 namespace, via the shared decoder.

    ``ASSEMBLY.md`` §2 / publication.py already write this on every current
    build (``build_bundle``'s ``geometry_index`` field);
    :func:`~hephaestus.core.executor.published_geometry.published_index` is the
    ONE reader of it, shared with
    :class:`~hephaestus.core.assembly.AnchorResolver` — using it here rather
    than re-decoding the field is the parity this fix is for.
    """
    from hephaestus.core.executor.published_geometry import published_index

    return published_index(bundle, result)


def _placements_of(result: BuildResult, store: OpStore) -> dict[str, TagPlacement]:
    """Tag placements from the build's stored source map (§5.3), via the shared decoder.

    :func:`~hephaestus.core.executor.published_geometry.tag_placements` is the
    ONE decoder of the source map's ``tags`` table
    (:class:`~hephaestus.core.assembly.AnchorResolver` reads through it too);
    this only fetches the blob the ref names.
    """
    import json

    from hephaestus.core.executor.published_geometry import tag_placements

    ref = result.source_map_ref
    if ref is None:
        return {}
    blob = blob_hash_of_ref(ref)
    if not store.blobs.has(blob):
        return {}
    raw = json.loads(store.blobs.get(blob).decode("utf-8"))
    if not isinstance(raw, dict):  # pragma: no cover - our own JSON
        return {}
    return tag_placements(raw)


# --------------------------------------------------------------------------
# addressable_namespace — what a caller ADVERTISES as candidates (fix item 3):
# every rule-4-only (binding) name dropped, a name that is BOTH a label and a
# binding kept (label outranks binding at the same name, so it never becomes
# unaddressable).


class TestAddressableNamespace:
    """``addressable_namespace`` strips names that would resolve as a binding.

    A hand-built :class:`GeometryIndex` (not a real build) is the right proof
    here: the claim is purely about the join between ``namespace()`` and
    ``resolve()``'s kind, independent of how any particular script produced
    the index — :class:`TestPublishedArtifactSource` above already proves the
    real-build case (``"body"`` refuses) via ``published_w``.
    """

    def test_drops_binding_only_names_keeps_label_binding_overlap(self) -> None:
        # "rib" is deliberately both a duplicated label (index 1 and 2) AND a
        # list binding (count 2) of the SAME name: §7 label precedence (rule
        # 3) beats binding precedence (rule 4) for every one of its spellings
        # ("rib", "rib#1", "rib#2", "rib#*"), so all of them stay addressable.
        # "body" (binding only, count 1) and "ribs" (binding only, count 2,
        # plus its "#1"/"#2"/"#*" aliases) match no label at all and so are
        # rule-4-only: every one of THEIR spellings must be dropped.
        index = GeometryIndex(
            labels=("wb", "rib", "rib"),
            bindings={"body": 1, "ribs": 2, "rib": 2},
            tags=frozenset({"top_face"}),
        )
        full = namespace(index)
        assert set(full) >= {
            "part",
            "top_face",
            "wb",
            "rib",
            "rib#1",
            "rib#2",
            "rib#*",
            "body",
            "ribs",
            "ribs#1",
            "ribs#2",
            "ribs#*",
        }
        result = addressable_namespace(index)
        assert result == ("part", "top_face", "wb", "rib", "rib#2", "rib#1", "rib#*")
        # Every dropped name resolves as a binding (the mechanism, not just
        # the outcome) — and none of the kept ones do.
        for name in result:
            assert resolve(name, index).kind != "binding"
        dropped = set(full) - set(result)
        assert dropped == {"body", "ribs", "ribs#1", "ribs#2", "ribs#*"}
        for name in dropped:
            assert resolve(name, index).kind == "binding"

    def test_index_with_no_bindings_is_unchanged(self) -> None:
        # The common case (no binding shadows a label): addressable_namespace
        # must not perturb order or content when nothing is rule-4-only.
        index = GeometryIndex(labels=("wb",), bindings={}, tags=frozenset({"top_face"}))
        assert addressable_namespace(index) == namespace(index)


# --------------------------------------------------------------------------
# published_source_for — the one store-only joint every parent-side
# measurement shares (``measure``, project-scope ``run_checks``, ``heph
# check``): with the build's bundle in hand it resolves the full §7 grammar;
# with no bundle it is the honest "part"-only fallback and says so via
# ``namespace_recorded`` (fix item 6).


class TestPublishedSourceFor:
    def test_bundle_present_resolves_tag_label_and_part(
        self, published_w: tuple[ProjectLayout, OpStore, Publisher], tmp_path: Path
    ) -> None:
        from hephaestus.core.executor.artifact_geometry import published_source_for

        _layout, store, publisher = published_w
        result = publisher.current_result("w")
        assert result is not None and result.artifact_ref is not None
        bundle = publisher.current_bundle("w")
        assert bundle is not None
        source = published_source_for(
            store,
            artifact_ref=result.artifact_ref,
            part="w",
            bundle=dict(bundle),
            scratch_dir=tmp_path / "scratch",
        )
        assert source.namespace_recorded is True

        tag_shape = cast("Any", source.shape(resolve("top_face", source.index)))
        box = tag_shape.bounding_box()
        assert pytest.approx((40.0, 20.0, 0.0), abs=1e-6) == (box.size.X, box.size.Y, box.size.Z)

        label_shape = source.shape(resolve("wb", source.index))
        assert getattr(label_shape, "volume", None) == pytest.approx(40.0 * 20.0 * 6.0, abs=1e-6)

        whole = source.shape(resolve("part", source.index))
        assert getattr(whole, "volume", None) == pytest.approx(40.0 * 20.0 * 6.0, abs=1e-6)

    def test_bundle_none_is_the_honest_part_only_fallback(
        self, published_w: tuple[ProjectLayout, OpStore, Publisher], tmp_path: Path
    ) -> None:
        from hephaestus.core.executor.artifact_geometry import published_source_for

        _layout, store, publisher = published_w
        result = publisher.current_result("w")
        assert result is not None and result.artifact_ref is not None

        source = published_source_for(
            store,
            artifact_ref=result.artifact_ref,
            part="w",
            bundle=None,
            scratch_dir=tmp_path / "scratch",
        )
        assert source.namespace_recorded is False
        assert source.index.labels == ()
        assert dict(source.index.bindings) == {}
        assert source.index.tags == frozenset()

        with pytest.raises(AddressingError):
            resolve("wb", source.index)

        whole = source.shape(resolve("part", source.index))
        assert getattr(whole, "volume", None) == pytest.approx(40.0 * 20.0 * 6.0, abs=1e-6)
