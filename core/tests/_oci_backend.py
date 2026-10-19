"""Owned synthetic control seams. Never use these doubles for live acceptance."""

from hephaestus.core.executor.sandbox.base import CapabilityReport
from hephaestus.core.executor.sandbox.oci import OciBackend


class ManifestBackend(OciBackend):
    def set_observed_image(self, image_id: str) -> None:
        self._image_id = image_id

    def accept_manifest(self, payload: bytes) -> None:
        self._accept_manifest(payload)

    def validate_image(self) -> None:
        self._validate_image()

    def poison(self, *, unsettled: bool) -> None:
        (self._unsettled_creates if unsettled else self._unreconciled_containers).add("owned")

    @property
    def passing_report(self) -> CapabilityReport | None:
        return self._passing_report
