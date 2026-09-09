# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""The tool configuration is the sole declaration, and every exclusion says why.

Three separate audit findings share one shape: a tool's *configuration* claims
one coverage and a workflow step, a documented command or an undocumented
exclusion entry quietly delivers a narrower one. Nothing surfaced any of them,
because the extra coverage happened to be clean — a gap that is silent by
construction is the kind that only a structural assertion closes.

* J-mirrors-and-dx-26 — ``ci.yml``'s type-check step spelled three of the five
  directories ``[tool.pyright] include`` lists. Fixed by deleting the paths; kept
  fixed by :func:`test_the_lint_and_type_steps_take_no_path_arguments`.
* J-mirrors-and-dx-27 — ``bench`` sat in ruff's exclusion list beside five
  entries that each carry a documented justification, and had none. Fixed by
  removing it; kept fixed by
  :func:`test_every_ruff_exclusion_is_justified_in_the_comment_above_it`, which
  turns ``ci.yml``'s house standard ("everything excluded is excluded for ONE
  documented reason … rather than to make CI pass") into a check.
* J-mirrors-and-dx-34 — the pnpm pin is a string copied into five files.
  ``docs/install.md`` names the intended precedence (the sidecar's manifest
  first, the workflow variable second) and ``scripts/bootstrap.sh`` implements
  it; the workflows are the one consumer that copies, because a workflow ``env:``
  value cannot reference a file. :func:`test_the_pnpm_pin_agrees_everywhere`
  makes the copies verifiable.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"

#: The workflows that declare a pnpm version of their own.
PIN_WORKFLOWS: tuple[str, ...] = ("ci.yml", "release.yml", "bench.yml")

#: The Node packages whose ``packageManager`` field is the pin's source.
PIN_MANIFESTS: tuple[str, ...] = ("agent/package.json", "web/package.json")


def _root_pyproject() -> dict[str, Any]:
    return tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))


def _ci() -> dict[str, Any]:
    doc = yaml.safe_load((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def _runs(job: dict[str, Any]) -> list[str]:
    return [
        str(step["run"])
        for step in job.get("steps", [])
        if isinstance(step, dict) and "run" in step
    ]


# --------------------------------------------------------------------------
# J-mirrors-and-dx-26


def test_the_lint_and_type_steps_take_no_path_arguments() -> None:
    """The configuration declares the target; the workflow only runs the tool.

    A path argument on either step is how the two diverge: it overrides the
    configured set with a hand-maintained list that no one re-reads when a
    package is added to ``include``.
    """
    steps = _runs(_ci()["jobs"]["lint-type"])
    invocations = [line.strip() for line in steps if re.search(r"\b(ruff|pyright)\b", line)]
    assert invocations, "the lint + type job runs neither ruff nor pyright"
    for line in invocations:
        # `ruff check .` and `ruff format --check .` name the repository root,
        # which is not a narrowing; anything else is.
        remainder = re.sub(r"^uv run (ruff (check|format)|pyright)\b", "", line).strip()
        arguments = [tok for tok in remainder.split() if not tok.startswith("-")]
        assert arguments in ([], ["."]), (
            f"{line!r} narrows the target by hand; pyproject.toml is the declaration"
        )


# --------------------------------------------------------------------------
# J-mirrors-and-dx-27


def test_every_ruff_exclusion_is_justified_in_the_comment_above_it() -> None:
    """An entry with no reason beside it reads as an oversight — and was one."""
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    start = text.index("extend-exclude = [")
    # The contiguous comment block immediately preceding the list.
    before = text[:start].splitlines()
    block: list[str] = []
    for line in reversed(before):
        if not line.startswith("#"):
            break
        block.append(line)
    justification = "\n".join(block)
    assert justification, "the exclusion list has no comment block above it at all"

    excluded = _root_pyproject()["tool"]["ruff"]["extend-exclude"]
    assert isinstance(excluded, list)
    unjustified = [
        entry for entry in excluded if str(entry).strip("*.").rstrip("/") not in justification
    ]
    assert not unjustified, (
        "these ruff exclusions are not named in the comment block above the list, "
        f"so nothing says why they are excluded: {unjustified}"
    )


# --------------------------------------------------------------------------
# J-mirrors-and-dx-34


def _pin_from_manifest(relative: str) -> str:
    manifest = json.loads((REPO / relative).read_text(encoding="utf-8"))
    field = str(manifest["packageManager"])
    name, _, version = field.partition("@")
    assert name == "pnpm", f"{relative} pins {name!r}, not pnpm"
    return version


def test_the_pnpm_pin_agrees_everywhere() -> None:
    """One string, five files, and until now nothing compared them.

    The pinned CI container image is the one deliberate divergence and is
    excluded here by name: ``docker/ci/README.md`` explains that the manifest
    field does not by itself change what corepack runs, which is why the pinned
    lane activates the repository pin explicitly before using it. Once the image
    is rebaked on the pin, that step and this exclusion both disappear.
    """
    expected = _pin_from_manifest("agent/package.json")
    found: dict[str, str] = {name: _pin_from_manifest(name) for name in PIN_MANIFESTS}
    for workflow in PIN_WORKFLOWS:
        doc = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))
        assert isinstance(doc, dict)
        env = doc.get("env") or {}
        assert "PNPM_VERSION" in env, f"{workflow} declares no PNPM_VERSION"
        found[workflow] = str(env["PNPM_VERSION"])
    off = {where: value for where, value in found.items() if value != expected}
    assert not off, (
        f"agent/package.json pins pnpm {expected}; these disagree: {off}. "
        "The pin has one source (docs/install.md, 'the pin is read, never copied')."
    )


def test_the_image_divergence_is_documented_where_it_is_excluded() -> None:
    """The exclusion above is only legitimate while its reason is written down."""
    readme = (REPO / "docker" / "ci" / "README.md").read_text(encoding="utf-8")
    assert "corepack" in readme, "docker/ci/README.md no longer explains the pnpm mechanism"
    assert "corepack prepare" in readme, (
        "docker/ci/README.md no longer records that the pinned lane activates the "
        "repository pin explicitly — which is the whole reason the image may bake a "
        "different pnpm (J-mirrors-and-dx-34)"
    )


def test_the_declined_derivation_is_recorded_as_a_decision() -> None:
    """The pin is restated, not derived; the workflow must say that was a choice.

    J-mirrors-and-dx-34's fix design offered a first step in each job reading the
    pin out of ``agent/package.json`` into ``$GITHUB_ENV``. That was declined in
    favour of restate-and-enforce, and a comment saying only that ``env:`` cannot
    reference a file explains a *constraint* rather than the decision — which is
    how a shortfall reads as an accident to the next auditor. The three copies
    are proved equal above; this asserts the reader is told why there are three.
    """
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    head = ci[: ci.index('PNPM_VERSION: "')]
    assert "Derivation was CONSIDERED and declined" in head, (
        "ci.yml's PNPM_VERSION note no longer records that reading the pin into "
        "$GITHUB_ENV was considered and declined. Either restore the record or, if "
        "derivation has since landed, delete this test with the restated copies."
    )
    for workflow in ("release.yml", "bench.yml"):
        text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
        line = next(
            entry for entry in text.splitlines() if entry.strip().startswith("PNPM_VERSION:")
        )
        assert "ci.yml" in line, (
            f"{workflow}'s PNPM_VERSION copy no longer points at ci.yml's note, so a "
            "reader of this file cannot find out why the number is restated"
        )


# --------------------------------------------------------------------------
# The configuration's own cross-references
#
# `scripts/docs_check.py` closed this class for markdown links (J-mirrors-and-dx-33)
# and cannot see TOML or YAML comments. A comment that names the test enforcing a
# setting is the reader's only route from the setting to its proof, and it rotted
# twice: `pyproject.toml`'s `testpaths` block pointed at
# `tests/stage7h/test_test_path_census.py` and `ci.yml` pointed at that same
# never-existent module plus `test_pnpm_pin.py` and `test_tool_targets.py`. A
# dead enforcer name is worse than none — it reads as proof and is not — so the
# check covers every governing file this lane owns, not just the two pyprojects,
# and follows a `::name` suffix into the module to confirm the function is there.

_REFERENCE_RE = re.compile(
    r"\b((?:tests|scripts|core|server|opstore|contract|bench|web|agent|docker)"
    r"/[\w./-]+\.py)(?:\s*::\s*(\w+))?"
)

# Files whose commentary cites the tests that enforce it. Comments only for the
# machine-readable formats (a `#` line in TOML/YAML); the whole document for the
# contributor guide, where every path named in prose is a promise to a reader.
_COMMENTED = (
    "pyproject.toml",
    "opstore/pyproject.toml",
    ".github/workflows/ci.yml",
    ".github/workflows/bench.yml",
    ".github/workflows/release.yml",
    ".github/workflows/ci-image.yml",
)
_PROSE = ("CONTRIBUTING.md",)


def _comment_text(source: str) -> str:
    """Blank every non-comment character, preserving offsets.

    Offsets are preserved so a match can still be reported with its real line
    number, and a reference wrapped across two comment lines (``module.py``
    then ``# ::test_name``) still reads as one token, because the intervening
    marker becomes whitespace.
    """
    kept: list[str] = []
    for line in source.splitlines():
        stripped = line.lstrip()
        kept.append(line.replace("#", " ", 1) if stripped.startswith("#") else " " * len(line))
    return "\n".join(kept)


def _dead_references(member: str, text: str) -> list[str]:
    dead: list[str] = []
    for match in _REFERENCE_RE.finditer(text):
        named, function = match.group(1), match.group(2)
        line = text[: match.start()].count("\n") + 1
        target = REPO / named
        if not target.is_file():
            dead.append(f"{member} line {line}: {named} does not exist")
            continue
        if function and f"def {function}(" not in target.read_text(encoding="utf-8"):
            dead.append(f"{member} line {line}: {named} has no {function}")
    return dead


def test_every_repository_path_named_in_a_governing_comment_exists() -> None:
    dead: list[str] = []
    for member in _COMMENTED:
        path = REPO / member
        if not path.is_file():  # ci-image.yml is optional; the rest are not
            continue
        dead += _dead_references(member, _comment_text(path.read_text(encoding="utf-8")))
    for member in _PROSE:
        dead += _dead_references(member, (REPO / member).read_text(encoding="utf-8"))
    assert not dead, (
        "these comments point a reader at a file or test function that does not "
        "exist, so the setting they justify has no reachable proof: " + "; ".join(dead)
    )
