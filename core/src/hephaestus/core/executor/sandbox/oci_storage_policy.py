"""Immutable filesystem and transfer ceilings for experimental OCI profiles 4/5."""

from dataclasses import dataclass, fields
from types import MappingProxyType

# Docker's ipc=none still exposes POSIX mqueue. Mask it with a tiny RO tmpfs.
MQUEUE_MASK = "ro,nosuid,nodev,noexec,size=4096,nr_inodes=1,mode=0000"
ARTIFACT_TRANSFER_VERSION = 1
REQUEST_MAX_BYTES = 16 * 1024**2
STORAGE_WORKER = "hephaestus.core.executor.sandbox._oci_storage_worker"
STORAGE_OPERATIONS = frozenset(
    {
        "positive",
        "work-bytes",
        "tmp-bytes",
        "work-inodes",
        "tmp-inodes",
        "truncated",
        "bad-digest",
        "trailing",
        "oversized-header",
        "finite-stderr",
        "partial-body",
        "artifact-truncated-footer",
        "stdout-overflow",
    }
)


@dataclass(frozen=True)
class StoragePolicy:
    work_bytes: int = 128 * 1024**2
    work_inodes: int = 2048
    tmp_bytes: int = 16 * 1024**2
    tmp_inodes: int = 256
    input_bytes: int = 64 * 1024**2
    input_files: int = 128
    result_bytes: int = 16 * 1024**2
    export_bytes: int = 72 * 1024**2

    def __post_init__(self) -> None:
        # Policies can tighten but never silently widen the library's ceilings.
        for field in fields(self):
            value = getattr(self, field.name)
            maximum = field.default
            if type(maximum) is not int:
                raise TypeError("storage policy default must be an integer")
            if type(value) is not int or not 0 < value <= maximum:
                raise ValueError("invalid storage policy limit")


DEFAULT_STORAGE = StoragePolicy()
CONTROL_STORAGE = StoragePolicy(8 * 1024**2, 128, 2 * 1024**2, 64, 65536, 8, 65536, 262144)
STORAGE_POLICIES = MappingProxyType({"ordinary": DEFAULT_STORAGE, "control": CONTROL_STORAGE})
