"""Synthetic identities for host unit tests; never live execution evidence."""

from hephaestus.core.executor.identity import ExecutionIdentity


def runtime_inventory():
    return {
        "version": 1,
        "python": "3.13.7",
        "packages": {
            name: {"version": version, "metadata_sha256": "sha256:" + "d" * 64}
            for name, version in (
                ("hephaestus-executor-runtime", "0.1.0"),
                ("opstore", "0.1.0"),
                ("build123d", "0.11.1"),
                ("cadquery-ocp-novtk", "7.9.3.1.1"),
            )
        },
        "source_trees": {
            "hephaestus-executor-runtime": "sha256:" + "a" * 64,
            "opstore": "sha256:" + "b" * 64,
        },
    }


def identity(*, image_ref=None, platform="linux/amd64", runtime=None, image_id=None):
    return ExecutionIdentity.for_oci(
        image_ref=image_ref or "registry.example/hephaestus/executor@sha256:" + "a" * 64,
        image_id=image_id or "sha256:" + "e" * 64,
        platform=platform,
        runtime=runtime or runtime_inventory(),
    )
