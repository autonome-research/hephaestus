"""Render artifact types, refs, and selection resolution over opstore (§3.3/§3.5).

Two published artifact families, both content-addressed through ``opstore``
blobs and named with the project-store ref grammar
(:func:`hephaestus.core.project_store.store.artifact_ref`):

- :class:`RenderArtifact` — one PNG (``artifact:render:sha256:…``) for a shaded
  ``rgb``/``section`` channel or the non-decodable composite selection preview
  (``artifact:selection-preview:sha256:…``).
- :class:`SelectionBundle` — one per view (``artifact:selection-bundle:…``)
  linking the three separate non-antialiased ID passes
  (``artifact:selection-pass:…`` for solid/face/edge), one global selection
  table (``artifact:selection-table:…``), and the **exact source build
  artifact ref** it was rendered from.

Immutability. Bundles and passes are content-addressed, so publishing a newer
build mints new bundles and never mutates an existing one; an old bundle keeps
resolving to its original source build.

GC transitivity (arch §3.5). Publication records ``opstore`` links so pinning
propagates both ways: the bundle links to every pass, the table, and the source
build (pinning the bundle retains them all), and every pass/preview links back
to its bundle (pinning one layer retains the bundle, table, and source build).

Resolution accepts a bundle ref **or** any pass ref and follows the immutable
bundle link. Anything else — an RGB render ref, the non-decodable preview, a
ref bound to a different build, or a ref whose blob has aged out — raises a
structured :class:`StaleSelectionError`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from hephaestus.core.project_store.store import artifact_ref, blob_hash_of_ref
from hephaestus.core.render.palette import SelectionEntry, build_legend
from opstore.types import JSONValue

from opstore import OpStore, canonical_json

__all__ = [
    "RENDER_KIND",
    "SELECTION_BUNDLE_KIND",
    "SELECTION_PASS_KIND",
    "SELECTION_PREVIEW_KIND",
    "SELECTION_TABLE_KIND",
    "PassRefs",
    "RenderArtifact",
    "RenderStore",
    "SelectionBundle",
    "SelectionResolution",
    "StaleSelection",
    "StaleSelectionError",
    "resolve_selection",
]

RENDER_KIND = "render"
SELECTION_PREVIEW_KIND = "selection-preview"
SELECTION_PASS_KIND = "selection-pass"
SELECTION_TABLE_KIND = "selection-table"
SELECTION_BUNDLE_KIND = "selection-bundle"

PassKind = Literal["solid", "face", "edge"]
StaleReason = Literal["rgb_ref", "wrong_mode", "mismatched", "expired", "malformed"]


def _ref_kind(ref: str) -> str | None:
    parts = ref.split(":")
    if len(parts) != 4 or parts[0] != "artifact" or parts[2] != "sha256" or not parts[3]:
        return None
    return parts[1]


@dataclass(frozen=True)
class RenderArtifact:
    """One published PNG artifact and its ref."""

    ref: str
    blob_hash: str


@dataclass(frozen=True)
class PassRefs:
    """The three separate ID-pass refs of one selection bundle."""

    solid: str
    face: str
    edge: str

    def to_json(self) -> dict[str, JSONValue]:
        return {"solid": self.solid, "face": self.face, "edge": self.edge}

    def as_tuple(self) -> tuple[str, str, str]:
        return (self.solid, self.face, self.edge)

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> PassRefs:
        for key in ("solid", "face", "edge"):
            if not isinstance(data.get(key), str):
                raise ValueError(f"pass_refs missing {key!r}")
        return cls(
            solid=cast("str", data["solid"]),
            face=cast("str", data["face"]),
            edge=cast("str", data["edge"]),
        )


@dataclass(frozen=True)
class SelectionBundle:
    """A published per-view selection bundle."""

    bundle_ref: str
    view: str
    source_artifact_ref: str
    pass_refs: PassRefs
    selection_table_ref: str
    preview_ref: str | None = None


@dataclass(frozen=True)
class SelectionResolution:
    """The immutable content one selection ref resolves to."""

    bundle_ref: str
    view: str
    source_artifact_ref: str
    pass_refs: PassRefs
    selection_table_ref: str
    entries: Mapping[int, SelectionEntry]
    preview_ref: str | None = None

    def legend(self) -> dict[str, dict[str, JSONValue]]:
        """The mask legend ``{colour_hex: descriptor}`` for this bundle."""
        return build_legend(self.entries)


@dataclass(frozen=True)
class StaleSelection:
    """A structured resolution failure (never raised bytes, always typed)."""

    reason: StaleReason
    ref: str
    detail: str

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "status": "error",
            "code": "stale_selection",
            "reason": self.reason,
            "ref": self.ref,
            "detail": self.detail,
        }


class StaleSelectionError(Exception):
    """Raised by :func:`resolve_selection`; carries a :class:`StaleSelection`."""

    def __init__(self, stale: StaleSelection) -> None:
        super().__init__(f"{stale.reason}: {stale.detail}")
        self.stale = stale


def _table_payload(
    source_artifact_ref: str, entries: Mapping[int, SelectionEntry]
) -> dict[str, JSONValue]:
    return {
        "kind": "selection_table",
        "version": 1,
        "source_artifact_ref": source_artifact_ref,
        "entries": {str(k): v.to_json() for k, v in sorted(entries.items())},
    }


def _parse_table(data: Mapping[str, JSONValue]) -> dict[int, SelectionEntry]:
    entries_raw = data.get("entries")
    if not isinstance(entries_raw, dict):
        raise ValueError("selection table has no entries")
    out: dict[int, SelectionEntry] = {}
    for key, value in cast("Mapping[str, JSONValue]", entries_raw).items():
        if not isinstance(value, dict):
            raise ValueError(f"selection entry {key!r} is not an object")
        out[int(key)] = SelectionEntry.from_json(cast("Mapping[str, JSONValue]", value))
    return out


class RenderStore:
    """Publishes render artifacts and selection bundles into one ``opstore``."""

    def __init__(self, store: OpStore) -> None:
        self._store = store

    def publish_render(self, png: bytes, *, kind: str = RENDER_KIND) -> RenderArtifact:
        """Publish one PNG as a content-addressed blob and return its ref."""
        blob = self._store.blobs.put(png)
        return RenderArtifact(ref=artifact_ref(kind, blob), blob_hash=blob)

    def publish_selection_bundle(
        self,
        *,
        view: str,
        source_artifact_ref: str,
        solid_png: bytes,
        face_png: bytes,
        edge_png: bytes,
        entries: Mapping[int, SelectionEntry],
        preview_png: bytes | None = None,
    ) -> SelectionBundle:
        """Publish one view's three ID passes, table, and linking bundle.

        Records GC links for pin transitivity in both directions (bundle ↔
        passes/preview, bundle → table/source). Content-addressed and therefore
        immutable: re-publishing identical inputs is a no-op that returns the
        same refs.
        """
        source_blob = blob_hash_of_ref(source_artifact_ref)
        solid_blob = self._store.blobs.put(solid_png)
        face_blob = self._store.blobs.put(face_png)
        edge_blob = self._store.blobs.put(edge_png)
        pass_refs = PassRefs(
            solid=artifact_ref(SELECTION_PASS_KIND, solid_blob),
            face=artifact_ref(SELECTION_PASS_KIND, face_blob),
            edge=artifact_ref(SELECTION_PASS_KIND, edge_blob),
        )
        table_blob = self._store.blobs.put(
            canonical_json(_table_payload(source_artifact_ref, entries)).encode("utf-8")
        )
        table_ref = artifact_ref(SELECTION_TABLE_KIND, table_blob)

        preview_ref: str | None = None
        preview_blob: str | None = None
        if preview_png is not None:
            preview_blob = self._store.blobs.put(preview_png)
            preview_ref = artifact_ref(SELECTION_PREVIEW_KIND, preview_blob)

        bundle_payload: dict[str, JSONValue] = {
            "kind": "selection_bundle",
            "version": 1,
            "view": view,
            "source_artifact_ref": source_artifact_ref,
            "pass_refs": pass_refs.to_json(),
            "selection_table_ref": table_ref,
        }
        if preview_ref is not None:
            bundle_payload["preview_ref"] = preview_ref
        bundle_blob = self._store.blobs.put(canonical_json(bundle_payload).encode("utf-8"))
        bundle_ref = artifact_ref(SELECTION_BUNDLE_KIND, bundle_blob)

        layer_blobs = [solid_blob, face_blob, edge_blob]
        if preview_blob is not None:
            layer_blobs.append(preview_blob)
        # bundle -> passes/preview/table/source: pinning the bundle keeps them.
        for target in (*layer_blobs, table_blob, source_blob):
            self._store.gc.link(bundle_blob, target)
        # each layer -> bundle: pinning one layer keeps the whole bundle.
        for layer in layer_blobs:
            self._store.gc.link(layer, bundle_blob)

        return SelectionBundle(
            bundle_ref=bundle_ref,
            view=view,
            source_artifact_ref=source_artifact_ref,
            pass_refs=pass_refs,
            selection_table_ref=table_ref,
            preview_ref=preview_ref,
        )


def _read_bundle(store: OpStore, bundle_blob: str, ref: str) -> dict[str, JSONValue]:
    if not store.blobs.has(bundle_blob):
        raise StaleSelectionError(
            StaleSelection("expired", ref, f"bundle blob {bundle_blob} is no longer stored")
        )
    loaded: object = json.loads(store.blobs.get(bundle_blob).decode("utf-8"))
    if not isinstance(loaded, dict):
        raise StaleSelectionError(
            StaleSelection("malformed", ref, "blob is not a selection bundle")
        )
    payload = cast("dict[str, JSONValue]", loaded)
    if payload.get("kind") != "selection_bundle":
        raise StaleSelectionError(
            StaleSelection("malformed", ref, "blob is not a selection bundle")
        )
    return payload


def _bundle_blob_for_pass(store: OpStore, pass_blob: str, ref: str) -> str:
    """Follow the immutable pass→bundle link to the pass's bundle blob."""
    if not store.blobs.has(pass_blob):
        raise StaleSelectionError(
            StaleSelection("expired", ref, f"pass blob {pass_blob} is no longer stored")
        )
    # Sorted for determinism: a pass blob shared by byte-identical passes of two
    # builds links to both bundles; pick the lexicographically smallest so
    # resolution is stable (real passes differ per build and are unambiguous).
    targets = sorted(target for source, target in store.gc.links() if source == pass_blob)
    for target in targets:
        if not store.blobs.has(target):
            continue
        try:
            loaded: object = json.loads(store.blobs.get(target).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(loaded, dict):
            payload = cast("dict[str, JSONValue]", loaded)
            if payload.get("kind") == "selection_bundle":
                pass_refs = payload.get("pass_refs")
                if (
                    isinstance(pass_refs, dict)
                    and ref in (cast("dict[str, JSONValue]", pass_refs)).values()
                ):
                    return target
    raise StaleSelectionError(
        StaleSelection("mismatched", ref, "no selection bundle links this pass ref")
    )


def resolve_selection(
    store: OpStore,
    ref: str,
    *,
    expected_source_artifact_ref: str | None = None,
) -> SelectionResolution:
    """Resolve a bundle or pass ref to its immutable :class:`SelectionResolution`.

    Raises :class:`StaleSelectionError` with a structured reason for an RGB
    render ref, the non-decodable preview, a ref bound to a different build than
    ``expected_source_artifact_ref``, a malformed ref, or an aged-out blob.
    """
    kind = _ref_kind(ref)
    if kind is None:
        raise StaleSelectionError(StaleSelection("malformed", ref, "not an artifact ref"))
    if kind == RENDER_KIND:
        raise StaleSelectionError(
            StaleSelection("rgb_ref", ref, "an rgb render ref is not palette-decodable")
        )
    if kind == SELECTION_PREVIEW_KIND:
        raise StaleSelectionError(
            StaleSelection(
                "wrong_mode", ref, "the composite preview is not a decodable selection pass"
            )
        )
    if kind == SELECTION_BUNDLE_KIND:
        bundle_blob = blob_hash_of_ref(ref)
    elif kind == SELECTION_PASS_KIND:
        pass_blob = blob_hash_of_ref(ref)
        bundle_blob = _bundle_blob_for_pass(store, pass_blob, ref)
    else:
        raise StaleSelectionError(
            StaleSelection("wrong_mode", ref, f"{kind!r} is not a selectable render ref")
        )

    payload = _read_bundle(store, bundle_blob, ref)
    bundle_ref = artifact_ref(SELECTION_BUNDLE_KIND, bundle_blob)
    try:
        view = cast("str", payload["view"])
        source_artifact_ref = cast("str", payload["source_artifact_ref"])
        pass_refs = PassRefs.from_json(cast("Mapping[str, JSONValue]", payload["pass_refs"]))
        table_ref = cast("str", payload["selection_table_ref"])
    except (KeyError, ValueError, TypeError) as exc:
        raise StaleSelectionError(
            StaleSelection("malformed", ref, f"bundle payload invalid: {exc}")
        ) from exc
    preview_ref = payload.get("preview_ref")
    if preview_ref is not None and not isinstance(preview_ref, str):
        preview_ref = None

    if expected_source_artifact_ref is not None and source_artifact_ref != (
        expected_source_artifact_ref
    ):
        raise StaleSelectionError(
            StaleSelection(
                "mismatched",
                ref,
                f"bundle source {source_artifact_ref} != expected {expected_source_artifact_ref}",
            )
        )

    # Verify the source build and table blobs survive; else the selection is
    # expired (its provenance/decode data has aged out).
    source_blob = blob_hash_of_ref(source_artifact_ref)
    if not store.blobs.has(source_blob):
        raise StaleSelectionError(
            StaleSelection("expired", ref, f"source build blob {source_blob} is no longer stored")
        )
    table_blob = blob_hash_of_ref(table_ref)
    if not store.blobs.has(table_blob):
        raise StaleSelectionError(
            StaleSelection("expired", ref, f"selection table blob {table_blob} is no longer stored")
        )
    try:
        table_payload = json.loads(store.blobs.get(table_blob).decode("utf-8"))
        entries = _parse_table(cast("Mapping[str, JSONValue]", table_payload))
    except (ValueError, UnicodeDecodeError) as exc:
        raise StaleSelectionError(
            StaleSelection("malformed", ref, f"selection table invalid: {exc}")
        ) from exc

    return SelectionResolution(
        bundle_ref=bundle_ref,
        view=view,
        source_artifact_ref=source_artifact_ref,
        pass_refs=pass_refs,
        selection_table_ref=table_ref,
        entries=entries,
        preview_ref=preview_ref,
    )
