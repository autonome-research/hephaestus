"""§9 lint findings on a deliberately messy script + clean pass on fixtures."""

from __future__ import annotations

from pathlib import Path

from hephaestus.core.lint import (
    LintFinding,
    hc_names_from_globals,
    lint_part_script,
    lint_script,
)

FIXTURES = Path(__file__).resolve().parents[2] / "corpus" / "public_fixtures"

#: Every §9 lint plus the §4 shadowing error fires at least once here.
MESSY = """\
PARAMS = {
    "width": Param(40.0, min=10, max=80),
    "unused_knob": Param(2, min=1, max=4),
    "sheet_t": Param(6.0, min=3, max=12),
}
plate = Box(p.width, 20, 6)
ghost = Cylinder(4, 30)
lonely = Box(1, 1, 1)
combo = Compound(children=[plate, Box(5, 5, 5)])
tag(plate.faces().sort_by(Axis.Z)[-1], "top_face")
tag(plate.faces().sort_by(Axis.Z)[0], "forgotten")
part.geometry = combo
part.feature("top_face").surface_finish = "smooth"
"""

HC_NAMES = ("sheet_t", "shelf_w", "joint_clear")


def codes(findings: tuple[LintFinding, ...]) -> set[str]:
    return {finding.code for finding in findings}


def named(findings: tuple[LintFinding, ...], code: str) -> set[str]:
    return {f.name for f in findings if f.code == code and f.name is not None}


class TestMessyScript:
    def findings(self) -> tuple[LintFinding, ...]:
        return lint_script(MESSY, hc_names=HC_NAMES)

    def test_shadowed_param_is_error(self) -> None:
        findings = self.findings()
        shadowed = [f for f in findings if f.code == "shadowed-param"]
        assert [f.name for f in shadowed] == ["sheet_t"]
        assert all(f.severity == "error" for f in shadowed)
        # located at the PARAMS key, not the module head
        assert shadowed[0].line == 4

    def test_unread_params(self) -> None:
        assert named(self.findings(), "unread-param") == {"unused_knob", "sheet_t"}

    def test_unreferenced_tag(self) -> None:
        # top_face is referenced via part.feature("top_face"); forgotten is not
        assert named(self.findings(), "unreferenced-tag") == {"forgotten"}

    def test_unlabeled_compound_child(self) -> None:
        unlabeled = [f for f in self.findings() if f.code == "unlabeled-compound"]
        assert len(unlabeled) == 1
        assert unlabeled[0].line == 9  # the inline Box(5, 5, 5) child

    def test_unreachable_geometry(self) -> None:
        # plate reaches part.geometry through combo; ghost and lonely do not
        assert named(self.findings(), "unreachable-geometry") == {"ghost", "lonely"}

    def test_missing_metadata(self) -> None:
        assert named(self.findings(), "missing-metadata") == {"description", "process"}

    def test_all_warnings_except_shadowing(self) -> None:
        for finding in self.findings():
            expected = "error" if finding.code == "shadowed-param" else "warning"
            assert finding.severity == expected

    def test_findings_sorted_and_json_ready(self) -> None:
        findings = self.findings()
        keys = [(f.line, f.col, f.code, f.name or "") for f in findings]
        assert keys == sorted(keys)
        for finding in findings:
            data = finding.to_json()
            assert data["code"] == finding.code
            assert data["severity"] in ("warning", "error")
            assert isinstance(data["line"], int) and isinstance(data["col"], int)
            assert isinstance(data["message"], str) and data["message"]


class TestEdgeCases:
    def test_syntax_error_is_a_finding_not_a_raise(self) -> None:
        findings = lint_script("def broken(:\n")
        assert len(findings) == 1
        assert findings[0].code == "syntax"
        assert findings[0].severity == "error"
        assert findings[0].line == 1

    def test_no_geometry_assign_suppresses_unreachable(self) -> None:
        findings = lint_script("orphan = Box(1, 1, 1)\n")
        assert "unreachable-geometry" not in codes(findings)

    def test_empty_script_reports_only_missing_metadata(self) -> None:
        findings = lint_script("")
        assert codes(findings) == {"missing-metadata"}

    def test_list_binding_loop_is_reachable(self) -> None:
        source = (
            "items = []\n"
            "for i in range(3):\n"
            "    piece = Box(1, 1, 1)\n"
            "    items.append(piece)\n"
            "part.geometry = Compound(children=[*items])\n"
            "part.description = 'd'\n"
            "part.process = 'fdm'\n"
        )
        assert lint_script(source) == ()


class TestHcNamesFromGlobals:
    def test_assembly_globals_names(self) -> None:
        source = (FIXTURES / "assembly" / "globals.py").read_text(encoding="utf-8")
        assert hc_names_from_globals(source) == (
            "sheet_t",
            "joint_clear",
            "shelf_w",
            "shelf_d",
            "post_h",
            "post_side",
            "frame_h",
        )

    def test_underscore_and_params_excluded(self) -> None:
        source = "PARAMS = {'a': Param(1, min=0, max=2)}\n_hidden = 3\nvisible = 4\n"
        assert hc_names_from_globals(source) == ("a", "visible")


class TestFixturesLintClean:
    def test_assembly_parts_are_clean(self) -> None:
        globals_source = (FIXTURES / "assembly" / "globals.py").read_text(encoding="utf-8")
        for name in ("primary.py", "bracket.py"):
            script = (FIXTURES / "assembly" / "parts" / name).read_text(encoding="utf-8")
            assert lint_part_script(script, globals_source=globals_source) == (), name

    def test_failure_fixture_is_stylistically_clean(self) -> None:
        script = (FIXTURES / "failure_fillet" / "parts" / "broken.py").read_text(encoding="utf-8")
        assert lint_part_script(script) == ()

    def test_fingerprint_fixtures_are_clean(self) -> None:
        for name in ("base.py", "displaced.py", "refactor.py", "swapped.py"):
            script = (FIXTURES / "fingerprint" / name).read_text(encoding="utf-8")
            assert lint_part_script(script) == (), name
