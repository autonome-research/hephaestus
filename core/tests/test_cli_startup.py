"""``heph`` startup cost: registration must not import the CAD/MCP/HTTP stacks.

Ledger ``docs/audit-2026-09-04-janky.md``, lane L2, root cause RC-2: import IS
registration, and a package ``__init__`` that eagerly re-exports everything
means a cheap leaf module (``mcp/cli_serve.py``, ``http/cli_web.py``,
``agent_bridge/cli_export.py``, the ``MESH_UNITS`` tuple in ``geom/mesh.py``)
cannot be reached without paying for its parent package's whole closure —
build123d, OCP, scikit-learn, fastmcp, starlette. J-cli-startup-1 through -5
each name one site; J-cli-robustness-21 shares the same
``try/except ImportError`` blocks in ``build_parser`` (covered by
``test_cli.py::TestOptionalVerbImportDiscrimination`` instead).

There is a **sixth** site the ledger does not name: ``cli_scan.add_subparsers``
reads ``MESH_UNITS`` from ``geom.mesh`` exactly as ``cli_import`` did, so
fixing only the site J-cli-startup-5 names left ``build_parser()`` at 1.66 s
with build123d loaded. It is pinned below beside the fifth.

Every case here runs in a **subprocess**: measuring ``sys.modules`` in the test
process only reports what the snippet imported when nothing else has been
imported first — in a full-suite run other tests have already loaded
build123d, so an in-process assertion would measure the session, not the
package boundary (see ``server/tests/test_http_boundary.py`` and
``tests/stage0a/test_import_boundary.py`` for the same pattern). The ledger
explicitly prefers this exact-and-CI-stable assertion over a wall-clock one
("Prefer the ``sys.modules`` assertion to a wall-clock one: it is exact and
CI-stable" — J-cli-startup-1's Tests section), so no timing threshold is
asserted here.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import textwrap
from collections.abc import Mapping
from typing import cast, get_args

import pytest

#: The heavy stacks that registering a verb must not need. Each name is the
#: home of one of RC-2's five sites (build123d/OCP/sklearn for the geometry
#: kernel via CAD ops or MESH_UNITS; fastmcp/mcp/IPython for the MCP server;
#: starlette/uvicorn for the HTTP workspace).
GEOMETRY_STACK = frozenset({"build123d", "OCP", "sklearn", "scipy", "sympy"})
MCP_STACK = frozenset({"fastmcp", "mcp", "IPython"})
HTTP_STACK = frozenset({"starlette", "uvicorn"})
ALL_HEAVY = GEOMETRY_STACK | MCP_STACK | HTTP_STACK


def _top_level_modules_after(snippet: str) -> set[str]:
    """Run ``snippet`` in a fresh interpreter; return the top-level module
    names left in ``sys.modules`` afterward."""
    program = textwrap.dedent(
        f"""
        import json, sys
        {textwrap.indent(textwrap.dedent(snippet), "        ")}
        print(json.dumps(sorted({{n.partition(".")[0] for n in sys.modules}})))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"snippet failed (rc={result.returncode}):\nSTDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
    # Fontconfig prints warnings/errors to stderr on this host; harmless noise
    # named in the lane brief, not a test failure.
    return set(json.loads(result.stdout.strip().splitlines()[-1]))


def _modules_after(snippet: str) -> set[str]:
    """Run ``snippet`` in a fresh interpreter; return every module name left in
    ``sys.modules`` (not just top-level ones), so an in-package boundary such as
    ``hephaestus.geom`` can be asserted as well as ``build123d``."""
    program = textwrap.dedent(
        f"""
        import json, sys
        {textwrap.indent(textwrap.dedent(snippet), "        ")}
        print(json.dumps(sorted(sys.modules)))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"snippet failed (rc={result.returncode}):\nSTDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
    return set(json.loads(result.stdout.strip().splitlines()[-1]))


def _subparsers(parser: argparse.ArgumentParser) -> Mapping[str, argparse.ArgumentParser]:
    """The ``{verb name: sub-parser}`` map of ``parser``'s subparsers action,
    typed. Mirrors ``_assert_no_arity_collisions`` in
    ``hephaestus.core.cli`` — argparse's own stubs type ``choices`` as an
    untyped mapping, and there is exactly one subparsers action per parser
    built by this module's ``add_subparsers`` functions."""
    for action in parser._actions:  # pyright: ignore[reportPrivateUsage]
        if isinstance(action, argparse._SubParsersAction):  # pyright: ignore[reportPrivateUsage]
            return cast(
                "Mapping[str, argparse.ArgumentParser]",
                action.choices,  # pyright: ignore[reportUnknownMemberType]
            )
    raise AssertionError(f"{parser.prog!r} has no subparsers action")


class TestBuildParserClosure:
    """J-cli-startup-1 through -5, combined: the full ``build_parser()``
    closure. This is the assertion the ledger measured 2.9s/108ms against."""

    def test_build_parser_leaves_every_heavy_stack_unimported(self) -> None:
        loaded = _top_level_modules_after(
            """
            from hephaestus.core.cli import build_parser
            build_parser()
            """
        )
        present = loaded & ALL_HEAVY
        assert not present, (
            f"build_parser() pulled in {sorted(present)}; registration must "
            "import only modules whose closure excludes build123d, fastmcp, "
            "starlette and the geometry package (J-cli-startup-1's stated "
            "invariant)"
        )

    def test_build_parser_leaves_the_geometry_package_unimported(self) -> None:
        """The invariant J-cli-startup-1 states names four things, and
        ``hephaestus.geom`` is one of them. Asserted separately from the
        third-party stacks because it is an in-repo module, and because it is
        the one the geometry package's docstring already warns about for the
        solver. The package's ``__init__`` is itself lazy now
        (:class:`TestGeometryPackageIsLazy`), so this pins the stronger claim:
        registration does not so much as name it."""
        loaded = _modules_after(
            """
            from hephaestus.core.cli import build_parser
            build_parser()
            """
        )
        assert "hephaestus.geom" not in loaded, (
            "build_parser() imported the geometry package; registration may "
            "import only modules whose closure excludes build123d, fastmcp, "
            "starlette and hephaestus.geom"
        )

    def test_build_parser_output_is_unaffected(self) -> None:
        """A deferred import that silently drops an argument must be caught
        even though this file cannot compare against a golden captured before
        the fix (the fix is not landed yet); this locks the *shape* — every
        verb the eager build produces today must still be present."""
        from hephaestus.core.cli import build_parser

        parser = build_parser()
        expected_verbs = {
            "build",
            "check",
            "lint",
            "init",
            "part",
            "script",
            "params",
            "prompt",
            "render",
            "goldens",
            "registry",
            "reference",
            "import",
            "diff",
            "scan",
            "assembly",
            "joints",
            "motion",
            "cam",
            "solve",
            "proposals",
            "agent",
            "export",
            "bench",
            "serve",
        }
        assert set(_subparsers(parser)) == expected_verbs


class TestExportVerbClosure:
    """J-cli-startup-2: ``cad_ops/__init__.py``'s eager aggregate makes
    registering ``heph export list`` cost 3.5s importing build123d/OCP/sklearn
    for a leaf (``export_history.py``) that needs none of them."""

    def test_registering_export_verb_excludes_geometry_kernel(self) -> None:
        loaded = _top_level_modules_after(
            """
            from hephaestus.agent_bridge import cli_export
            """
        )
        present = loaded & GEOMETRY_STACK
        assert not present, (
            f"importing cli_export pulled in {sorted(present)}; `list` and "
            "`unpin` need no geometry kernel (INTERFACE.md §19.40, §22.6)"
        )

    def test_export_verb_still_registers_list_and_unpin(self) -> None:
        from hephaestus.agent_bridge import cli_export

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        cli_export.add_subparsers(sub)
        export_parser = _subparsers(parser)["export"]
        assert set(_subparsers(export_parser)) == {"list", "unpin"}


class TestMcpServeClosure:
    """J-cli-startup-3: ``mcp/__init__.py`` re-exports ``app.py`` eagerly,
    which imports fastmcp (and IPython through it) before the leaf's lazy
    ``serve`` handler ever runs."""

    def test_registering_mcp_serve_excludes_fastmcp_stack(self) -> None:
        loaded = _top_level_modules_after(
            """
            from hephaestus.mcp import cli_serve
            """
        )
        present = loaded & MCP_STACK
        assert not present, (
            f"importing cli_serve pulled in {sorted(present)}; the handler "
            "imports FastMCP lazily, so registering must cost nothing"
        )

    def test_registering_mcp_serve_leaves_geometry_kernel_unimported(self) -> None:
        loaded = _top_level_modules_after(
            """
            from hephaestus.mcp import cli_serve
            """
        )
        present = loaded & GEOMETRY_STACK
        assert not present

    def test_mcp_serve_still_registers_mcp_flag(self) -> None:
        from hephaestus.mcp import cli_serve

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        cli_serve.add_subparsers(sub)
        args = parser.parse_args(["serve", "--mcp"])
        assert getattr(args, "mcp", None) is True


class TestHttpWebClosure:
    """J-cli-startup-4: ``http/__init__.py`` imports the app (starlette
    routing, every projection) and the runtime (the CAD ops), so registering
    ``--web`` costs the whole workspace API even though the leaf imports
    nothing beyond argparse/sys/pathlib/typing."""

    def test_registering_web_verb_excludes_http_stack(self) -> None:
        loaded = _top_level_modules_after(
            """
            from hephaestus.http import cli_web
            """
        )
        present = loaded & HTTP_STACK
        assert not present, (
            f"importing cli_web pulled in {sorted(present)}; the leaf imports "
            "nothing beyond argparse, sys, pathlib and typing"
        )

    def test_registering_web_verb_excludes_geometry_kernel(self) -> None:
        loaded = _top_level_modules_after(
            """
            from hephaestus.http import cli_web
            """
        )
        present = loaded & GEOMETRY_STACK
        assert not present

    def test_web_verb_still_extends_serve_with_web_flags(self) -> None:
        from hephaestus.http import cli_web
        from hephaestus.mcp import cli_serve

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        serve_parser = cli_serve.add_subparsers(sub)
        cli_web.extend_serve(serve_parser)
        args = parser.parse_args(["serve", "--web", "--web-address", "127.0.0.1:9999"])
        assert getattr(args, "web", None) is True
        assert getattr(args, "web_address", None) == "127.0.0.1:9999"


class TestAgentVerbClosure:
    """J-cli-startup-1: ``agent_bridge/cli.py``'s five module-level imports
    (``.app``, ``.cad_ops`` among them) pull the CAD ops aggregate, and
    through it build123d/OCP (1.60s) plus scikit-learn (0.31s), even though
    every one of the five names is used only inside function bodies or string
    annotations — ``add_subparsers`` needs none of them."""

    def test_registering_agent_verb_excludes_geometry_kernel(self) -> None:
        loaded = _top_level_modules_after(
            """
            from hephaestus.agent_bridge import cli
            """
        )
        present = loaded & GEOMETRY_STACK
        assert not present, (
            f"importing agent_bridge.cli pulled in {sorted(present)}; the "
            "five module-level imports (.app, .cad_ops among them) are used "
            "only inside function bodies or annotations, so add_subparsers "
            "needs none of them"
        )

    def test_agent_verb_still_registers_its_flags(self) -> None:
        from hephaestus.agent_bridge import cli as agent_cli

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        agent_cli.add_subparsers(sub)
        args = parser.parse_args(["agent", "--session", "s1", "--part", "plate"])
        assert args.command == "agent"
        assert args.session == "s1"
        assert args.part == "plate"


class TestImportVerbMeshUnitsClosure:
    """J-cli-startup-5: ``add_subparsers`` (registration, not the handler)
    imports ``MESH_UNITS`` from ``hephaestus.geom.mesh`` for a four-string
    tuple, running ``geom/__init__.py``'s eager re-export of build123d, OCP,
    scikit-learn, scipy and sympy on every ``heph`` invocation. The fix
    relocates the constant to ``core/src/hephaestus/core/types.py`` (on the
    geometry package's own dependency allowlist, ~8ms) and re-exports it from
    ``geom/mesh.py`` for compatibility; the CLI is meant to import the leaf
    directly rather than through the geometry package."""

    def test_registering_import_verb_excludes_geometry_kernel(self) -> None:
        loaded = _top_level_modules_after(
            """
            import argparse
            from hephaestus.core import cli_import

            parser = argparse.ArgumentParser()
            sub = parser.add_subparsers(dest="command")
            cli_import.add_subparsers(sub)
            """
        )
        present = loaded & GEOMETRY_STACK
        assert not present, (
            f"registering `heph import` pulled in {sorted(present)}; MESH_UNITS "
            "is a four-string tuple and must not require the geometry package"
        )

    def test_registering_the_scan_verb_excludes_geometry_kernel(self) -> None:
        """The SIXTH site, which the ledger's J-cli-startup-5 does not name:
        ``cli_scan.add_subparsers`` read ``MESH_UNITS`` from ``geom.mesh`` too,
        so with ``cli_import`` alone fixed ``build_parser()`` still cost
        1.66 s and still loaded build123d. Same defect, same root cause (RC-2),
        one line apart."""
        loaded = _top_level_modules_after(
            """
            import argparse
            from hephaestus.core import cli_scan

            parser = argparse.ArgumentParser()
            sub = parser.add_subparsers(dest="command")
            cli_scan.add_subparsers(sub)
            """
        )
        present = loaded & GEOMETRY_STACK
        assert not present, (
            f"registering `heph scan` pulled in {sorted(present)}; --units is a "
            "four-string choice list and must not require the geometry package"
        )

    def test_the_two_import_paths_are_one_object(self) -> None:
        """The anti-fork guard the relocation exists to make possible.

        ``MESH_INGEST.md`` §1.3's unit set is normative and was already written
        twice inside ``geom/mesh.py`` (a tuple and a ``Literal``); moving it to
        ``core.types`` would have been worth nothing if the CLI had grown a
        third copy. There is one definition — ``core.types.MESH_UNITS``,
        derived from ``core.types.MeshUnits`` — reachable by both paths."""
        from hephaestus.core.types import MESH_UNITS as FROM_TYPES
        from hephaestus.core.types import MeshUnits
        from hephaestus.geom.mesh import MESH_UNITS as FROM_GEOM

        assert FROM_GEOM is FROM_TYPES
        assert FROM_TYPES == ("mm", "cm", "m", "in")
        assert set(get_args(MeshUnits)) == set(FROM_TYPES)

    def test_import_add_verb_still_declares_units_choices(self) -> None:
        from hephaestus.core import cli_import

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        cli_import.add_subparsers(sub)
        import_parser = _subparsers(parser)["import"]
        add_parser = _subparsers(import_parser)["add"]
        units_action = next(
            a
            for a in add_parser._actions
            if a.dest == "units"  # pyright: ignore[reportPrivateUsage]
        )
        assert units_action.choices == ["mm", "cm", "m", "in"]


class TestHelpTextGoldens:
    """A deferred import that drops an argument must be caught even though the
    fix changes *when* modules load, never *what* the CLI does. These pin the
    help text captured from the current (pre-fix, eager) implementation, which
    the fix is required to leave byte-identical (J-cli-startup-1's Tests
    section: "a byte-identical `heph --help` golden and per-verb help goldens
    for the four affected verbs").

    A golden here is a claim about import timing, not a veto on new flags: a
    verb that *deliberately* gains an argument re-records its golden in the
    same change that adds the argument. ``heph agent``'s was re-recorded on
    2026-09-07 for J-agent-wiring-4's ``--unsafe-local-executor``; everything
    else in these blocks is as the eager implementation printed it.
    """

    def test_main_help_still_lists_every_verb(self) -> None:
        """A verb-set + substring check, not a byte comparison: several other
        lanes in this cycle are adding verbs and flags to the top-level
        parser concurrently, so a byte golden here would fail for reasons
        unrelated to J-cli-startup-1's import-timing fix. The byte-exact
        check the ledger's Tests section asks for
        (``test_main_help_is_byte_identical`` below) is scoped to the parts
        of the output import-deferral can actually touch — the verb list and
        its help strings — and is expected to need re-recording once this
        cycle's other lanes land; this test is the one that should keep
        passing regardless."""
        from hephaestus.core.cli import build_parser

        parser = build_parser()
        help_text = parser.format_help()
        for verb in (
            "build",
            "check",
            "lint",
            "init",
            "part",
            "script",
            "params",
            "prompt",
            "render",
            "goldens",
            "registry",
            "reference",
            "import",
            "diff",
            "scan",
            "assembly",
            "joints",
            "motion",
            "cam",
            "solve",
            "proposals",
            "agent",
            "export",
            "bench",
            "serve",
        ):
            assert verb in help_text
        assert "--version" in help_text
        assert "Hephaestus CAD engine CLI (engine-first: no server)" in help_text

    def test_main_help_is_byte_identical(self) -> None:
        """The byte-identical ``heph --help`` golden J-cli-startup-1's Tests
        section names. Captured from the tree at the point this lane's fix
        landed (2026-09); if a later lane changes the top-level verb list or
        flags for reasons unrelated to import timing, re-record this literal
        rather than delete the test — it exists to catch a deferred import
        silently dropping an argument, which a verb-set check alone would
        miss (a wrapped help string can lose its continuation line without
        losing the verb name)."""
        from hephaestus.core.cli import build_parser

        parser = build_parser()
        help_text = parser.format_help()
        # The verb-set line exceeds ruff's line-length limit as a single
        # literal (it is one unbreakable argparse-wrapped token, not prose);
        # split across adjacent string literals instead of a `noqa` so the
        # golden content itself stays untouched.
        usage_verb_line = (
            "            {build,check,lint,init,part,script,params,prompt,render,"
            "goldens,registry,reference,import,diff,scan,assembly,joints,motion,"
            "cam,solve,proposals,agent,export,bench,serve} ...\n"
        )
        assert help_text == "usage: heph [-h] [--version]\n" + usage_verb_line + textwrap.dedent(
            """\

            Hephaestus CAD engine CLI (engine-first: no server)

            positional arguments:
              {build,check,lint,init,part,script,params,prompt,render,goldens,registry,reference,import,diff,scan,assembly,joints,motion,cam,solve,proposals,agent,export,bench,serve}
                build               build a part and publish the result
                check               run the cross-part check set
                lint                lint a part script (§9 + hc shadowing)
                init                scaffold a new Hephaestus project directory
                part                list, create, or show a part
                script              read or write a part script
                params              show PARAMS declarations and effective values
                prompt              show or store the operator request text (not a hosted
                                    chat)
                render              render a part's current build, or a posed scene, to
                                    PNG(s)
                goldens             verify the golden corpus against its sidecars
                                    (--update regenerates it)
                registry            inspect and pin content registries
                reference           register operator-supplied reference documents and
                                    images
                import              admit a STEP, mesh, or point cloud into imports/
                diff                compare a part against another part or an import
                scan                print the facts of a mesh or point cloud already under
                                    imports/ (admit with heph import add; no
                                    reconstruction)
                assembly            show declared constraints and their latest residuals
                joints              show declared joints and poses with their latest
                                    motion outcomes
                motion              show declared motion checks, their latest sweep
                                    results, and couplings
                cam                 2D CAM: laser-cut / waterjet toolpath and DXF
                solve               propose values for declared free variables (writes
                                    nothing)
                proposals           list recorded placement proposals and their staleness
                                    (writes nothing)
                agent               interactive CAD agent session (requires Node and a
                                    provider config)
                export              list exported files and release their GC roots
                bench               Tier 3 golden-prompt benchmark (corpus tasks)
                serve               serve the project over MCP or the web workspace

            options:
              -h, --help            show this help message and exit
              --version             print the installed Hephaestus version and exit
            """
        )

    def test_agent_help_is_unchanged(self) -> None:
        from hephaestus.core.cli import build_parser

        parser = build_parser()
        help_text = _subparsers(parser)["agent"].format_help()
        assert help_text == textwrap.dedent(
            """\
            usage: heph agent [-h] [--project DIR] [--session NAME] [--resume]
                              [--profile {orchestrator,part,quick_edit}] [--part PART]
                              [--providers FILE] [--unsafe-local-executor]

            Run an interactive Hephaestus agent session. Provider configuration is read
            from --providers, else $HEPHAESTUS_AGENT_PROVIDERS, else
            <project>/.heph/providers.json: {"providers": [...], "credential_allowlist":
            ["ANTHROPIC_API_KEY"]}. Only allowlisted environment variables are forwarded
            to the sidecar.

            options:
              -h, --help            show this help message and exit
              --project DIR         project directory (default: cwd)
              --session NAME        session id to create or resume
              --resume              resume the named session's transcript
              --profile {orchestrator,part,quick_edit}
                                    session profile (default: orchestrator)
              --part PART           bound part for a part/quick_edit session
              --providers FILE      provider config JSON path
              --unsafe-local-executor
                                    run the build worker WITHOUT OS sandboxing (local
                                    debugging only)
            """
        )

    def test_export_help_is_unchanged(self) -> None:
        from hephaestus.core.cli import build_parser

        parser = build_parser()
        help_text = _subparsers(parser)["export"].format_help()
        assert help_text == textwrap.dedent(
            """\
            usage: heph export [-h] {list,unpin} ...

            positional arguments:
              {list,unpin}
                list        show every committed export and its pinned outputs
                unpin       drop one exported blob's GC root (deletes nothing)

            options:
              -h, --help    show this help message and exit
            """
        )

    def test_serve_help_is_unchanged(self) -> None:
        from hephaestus.core.cli import build_parser

        parser = build_parser()
        help_text = _subparsers(parser)["serve"].format_help()
        assert help_text == textwrap.dedent(
            """\
            usage: heph serve [-h] [--mcp] [--http HOST:PORT] [--web]
                              [--web-address HOST:PORT] [--project DIR]

            options:
              -h, --help            show this help message and exit
              --mcp                 serve the MCP tool surface
              --http HOST:PORT      serve streamable HTTP instead of stdio (default
                                    127.0.0.1:8765)
              --web                 serve the web workspace API (INTERFACE.md §2)
              --web-address HOST:PORT
                                    bind address for --web (loopback only; default
                                    127.0.0.1:8760)
              --project DIR         project directory for --web (default: cwd)
            """
        )

    def test_import_add_help_is_unchanged(self) -> None:
        from hephaestus.core.cli import build_parser

        parser = build_parser()
        import_parser = _subparsers(parser)["import"]
        help_text = _subparsers(import_parser)["add"].format_help()
        assert help_text == textwrap.dedent(
            """\
            usage: heph import add [-h] [--name NAME] [--units {mm,cm,m,in}] [--part PART]
                                   [--redeclare] [--json]
                                   path

            positional arguments:
              path                  file to copy (original is left untouched)

            options:
              -h, --help            show this help message and exit
              --name NAME           store under this imports/-relative name (default:
                                    filename)
              --units {mm,cm,m,in}  required for STL/PLY/OBJ/OFF/XYZ; refused for STEP
                                    (never inferred)
              --part PART           create parts/<name>.py via create_part (refuse if it
                                    exists; no force). STEP seeds import_step; mesh seeds
                                    import_mesh + mesh_to_solid; a point cloud is
                                    point_cloud_has_no_solid (no reconstruction)
              --redeclare           replace a prior admission of this name whose bytes or
                                    units differ (importing parts go stale); without it a
                                    contradiction is refused
              --json                emit {name, kind, sha256, path, units, recorded}
            """
        )


class TestCadOpsAggregateIsComplete:
    """J-cli-startup-2's one structural cost: :class:`CadOps` is defined *from*
    the mixins, so it cannot be re-exported from a submodule the way every
    other name in ``cad_ops/__init__.py`` now is. It is assembled on first
    access instead, which means its base list is written twice — once in the
    ``TYPE_CHECKING`` declaration the type checker reads, once in the runtime
    factory. (The *constructor* is not: both halves inherit it from
    ``CadOpsState``, so it exists once, in ``_base.py``.) This is the guard
    against the two base lists drifting apart, and it is stated as an invariant
    rather than as a copy of the list: the aggregate aggregates *everything*,
    so a twenty-second domain mixin cannot be added and silently left out of
    the class the dispatcher actually gets.
    """

    def test_every_ops_mixin_in_the_package_is_a_base_of_cad_ops(self) -> None:
        import importlib
        import inspect
        import pkgutil

        from hephaestus.agent_bridge import cad_ops

        mixins: dict[str, type] = {}
        for info in pkgutil.iter_modules(cad_ops.__path__):
            if not info.name.startswith("_"):
                continue
            module = importlib.import_module(f"{cad_ops.__name__}.{info.name}")
            for name, obj in vars(module).items():
                if (
                    inspect.isclass(obj)
                    and name.endswith("Ops")
                    and obj.__module__ == module.__name__
                ):
                    mixins[name] = obj
        assert mixins, "no *Ops mixins found; the discovery itself is broken"
        missing = sorted(
            name for name, cls in mixins.items() if not issubclass(cad_ops.CadOps, cls)
        )
        assert not missing, (
            f"{missing} is defined in the cad_ops package but is not a base of "
            "CadOps; the runtime factory and the TYPE_CHECKING declaration in "
            "cad_ops/__init__.py have drifted"
        )


class TestGeometryPackageIsLazy:
    """``hephaestus.geom``'s package ``__init__`` re-exported nine services
    eagerly, and that cost more than time: ``geom.nesting`` depends downward on
    ``hephaestus.core.cutfile``, ``core.cutfile`` imports
    ``hephaestus.core.dfm.types``, and the ``core.dfm`` package ``__init__``
    imports ``core.dfm.context``, which imports ``hephaestus.geom.topology``.
    Eager re-export closed that into a real cycle — a cycle the suites never saw
    only because something always happened to import ``hephaestus.geom`` first.

    Making ``cad_ops/__init__.py`` lazy (J-cli-startup-2) changed which module
    got there first and the latent cycle became a live ``ImportError`` on the
    plain line ``from hephaestus.agent_bridge.cad_ops import EXPORT_FORMATS,
    CadOps``. The fix is one layer down and is the same root cause (RC-2): a
    package ``__init__`` may not turn a leaf import into a whole-closure
    import. These cases pin both halves — the cycle stays broken, and the
    public surface the eager version offered is unchanged.
    """

    def test_core_cutfile_imports_first_in_a_fresh_interpreter(self) -> None:
        # The minimal reproduction. Before the fix this raised
        # ``ImportError: cannot import name 'BLANK_LAYER' from partially
        # initialized module 'hephaestus.core.cutfile'``.
        modules = _modules_after(
            """
            import hephaestus.core.cutfile
            """
        )
        assert "hephaestus.core.cutfile" in modules
        # And it must not have dragged the geometry services in to get there.
        assert "hephaestus.geom.nesting" not in modules

    def test_cad_ops_re_exports_import_without_a_cycle(self) -> None:
        # The line that actually broke (server/tests/test_dispatch_tools.py:21).
        modules = _modules_after(
            """
            from hephaestus.agent_bridge.cad_ops import EXPORT_FORMATS, CadOps
            """
        )
        assert "hephaestus.agent_bridge.cad_ops" in modules

    def test_importing_the_package_costs_nothing(self) -> None:
        top = _top_level_modules_after(
            """
            import hephaestus.geom
            """
        )
        assert not (top & ALL_HEAVY), (
            f"importing hephaestus.geom loaded {sorted(top & ALL_HEAVY)}; the "
            "package __init__ is re-exporting eagerly again"
        )

    def test_importing_one_service_does_not_import_the_others(self) -> None:
        modules = _modules_after(
            """
            import hephaestus.geom.topology
            """
        )
        assert "hephaestus.geom.topology" in modules
        # `topology` is stdlib-only; `nesting` is what reaches back down into
        # `core.cutfile` and closes the cycle.
        assert "hephaestus.geom.nesting" not in modules
        assert "hephaestus.core.cutfile" not in modules

    def test_every_promised_name_still_resolves(self) -> None:
        import hephaestus.geom as geom

        missing = sorted(name for name in geom.__all__ if not hasattr(geom, name))
        assert not missing, f"{missing} is in __all__ but does not resolve"

    def test_the_service_submodules_are_still_attributes(self) -> None:
        # The eager `__init__` left each service bound as an attribute of the
        # package as a side effect of importing it, so `geom.nesting.shelf_nest`
        # worked. That is part of the surface and it has to survive.
        import hephaestus.geom as geom

        assert callable(getattr(geom.nesting, "shelf_nest", None))
        assert callable(getattr(geom.topology, "planar_faces", None))

    def test_the_metrics_name_is_the_function_whatever_the_order(self) -> None:
        # `metrics` is both a service module and a function that module defines.
        # The eager version resolved the collision in favour of the function; a
        # lazy resolution that let the import system's submodule binding win
        # would make the answer depend on which name a caller touched first.
        for first in ("bbox_mm", "metrics", "nesting"):
            _modules_after(
                f"""
                import types
                import hephaestus.geom as g
                g.{first}
                assert not isinstance(g.metrics, types.ModuleType), (
                    "touching {first} first left hephaestus.geom.metrics bound "
                    "to the module rather than to the function"
                )
                """
            )  # the assertion runs inside the subprocess

    def test_the_solver_is_still_omitted_from_the_surface(self) -> None:
        # ``SOLVER.md`` §7.1: the verification pass runs in a process whose
        # closure EXCLUDES the solver, and the omission from this package's
        # surface is the guarantee. Lazy or eager, ``solve`` is not a name here.
        import hephaestus.geom as geom

        assert "solve" not in geom.__all__
        with pytest.raises(AttributeError):
            _ = geom.solve
