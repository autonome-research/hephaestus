"""Host regressions with synthetic artifacts/daemon records, NOT CAD evidence.

No CAD distributions are installed and no global functions are monkeypatched.
The same explicit backend/native-hash APIs used by embedders carry test inputs.
"""

from __future__ import annotations

import copy
import importlib.metadata
import json
from dataclasses import FrozenInstanceError, replace

import pytest
from _execution_identity import identity, runtime_inventory
from hephaestus.core.errors import SandboxDeniedError, ValidationError
from hephaestus.core.executor.identity import (
    IDENTITY_METADATA_KEY,
    ExecutionIdentity,
    backend_execution_identity,
)
from hephaestus.core.executor.runner import BuildRequest, assemble_build, run_build
from hephaestus.core.executor.sandbox.base import CapabilityReport, ExecOutcome, Rlimits
from hephaestus.core.executor.sandbox.oci import OciBackend
from hephaestus.core.executor.sandbox.oci_identity import (
    collect_runtime_identity,
    installed_source_hash,
    validate_runtime_identity,
)
from hephaestus.core.executor.sandbox.oci_protocol import manifest_bytes
from hephaestus.core.project_store.layout import open_store
from hephaestus.core.project_store.publication import Publisher, current_pointer
from hephaestus.core.project_store.store import blob_hash_of_ref
from opstore.gc import PREVIEW_RETENTION_CLASS
from test_project_store_helpers import DEFAULT_SCRIPT, make_project
from test_sandbox_oci import IMAGE, FakeTransport, passing, runtime

from opstore import canonical_json, sha256_bytes, sha256_canonical_json

NATIVE_HASH = sha256_bytes(b"synthetic native toolchain")


def native_hash():
    return NATIVE_HASH


def forbidden_host_hash():
    pytest.fail("OCI path consulted the host toolchain")


def result_record(status="ok"):
    return {
        "status": status,
        "artifacts": {"build": "final.brep", "source_map": "source_map.json"}
        if status == "ok"
        else {"last_good": "last_good.brep"},
        "source_map": {} if status == "ok" else None,
        "params_declaration": {},
        "error": None
        if status == "ok"
        else {
            "line": 1,
            "col": 0,
            "type": "ValueError",
            "message": "synthetic failure",
            "frame": [],
            "built_through": None,
            "last_good": None,
            "last_good_artifact_ref": None,
            "hint": "synthetic test",
        },
        "metadata": {IDENTITY_METADATA_KEY: "script-forgery", "description": "test"},
        "execution_identity": "script-forgery",
        "toolchain_hash": "script-forgery",
    }


def write_artifacts(out, status="ok"):
    out.mkdir(parents=True, exist_ok=True)
    if status == "ok":
        (out / "final.brep").write_bytes(b"synthetic geometry, not kernel evidence")
        (out / "source_map.json").write_text("{}")
    else:
        (out / "last_good.brep").write_bytes(b"synthetic checkpoint")


class ImageBackend:
    """Trusted-control test double, deliberately separate from workload JSON."""

    name = "oci-unit"

    def __init__(self, value=None):
        self.value = value or identity()
        self.outcome_identity = self.value
        self.unavailable = False
        self.executed = False
        self.next_identity = None

    def probe(self):
        return CapabilityReport(self.name, True)

    def execution_identity(self):
        if self.unavailable:
            raise SandboxDeniedError("unit backend identity unavailable")
        return self.value

    def execute(self, spec, stdin_payload):
        self.executed = True
        assert spec.rlimits.address_space_bytes <= 2 * 1024**3
        assert IDENTITY_METADATA_KEY not in json.loads(stdin_payload)
        write_artifacts(spec.rw_out_dir)
        if self.next_identity is not None:
            self.value = self.next_identity
        return ExecOutcome(
            0, json.dumps(result_record()).encode(), b"", execution_identity=self.outcome_identity
        )


class NativeBackend:
    name = "bwrap-unit"

    def probe(self):
        return CapabilityReport(self.name, True)

    def execute(self, spec, stdin_payload):
        write_artifacts(spec.rw_out_dir)
        return ExecOutcome(0, json.dumps(result_record()).encode(), b"")


def build(out, *, backend=None, status="ok"):
    write_artifacts(out, status)
    return assemble_build(
        BuildRequest("widget", DEFAULT_SCRIPT),
        result_record(status),
        out_dir=out,
        execution_identity=None if backend is None else backend.execution_identity(),
        native_toolchain_hash=native_hash if backend is None else forbidden_host_hash,
    )


def run(backend, out):
    return run_build(
        BuildRequest("widget", DEFAULT_SCRIPT, wall_clock_s=60),
        backend=backend,
        out_dir=out,
        rlimits=Rlimits(30, 512 * 1024**2, 64),
        native_toolchain_hash=forbidden_host_hash,
    )


def test_runner_uses_control_identity_not_script_fingerprint(tmp_path):
    backend = ImageBackend()
    built = run(backend, tmp_path / "out")
    assert backend.executed
    assert built.execution_identity == backend.value
    assert built.result.input_hashes.toolchain == backend.value.toolchain_hash
    assert built.result.metadata[IDENTITY_METADATA_KEY] == backend.value.canonical
    assert built.result.metadata["description"] == "test"
    assert "script-forgery" not in built.result.to_json()["metadata"].values()


@pytest.mark.parametrize("bad", ["missing", "wrong", "changed"])
def test_runner_refuses_outcome_identity_drift(tmp_path, bad):
    backend = ImageBackend()
    other = identity(image_id="sha256:" + "f" * 64)
    if bad == "missing":
        backend.outcome_identity = None
    elif bad == "wrong":
        backend.outcome_identity = other
    else:
        backend.next_identity = other
    with pytest.raises(SandboxDeniedError, match="identity"):
        run(backend, tmp_path / "out")
    assert backend.executed


def test_missing_provider_or_unavailable_identity_refuses_before_worker(tmp_path):
    class Missing(NativeBackend):
        name = "oci-invalid"

    with pytest.raises(ValidationError, match="provider"):
        run(Missing(), tmp_path / "missing")
    backend = ImageBackend()
    backend.unavailable = True
    with pytest.raises(SandboxDeniedError, match="identity"):
        run(backend, tmp_path / "unavailable")
    assert not backend.executed
    assert not (tmp_path / "unavailable").exists()


def test_native_runner_preserves_hash_and_cannot_smuggle_oci_metadata(tmp_path):
    built = run_build(
        BuildRequest("widget", DEFAULT_SCRIPT),
        backend=NativeBackend(),
        out_dir=tmp_path / "out",
        native_toolchain_hash=native_hash,
    )
    assert built.execution_identity is None
    assert built.result.input_hashes.toolchain == NATIVE_HASH
    assert IDENTITY_METADATA_KEY not in built.result.metadata
    assert backend_execution_identity(NativeBackend()) is None


@pytest.mark.parametrize(
    "field",
    ["image_ref", "image_id", "platform", "python", "source", "opstore", "package", "metadata"],
)
def test_every_executor_input_changes_immutable_build_identity(tmp_path, field):
    first = identity()
    record = first.to_json()
    if field == "image_ref":
        record[field] = IMAGE.replace("a" * 64, "f" * 64)
    elif field == "image_id":
        record[field] = "sha256:" + "f" * 64
    elif field == "platform":
        record[field] = "linux/arm64"
    elif field == "python":
        record["runtime"]["python"] = "3.13.8"
    elif field in {"source", "opstore"}:
        key = "opstore" if field == "opstore" else "hephaestus-executor-runtime"
        record["runtime"]["source_trees"][key] = "sha256:" + "f" * 64
    elif field == "package":
        record["runtime"]["packages"]["build123d"]["version"] = "0.11.2"
    else:
        record["runtime"]["packages"]["build123d"]["metadata_sha256"] = "sha256:" + "f" * 64
    second = ExecutionIdentity(canonical_json(record))
    assert first.toolchain_hash != second.toolchain_hash
    layout = make_project(tmp_path / "project")
    with open_store(layout) as store:
        a, b = ImageBackend(first), ImageBackend(second)
        built_a, built_b = build(tmp_path / "a", backend=a), build(tmp_path / "b", backend=b)
        pub_a = Publisher(layout, store, backend=a, native_toolchain_hash=forbidden_host_hash)
        pub_b = Publisher(layout, store, backend=b, native_toolchain_hash=forbidden_host_hash)
        result_a = pub_a.publish_build(built_a, op_id="a")
        assert result_a.kind == "current"
        assert pub_a.freshness("widget").fresh
        assert pub_b.freshness("widget").changed_inputs == ("toolchain",)
        result_b = pub_b.publish_build(built_b, op_id="b")
        assert result_b.kind == "current"
        # Geometry refs stay byte identities. The immutable build bundles differ.
        assert result_a.artifact_ref == result_b.artifact_ref
        assert result_a.record_blob != result_b.record_blob
        assert store.blobs.has(result_a.record_blob)
        assert pub_b.freshness("widget").fresh
        assert pub_a.freshness("widget").changed_inputs == ("toolchain",)
        assert pub_a.current_result("widget").current  # not read-time freshness


@pytest.mark.parametrize("direction", ["native-to-oci", "oci-to-native"])
def test_cross_backend_publication_races_and_freshness_is_stale(tmp_path, direction):
    layout = make_project(tmp_path / "project")
    image = ImageBackend()
    with open_store(layout) as store:
        native = Publisher(layout, store, native_toolchain_hash=native_hash)
        oci = Publisher(layout, store, backend=image, native_toolchain_hash=forbidden_host_hash)
        native_build = build(tmp_path / "native")
        oci_build = build(tmp_path / "oci", backend=image)
        original, other, built = (
            (native, oci, native_build)
            if direction == "native-to-oci"
            else (oci, native, oci_build)
        )
        accepted = original.publish_build(built, op_id="original")
        assert accepted.kind == "current"
        raced = other.publish_build(built, op_id="cross-backend")
        assert raced.kind == "raced"
        assert any("toolchain" in detail for detail in raced.details)
        assert other.freshness("widget").changed_inputs == ("toolchain",)
        assert store.blobs.read_pointer(current_pointer("widget")) == accepted.record_blob
        assert original.freshness("widget").fresh


def test_identical_image_alias_is_location_not_changed_executor_input(tmp_path):
    layout = make_project(tmp_path / "project")
    a = ImageBackend()
    alias = identity(image_ref=IMAGE.replace("registry.example", "localhost"))
    assert a.value != alias  # full reference retained for audit
    assert a.value.toolchain_hash == alias.toolchain_hash
    with open_store(layout) as store:
        first = Publisher(layout, store, backend=a, native_toolchain_hash=forbidden_host_hash)
        second = Publisher(
            layout, store, backend=ImageBackend(alias), native_toolchain_hash=forbidden_host_hash
        )
        first.publish_build(build(tmp_path / "out", backend=a), op_id="first")
        assert second.freshness("widget").fresh


def test_revalidation_rechecks_live_identity_and_preserves_stale(tmp_path):
    layout = make_project(tmp_path / "project")
    backend = ImageBackend()
    with open_store(layout) as store:
        publisher = Publisher(
            layout, store, backend=backend, native_toolchain_hash=forbidden_host_hash
        )
        built = build(tmp_path / "out", backend=backend)
        first = publisher.publish_build(built, op_id="first")
        backend.value = identity(image_id="sha256:" + "f" * 64)
        raced = publisher.publish_build(built, op_id="raced")
        assert raced.kind == "raced"
        assert store.blobs.read_pointer(current_pointer("widget")) == first.record_blob
        assert publisher.freshness("widget").changed_inputs == ("toolchain",)
        backend.unavailable = True
        assert publisher.freshness("widget").changed_inputs == ("toolchain",)
        assert publisher.publish_build(built, op_id="unavailable").kind == "raced"


@pytest.mark.parametrize(
    "mode", ["missing-metadata", "missing-control", "wrong-metadata", "wrong-hash"]
)
def test_publication_refuses_inconsistent_identity_before_install(tmp_path, mode):
    layout = make_project(tmp_path / "project")
    backend = ImageBackend()
    built = build(tmp_path / "out", backend=backend)
    if mode == "missing-metadata":
        built = replace(built, result=replace(built.result, metadata={}))
    elif mode == "missing-control":
        built = replace(built, execution_identity=None)
    elif mode == "wrong-metadata":
        built = replace(
            built,
            result=replace(
                built.result,
                metadata={IDENTITY_METADATA_KEY: identity(platform="linux/arm64").canonical},
            ),
        )
    else:
        built = replace(
            built,
            result=replace(
                built.result, input_hashes=replace(built.result.input_hashes, toolchain=NATIVE_HASH)
            ),
        )
    with open_store(layout) as store:
        publisher = Publisher(
            layout, store, backend=backend, native_toolchain_hash=forbidden_host_hash
        )
        with pytest.raises(ValidationError, match="identity"):
            publisher.publish_build(built, op_id="bad")
        assert store.blobs.read_pointer(current_pointer("widget")) is None
        assert not store.blobs.has(blob_hash_of_ref(built.result.artifact_ref))


@pytest.mark.parametrize("mode", ["missing", "malformed", "wrong-hash"])
def test_freshness_never_accepts_missing_or_corrupt_stored_identity(tmp_path, mode):
    layout = make_project(tmp_path / "project")
    backend = ImageBackend()
    with open_store(layout) as store:
        publisher = Publisher(
            layout, store, backend=backend, native_toolchain_hash=forbidden_host_hash
        )
        publisher.publish_build(build(tmp_path / "out", backend=backend), op_id="first")
        bundle = dict(publisher.current_bundle("widget"))
        metadata = bundle["result"]["metadata"]
        if mode == "missing":
            metadata.pop(IDENTITY_METADATA_KEY)
        elif mode == "malformed":
            metadata[IDENTITY_METADATA_KEY] = "forgery"
        else:
            metadata[IDENTITY_METADATA_KEY] = identity(platform="linux/arm64").canonical
        old = store.blobs.read_pointer(current_pointer("widget"))
        blob = store.blobs.put(canonical_json(bundle).encode())
        store.blobs.cas_swap(current_pointer("widget"), old, blob)
        if mode == "missing":
            assert publisher.freshness("widget").changed_inputs == ("toolchain",)
        else:
            with pytest.raises(ValidationError, match="identity"):
                publisher.freshness("widget")
        assert publisher.current_result("widget").current


def test_identity_durable_on_failed_preview_and_replay_without_new_gc_roots(tmp_path):
    layout = make_project(tmp_path / "project")
    backend = ImageBackend()
    with open_store(layout) as store:
        publisher = Publisher(
            layout, store, backend=backend, native_toolchain_hash=forbidden_host_hash
        )
        built = build(tmp_path / "ok", backend=backend)
        first = publisher.publish_build(built, op_id="first")
        replay = publisher.publish_build(built, op_id="first")
        assert replay.replayed and replay.record_blob == first.record_blob
        preview_build = replace(
            built,
            result=replace(
                built.result,
                params={"width": 1},
                input_hashes=replace(
                    built.result.input_hashes, effective_params=sha256_canonical_json({"width": 1})
                ),
            ),
        )
        preview = publisher.publish_build(preview_build, op_id="preview", preview=True)
        assert preview.kind == "preview"
        assert store.blobs.retention_class(preview.record_blob) == PREVIEW_RETENTION_CLASS
        failed = publisher.publish_build(
            build(tmp_path / "failure", backend=backend, status="failed"), op_id="failure"
        )
        assert failed.kind == "failed"
        assert (
            publisher.last_failure_result("widget").metadata[IDENTITY_METADATA_KEY]
            == backend.value.canonical
        )
        assert publisher.current_result("widget").current
        assert (
            publisher.current_bundle("widget")["result"]["metadata"][IDENTITY_METADATA_KEY]
            == backend.value.canonical
        )
        assert publisher.bundle_ref_for_artifact("widget", built.result.artifact_ref).endswith(
            first.record_blob
        )
        assert store.gc.pins() == frozenset()
        reachable = store.gc.reachable()
        assert first.record_blob in reachable
        assert failed.record_blob in reachable
        assert blob_hash_of_ref(built.result.artifact_ref) in reachable
        assert all(blob_hash_of_ref(ref) in reachable for ref in failed.evidence_refs)


def test_cadops_publisher_factory_uses_injected_backend(tmp_path):
    from hephaestus.agent_bridge.cad_ops._base import CadOpsState

    layout = make_project(tmp_path / "project")
    backend = ImageBackend()
    with open_store(layout) as store:
        cad = CadOpsState(layout, store, backend=backend)
        publisher = cad._publisher()
        assert (
            publisher.publish_build(build(tmp_path / "out", backend=backend), op_id="cad").kind
            == "current"
        )
        assert cad._publisher().freshness("widget").fresh
        backend.value = identity(platform="linux/arm64")
        assert cad._publisher().freshness("widget").changed_inputs == ("toolchain",)


def test_identity_is_deeply_immutable_and_order_independent():
    inventory = runtime_inventory()
    original = identity(runtime=inventory)
    inventory["packages"]["build123d"]["version"] = "changed"
    returned = original.to_json()
    returned["runtime"]["packages"].clear()
    assert original == identity()
    assert (
        original.toolchain_hash
        == identity(runtime=dict(reversed(list(runtime_inventory().items())))).toolchain_hash
    )
    with pytest.raises(FrozenInstanceError):
        original.canonical = "{}"


@pytest.mark.parametrize(
    "mutation", ["missing", "old", "bool", "extra", "source", "package", "python", "duplicate"]
)
def test_manifest_inventory_is_mandatory_closed_and_versioned(mutation):
    backend = OciBackend(runtime(), IMAGE, "linux/amd64", transport=FakeTransport())
    backend._image_id = "sha256:" + "e" * 64
    inventory = runtime_inventory()
    payload = manifest_bytes(inventory)
    value = json.loads(payload)
    if mutation == "missing":
        value.pop("execution_identity")
    elif mutation == "old":
        value["manifest_version"] = 3
    elif mutation == "bool":
        value["execution_identity"]["version"] = True
    elif mutation == "extra":
        value["unexpected"] = 1
    elif mutation == "source":
        value["execution_identity"]["source_trees"].pop("opstore")
    elif mutation == "package":
        value["execution_identity"]["packages"].pop("build123d")
    elif mutation == "python":
        value["execution_identity"]["python"] = None
    else:
        payload = payload.replace(
            b'"manifest_version":4', b'"manifest_version":4,"manifest_version":4'
        )
    if mutation != "duplicate":
        payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with pytest.raises((ValidationError, ValueError, SandboxDeniedError)):
        backend._accept_manifest(payload)
    with pytest.raises(SandboxDeniedError, match="identity"):
        backend.execution_identity()


def test_containment_features_without_identity_cannot_pass_probe():
    from hephaestus.core.executor.sandbox.oci_protocol import REQUIRED_OCI_FEATURES

    class MissingInventoryBackend(OciBackend):
        def _validate_runtime(self):
            pass

        def _validate_image(self):
            self._image_id = "sha256:" + "e" * 64

        def _live_probe(self):
            return {name: True for name in REQUIRED_OCI_FEATURES}

    backend = MissingInventoryBackend(runtime(), IMAGE, "linux/amd64", transport=FakeTransport())
    report = backend.probe()
    assert not report.available
    assert "identity" in report.reason
    assert backend._passing_report is None


def test_manifest_inventory_is_bound_to_daemon_image_and_unusable_before_probe():
    backend = OciBackend(runtime(), IMAGE, "linux/arm64", transport=FakeTransport())
    with pytest.raises(SandboxDeniedError):
        backend._accept_manifest(manifest_bytes(runtime_inventory()))
    backend._image_id = "sha256:" + "e" * 64
    backend._accept_manifest(manifest_bytes(runtime_inventory()))
    with pytest.raises(SandboxDeniedError):
        backend.execution_identity()
    passing(backend)
    backend._accept_manifest(manifest_bytes(runtime_inventory()))
    assert backend.execution_identity() == identity(platform="linux/arm64")
    backend.image_ref = IMAGE.replace("a" * 64, "f" * 64)
    with pytest.raises(SandboxDeniedError, match="changed"):
        backend.execution_identity()


@pytest.mark.parametrize("change", ["platform", "image_id", "unsettled", "cleanup"])
def test_cached_identity_cannot_authorize_changed_or_poisoned_backend(change):
    backend = OciBackend(runtime(), IMAGE, "linux/amd64", transport=FakeTransport())
    passing(backend)
    if change == "platform":
        backend.platform = "linux/arm64"
    elif change == "image_id":
        backend._image_id = "sha256:" + "f" * 64
    elif change == "unsettled":
        backend._unsettled_creates.add("owned")
    else:
        backend._unreconciled_containers.add("owned")
    with pytest.raises(SandboxDeniedError):
        backend.execution_identity()
    assert not backend.probe().available


def distribution(root, name, source_prefix=None):
    """A fixture directory, not a package installed into the host environment."""
    directory = root / (name.replace("-", "_") + "-0.1.0.dist-info")
    directory.mkdir(parents=True)
    (directory / "METADATA").write_text(f"Name: {name}\nVersion: 0.1.0\n")
    if source_prefix is not None:
        file = root / source_prefix / "module.py"
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("# measured source\n")
        (directory / "RECORD").write_text(f"{source_prefix}/module.py,,\n")
    return importlib.metadata.PathDistribution(directory)


def test_collector_measures_actual_installed_source_and_package_metadata(tmp_path):
    distributions = [
        distribution(tmp_path, "hephaestus-executor-runtime", "hephaestus/core"),
        distribution(tmp_path, "opstore", "opstore"),
        distribution(tmp_path, "build123d"),
        distribution(tmp_path, "cadquery-ocp-novtk"),
    ]
    first = collect_runtime_identity(distributions=distributions, python_version="3.13.7")
    assert validate_runtime_identity(first) == first
    (tmp_path / "hephaestus/core/module.py").write_text(
        "# changed bytes, same RECORD and version\n"
    )
    second = collect_runtime_identity(distributions=distributions, python_version="3.13.7")
    assert first["source_trees"] != second["source_trees"]
    assert first["packages"] == second["packages"]
    (tmp_path / "build123d-0.1.0.dist-info/METADATA").write_text(
        "Name: build123d\nVersion: 0.1.0\nSummary: changed metadata\n"
    )
    third = collect_runtime_identity(distributions=distributions, python_version="3.13.7")
    assert second["packages"] != third["packages"]
    assert identity(runtime=first).toolchain_hash != identity(runtime=second).toolchain_hash


def test_collector_refuses_missing_and_symlinked_sources(tmp_path):
    dist = distribution(tmp_path, "opstore", "opstore")
    source = tmp_path / "opstore/module.py"
    source.unlink()
    with pytest.raises(ValueError, match="source"):
        installed_source_hash(dist, "opstore/")
    source.symlink_to(tmp_path / "opstore-0.1.0.dist-info/METADATA")
    with pytest.raises(ValueError, match="source"):
        installed_source_hash(dist, "opstore/")
    with pytest.raises(ValueError, match="packages"):
        collect_runtime_identity(distributions=[], python_version="3.13.7")


def test_collector_refuses_duplicate_distributions(tmp_path):
    dist = distribution(tmp_path, "build123d")
    with pytest.raises(ValueError, match="duplicate"):
        collect_runtime_identity(distributions=[dist, dist], python_version="3.13.7")


@pytest.mark.parametrize("missing", ["python", "packages", "source_trees", "version"])
def test_runtime_inventory_requires_every_field(missing):
    value = copy.deepcopy(runtime_inventory())
    value.pop(missing)
    with pytest.raises(ValueError):
        validate_runtime_identity(value)
