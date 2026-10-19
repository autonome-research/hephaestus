"""Shared acceptance assertion for the authored two-cuboid render fixture."""

from collections.abc import Mapping

from hephaestus.core.render.palette import SelectionEntry
from opstore.types import JSONValue


def require_fixture_faces(
    validation: Mapping[str, JSONValue], entries: Mapping[int, SelectionEntry]
) -> None:
    """The fixture must retain all twelve faces, not merely a valid partial GLB."""
    faces = {key: entry for key, entry in entries.items() if entry.kind == "face"}
    face_ids = validation["face_ids"]
    if not (
        len(faces) == 12
        and {(e.solid_index, e.topology_index) for e in faces.values()}
        == {(solid, face) for solid in range(2) for face in range(6)}
        and validation["primitive_count"] == 12
        and isinstance(face_ids, list)
        and set(face_ids) == set(faces)
    ):
        raise RuntimeError("complete two-cuboid GLB face set (12 primitives)")
