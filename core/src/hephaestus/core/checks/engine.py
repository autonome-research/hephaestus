"""Checks engine: CHECKS collection/run plus check-set generations (arch §3.4).

Part scope: :func:`collect_checks` pulls the ``CHECKS`` dict out of an
executed part namespace; :func:`run_checks` evaluates each predicate against
a fresh measurement facade. A failing (or crashing) check fails its report
entry — it never fails the build.

Cross-part scope: ``checks/*.py`` files execute in a restricted namespace
(measurement facade + ``approx`` + a safe builtin subset; no filesystem,
import, or introspection surface). Their lifecycle follows architecture §3.4
over ``opstore`` primitives owned by :class:`CheckSet`:

- a dedicated check-set lock (exclusive opstore lease on ``check-set-lock``);
- a generation counter + tree hash + lexically-ordered immutable bundle
  (opstore CAS blobs) behind the ``check-set`` CAS pointer;
- cooperative create/edit as a typed WAL pair (file mutation + generation
  publication compare-and-swapped before COMMITTED) under a durable intent
  record, so recovery after any crash completes exactly one generation
  advance or rolls wholly back — changed content is never visible under the
  prior cooperative generation;
- every lock acquisition first resolves relevant ``PREPARED`` check WAL rows,
  then reconciles a stable direct-filesystem change into exactly one
  ``external_import`` generation; a tree still changing during capture raises
  ``check_set_drift``;
- a generation whose files fail sandbox parse/contract validation is
  persisted ``invalid`` with a diagnostics blob; capture returns the
  discriminated invalid state and :func:`run_bundle` fails closed with
  ``invalid_check_generation`` — malformed checks are never omitted.
"""

from __future__ import annotations

import builtins
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from hephaestus.core.checks.facade import (
    GeometrySource,
    ImportResolver,
    KernelOps,
    Measurement,
    PosedContextFactory,
    PosedPlacement,
    SweepResolver,
    project_measurement,
)
from hephaestus.core.errors import (
    CheckSetDriftError,
    HephaestusError,
    InvalidCheckGenerationError,
    ValidationError,
)
from hephaestus.core.types import CheckReport, CheckResult
from opstore.types import JSONValue, OwnerId
from opstore.wal import POINTER_TARGET_PREFIX

from opstore import (
    Fresh,
    LeaseHeldError,
    OpStore,
    PendingRecovery,
    Replay,
    canonical_json,
    current_owner,
    sha256_bytes,
    sha256_canonical_json,
)

__all__ = [
    "BUNDLE_REF_PREFIX",
    "CheckBundle",
    "CheckPredicate",
    "CheckSet",
    "CheckSetState",
    "check_namespace",
    "collect_checks",
    "load_check_module",
    "run_bundle",
    "run_checks",
]

CheckPredicate = Callable[[Measurement], object]

#: CAS pointer holding the current check-set generation state blob.
STATE_POINTER = "check-set"
#: CAS pointer holding the in-flight cooperative-mutation intent blob.
INTENT_POINTER = "check-set-intent"
#: Lease ref of the dedicated check-set lock.
LOCK_REF = "check-set-lock"
#: Ref prefix for immutable check-bundle manifests.
BUNDLE_REF_PREFIX = "artifact:check-bundle:"

CheckSetOrigin = Literal["initial", "cooperative", "external_import"]
CheckSetStatus = Literal["valid", "invalid"]

_SAFE_BUILTIN_NAMES: tuple[str, ...] = (
    "ArithmeticError",
    "AttributeError",
    "Exception",
    "IndexError",
    "KeyError",
    "TypeError",
    "ValueError",
    "ZeroDivisionError",
    "abs",
    "all",
    "any",
    "bool",
    "dict",
    "divmod",
    "enumerate",
    "filter",
    "float",
    "frozenset",
    "int",
    "isinstance",
    "len",
    "list",
    "map",
    "max",
    "min",
    "pow",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "sorted",
    "str",
    "sum",
    "tuple",
    "zip",
)

_DENIED_BUILTIN_NAMES: tuple[str, ...] = (
    "__import__",
    "breakpoint",
    "compile",
    "delattr",
    "eval",
    "exec",
    "exit",
    "getattr",
    "globals",
    "help",
    "input",
    "locals",
    "memoryview",
    "open",
    "quit",
    "setattr",
    "vars",
)


def _denied(name: str) -> Callable[..., object]:
    def _refuse(*_args: object, **_kwargs: object) -> object:
        raise ValidationError(
            f"{name!r} is not available in the check sandbox "
            "(checks receive the measurement facade and approx only)",
            kind="sandbox",
        )

    return _refuse


def check_namespace(module_name: str = "checks") -> dict[str, object]:
    """Restricted exec namespace for a cross-part check module.

    Exposes ``approx`` plus a pure builtin subset; filesystem, import, exec
    and introspection builtins raise ``validation_error(kind='sandbox')``.
    """
    from hephaestus.core.checks.approx import approx

    restricted: dict[str, object] = {name: getattr(builtins, name) for name in _SAFE_BUILTIN_NAMES}
    restricted.update({name: _denied(name) for name in _DENIED_BUILTIN_NAMES})
    return {"__builtins__": restricted, "__name__": module_name, "approx": approx}


def collect_checks(namespace: Mapping[str, object]) -> dict[str, CheckPredicate]:
    """Pull CHECKS out of an executed namespace (absent -> {}); validate its shape."""
    raw = namespace.get("CHECKS")
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValidationError(
            f"CHECKS must be a dict of name -> predicate, got {type(raw).__name__}",
            kind="contract",
        )
    checks: dict[str, CheckPredicate] = {}
    for key, value in cast("Mapping[object, object]", raw).items():
        if not isinstance(key, str) or not key:
            raise ValidationError(
                f"CHECKS keys must be non-empty strings, got {key!r}", kind="contract"
            )
        if not callable(value):
            raise ValidationError(
                f"CHECKS[{key!r}] must be callable (a predicate over m), "
                f"got {type(value).__name__}",
                kind="contract",
            )
        checks[key] = cast("CheckPredicate", value)
    return checks


def load_check_module(source: str, *, filename: str) -> dict[str, CheckPredicate]:
    """Execute one check module in the restricted namespace and return its CHECKS.

    Raises ``validation_error`` discriminated by kind: ``syntax`` (parse),
    ``sandbox`` (denied surface reached at module level), ``evaluation``
    (module-level crash), ``contract`` (missing/malformed CHECKS).
    """
    try:
        code = compile(source, filename, "exec")
    except SyntaxError as exc:
        raise ValidationError(f"{filename}: {exc.msg} (line {exc.lineno})", kind="syntax") from exc
    namespace = check_namespace(Path(filename).stem)
    try:
        exec(code, namespace)
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(
            f"{filename}: {type(exc).__name__}: {exc}", kind="evaluation"
        ) from exc
    if "CHECKS" not in namespace:
        raise ValidationError(f"{filename}: check module defines no CHECKS", kind="contract")
    try:
        return collect_checks(namespace)
    except ValidationError as exc:
        raise ValidationError(f"{filename}: {exc.message}", kind=exc.kind) from exc


def run_checks(
    checks: Mapping[str, CheckPredicate],
    measurement_factory: Callable[[], Measurement],
) -> dict[str, CheckResult]:
    """Evaluate every check against a fresh facade; never raises (§6).

    A predicate exception (including addressing errors) fails that check's
    report entry with the error recorded as its measured value. Two exceptions
    are discriminated further, the same rule twice: a measurement whose
    bounded subprocess hit the wall-clock ceiling makes the check
    **unverifiable** — the predicate was never answered, so the entry records
    the named refusal (with whatever partial facts arrived) under
    ``measured.unverifiable`` instead of an ``error``. Not a pass, and not a
    crash: the report says the measurement was cut short, not that it failed.
    The three classes are ``compare_timeout`` (``COMPARE.md`` §5, an
    ``m.diff``), ``motion_timeout`` (``KINEMATICS.md`` §4, an ``m.sweep`` whose
    grid was ceiling-killed — the partial per-sample facts ride the refusal) and
    ``scan_timeout`` (``MESH_INGEST.md`` §7.3, an ``m.scan_diff`` whose distance
    computation was ceiling-killed — the §3 quality record, both bboxes and
    whichever direction completed ride the refusal).
    """
    from hephaestus.core.motion import MotionTimeout
    from hephaestus.core.project_compare import CompareTimeout
    from hephaestus.core.scan_compare import ScanTimeout

    results: dict[str, CheckResult] = {}
    for name, predicate in checks.items():
        measurement = measurement_factory()
        measured: JSONValue
        try:
            passed = bool(predicate(measurement))
            measured = measurement.measured_json()
        except (CompareTimeout, MotionTimeout, ScanTimeout) as exc:
            passed = False
            measured = {"unverifiable": cast("JSONValue", exc.to_json())}
        except HephaestusError as exc:
            passed = False
            measured = {
                "error": {"type": type(exc).__name__, "code": exc.code, "message": exc.message}
            }
        except Exception as exc:  # checks fail the report, never the build
            passed = False
            measured = {"error": {"type": type(exc).__name__, "message": str(exc)}}
        results[name] = CheckResult(passed=passed, measured=measured)
    return results


@dataclass(frozen=True)
class CheckSetState:
    """One persisted check-set generation (architecture §3.4)."""

    generation: int
    origin: CheckSetOrigin
    status: CheckSetStatus
    tree_hash: str
    files: Mapping[str, str] = field(default_factory=dict[str, str])
    bundle: str = ""
    diagnostics: str | None = None

    @property
    def bundle_ref(self) -> str:
        """Immutable provenance ref of the frozen bundle manifest."""
        return BUNDLE_REF_PREFIX + self.bundle

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "generation": self.generation,
            "origin": self.origin,
            "status": self.status,
            "tree_hash": self.tree_hash,
            "files": dict(self.files),
            "bundle": self.bundle,
            "diagnostics": self.diagnostics,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> CheckSetState:
        origin = data["origin"]
        status = data["status"]
        if origin not in ("initial", "cooperative", "external_import"):
            raise ValidationError(f"invalid check-set origin: {origin!r}", kind="contract")
        if status not in ("valid", "invalid"):
            raise ValidationError(f"invalid check-set status: {status!r}", kind="contract")
        files_raw = data["files"]
        if not isinstance(files_raw, dict):
            raise ValidationError("check-set files must be an object", kind="contract")
        files: dict[str, str] = {}
        for name, value in files_raw.items():
            if not isinstance(value, str):
                raise ValidationError("check-set file hashes must be strings", kind="contract")
            files[name] = value
        generation = data["generation"]
        tree_hash = data["tree_hash"]
        bundle = data["bundle"]
        diagnostics = data.get("diagnostics")
        if not isinstance(generation, int) or isinstance(generation, bool):
            raise ValidationError("check-set generation must be an int", kind="contract")
        if not isinstance(tree_hash, str) or not isinstance(bundle, str):
            raise ValidationError("check-set hashes must be strings", kind="contract")
        if diagnostics is not None and not isinstance(diagnostics, str):
            raise ValidationError("check-set diagnostics must be a hash or null", kind="contract")
        return cls(
            generation=generation,
            origin=origin,
            status=status,
            tree_hash=tree_hash,
            files=files,
            bundle=bundle,
            diagnostics=diagnostics,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CheckSetState):
            return NotImplemented
        return self.to_json() == other.to_json()

    def __hash__(self) -> int:
        return hash((self.generation, self.tree_hash, self.bundle))


@dataclass(frozen=True)
class CheckBundle:
    """A frozen, immutable snapshot of one generation's check files.

    ``contents`` come from the CAS blobs recorded at generation publication,
    never the live filesystem — execution after lock release always sees
    wholly this generation. ``diagnostics`` carries the decoded diagnostics
    artifact when the generation is invalid.
    """

    state: CheckSetState
    contents: Mapping[str, str] = field(default_factory=dict[str, str])
    diagnostics: JSONValue = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CheckBundle):
            return NotImplemented
        return (
            self.state == other.state
            and dict(self.contents) == dict(other.contents)
            and self.diagnostics == other.diagnostics
        )

    def __hash__(self) -> int:
        return hash(self.state)


def run_bundle(
    bundle: CheckBundle,
    sources: Mapping[str, GeometrySource],
    *,
    part: str,
    ops: KernelOps | None = None,
    densities: Mapping[str, float] | None = None,
    project_snapshot_ref: str | None = None,
    imports: ImportResolver | None = None,
    at_pose: PosedContextFactory | None = None,
    sweep: SweepResolver | None = None,
    motion_generations: Mapping[str, int] | None = None,
) -> CheckReport:
    """Execute a frozen bundle's cross-part checks and build the CheckReport.

    Fails closed with ``invalid_check_generation`` (diagnostics included in
    the message) when the generation is persisted invalid. Check names are
    reported as ``"<file stem>:<check name>"`` in lexical file order.

    When no backend is injected, measurement runs on the bounded production
    ops (``COMPARE.md`` §5): ``run_bundle`` is the engine-side surface — the
    ``run_checks`` tool's project scope and ``heph check`` — where an unbounded
    ``m.diff`` could outlive the session. (Part-scope ``CHECKS`` inside the
    sandboxed build worker call :func:`run_checks` directly and keep the
    unbounded in-process diff: the worker itself is the killable subprocess.)

    ``imports`` resolves an ``m.diff(..., "import:<path>")`` target to a shape
    (``COMPARE.md`` §2: acceptance checks may assert against a seeded import).
    The resolver is injected by the caller that owns the project — the engine
    does not decide who may read ``imports/`` — and when it is absent an
    import-target diff keeps its discriminated facade refusal. Added
    2026-08-25: the corpus-v2 editing task ``flange-edit`` grades through
    project-scoped checks, which previously had no resolver at all, so the
    predicate ``COMPARE.md`` §2 promises could never run at grade time.

    ``at_pose`` / ``sweep`` / ``motion_generations`` are the ``KINEMATICS.md``
    §4 motion read surfaces, threaded on exactly the ``imports`` rule: the
    caller that owns the run builds them over the SAME frozen snapshot
    ``sources`` came from (§2, last bullet — never CURRENT mid-run), and when
    they are absent a predicate calling ``m.at_pose``/``m.sweep`` keeps its
    discriminated facade refusal. When a predicate actually resolves motion
    state through them, the report records ``motion_generations`` (the frozen
    joint/pose/motion-check generations) alongside ``project_snapshot_ref``,
    so motion evidence is replayable like every other kind; a run whose
    predicates never touch motion records none, because none governed it.
    """
    if ops is None:
        from hephaestus.core.project_compare import bounded_kernel_ops

        ops = bounded_kernel_ops()
    if bundle.state.status == "invalid":
        raise InvalidCheckGenerationError(
            f"check-set generation {bundle.state.generation} is invalid and fails closed; "
            f"diagnostics: {json.dumps(bundle.diagnostics, sort_keys=True)}"
        )
    checks: dict[str, CheckPredicate] = {}
    for rel in sorted(bundle.contents):
        module_checks = load_check_module(bundle.contents[rel], filename=rel)
        stem = Path(rel).stem
        for name, predicate in module_checks.items():
            checks[f"{stem}:{name}"] = predicate

    # Wrapped rather than passed through so the report can say whether motion
    # state actually governed this run: the flag flips on invocation — a named
    # refusal or a ceiling kill still read the frozen motion state, so they
    # count — never on mere availability of the resolvers.
    motion_used = False

    def _at_pose(pose_id: str) -> PosedPlacement:
        nonlocal motion_used
        assert at_pose is not None  # guarded at facade construction below
        motion_used = True
        return at_pose(pose_id)

    def _sweep(check_id: str) -> Mapping[str, JSONValue]:
        nonlocal motion_used
        assert sweep is not None  # guarded at facade construction below
        motion_used = True
        return sweep(check_id)

    def _factory() -> Measurement:
        return project_measurement(
            sources,
            ops=ops,
            densities=densities,
            imports=imports,
            at_pose=None if at_pose is None else _at_pose,
            sweep=None if sweep is None else _sweep,
        )

    results = run_checks(checks, _factory)
    return CheckReport(
        part=part,
        check_set_generation=bundle.state.generation,
        check_bundle_ref=bundle.state.bundle_ref,
        file_hashes=dict(bundle.state.files),
        project_snapshot_ref=project_snapshot_ref,
        motion_generations=(
            dict(motion_generations) if motion_used and motion_generations is not None else None
        ),
        checks=results,
    )


class CheckSet:
    """Generation-managed ``checks/*.py`` tree over one opstore (arch §3.4).

    ``on_between_scans`` is a test seam invoked between the two stability
    scans of external reconciliation, making drift detection deterministic.
    """

    def __init__(
        self,
        checks_dir: Path,
        store: OpStore,
        *,
        owner: OwnerId | None = None,
        lease_ttl_s: float = 60.0,
        lock_timeout_s: float = 30.0,
        on_between_scans: Callable[[], None] | None = None,
    ) -> None:
        self.checks_dir = checks_dir
        self._store = store
        self._owner = owner or current_owner()
        self._lease_ttl_s = lease_ttl_s
        self._lock_timeout_s = lock_timeout_s
        self._on_between_scans = on_between_scans

    # -- lock ---------------------------------------------------------------

    def _acquire_lock(self) -> str:
        deadline = time.monotonic() + self._lock_timeout_s
        while True:
            try:
                lease = self._store.leases.acquire_exclusive(
                    LOCK_REF, self._owner, self._lease_ttl_s
                )
            except LeaseHeldError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.005)
            else:
                return lease.lease_id

    # -- tree scanning ------------------------------------------------------

    def _scan(self) -> tuple[dict[str, str], dict[str, bytes]]:
        """Lexically-ordered live tree: relpath -> content hash, and raw contents."""
        hashes: dict[str, str] = {}
        contents: dict[str, bytes] = {}
        if not self.checks_dir.is_dir():
            return hashes, contents
        for path in sorted(self.checks_dir.glob("*.py")):
            try:
                raw = path.read_bytes()
            except OSError:
                continue  # vanished mid-scan; the stability rescan will disagree
            hashes[path.name] = sha256_bytes(raw)
            contents[path.name] = raw
        return hashes, contents

    @staticmethod
    def _tree_hash(hashes: Mapping[str, str]) -> str:
        return sha256_canonical_json(cast("JSONValue", dict(hashes)))

    # -- persisted state ----------------------------------------------------

    def _load_state(self) -> tuple[CheckSetState | None, str | None]:
        pointer = self._store.blobs.read_pointer(STATE_POINTER)
        if pointer is None:
            return None, None
        raw = json.loads(self._store.blobs.get(pointer).decode("utf-8"))
        return CheckSetState.from_json(cast("Mapping[str, JSONValue]", raw)), pointer

    def _freeze(
        self,
        *,
        generation: int,
        origin: CheckSetOrigin,
        hashes: Mapping[str, str],
        contents: Mapping[str, bytes],
    ) -> tuple[CheckSetState, str]:
        """Build the immutable bundle + state blob; returns (state, state blob hash)."""
        diagnostics: list[JSONValue] = []
        for rel in sorted(hashes):
            try:
                load_check_module(contents[rel].decode("utf-8"), filename=rel)
            except UnicodeDecodeError as exc:
                diagnostics.append(
                    {
                        "file": rel,
                        "kind": "syntax",
                        "type": "UnicodeDecodeError",
                        "message": str(exc),
                    }
                )
            except ValidationError as exc:
                diagnostics.append(
                    {
                        "file": rel,
                        "kind": exc.kind,
                        "type": type(exc).__name__,
                        "message": exc.message,
                    }
                )
        for rel in sorted(hashes):
            self._store.blobs.put(contents[rel])
        manifest: JSONValue = {
            "files": [{"path": rel, "hash": hashes[rel]} for rel in sorted(hashes)]
        }
        bundle_hash = self._store.blobs.put(canonical_json(manifest).encode("utf-8"))
        diagnostics_hash: str | None = None
        if diagnostics:
            diagnostics_hash = self._store.blobs.put(canonical_json(diagnostics).encode("utf-8"))
        state = CheckSetState(
            generation=generation,
            origin=origin,
            status="invalid" if diagnostics else "valid",
            tree_hash=self._tree_hash(hashes),
            files=dict(hashes),
            bundle=bundle_hash,
            diagnostics=diagnostics_hash,
        )
        state_blob = self._store.blobs.put(canonical_json(state.to_json()).encode("utf-8"))
        return state, state_blob

    # -- recovery + reconciliation (every lock acquisition) -----------------

    def _recover_check_ops(self) -> None:
        """Resolve every PREPARED check WAL row before exposing generation/files."""
        rows = self._store.db.conn.execute(
            "SELECT op_key, target_path FROM operations WHERE state = 'PREPARED' "
            "ORDER BY created_at, op_key"
        ).fetchall()
        checks_root = str(self.checks_dir.resolve())
        for row in rows:
            target = row["target_path"]
            if target is None:
                continue  # begun-but-unprepared skeleton; resolved on its own retry
            target_str = str(target)
            relevant = target_str == POINTER_TARGET_PREFIX + STATE_POINTER or (
                not target_str.startswith(POINTER_TARGET_PREFIX)
                and str(Path(target_str).resolve().parent) == checks_root
            )
            if relevant:
                self._store.wal.recover(str(row["op_key"]))

    def _clear_intent(self, intent_blob: str) -> None:
        self._store.blobs.cas_swap(INTENT_POINTER, intent_blob, None)

    def _resolve_intent(self, state: CheckSetState | None) -> CheckSetState | None:
        """Complete or roll back a crashed cooperative mutation (exactly-once)."""
        intent_pointer = self._store.blobs.read_pointer(INTENT_POINTER)
        if intent_pointer is None:
            return state
        intent = cast(
            "Mapping[str, JSONValue]",
            json.loads(self._store.blobs.get(intent_pointer).decode("utf-8")),
        )
        new_state_blob = cast("str", intent["new_state_blob"])
        old_state_blob = cast("str | None", intent["old_state_blob"])
        new_tree_hash = cast("str", intent["new_tree_hash"])
        publish_op_id = cast("str", intent["publish_op_id"])
        payload_hash = cast("str", intent["payload_hash"])
        if self._store.blobs.read_pointer(STATE_POINTER) == new_state_blob:
            self._clear_intent(intent_pointer)
            reloaded, _ = self._load_state()
            return reloaded
        live_hashes, _ = self._scan()
        if self._tree_hash(live_hashes) == new_tree_hash:
            self._complete_publication(publish_op_id, payload_hash, old_state_blob, new_state_blob)
            self._clear_intent(intent_pointer)
            reloaded, _ = self._load_state()
            return reloaded
        # The file mutation never landed (or a third version intervened):
        # the mutation belongs wholly to no generation — roll the intent back.
        self._clear_intent(intent_pointer)
        return state

    def _complete_publication(
        self,
        publish_op_id: str,
        payload_hash: str,
        old_state_blob: str | None,
        new_state_blob: str,
    ) -> None:
        outcome = self._store.opkeys.begin(publish_op_id, payload_hash)
        if isinstance(outcome, PendingRecovery):
            self._store.wal.recover(outcome.op_key)
            outcome = self._store.opkeys.begin(publish_op_id, payload_hash)
        if isinstance(outcome, Fresh):
            self._store.wal.publish(
                outcome,
                STATE_POINTER,
                old_state_blob,
                new_state_blob,
                intended_outcome=canonical_json({"published": new_state_blob}),
            )
        elif not isinstance(outcome, Replay):
            raise ValidationError(
                f"check-set publication {publish_op_id!r} cannot be completed: {outcome!r}",
                kind="contract",
            )

    def _sync_locked(self) -> CheckSetState:
        """Recovery, intent resolution and external reconciliation under the lock."""
        self._recover_check_ops()
        state, _ = self._load_state()
        state = self._resolve_intent(state)
        hashes, _contents = self._scan()
        live_tree = self._tree_hash(hashes)
        if state is not None and live_tree == state.tree_hash:
            return state
        # Stability probe: an actively-changing tree is drift, not an import.
        if self._on_between_scans is not None:
            self._on_between_scans()
        rescan_hashes, rescan_contents = self._scan()
        if self._tree_hash(rescan_hashes) != live_tree:
            raise CheckSetDriftError(
                "checks/ tree changed while being captured; retry once writes settle"
            )
        old_pointer = self._store.blobs.read_pointer(STATE_POINTER)
        if state is None:
            new_state, state_blob = self._freeze(
                generation=0, origin="initial", hashes=rescan_hashes, contents=rescan_contents
            )
        else:
            new_state, state_blob = self._freeze(
                generation=state.generation + 1,
                origin="external_import",
                hashes=rescan_hashes,
                contents=rescan_contents,
            )
        self._store.blobs.cas_swap(STATE_POINTER, old_pointer, state_blob)
        return new_state

    # -- public API ---------------------------------------------------------

    def current(self) -> CheckSetState:
        """The current generation after recovery/reconciliation (may raise drift)."""
        lease_id = self._acquire_lock()
        try:
            return self._sync_locked()
        finally:
            self._store.leases.release(lease_id)

    def capture(self) -> CheckBundle:
        """Freeze the complete authorized check set for one run, then release.

        The returned bundle's contents come from CAS blobs of exactly one
        generation — a concurrent edit lands wholly before or wholly after.
        """
        lease_id = self._acquire_lock()
        try:
            state = self._sync_locked()
            contents = {
                rel: self._store.blobs.get(blob_hash).decode("utf-8")
                for rel, blob_hash in sorted(state.files.items())
            }
            diagnostics: JSONValue = None
            if state.diagnostics is not None:
                diagnostics = cast(
                    "JSONValue",
                    json.loads(self._store.blobs.get(state.diagnostics).decode("utf-8")),
                )
        finally:
            self._store.leases.release(lease_id)
        return CheckBundle(state=state, contents=contents, diagnostics=diagnostics)

    def diagnostics(self, state: CheckSetState) -> JSONValue:
        """Decoded diagnostics artifact of an invalid generation (None when valid)."""
        if state.diagnostics is None:
            return None
        return cast(
            "JSONValue", json.loads(self._store.blobs.get(state.diagnostics).decode("utf-8"))
        )

    def write_check(self, name: str, content: str, *, op_id: str) -> CheckSetState:
        """Cooperative create/edit of ``checks/<name>``; increments the generation.

        Validates in the check sandbox before commit (nothing lands on
        failure). The mutation is a typed WAL pair — file install, then
        generation publication CAS — under a durable intent, all beneath the
        check-set lock; crash recovery completes exactly one generation
        advance or rolls wholly back.
        """
        if "/" in name or "\\" in name or name in (".", "..") or not name.endswith(".py"):
            raise ValidationError(
                f"check file name must be a plain <name>.py, got {name!r}", kind="contract"
            )
        load_check_module(content, filename=name)  # reject before commit
        lease_id = self._acquire_lock()
        try:
            state = self._sync_locked()
            raw = content.encode("utf-8")
            new_hashes = dict(state.files)
            new_hashes[name] = sha256_bytes(raw)
            new_contents = {
                rel: (raw if rel == name else self._store.blobs.get(state.files[rel]))
                for rel in new_hashes
            }
            new_state, new_state_blob = self._freeze(
                generation=state.generation + 1,
                origin="cooperative",
                hashes=new_hashes,
                contents=new_contents,
            )
            old_state_blob = self._store.blobs.read_pointer(STATE_POINTER)
            payload: JSONValue = {
                "kind": "check_mutation",
                "file": name,
                "old_generation": state.generation,
                "new_generation": new_state.generation,
                "before_hash": state.files.get(name),
                "after_hash": new_hashes[name],
                "old_tree_hash": state.tree_hash,
                "new_tree_hash": new_state.tree_hash,
            }
            payload_hash = sha256_canonical_json(payload)
            publish_op_id = f"{op_id}:publish"
            file_op_id = f"{op_id}:file"
            intent: JSONValue = {
                "publish_op_id": publish_op_id,
                "payload_hash": payload_hash,
                "old_state_blob": old_state_blob,
                "new_state_blob": new_state_blob,
                "new_tree_hash": new_state.tree_hash,
                "file": name,
            }
            intent_blob = self._store.blobs.put(canonical_json(intent).encode("utf-8"))
            self._store.blobs.cas_swap(INTENT_POINTER, None, intent_blob)
            outcome = self._store.opkeys.begin(file_op_id, payload_hash)
            if isinstance(outcome, PendingRecovery):
                self._store.wal.recover(outcome.op_key)
                outcome = self._store.opkeys.begin(file_op_id, payload_hash)
            if isinstance(outcome, Fresh):
                self._store.wal.execute(
                    outcome,
                    self.checks_dir / name,
                    raw,
                    intended_outcome=canonical_json(
                        {"generation": new_state.generation, "file": name}
                    ),
                )
            self._complete_publication(publish_op_id, payload_hash, old_state_blob, new_state_blob)
            self._clear_intent(intent_blob)
            return new_state
        finally:
            self._store.leases.release(lease_id)

    def run(
        self,
        sources: Mapping[str, GeometrySource],
        *,
        part: str,
        ops: KernelOps | None = None,
        densities: Mapping[str, float] | None = None,
        project_snapshot_ref: str | None = None,
        imports: ImportResolver | None = None,
        at_pose: PosedContextFactory | None = None,
        sweep: SweepResolver | None = None,
        motion_generations: Mapping[str, int] | None = None,
    ) -> CheckReport:
        """Capture under the lock, release, then execute (architecture §3.4)."""
        bundle = self.capture()
        return run_bundle(
            bundle,
            sources,
            part=part,
            ops=ops,
            densities=densities,
            project_snapshot_ref=project_snapshot_ref,
            imports=imports,
            at_pose=at_pose,
            sweep=sweep,
            motion_generations=motion_generations,
        )
