"""Private OCI launcher/identity/rlimit probe worker.

The input schema is intentionally closed.  This module never accepts source,
paths, commands, URLs, or module names.
"""

from __future__ import annotations

import json
import os
import re
import resource
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import BinaryIO, TextIO

from hephaestus.core.executor.sandbox.oci_protocol import (
    PROTOCOL_VERSION,
    diagnostic_bytes,
)

MAX_REQUEST_BYTES = 1024
_NONCE_RE = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


class ProbeRequestError(ValueError):
    pass


class ProbeProtocolError(ProbeRequestError):
    pass


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProbeRequestError("invalid probe request")
        result[key] = value
    return result


@dataclass(frozen=True)
class ProbeRequest:
    nonce: str
    protocol_version: int


def parse_request(payload: bytes) -> ProbeRequest:
    """Validate one size-bounded, closed-schema probe request."""
    if len(payload) > MAX_REQUEST_BYTES:
        raise ProbeRequestError("invalid probe request")
    try:
        value: object = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProbeRequestError("invalid probe request") from None
    if not isinstance(value, dict) or set(value) != {"nonce", "protocol_version"}:
        raise ProbeRequestError("invalid probe request")

    nonce = value.get("nonce")
    version = value.get("protocol_version")
    if not isinstance(nonce, str) or _NONCE_RE.fullmatch(nonce) is None:
        raise ProbeRequestError("invalid probe request")
    if type(version) is not int:
        raise ProbeRequestError("invalid probe request")
    if version != PROTOCOL_VERSION:
        raise ProbeProtocolError("unsupported protocol version")
    return ProbeRequest(nonce=nonce, protocol_version=version)


def _limit_value(
    name: str,
    *,
    required: bool,
    getrlimit: Callable[[int], tuple[int, int]],
) -> list[int] | None:
    kind = getattr(resource, name, None)
    if kind is None:
        if required:
            raise RuntimeError("required resource limit is unavailable")
        return None
    soft, hard = getrlimit(kind)
    return [int(soft), int(hard)]


def probe_record(
    request: ProbeRequest,
    *,
    getrlimit: Callable[[int], tuple[int, int]] | None = None,
    geteuid: Callable[[], int] | None = None,
    getegid: Callable[[], int] | None = None,
) -> dict[str, object]:
    """Describe the identity and limits inherited through the launcher."""
    read_limit = resource.getrlimit if getrlimit is None else getrlimit
    read_euid = os.geteuid if geteuid is None else geteuid
    read_egid = os.getegid if getegid is None else getegid
    effective_uid = read_euid()
    effective_gid = read_egid()
    return {
        "effective_gid": effective_gid,
        "effective_uid": effective_uid,
        "identity_matches": effective_uid == 65532 and effective_gid == 65532,
        "kind": "hephaestus_executor_probe",
        "nonce": request.nonce,
        "non_root": effective_uid != 0,
        "protocol_version": PROTOCOL_VERSION,
        "rlimits": {
            "RLIMIT_AS": _limit_value("RLIMIT_AS", required=True, getrlimit=read_limit),
            "RLIMIT_CORE": _limit_value("RLIMIT_CORE", required=True, getrlimit=read_limit),
            "RLIMIT_CPU": _limit_value("RLIMIT_CPU", required=True, getrlimit=read_limit),
            "RLIMIT_DATA": _limit_value("RLIMIT_DATA", required=False, getrlimit=read_limit),
            "RLIMIT_NPROC": _limit_value("RLIMIT_NPROC", required=False, getrlimit=read_limit),
        },
    }


def probe_bytes(
    request: ProbeRequest,
    *,
    getrlimit: Callable[[int], tuple[int, int]] | None = None,
    geteuid: Callable[[], int] | None = None,
    getegid: Callable[[], int] | None = None,
) -> bytes:
    record = probe_record(
        request,
        getrlimit=getrlimit,
        geteuid=geteuid,
        getegid=getegid,
    )
    return (
        json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("ascii")


def _write(stream: TextIO, payload: bytes) -> None:
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(payload)
        buffer.flush()
    else:
        stream.write(payload.decode("ascii"))
        stream.flush()


def _read_bounded(stream: BinaryIO) -> bytes:
    return stream.read(MAX_REQUEST_BYTES + 1)


def main() -> int:
    try:
        request = parse_request(_read_bounded(sys.stdin.buffer))
    except ProbeProtocolError:
        _write(
            sys.stderr,
            diagnostic_bytes("protocol_version_mismatch", component="oci_probe_worker"),
        )
        return 65
    except ProbeRequestError:
        _write(
            sys.stderr,
            diagnostic_bytes("invalid_probe_request", component="oci_probe_worker"),
        )
        return 64

    try:
        response = probe_bytes(request)
    except Exception:
        _write(
            sys.stderr,
            diagnostic_bytes("probe_inspection_failed", component="oci_probe_worker"),
        )
        return 78
    _write(sys.stdout, response)
    return 0


if __name__ == "__main__":  # pragma: no cover - invoked as an allowlisted module
    raise SystemExit(main())
