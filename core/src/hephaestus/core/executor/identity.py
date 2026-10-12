"""Host-owned execution identity, independent of worker result JSON.

Native backends retain the existing toolchain hash. OCI backends implement the
optional ExecutionIdentityProvider protocol; their identity must accompany the
host outcome as well as match the provider before assembly. Stored metadata is
an audit record, never an authority for selecting a live executor.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol, cast, runtime_checkable

from hephaestus.core.errors import ValidationError
from hephaestus.core.executor.sandbox.oci_identity import validate_runtime_identity
from opstore.hashing import canonical_json, is_hash, sha256_canonical_json
from opstore.types import JSONValue

IDENTITY_METADATA_KEY = "hephaestus.execution_identity"


@dataclass(frozen=True)
class ExecutionIdentity:
    """Deeply immutable canonical record; construction validates, not attests.

    Only trusted backend control code may provide this to the runner. Parsing a
    stored record proves schema/hash consistency, not that a workload executed.
    """

    canonical: str

    def __post_init__(self) -> None:
        try:
            if not isinstance(self.canonical, str) or len(self.canonical.encode()) > 64 * 1024:
                raise ValueError("oversized execution identity")
            value = json.loads(self.canonical)
            if not isinstance(value, dict) or set(value) != {
                "kind",
                "version",
                "image_ref",
                "image_id",
                "platform",
                "runtime",
            }:
                raise ValueError("invalid execution identity schema")
            if value["kind"] != "oci" or type(value["version"]) is not int or value["version"] != 1:
                raise ValueError("unsupported execution identity")
            # Lazy import: the lightweight record does not import the OCI transport.
            from hephaestus.core.executor.sandbox.oci import parse_immutable_image_ref

            parse_immutable_image_ref(value["image_ref"])
            if not is_hash(value["image_id"]) or value["platform"] not in {
                "linux/arm64",
                "linux/amd64",
            }:
                raise ValueError("invalid execution image/platform")
            validate_runtime_identity(value["runtime"])
            if canonical_json(value) != self.canonical:
                raise ValueError("noncanonical execution identity")
        except (ValueError, TypeError, KeyError) as exc:
            raise ValidationError("invalid execution identity", kind="contract") from exc

    @classmethod
    def for_oci(
        cls, *, image_ref: str, image_id: str, platform: str, runtime: object
    ) -> ExecutionIdentity:
        return cls(
            canonical_json(
                cast(
                    "JSONValue",
                    {
                        "kind": "oci",
                        "version": 1,
                        "image_ref": image_ref,
                        "image_id": image_id,
                        "platform": platform,
                        "runtime": runtime,
                    },
                )
            )
        )

    def to_json(self) -> dict[str, JSONValue]:
        return cast("dict[str, JSONValue]", json.loads(self.canonical))

    @property
    def toolchain_hash(self) -> str:
        # Repository names are locations, not executor content. Retain the full
        # attested reference for audit, but identical immutable image aliases
        # must not invalidate a build merely because the local tag was renamed.
        value = self.to_json()
        reference = cast("str", value.pop("image_ref"))
        value["image_digest"] = reference.partition("@")[2]
        return sha256_canonical_json(value)


@runtime_checkable
class ExecutionIdentityProvider(Protocol):
    def execution_identity(self) -> ExecutionIdentity:
        """Return a trusted currently usable identity, or refuse; never None."""
        ...


def backend_execution_identity(backend: object) -> ExecutionIdentity | None:
    """Supported opt-in backend API. Absence denotes the legacy native backend.

    An OCI-named backend without the provider is an invalid integration, not a
    reason to hash whatever CAD packages happen to be installed on the host.
    """
    if isinstance(backend, ExecutionIdentityProvider):
        identity = backend.execution_identity()
        if not isinstance(identity, ExecutionIdentity):
            raise ValidationError("backend execution identity is missing", kind="contract")
        return identity
    if str(getattr(backend, "name", "")).startswith("oci-"):
        raise ValidationError("OCI backend has no execution identity provider", kind="contract")
    return None


def recorded_execution_identity(metadata: object, toolchain: str) -> ExecutionIdentity | None:
    if not isinstance(metadata, dict) or IDENTITY_METADATA_KEY not in metadata:
        return None
    raw = metadata[IDENTITY_METADATA_KEY]
    if not isinstance(raw, str):
        raise ValidationError("execution identity metadata must be text", kind="contract")
    identity = ExecutionIdentity(raw)
    if identity.toolchain_hash != toolchain:
        raise ValidationError("execution identity hash mismatch", kind="contract")
    return identity
