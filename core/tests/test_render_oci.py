"""Daemon-free renderer boundaries; fabricated pixels here are parser tests, not render evidence."""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path

import pytest
from hephaestus.core.executor.sandbox.base import Rlimits, SandboxSpec
from hephaestus.core.executor.sandbox.oci import (
    OciBackend,
    OciIdentity,
    OciRuntime,
    build_create_argv,
)
from hephaestus.core.executor.sandbox.oci_protocol import (
    BUILD_WORKER,
    PROTOCOL_VERSION,
    approved_module_for_worker_args,
)
from hephaestus.core.executor.sandbox.oci_storage_policy import STORAGE_POLICIES
from hephaestus.core.executor.sandbox.oci_transfer import Receiver, encode, export
from hephaestus.core.render.oci_launcher import parse_render_argv
from hephaestus.core.render.oci_protocol import (
    RENDER_WORKER,
    manifest_bytes,
    read_request,
    request_bytes,
    request_hash,
    validate_response,
)


def request(operation="selection"):
    return {
        "version": 2,
        "links": None,
        "operation": operation,
        "source_ref": "artifact:build:sha256:" + "a" * 64,
        "brep_sha256": "a" * 64,
        "view": "iso",
        "width": 16,
        "height": 16,
        "solids": [{"label": "cube", "color": None}],
        "placements": [],
        "section": {"axis": "Z", "sign": 1, "offset": 0} if operation == "section" else None,
    }


def response(req):
    result = {
        "version": 2,
        "glb": None,
        "operation": req["operation"],
        "request_sha256": request_hash(req),
        "source_ref": req.get("source_ref"),
        "gl_renderer": "llvmpipe (test schema fixture, not evidence)",
        "topology": [],
        "entries": {},
        "images": {},
        "section": None,
    }
    if req["operation"] == "probe":
        return result
    result["topology"] = [{"faces": 1, "edges": 1}]
    for index, kind in enumerate(("solid", "face", "edge"), 1):
        result["entries"][str(index)] = {
            "kind": kind,
            "solid_index": 0,
            "topology_index": 0,
            "label": "cube",
        }
    op = req["operation"]
    if op == "mask":
        result["entries"] = {"0": result["entries"]["1"]}
    elif op != "selection":
        result["entries"] = {}
    for index, kind in enumerate(
        ("solid", "face", "edge", "preview") if op == "selection" else (op,), 1
    ):
        raw = (
            bytes([0, 0, index + 1])
            if op == "selection" and kind != "preview"
            else bytes([0, 0, 1, 255])
        ) * 256
        result["images"][kind] = {
            "channels": 3 if op == "selection" and kind != "preview" else 4,
            "pixels": base64.b64encode(raw).decode(),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    if op == "section":
        result["section"] = {"faces": 1, "area_mm2": 1.0}
    return result


@pytest.mark.parametrize("operation", ["rgb", "mask", "selection", "section", "probe"])
def test_closed_roundtrip(operation):
    req = request(operation) if operation != "probe" else {"version": 2, "operation": "probe"}
    assert read_request(request_bytes(req)) == req
    result = response(req)
    assert validate_response(encode(result), req) == result


@pytest.mark.parametrize(
    "key,mutation",
    [
        (key, mutation)
        for key in request()
        for mutation in ("remove", "null")
        if (key, mutation) not in (("section", "null"), ("links", "null"))
    ],
)
def test_request_missing_or_null(key, mutation):
    req = request()
    if mutation == "remove":
        del req[key]
    else:
        req[key] = None
    with pytest.raises((ValueError, TypeError)):
        request_bytes(req)


@pytest.mark.parametrize(
    "key,value",
    [
        ("version", True),
        ("version", 0),
        ("version", 1),
        ("version", 3),
        ("operation", "exec"),
        ("operation", BUILD_WORKER),
        ("width", True),
        ("width", 513),
        ("width", 0),
        ("height", 16.0),
        ("height", -1),
        ("source_ref", "artifact:build:sha256:" + "b" * 64),
        ("view", "aznan_el0"),
        ("solids", []),
        ("script", "print(1)"),
        ("path", "/home/source.brep"),
        ("entrypoint", ["sh"]),
        ("module", "os"),
        ("section", {"axis": "Z", "sign": 1, "offset": 0}),
    ],
)
def test_request_refusals(key, value):
    req = request()
    req[key] = value
    with pytest.raises(ValueError):
        request_bytes(req)


@pytest.mark.parametrize(
    "section",
    [
        {"axis": "Z", "sign": 0, "offset": 0},
        {"axis": "X", "sign": True, "offset": 0},
        {"axis": "Z", "sign": 1, "offset": float("nan")},
        {"axis": "Z", "sign": 1, "offset": float("inf")},
        {"axis": "W", "sign": 1, "offset": 0},
        {"axis": "Z", "sign": 1, "offset": 1e7},
    ],
)
def test_section_refusals(section):
    req = request("section")
    req["section"] = section
    with pytest.raises(ValueError):
        request_bytes(req)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"version":1,"version":1,"operation":"probe"}',
        b'{"version":NaN}',
        b"[" * 33 + b"]" * 33,
        b" " * (128 * 1024 + 1),
    ],
)
def test_wire_refusals(raw):
    with pytest.raises(ValueError):
        read_request(raw)


@pytest.mark.parametrize(
    "key,mutation",
    [
        (key, mutation)
        for key in response(request())
        for mutation in ("remove", "null", "extra")
        if (key, mutation) not in (("section", "null"), ("glb", "null"))
    ],
)
def test_response_fields(key, mutation):
    req = request()
    result = response(req)
    if mutation == "remove":
        del result[key]
    elif mutation == "null":
        result[key] = None
    else:
        result["unexpected"] = True
    with pytest.raises((ValueError, TypeError)):
        validate_response(encode(result), req)


@pytest.mark.parametrize(
    "key,value",
    [
        ("version", True),
        ("version", 1),
        ("version", 3),
        ("gl_renderer", "hardware GPU"),
        ("source_ref", "wrong"),
        ("request_sha256", "b" * 64),
        ("operation", "rgb"),
        ("topology", [{"faces": True, "edges": 1}]),
        ("topology", [{"faces": 2048, "edges": 1}]),
        ("entries", {}),
        ("images", {}),
    ],
)
def test_response_refusals(key, value):
    req = request()
    result = response(req)
    result[key] = value
    with pytest.raises(ValueError):
        validate_response(encode(result), req)


@pytest.mark.parametrize(
    "mutation",
    [
        "kind",
        "index",
        "bool",
        "tag",
        "label",
        "id",
        "image_length",
        "image_digest",
        "image_channels",
        "pixel_kind",
        "pixel_unknown",
        "extra_image",
        "image_traversal",
    ],
)
def test_exact_table_and_palette(mutation):
    req = request()
    result = response(req)
    entry = result["entries"]["1"]
    image = result["images"]["solid"]
    if mutation in ("kind", "index", "bool", "tag", "label"):
        key, value = {
            "kind": ("kind", "edge"),
            "index": ("topology_index", 1),
            "bool": ("solid_index", False),
            "tag": ("tag", "invented"),
            "label": ("label", "wrong"),
        }[mutation]
        entry[key] = value
    elif mutation == "id":
        result["entries"]["01"] = result["entries"].pop("1")
    elif mutation == "image_length":
        image["pixels"] += "AAAA"
    elif mutation == "image_digest":
        image["sha256"] = "a" * 64
    elif mutation == "image_channels":
        image["channels"] = 4
    elif mutation.startswith("pixel_"):
        raw = bytes([0, 0, 3 if mutation == "pixel_kind" else 200]) * 256
        image.update(pixels=base64.b64encode(raw).decode(), sha256=hashlib.sha256(raw).hexdigest())
    else:
        result["images"]["extra" if mutation == "extra_image" else "../escape"] = copy.deepcopy(
            image
        )
    with pytest.raises(ValueError):
        validate_response(encode(result), req)


def test_shared_transfer_fragmented_and_truncated(tmp_path):
    req = request()
    result = response(req)
    wire = io.BytesIO()
    export(wire, result, "a" * 64, RENDER_WORKER, tmp_path, STORAGE_POLICIES["ordinary"])
    with Receiver(tmp_path, "a" * 64, RENDER_WORKER, STORAGE_POLICIES["ordinary"]) as receiver:
        for b in wire.getvalue():
            receiver.feed(bytes([b]))
        assert validate_response(receiver.finish(), req) == result
        assert not receiver.files
    with Receiver(tmp_path, "a" * 64, RENDER_WORKER, STORAGE_POLICIES["ordinary"]) as receiver:
        receiver.feed(wire.getvalue()[:-1])
        with pytest.raises(ValueError, match="truncated"):
            receiver.finish()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "module", [BUILD_WORKER, "os", RENDER_WORKER + ".extra", "hephaestus.core.dfm.worker"]
)
def test_renderer_launcher_refuses_cad_and_arbitrary(module):
    with pytest.raises(ValueError):
        parse_render_argv(
            (
                "run",
                str(PROTOCOL_VERSION),
                module,
                "120",
                str(2 * 1024**3),
                "256",
                "ordinary",
                "a" * 64,
            )
        )


def test_cad_worker_allowlist_unchanged():
    with pytest.raises(ValueError):
        approved_module_for_worker_args(("-m", RENDER_WORKER))


@pytest.mark.parametrize("version", ["1", "2", "4", "true"])
def test_renderer_run_version_rejection(version):
    with pytest.raises(ValueError):
        parse_render_argv(
            ("run", version, RENDER_WORKER, "120", str(2 * 1024**3), "256", "ordinary", "a" * 64)
        )


def test_separate_manifest_and_create(tmp_path):
    from hephaestus.core.executor.sandbox.oci_protocol import manifest_bytes as cad_manifest

    assert manifest_bytes() != cad_manifest()
    assert json.loads(manifest_bytes())["workers"] == sorted(
        {
            RENDER_WORKER,
            "hephaestus.core.executor.sandbox._oci_probe_worker",
            "hephaestus.core.executor.sandbox._oci_storage_worker",
        }
    )
    runtime = OciRuntime("docker", Path("/usr/bin/docker"))
    spec = SandboxSpec(("-m", RENDER_WORKER), (), tmp_path, Rlimits(120, 2 * 1024**3, 256), 120)
    args = (
        runtime,
        "localhost/render@sha256:" + "a" * 64,
        "linux/arm64",
        spec,
        "heph-exec-" + "a" * 64,
    )
    with pytest.raises(ValueError):
        build_create_argv(*args, identity=OciIdentity(501, 20))
    argv = build_create_argv(*args, identity=OciIdentity(501, 20), runtime_profile="renderer")
    assert "--log-driver=none" in argv and "--read-only" in argv
    assert "--entrypoint" not in argv
    with pytest.raises(ValueError):
        build_create_argv(
            *args[:3],
            replace(spec, worker_args=("-m", BUILD_WORKER)),
            args[4],
            identity=OciIdentity(501, 20),
            runtime_profile="renderer",
        )
    with pytest.raises(ValueError):
        OciBackend(runtime, args[1], "linux/amd64", runtime_profile="renderer")


class RenderTransport:
    """Synthetic lifecycle only; never supplied to live acceptance."""

    def __init__(self, mode):
        self.mode = mode
        self.argv = None
        self.exists = True
        self.running = False
        self.killed = False
        self.removed = False
        self.started = False

    def run(self, argv, *, stdout_consumer=None, **kwargs):
        from hephaestus.core.executor.sandbox.oci import TransportResult, TransportTimeout
        from test_sandbox_oci import CONTAINER_ID, synthetic_effective

        def result(value):
            return TransportResult(0, (json.dumps(value) + "\n").encode(), b"")

        if "create" in argv:
            self.argv = argv
            return TransportResult(0, (CONTAINER_ID + "\n").encode(), b"")
        if "inspect" in argv:
            if not self.exists:
                return TransportResult(1, b"", b"No such object\n")
            if "{{json .}}" in argv:
                effective = synthetic_effective(self.argv)
                effective["Config"]["Entrypoint"][-1] = "hephaestus.core.render.oci_launcher"
                if self.mode == "image_mismatch":
                    effective["Image"] = "sha256:" + "f" * 64
                return result(effective)
            return result(
                {
                    "Running": self.running,
                    "ExitCode": 137 if self.killed else (1 if self.mode == "failure" else 0),
                    "OOMKilled": self.mode == "oom",
                }
            )
        if "start" in argv:
            self.started = True
            if self.mode == "timeout":
                self.running = True
                raise TransportTimeout()
            if self.mode == "failure":
                return TransportResult(1, b"", b"renderer_failed\n")
            wire = io.BytesIO()
            req = {"version": 2, "operation": "probe"}
            export(
                wire,
                response(req),
                self.argv[-1],
                RENDER_WORKER,
                Path(self.argv[self.argv.index("--mount") + 1].split("source=")[1].split(",")[0]),
                STORAGE_POLICIES["ordinary"],
            )
            data = wire.getvalue()
            if self.mode == "malformed":
                data = b"BAD" + data[3:]
            elif self.mode == "truncated":
                data = data[:-1]
            stdout_consumer(data)
            return TransportResult(0, b"", b"")
        if "kill" in argv:
            self.killed = True
            self.running = False
            return TransportResult(0, b"", b"")
        if "rm" in argv:
            self.removed = True
            self.exists = self.mode == "uncertain_cleanup"
            return TransportResult(0, b"", b"")
        raise AssertionError(argv)


@pytest.mark.parametrize(
    "mode",
    [
        "success",
        "failure",
        "timeout",
        "oom",
        "malformed",
        "truncated",
        "image_mismatch",
        "uncertain_cleanup",
    ],
)
def test_renderer_reuses_fail_closed_lifecycle(tmp_path, mode):
    from hephaestus.core.errors import SandboxDeniedError
    from test_sandbox_oci import IMAGE, passing, runtime

    transport = RenderTransport(mode)
    backend = OciBackend(
        runtime(),
        IMAGE,
        "linux/arm64",
        identity=OciIdentity(501, 20),
        transport=transport,
        runtime_profile="renderer",
    )
    passing(backend)  # unit fixture only; live CLI never injects capability reports
    spec = SandboxSpec(("-m", RENDER_WORKER), (), tmp_path, Rlimits(120, 2 * 1024**3, 256), 120)
    payload = request_bytes({"version": 2, "operation": "probe"})
    if mode in {"oom", "malformed", "truncated", "image_mismatch", "uncertain_cleanup"}:
        with pytest.raises(SandboxDeniedError):
            backend.execute(spec, payload)
    else:
        outcome = backend.execute(spec, payload)
        assert outcome.timed_out is (mode == "timeout")
        assert outcome.exit_code == {"success": 0, "timeout": 137, "failure": 1}[mode]
    assert transport.removed
    assert list(tmp_path.iterdir()) == []
    if mode == "timeout":
        assert transport.killed
    if mode == "image_mismatch":
        assert not transport.started
    if mode == "uncertain_cleanup":
        assert backend.unreconciled_containers
    else:
        assert not transport.exists and not backend.unsettled_creates


@pytest.mark.parametrize(
    "mutation", ["cad", "no_extension", "old_api", "extra_operation", "extra_field"]
)
def test_manifest_rejects_old_and_other_images(mutation):
    from _execution_identity import runtime_inventory
    from hephaestus.core.errors import SandboxDeniedError
    from hephaestus.core.executor.sandbox.oci_protocol import manifest_bytes as cad_manifest
    from test_sandbox_oci import IMAGE, runtime

    inventory = runtime_inventory()
    backend = OciBackend(
        runtime(), IMAGE, "linux/arm64", identity=OciIdentity(501, 20), runtime_profile="renderer"
    )
    backend._image_id = "sha256:" + "e" * 64
    data = json.loads(manifest_bytes(inventory))
    if mutation == "cad":
        raw = cad_manifest(inventory)
    else:
        if mutation == "no_extension":
            del data["renderer"]
        elif mutation == "old_api":
            data["renderer"]["version"] = 0
        elif mutation == "extra_operation":
            data["renderer"]["operations"].append("exec")
        else:
            data["unexpected"] = True
        raw = encode(data)
    with pytest.raises(SandboxDeniedError):
        backend._accept_manifest(raw)


@pytest.mark.parametrize(
    "field,value", [(3, "121"), (4, str(2 * 1024**3 + 1)), (5, "257"), (5, "true"), (6, "custom")]
)
def test_renderer_launcher_limits(field, value):
    argv = [
        "run",
        str(PROTOCOL_VERSION),
        RENDER_WORKER,
        "120",
        str(2 * 1024**3),
        "256",
        "ordinary",
        "a" * 64,
    ]
    argv[field] = value
    with pytest.raises(ValueError):
        parse_render_argv(argv)


@pytest.mark.parametrize(
    "change", ["digest", "platform", "cad_entrypoint", "environment", "healthcheck", "volumes"]
)
def test_renderer_image_attestation_rejects_mismatch(change):
    from hephaestus.core.errors import SandboxDeniedError
    from hephaestus.core.executor.sandbox.oci import (
        AUDITED_ENTRYPOINT,
        AUDITED_IMAGE_ENV,
        TransportResult,
    )
    from test_sandbox_oci import IMAGE, FakeTransport, runtime

    config = {
        "Entrypoint": [*AUDITED_ENTRYPOINT[:-1], "hephaestus.core.render.oci_launcher"],
        "Cmd": [],
        "Env": list(AUDITED_IMAGE_ENV),
    }
    image = {
        "Id": "sha256:" + "e" * 64,
        "Architecture": "arm64",
        "Os": "linux",
        "RepoDigests": [IMAGE],
        "Config": config,
    }
    if change == "digest":
        image["RepoDigests"] = []
    elif change == "platform":
        image["Architecture"] = "amd64"
    elif change == "cad_entrypoint":
        config["Entrypoint"] = list(AUDITED_ENTRYPOINT)
    elif change == "environment":
        config["Env"].append("PYTHONPATH=/inputs")
    elif change == "healthcheck":
        config["Healthcheck"] = {"Test": ["CMD", "sh"]}
    else:
        config["Volumes"] = {"/output": {}}
    transport = FakeTransport([TransportResult(0, (json.dumps(image) + "\n").encode(), b"")])
    backend = OciBackend(
        runtime(),
        IMAGE,
        "linux/arm64",
        identity=OciIdentity(501, 20),
        transport=transport,
        runtime_profile="renderer",
    )
    with pytest.raises(SandboxDeniedError):
        backend._validate_image()
    assert all("create" not in call[0] for call in transport.calls)


def test_pinned_renderer_dependencies_not_upgrades():
    import tomllib

    root = Path(__file__).resolve().parents[2]
    pins = {
        p["name"]: p["version"] for p in tomllib.loads((root / "uv.lock").read_text())["package"]
    }
    lock = json.loads((root / "docker/renderer/python-arm64.lock.json").read_text())
    for item in lock["packages"]:
        if item["name"] in {"setuptools", "wheel"}:
            continue  # separately pinned build-only tools, excluded from runtime
        assert item["version"] == pins[item["name"]]
    dockerfile = (root / "docker/renderer/Dockerfile").read_text()
    assert "FROM hephaestus" not in dockerfile
    assert "--require-hashes" in dockerfile and "pip check" in dockerfile
    assert "core.render.oci_launcher" in dockerfile
    executor = (root / "docker/executor/Dockerfile").read_text()
    assert "core.render.oci_launcher" not in executor


def test_host_boundary_has_no_native_imports():
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from hephaestus.core.render.oci_backend import OciRenderer; "
            "assert not {'numpy','build123d','OCP','pyrender','OpenGL','PIL','trimesh'}"
            ".intersection(sys.modules)",
        ],
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
