"""Separate image entrypoint. No CAD script/DFM entry point, argv or environment passthrough."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

from hephaestus.core.executor.sandbox.oci_identity import collect_runtime_identity
from hephaestus.core.executor.sandbox.oci_launcher import (
    FIXED_WORKER_ENV,
    LaunchRequest,
    apply_rlimits,
    parse_argv,
    write_payload,
)
from hephaestus.core.executor.sandbox.oci_protocol import PROBE_WORKER, diagnostic_bytes
from hephaestus.core.executor.sandbox.oci_storage import require_storage
from hephaestus.core.executor.sandbox.oci_storage_policy import STORAGE_POLICIES
from hephaestus.core.render.oci_protocol import (
    RENDER_ENV,
    RENDER_MODULES,
    RENDER_WORKER,
    manifest_bytes,
)


def parse_render_argv(argv: Sequence[str]) -> tuple[LaunchRequest | str, str | None]:
    if tuple(argv) == ("manifest",):
        return "manifest", None
    if len(argv) != 8 or argv[2] not in RENDER_MODULES:
        raise ValueError("renderer invocation not allowlisted")
    module = argv[2]
    # Reuse the reviewed run grammar/limit parser, NOT its workload allowlist.
    # The resulting request supplies limits/policy/nonce only; module is fixed
    # by the renderer's disjoint allowlist above.
    limits_argv = (*argv[:2], PROBE_WORKER, *argv[3:])
    request = parse_argv(limits_argv)
    if not isinstance(request, LaunchRequest) or (
        request.address_space_bytes > 2 * 1024**3 or request.nproc > 256
    ):
        raise ValueError("renderer resource envelope exceeded")
    return request, module


def main(argv: Sequence[str] | None = None) -> int:
    try:
        request, module = parse_render_argv(sys.argv[1:] if argv is None else argv)
        if request == "manifest":
            inventory = collect_runtime_identity()
            packages = inventory["packages"]
            for name, version in {
                "pyrender": "0.1.45",
                "pyopengl": "3.1.0",
                "pillow": "12.3.0",
                "pygltflib": "1.16.5",
            }.items():
                if not isinstance(packages, dict) or packages[name]["version"] != version:
                    raise ValueError("renderer package pin mismatch")
            write_payload(sys.stdout, manifest_bytes(inventory))
            return 0
        assert isinstance(request, LaunchRequest) and module is not None
        apply_rlimits(request)
        require_storage(STORAGE_POLICIES[request.storage_policy])
        env = dict(FIXED_WORKER_ENV)
        if module == RENDER_WORKER:
            env.update(RENDER_ENV)
        os.execve(
            sys.executable,
            [
                sys.executable,
                "-I",
                "-m",
                module,
                "--oci-transfer",
                request.storage_policy,
                request.nonce,
            ],
            env,
        )
    except Exception:
        write_payload(sys.stderr, diagnostic_bytes("renderer_launch_refused"))
        return 126
    raise AssertionError("execve returned")


if __name__ == "__main__":
    raise SystemExit(main())
