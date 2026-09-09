# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""``hephaestus.testing.sidecar``'s toolchain-resolution and freshness policy.

J-mirrors-and-dx-25: the guard `server/src/hephaestus/testing/sidecar.py` calls
before every sidecar-backed suite must resolve pnpm the way
``scripts/bootstrap.sh`` documents (an environment override, then its own
recorded resolution, then a PATH binary, then corepack, then a pinned
``npx`` fallback) — never a bare ``shutil.which("pnpm")``, which answers "no
sidecar" on exactly the checkout the documented bootstrap produces. And once
``HEPHAESTUS_REQUIRE_SIDECAR=1`` is set (every CI job that installs Node), an
unavailable toolchain must raise by name rather than let ~20 assertions skip
silently.

J-mirrors-and-dx-17: the ``HEPHAESTUS_SKIP_SIDECAR_BUILD=1`` escape hatch must
not let a sidecar-backed lane assert against stale TypeScript. The integrity
manifest hashes the staged OUTPUT (a tamper proof); :func:`sidecar_source_digest`
hashes the INPUTS, so a mismatch between what is staged and what the source
currently is can be told apart from "nobody tampered with the staged bytes".

Every test drives the real module functions against a private, monkeypatched
``repo_root()`` — never the real checkout's `agent/` tree — so nothing here
needs Node, pnpm, or network, and nothing here can leave the real checkout's
`agent/build/` dirty.
"""

from __future__ import annotations

import json
from pathlib import Path

import hephaestus.testing.sidecar as sidecar_mod
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private ``repo_root()`` with a minimal ``agent/`` source tree."""
    root = tmp_path / "repo"
    src = root / "agent" / "src"
    src.mkdir(parents=True)
    (src / "main.ts").write_text("console.log(1);\n", encoding="utf-8")
    (root / "agent" / "package.json").write_text(
        json.dumps({"packageManager": "pnpm@10.34.5"}), encoding="utf-8"
    )
    (root / "agent" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    (root / "agent" / "tsconfig.json").write_text("{}\n", encoding="utf-8")
    (root / "agent" / "scripts").mkdir(parents=True)
    (root / "agent" / "scripts" / "bundle.mjs").write_text("// bundler\n", encoding="utf-8")
    (root / "schemas").mkdir()
    (root / "schemas" / "bridge_limits.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(sidecar_mod, "repo_root", lambda: root)
    # Every test in this module is about resolution/digest policy, never the
    # real environment's pnpm/corepack/npx: start from a clean slate.
    for env in (
        sidecar_mod.REQUIRE_SIDECAR_ENV,
        sidecar_mod.PNPM_ENV,
        sidecar_mod.SKIP_BUILD_ENV,
    ):
        monkeypatch.delenv(env, raising=False)
    # An earlier suite in the same process may have built and cached the real
    # sidecar; resolution policy must be observed from an empty cache.
    monkeypatch.setattr(sidecar_mod, "_DIST_CACHE", {})
    return root


# --------------------------------------------------------------------------
# J-mirrors-and-dx-25 — pnpm_command()'s preference order


def test_the_environment_override_wins_over_everything_else(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(sidecar_mod.PNPM_ENV, "corepack pnpm --silent")
    assert sidecar_mod.pnpm_command() == ["corepack", "pnpm", "--silent"]


def test_the_bootstraps_own_recorded_resolution_is_used_when_present(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The script and this guard must agree BY CONSTRUCTION: the guard reads
    what `scripts/bootstrap.sh` actually recorded rather than re-deriving a
    possibly-different answer."""
    record = fake_repo / "agent" / "build" / "bootstrap_pnpm.json"
    record.parent.mkdir(parents=True)
    # A fake, always-resolvable binary so the recorded route is usable.
    fake_bin = fake_repo / "fake-pnpm"
    fake_bin.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    fake_bin.chmod(0o755)
    record.write_text(json.dumps({"command": [str(fake_bin)]}), encoding="utf-8")
    # `shutil.which` on an absolute path checks executability at that literal
    # path, independent of PATH, so no environment manipulation is needed here.
    assert sidecar_mod.pnpm_command() == [str(fake_bin)]


def test_a_stale_bootstrap_record_falls_through_rather_than_failing(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recorded route that has since left the machine must never be worse
    than no record at all — it falls through to the next preference, not to
    a failure."""
    record = fake_repo / "agent" / "build" / "bootstrap_pnpm.json"
    record.parent.mkdir(parents=True)
    record.write_text(
        json.dumps({"command": ["/nonexistent/definitely-not-pnpm"]}), encoding="utf-8"
    )
    monkeypatch.setattr(sidecar_mod.shutil, "which", lambda name: None)
    assert sidecar_mod._bootstrap_pnpm() is None


def test_a_path_pnpm_is_used_when_no_override_or_record_exists(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        sidecar_mod.shutil, "which", lambda name: "/usr/bin/pnpm" if name == "pnpm" else None
    )
    assert sidecar_mod.pnpm_command() == ["/usr/bin/pnpm"]


def test_corepack_is_the_fallback_when_no_pnpm_is_on_path(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        sidecar_mod.shutil,
        "which",
        lambda name: "/usr/bin/corepack" if name == "corepack" else None,
    )
    assert sidecar_mod.pnpm_command() == ["corepack", "pnpm"]


def test_npx_with_the_manifest_pin_is_the_last_resort(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        sidecar_mod.shutil, "which", lambda name: "/usr/bin/npx" if name == "npx" else None
    )
    assert sidecar_mod.pnpm_command() == ["npx", "--yes", "pnpm@10.34.5"]
    # The pin came from the manifest field, never restated: change the
    # manifest and the resolved command must move with it.
    (fake_repo / "agent" / "package.json").write_text(
        json.dumps({"packageManager": "pnpm@9.1.2"}), encoding="utf-8"
    )
    assert sidecar_mod.pnpm_command() == ["npx", "--yes", "pnpm@9.1.2"]


def test_nothing_at_all_resolves_to_none(fake_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sidecar_mod.shutil, "which", lambda name: None)
    assert sidecar_mod.pnpm_command() is None


# --------------------------------------------------------------------------
# J-mirrors-and-dx-25 — fail-rather-than-skip under HEPHAESTUS_REQUIRE_SIDECAR


def test_an_unavailable_toolchain_raises_by_name_when_required(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(sidecar_mod.REQUIRE_SIDECAR_ENV, "1")
    monkeypatch.setattr(sidecar_mod, "node_executable", lambda: None)
    with pytest.raises(sidecar_mod.SidecarUnavailable, match="J-mirrors-and-dx-25"):
        sidecar_mod._unavailable("no Node on this machine")


def test_an_unavailable_toolchain_is_a_quiet_none_when_not_required(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unset (the default on a developer's own machine): the same condition
    must NOT raise — the caller decides skip vs. fail, and CI is what opts in."""
    assert sidecar_mod._required() is False
    sidecar_mod._unavailable("no Node on this machine")  # must not raise


def test_build_agent_dist_raises_when_node_is_absent_and_required(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(sidecar_mod.REQUIRE_SIDECAR_ENV, "1")
    monkeypatch.setattr(sidecar_mod, "node_executable", lambda: None)
    with pytest.raises(sidecar_mod.SidecarUnavailable):
        sidecar_mod.build_agent_dist()


def test_a_negative_resolution_is_not_memoised(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """J-mirrors-and-dx-17's other half: the OLD cache stored ``None``, so once
    any call in a process found no toolchain every LATER call skipped even
    after the situation changed — invisible to a fixture that stages a
    sidecar mid-session. A failed attempt must be retried, not remembered."""
    calls = {"n": 0}

    def flaky_node() -> str | None:
        calls["n"] += 1
        return None if calls["n"] == 1 else "/usr/bin/node"

    monkeypatch.setattr(sidecar_mod, "node_executable", flaky_node)
    first = sidecar_mod.build_agent_dist()
    assert first is None
    assert calls["n"] == 1
    # The second call must actually RE-CHECK node_executable() rather than
    # short-circuiting on a cached None.
    sidecar_mod.build_agent_dist()
    assert calls["n"] == 2, "a negative build_agent_dist() result was cached across calls"


# --------------------------------------------------------------------------
# J-mirrors-and-dx-17 — the source digest and the staleness check


def test_the_digest_covers_every_input_the_bundle_is_built_from() -> None:
    """Sources, manifest, lockfile, type config, bundler script, shared limits.

    Against the REAL checkout (not ``fake_repo``): the point is that the
    production ``_source_files()`` — not a stand-in tree built for this test
    file — actually declares these exact inputs.
    """
    files = sidecar_mod._source_files()
    assert files is not None, "this is a source checkout; there are inputs to hash"
    covered = set(files)
    assert any(name.startswith("agent/src/") for name in covered)
    for exact in (
        "agent/package.json",
        "agent/pnpm-lock.yaml",
        "agent/tsconfig.json",
        "agent/scripts/bundle.mjs",
        "schemas/bridge_limits.json",
    ):
        assert exact in covered, f"{exact} is not part of the freshness digest"


def test_the_source_digest_changes_when_a_source_file_changes(fake_repo: Path) -> None:
    before = sidecar_mod.sidecar_source_digest()
    assert before is not None
    (fake_repo / "agent" / "src" / "main.ts").write_text("console.log(2);\n", encoding="utf-8")
    after = sidecar_mod.sidecar_source_digest()
    assert after != before


def test_the_source_digest_is_stable_over_an_unrelated_file(fake_repo: Path) -> None:
    """Only the declared inputs matter — an unrelated file in `agent/` must
    not perturb the digest, or every checkout would disagree for no reason."""
    before = sidecar_mod.sidecar_source_digest()
    (fake_repo / "agent" / "NOTES.txt").write_text("unrelated\n", encoding="utf-8")
    assert sidecar_mod.sidecar_source_digest() == before


def test_skipping_the_build_over_a_stale_stage_raises(fake_repo: Path) -> None:
    """The refusal names the count, the file, and the ONE command that fixes it."""
    sidecar_mod.record_staged_source_digest()
    (fake_repo / "agent" / "src" / "main.ts").write_text(
        "console.log('changed');\n", encoding="utf-8"
    )
    with pytest.raises(AssertionError) as excinfo:
        sidecar_mod._check_staged_is_fresh()
    message = str(excinfo.value)
    assert "different sources" in message
    assert "1 input file(s) differ" in message
    assert "agent/src/main.ts" in message
    assert "stage_sidecar.py" in message


def test_skipping_the_build_over_a_matching_stage_is_silent(fake_repo: Path) -> None:
    sidecar_mod.record_staged_source_digest()
    sidecar_mod._check_staged_is_fresh()  # must not raise or warn


def test_an_unstamped_staged_tree_warns_once_rather_than_failing(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checkout whose staging predates this record is UNKNOWN, not broken —
    nobody's tree may fail on upgrade merely for lacking the new record."""
    monkeypatch.setattr(sidecar_mod, "_staleness_warned", False)
    with pytest.warns(RuntimeWarning, match="UNKNOWN"):
        sidecar_mod._check_staged_is_fresh()


# --------------------------------------------------------------------------
# J-mirrors-and-dx-17, the half that decides whether any of the above runs in CI
#
# Every assertion above exercises the guard through the test helper's own build
# path, which records the digest itself. CI does not take that path: it stages by
# invoking `scripts/stage_sidecar.py`, which knows nothing about the record — so
# for as long as no workflow recorded it, `_check_staged_is_fresh()` took its
# warn-once "unknown" branch on every CI run and the guard was inert exactly
# where a stale stage costs the most. The recording step is therefore part of the
# fix, and a step is only as durable as the check that it is still there.


def _workflow_jobs() -> list[tuple[str, str, dict[str, object]]]:
    workflows = REPO / ".github" / "workflows"
    found: list[tuple[str, str, dict[str, object]]] = []
    for path in sorted(workflows.glob("*.yml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        for name, job in (document.get("jobs") or {}).items():
            if isinstance(job, dict):
                found.append((path.name, str(name), job))
    return found


def _sets_skip(scope: object) -> bool:
    return isinstance(scope, dict) and str(scope.get(sidecar_mod.SKIP_BUILD_ENV, "")) == "1"


def test_every_job_that_skips_the_build_records_the_digest_first() -> None:
    """A skipped build is only safe while something couples the stage to its source."""
    unarmed: list[str] = []
    for workflow, name, job in _workflow_jobs():
        steps = [step for step in (job.get("steps") or []) if isinstance(step, dict)]
        recorded_by: int | None = None
        for index, step in enumerate(steps):
            if "hephaestus.testing.sidecar" in str(step.get("run", "")):
                recorded_by = index
                break
        for index, step in enumerate(steps):
            if not (_sets_skip(step.get("env")) or _sets_skip(job.get("env"))):
                continue
            if recorded_by is None or recorded_by > index:
                unarmed.append(f"{workflow}:{name} step {index + 1}")
    assert not unarmed, (
        f"these jobs set {sidecar_mod.SKIP_BUILD_ENV}=1 with no earlier "
        "`python -m hephaestus.testing.sidecar` step, so the staged sidecar's "
        "freshness is UNKNOWN there and the lane can assert against stale "
        f"TypeScript (J-mirrors-and-dx-17): {unarmed}"
    )


def test_the_recording_step_follows_the_staging_it_describes() -> None:
    """The record describes what `scripts/stage_sidecar.py` just staged.

    Recording a digest for a tree nobody staged in this job would be worse than
    not recording one: it would turn "unknown" into a confident wrong answer.
    """
    misplaced: list[str] = []
    for workflow, name, job in _workflow_jobs():
        for index, step in enumerate(job.get("steps") or []):
            if not isinstance(step, dict):
                continue
            script = str(step.get("run", ""))
            if "hephaestus.testing.sidecar" not in script:
                continue
            staged_here = "stage_sidecar.py" in script
            earlier = "\n".join(
                str(previous.get("run", ""))
                for previous in list(job.get("steps") or [])[:index]
                if isinstance(previous, dict)
            )
            if not staged_here and "stage_sidecar.py" not in earlier:
                misplaced.append(f"{workflow}:{name} step {index + 1}")
    assert not misplaced, (
        "these steps record a sidecar source digest without any staging ahead of "
        f"them, so the record describes a tree this job never staged: {misplaced}"
    )
