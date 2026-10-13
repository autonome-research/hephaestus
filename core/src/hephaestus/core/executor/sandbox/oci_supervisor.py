"""Explicit experimental per-operation OCI owner; no daemon/service or discovery.

The spawned stdlib-only owner outlives an async await or parent EOF long enough
for bounded container/client cleanup. Each operation freshly probes the canonical
backend. Durable ownership precedes create. A killed owner or disconnected daemon
can leave pending state: recovery reclaims exact resources, NEVER guesses settlement
or signals restored PIDs. The local operator must retain that state for resolution.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import pickle
import signal
import stat
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from types import FrameType
from typing import Literal

from hephaestus.core.errors import SandboxDeniedError
from hephaestus.core.executor.bounded_pass import (
    ChildConnection,
    OwnerRefusal,
    run_independent_owner,
)
from hephaestus.core.executor.cancellation import (
    Cancellation,
    ExecutionCancelled,
    current_cancellation,
)
from hephaestus.core.executor.identity import ExecutionIdentity

from .base import CapabilityReport, ExecOutcome, SandboxSpec
from .oci import (
    OciBackend,
    OciIdentity,
    OciRuntime,
    OciTransport,
    SubprocessTransport,
    TransportResult,
    build_inspect_argv,
)
from .oci_ownership import OwnershipJournal
from .oci_storage_policy import REQUEST_MAX_BYTES, STORAGE_POLICIES, StoragePolicy

# 2 x 30s probes, bounded runtime/image controls, <=180s worker, client reaping
# and reconciliation. This is an outer hang detector, not a worker budget.
OWNER_SECONDS = 420
IPC_BYTES = 24 * 1024 * 1024
EVIDENCE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class SupervisorConfig:
    runtime: OciRuntime
    image_ref: str
    platform: Literal["linux/arm64", "linux/amd64"]
    directory: Path
    identity: OciIdentity
    storage_policy: str = "ordinary"
    runtime_profile: Literal["executor", "renderer"] = "executor"

    def __post_init__(self) -> None:
        if not self.directory.is_absolute():
            raise ValueError("supervision directory must be absolute")

    def binding(self) -> dict[str, object]:
        return {
            "runtime": str(self.runtime.path),
            "kind": self.runtime.kind,
            "endpoint": self.runtime.endpoint,
            "server_identity": self.runtime.server_identity,
            "image": self.image_ref,
            "platform": self.platform,
            "uid": self.identity.uid,
            "gid": self.identity.gid,
            "storage_policy": self.storage_policy,
            # Preserve executor journal binding compatibility. Render owners
            # are explicitly disjoint and can never reconcile as CAD owners.
            **({"runtime_profile": "renderer"} if self.runtime_profile == "renderer" else {}),
        }


def save_evidence(path: Path, value: object) -> None:
    """Create and fsync one bounded, exclusively owned supervisor evidence record."""
    data = json.dumps(value, sort_keys=True, indent=2).encode() + b"\n"
    if len(data) > EVIDENCE_BYTES:
        raise SandboxDeniedError("supervisor evidence limit")
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _exception_output(error: BaseException, name: str) -> object:
    try:
        return getattr(error, name, None)
    except BaseException:
        # Diagnostics must not replace the transport failure, even when a
        # malformed exception exposes a raising property instead of bytes.
        return None


class EvidenceTransport:
    """Collect actual bounded control bytes and streamed hashes, never fabricated labels."""

    def __init__(self, real: OciTransport, directory: Path) -> None:
        self.real = real
        self.directory = directory
        self.sequence = 0
        self.total = 0

    def run(
        self,
        argv: Sequence[str],
        *,
        input: bytes,
        timeout: float,
        stdout_limit: int,
        stderr_limit: int,
        env: Mapping[str, str],
        stdout_consumer: Callable[[bytes], None] | None = None,
    ) -> TransportResult:
        self.sequence += 1
        if self.sequence > 128 or self.total >= EVIDENCE_BYTES:
            raise SandboxDeniedError("supervisor command/evidence limit")
        record: dict[str, object] = {
            "argv": list(argv),
            "timeout": timeout,
            "input_bytes": len(input),
            "input_sha256": hashlib.sha256(input).hexdigest(),
            "stdout_limit": stdout_limit,
            "stderr_limit": stderr_limit,
        }
        digest = hashlib.sha256()
        count = 0
        prefix = bytearray()

        def consume(chunk: bytes) -> None:
            nonlocal count
            count += len(chunk)
            digest.update(chunk)
            prefix.extend(chunk[: max(0, 16384 - len(prefix))])
            assert stdout_consumer is not None
            stdout_consumer(chunk)

        stdout: object = None
        stderr: object = None
        try:
            result = self.real.run(
                argv,
                input=input,
                timeout=timeout,
                stdout_limit=stdout_limit,
                stderr_limit=stderr_limit,
                env=env,
                stdout_consumer=consume if stdout_consumer else None,
            )
            record.update(returncode=result.returncode)
            stdout, stderr = result.stdout, result.stderr
            return result
        except BaseException as exc:
            record["error"] = type(exc).__name__
            stdout = _exception_output(exc, "stdout")
            stderr = _exception_output(exc, "stderr")
            raise
        finally:
            for key, data, limit in (
                ("stdout", stdout, stdout_limit),
                ("stderr", stderr, stderr_limit),
            ):
                if not isinstance(data, bytes) or len(data) > limit:
                    record[key] = {"available": False}
                    continue
                record[key] = {
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "prefix_base64": base64.b64encode(data[:65536]).decode(),
                    "truncated": len(data) > 65536,
                }
            if stdout_consumer:
                record["wire"] = {
                    "bytes": count,
                    "sha256": digest.hexdigest(),
                    "prefix_base64": base64.b64encode(prefix).decode(),
                }
            data = json.dumps(record).encode()
            self.total += len(data)
            if self.total > EVIDENCE_BYTES:
                raise SandboxDeniedError("supervisor evidence byte limit")
            save_evidence(self.directory / f"command-{self.sequence:03d}.json", record)


def _require_owners_complete(config: SupervisorConfig) -> None:
    recovery = config.directory / "recovery"
    if recovery.exists():
        with OwnershipJournal(recovery, config.binding()) as journal:
            journal.require_clean()
    for index in range(16):
        directory = config.directory / f"operation-{index:02d}"
        if directory.exists() and not (directory / "owner-final.json").is_file():
            raise SandboxDeniedError("unfinished OCI owner; explicit recovery required")
        observer = directory / "observer-ownership"
        if observer.exists():
            with OwnershipJournal(observer, config.binding()) as journal:
                journal.require_clean()


def _owner(
    connection: ChildConnection,
    config: SupervisorConfig,
    directory: Path,
    spec: SandboxSpec | None,
    payload: bytes,
    expected: ExecutionIdentity | None,
) -> None:
    """Spawn target: no workload source executes in this process."""

    def expired(_signum: int, _frame: FrameType | None) -> None:
        raise TimeoutError("OCI owner lifetime exceeded")

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(OWNER_SECONDS)
    evidence: dict[str, object] = {
        "accepted": False,
        "stage": "probe" if spec is None else "execute",
    }
    backend = None
    listener = None
    with Cancellation() as cancellation:

        def stop(reason: str) -> None:
            # This is receipt by the synchronous owner's control path, not a
            # claim that a container kill succeeded. Raw kill/state evidence is
            # collected separately by the canonical cleanup path.
            try:
                save_evidence(
                    directory / "stop-received.json",
                    {
                        "reason": reason,
                        "monotonic_ns": time.monotonic_ns(),
                    },
                )
            finally:
                cancellation.cancel(reason)

        def listen() -> None:
            try:
                message = connection.recv_bytes(64)
                stop(
                    {b"cancel": "user_cancel", b"caller-cancel": "caller_cancel"}.get(
                        message, "parent_closed"
                    )
                )
            except (EOFError, OSError):
                if cancellation.reason is None:
                    stop("parent_closed")

        def interrupted(_signum: int, _frame: FrameType | None) -> None:
            cancellation.cancel("owner_signal")

        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)

        listener = threading.Thread(target=listen, daemon=True, name="oci-owner-control")
        listener.start()
        try:
            with OwnershipJournal(config.directory / "ownership", config.binding()) as journal:
                journal.admit_operation()
                real = SubprocessTransport(cancellation=cancellation, ownership=journal)
                transport = EvidenceTransport(real, directory)
                scratch = directory / "probe-scratch"
                scratch.mkdir(mode=0o700)
                backend = OciBackend(
                    config.runtime,
                    config.image_ref,
                    config.platform,
                    identity=config.identity,
                    storage_policy=config.storage_policy,
                    ownership=journal,
                    cancellation=cancellation,
                    transport=transport,
                    scratch_dir=scratch,
                    runtime_profile=config.runtime_profile,
                )
                report = backend.probe()
                evidence["capability"] = asdict(report)
                if not report.available:
                    raise SandboxDeniedError(str(report.reason))
                identity = backend.execution_identity()
                evidence["identity"] = identity.to_json()
                evidence["probe"] = backend.last_probe_response
                if expected is not None and expected != identity:
                    raise SandboxDeniedError("supervised execution identity changed")
                result = None
                if spec is not None:
                    # This file is a passive positive phase edge for observers.
                    save_evidence(directory / "executing.json", {"identity": identity.to_json()})
                    result = backend.execute(spec, payload)
                cancellation.check()
                journal.require_clean()
                evidence["terminal"] = dict(backend.last_terminal_state or {})
                evidence["container_id"] = backend.last_container_id
                evidence["effective"] = backend.last_effective_config
                evidence["transfer"] = backend.last_transfer_observation
                evidence["inputs"] = {k: asdict(v) for k, v in backend.last_input_records.items()}
                evidence["outputs"] = {
                    k: asdict(v) for k, v in backend.last_transfer_records.items()
                }
                evidence["ownership"] = journal.state
                evidence["outcome"] = "timeout" if result and result.timed_out else "completed"
                if result:
                    evidence["exit_code"] = result.exit_code
                    evidence["stdout_sha256"] = hashlib.sha256(result.stdout).hexdigest()
                    evidence["stderr_sha256"] = hashlib.sha256(result.stderr).hexdigest()
                save_evidence(directory / "result.json", evidence)
                connection.send(("ok", report, identity, result))
        except BaseException as exc:
            evidence["outcome"] = (
                cancellation.reason if isinstance(exc, ExecutionCancelled) else "failure"
            )
            evidence["error"] = f"{type(exc).__name__}: {exc}"
            if backend is not None:
                evidence["terminal"] = dict(backend.last_terminal_state or {})
                evidence["container_id"] = backend.last_container_id
                evidence["transfer"] = backend.last_transfer_observation
                evidence["effective"] = backend.last_effective_config
            try:
                if not (directory / "result.json").exists():
                    save_evidence(directory / "result.json", evidence)
                connection.send(
                    ("cancel" if isinstance(exc, ExecutionCancelled) else "error", str(exc))
                )
            except (OSError, EOFError):
                pass  # parent death; durable records remain authoritative
        finally:
            signal.alarm(0)
            # Wake the reader before its sockets/control are closed. The parent
            # closes its endpoint after receiving the terminal message.
            listener.join(timeout=5)
            connection.close()
            if listener.is_alive():
                # No further daemon commands are possible, but do not claim the
                # owner's control thread was reaped. Retain unfinished state.
                os._exit(125)
            save_evidence(
                directory / "owner-final.json", {"pid": os.getpid(), "commands_finished": True}
            )


class SupervisedOciBackend:
    """Supported local injection. Explicit directory/lifecycle, one operation at a time.

    No cached old report authorizes a new worker: each owner re-probes. The parent
    retains identity for assembly/freshness only after that fresh proof. At most
    16 operations per session; retain evidence and open a new session explicitly.
    """

    def __init__(self, config: SupervisorConfig) -> None:
        self.config = config
        # Validate immutable image/policy/runtime before any process is started.
        OciBackend(
            config.runtime,
            config.image_ref,
            config.platform,
            identity=config.identity,
            storage_policy=config.storage_policy,
            runtime_profile=config.runtime_profile,
        )
        config.directory.mkdir(mode=0o700, parents=False, exist_ok=True)
        info = config.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise SandboxDeniedError("supervision directory must be private and owned")
        _require_owners_complete(config)
        with OwnershipJournal(config.directory / "ownership", config.binding()) as journal:
            journal.require_clean()
        self._lock = threading.Lock()
        self._control_lock = threading.Lock()
        self._connection: ChildConnection | None = None
        self._identity: ExecutionIdentity | None = None
        self._report: CapabilityReport | None = None
        self._closed = False
        self.last_directory: Path | None = None
        self.last_owner_pid: int | None = None

    @property
    def name(self) -> str:
        return f"oci-{self.config.runtime.kind}"

    @property
    def storage_policy(self) -> StoragePolicy:
        return STORAGE_POLICIES[self.config.storage_policy]

    def execution_identity(self) -> ExecutionIdentity:
        if self._closed or self._identity is None or self._report is None:
            raise SandboxDeniedError("supervised execution identity unavailable")
        _require_owners_complete(self.config)
        with OwnershipJournal(
            self.config.directory / "ownership", self.config.binding()
        ) as journal:
            journal.require_clean()
        return self._identity

    def probe(self) -> CapabilityReport:
        if self._report is not None:
            try:
                self.execution_identity()
                return self._report
            except (OSError, SandboxDeniedError):
                pass
        try:
            self._invoke(None, b"")
            assert self._report is not None
            return self._report
        except (OSError, SandboxDeniedError) as exc:
            return CapabilityReport(self.name, False, str(exc))

    def execute(self, spec: SandboxSpec, stdin_payload: bytes) -> ExecOutcome:
        if self._identity is None:
            raise SandboxDeniedError("supervised execution requires a passing probe")
        if (
            not 0 < spec.wall_clock_s <= 180
            or spec.rlimits.cpu_seconds > 120
            or spec.rlimits.address_space_bytes > 2 * 1024**3
            or spec.rlimits.nproc > 256
            or len(stdin_payload) > REQUEST_MAX_BYTES
        ):
            raise SandboxDeniedError("experimental supervised job limits exceeded")
        result = self._invoke(spec, stdin_payload)
        assert isinstance(result, ExecOutcome)
        return result

    def cancel_active(
        self, reason: Literal["user_cancel", "caller_cancel"] = "user_cancel"
    ) -> bool:
        """Deliver explicit stop, not client disappearance; completion still must be awaited."""
        if reason not in {"user_cancel", "caller_cancel"}:
            raise ValueError("unsupported cancellation reason")
        with self._control_lock:
            if self._connection is None:
                return False
            assert self.last_directory is not None
            record_error: OSError | None = None
            try:
                save_evidence(
                    self.last_directory / "stop-request.json",
                    {
                        "reason": reason,
                        "monotonic_ns": time.monotonic_ns(),
                    },
                )
            except FileExistsError:
                pass  # retain the first request; retry delivery, not a fabricated ACK
            except OSError as exc:
                record_error = exc  # still deliver stop if evidence storage fails
            try:
                self._connection.send_bytes(
                    b"cancel" if reason == "user_cancel" else b"caller-cancel"
                )
            except (OSError, EOFError):
                if record_error is not None:
                    raise record_error from None
                return False
            if record_error is not None:
                raise record_error
            return True

    def _invoke(self, spec: SandboxSpec | None, payload: bytes) -> ExecOutcome | None:
        if not self._lock.acquire(blocking=False):
            raise SandboxDeniedError("one supervised OCI operation at a time")
        try:
            if self._closed:
                raise SandboxDeniedError("OCI supervisor session closed")
            _require_owners_complete(self.config)
            control = current_cancellation.get()
            if control is not None:
                control.check()
            for index in range(16):
                directory = self.config.directory / f"operation-{index:02d}"
                try:
                    directory.mkdir(mode=0o700)
                    break
                except FileExistsError:
                    continue
            else:
                raise SandboxDeniedError("supervision session operation limit reached")
            self.last_directory = directory
            save_evidence(
                directory / "request.json",
                {
                    "binding": self.config.binding(),
                    "input_sha256": hashlib.sha256(payload).hexdigest(),
                    "input_bytes": len(payload),
                    "limits": asdict(spec.rlimits) if spec else None,
                    "wall_clock_s": spec.wall_clock_s if spec else None,
                    "source_sha256": {
                        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in Path(__file__).parent.glob("*.py")
                    },
                },
            )
            # No multiprocessing.spawn resource-tracker/helper survives this owner.
            request_path = directory / "request.bin"
            request = pickle.dumps((self.config, directory, spec, payload, self._identity))
            if len(request) > IPC_BYTES:
                raise SandboxDeniedError("owner request IPC bound")
            with request_path.open("xb") as stream:
                stream.write(request)
                stream.flush()
                os.fsync(stream.fileno())

            def started(pid: int, connection: ChildConnection) -> None:
                self.last_owner_pid = pid
                save_evidence(directory / "owner.json", {"pid": pid})
                with self._control_lock:
                    self._connection = connection

            def reaped(pid: int, exitcode: int) -> None:
                save_evidence(directory / "reaped.json", {"pid": pid, "exitcode": exitcode})

            def unreaped() -> None:
                self._closed = True

            def cancel() -> None:
                self.cancel_active("caller_cancel")

            try:
                raw = run_independent_owner(
                    lambda fd: (
                        sys.executable,
                        "-m",
                        __name__,
                        "--owner",
                        str(fd),
                        str(request_path),
                    ),
                    env={
                        "PATH": "/usr/bin:/bin",
                        "LANG": "C",
                        "LC_ALL": "C",
                        "PYTHONDONTWRITEBYTECODE": "1",
                        "PYTHONPATH": os.pathsep.join(
                            str(Path(p).resolve()) for p in sys.path if p
                        ),
                    },
                    timeout_s=OWNER_SECONDS + 15,
                    maximum=IPC_BYTES,
                    on_started=started,
                    on_reaped=reaped,
                    on_unreaped=unreaped,
                    cancel_fd=control.reader.fileno() if control is not None else None,
                    on_cancel=cancel,
                )
            except OwnerRefusal as exc:
                raise SandboxDeniedError(f"OCI {exc}") from exc
            message = pickle.loads(raw)
            if message[0] != "ok":
                self._report = None
                if message[0] == "cancel":
                    raise ExecutionCancelled(message[1])
                raise SandboxDeniedError(message[1])
            _, self._report, self._identity, result = message
            if control is not None:
                control.check()
            return result
        except BaseException:
            self._report = None
            raise
        finally:
            with self._control_lock:
                self._connection = None
            self._lock.release()

    def observe_running(self) -> dict[str, object]:
        """One independent daemon observation; caller retries only within its own deadline.

        Does not accept a JSON running label or an attach-client PID as proof.
        Refuses probe containers, unknown creates, absence and stopped workers.
        """
        directory = self.last_directory
        if directory is None or not (directory / "executing.json").exists():
            raise SandboxDeniedError("no execution phase observed")
        path = self.config.directory / "ownership" / "state.json"
        with path.open("rb") as stream:
            raw = stream.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise SandboxDeniedError("ownership evidence limit")
        records = json.loads(raw)["containers"]
        ids = [r["id"] for r in records.values() if not r["pending"] and not r["absent"]]
        if len(ids) != 1:
            raise SandboxDeniedError("no unique settled in-flight worker")
        from .oci import RUNTIME_ENV

        with OwnershipJournal(directory / "observer-ownership", self.config.binding()) as journal:
            journal.require_clean()
            result = SubprocessTransport(ownership=journal).run(
                build_inspect_argv(self.config.runtime, ids[0]),
                input=b"",
                timeout=5,
                stdout_limit=65536,
                stderr_limit=65536,
                env=RUNTIME_ENV,
            )
            journal.require_clean()
        if result.returncode or result.stderr:
            raise SandboxDeniedError("worker observation failed")
        state = json.loads(result.stdout)
        if (
            not isinstance(state, dict)
            or state.get("Running") is not True
            or state.get("OOMKilled") is not False
            or type(state.get("ExitCode")) is not int
            or not 0 <= state["ExitCode"] <= 255
        ):
            raise SandboxDeniedError("worker not observed running")
        observation: dict[str, object] = {
            "container_id": ids[0],
            "state": state,
            "raw_base64": base64.b64encode(result.stdout).decode(),
            "monotonic_ns": time.monotonic_ns(),
        }
        save_evidence(directory / "running.json", observation)
        return observation

    def require_settled(self) -> None:
        """Affirmative durable settlement, without launching owners or daemon clients.

        Closing only delivers cancellation/waits. It cannot authorize rollover:
        an unknown create or lost reap acknowledgement remains a refusal.
        """
        if not self._lock.acquire(blocking=False):
            raise SandboxDeniedError("OCI owner still active")
        try:
            _require_owners_complete(self.config)
            with OwnershipJournal(
                self.config.directory / "ownership", self.config.binding()
            ) as journal:
                journal.require_clean()
            for directory in self.config.directory.glob("operation-*"):
                records = []
                for name in ("owner.json", "owner-final.json", "reaped.json"):
                    try:
                        with (directory / name).open("rb") as stream:
                            raw = stream.read(EVIDENCE_BYTES + 1)
                        if len(raw) > EVIDENCE_BYTES:
                            raise ValueError("owner record bound")
                        records.append(json.loads(raw))
                    except (OSError, ValueError) as exc:
                        raise SandboxDeniedError("OCI owner settlement evidence missing") from exc
                owner, final, reaped = records
                if (
                    type(owner.get("pid")) is not int
                    or owner["pid"] <= 0
                    or final != {"pid": owner["pid"], "commands_finished": True}
                    or reaped != {"pid": owner["pid"], "exitcode": 0}
                ):
                    raise SandboxDeniedError("OCI owner settlement evidence mismatch")
        finally:
            self._lock.release()

    def close(self) -> None:
        self._closed = True
        try:
            self.cancel_active("caller_cancel")
        finally:
            if not self._lock.acquire(timeout=OWNER_SECONDS + 15):
                raise SandboxDeniedError("OCI owner shutdown incomplete")
            self._lock.release()

    def __enter__(self) -> SupervisedOciBackend:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def reconcile(config: SupervisorConfig) -> None:
    """Bounded explicit operator recovery, no process/global discovery or unrelated kills."""
    with (
        OwnershipJournal(config.directory / "ownership", config.binding()) as journal,
        OwnershipJournal(config.directory / "recovery", config.binding()) as recovery,
    ):
        recovery.require_clean()
        backend = OciBackend(
            config.runtime,
            config.image_ref,
            config.platform,
            identity=config.identity,
            storage_policy=config.storage_policy,
            transport=SubprocessTransport(ownership=recovery),
            runtime_profile=config.runtime_profile,
        )
        backend.reconcile_owned(journal)
    _require_owners_complete(config)


def _main() -> None:
    # Internal host control channel, never a workload/image entry point. The
    # private request is written by _invoke, bounded and never imported from a
    # supplied acceptance report. Pickle is confined to this trusted parent/owner
    # channel; CAD bytes remain an opaque bytes field sent only into OCI.
    if len(sys.argv) != 4 or sys.argv[1] != "--owner":
        raise SystemExit("internal OCI owner invocation required")
    connection = ChildConnection(int(sys.argv[2]))
    with Path(sys.argv[3]).open("rb") as stream:
        raw = stream.read(IPC_BYTES + 1)
    if len(raw) > IPC_BYTES:
        raise SystemExit("owner request bound exceeded")
    config, directory, spec, payload, expected = pickle.loads(raw)
    _owner(connection, config, directory, spec, payload, expected)


if __name__ == "__main__":
    _main()
