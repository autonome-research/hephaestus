"""G11C clause 14: two processes agree, on the findings and on the resolution.

``PARTS_STORE.md`` §9 states determinism per artifact, because they do not all
have the same status. Everything this clause covers is on the **bit-reproducible**
list and nothing on it touches the geometry kernel: "every named refusal above:
same input, same reason, same detail", plus the registry Merkle root and its leaf
list. So byte equality is the right assertion here, where for §2.3's ``geom_type``
and descriptor ``scalar`` it would have been measuring the OCP build.

Run in **separate processes**, not twice in one. A rule whose output depended on
a module-level cache, on dict insertion order seeded per interpreter, or on a set
iteration order would agree with itself inside one process and disagree across
two — and a bench sweep and a CI lint run are two processes by construction.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from _g11c import (
    CLAIM_ID,
    DATASHEET_NAME,
    DATASHEET_SHA256,
    HOLDING_TORQUE_NM,
    OTHER_BYTES,
    PART_ID,
    SHIPPED_PARTS,
    component_tree,
    sha256_of,
)

REPO: Path = Path(__file__).resolve().parents[2]

#: One child program covering clauses 5, 6 and 7's findings and clause 9's
#: federated resolution. Written as source rather than as an importable helper
#: so the child shares nothing with the parent but the repository itself.
_CHILD = '''
import json, sys
from pathlib import Path
from hephaestus.core.lint import (
    ComponentClaimFacts, ComponentDatum, lint_component_citations, lint_script,
)
from hephaestus.core.registry import RegistryError, RegistrySet, load_registry

shipped, vendor, part_id, claim_id, torque, good, drifted, name = sys.argv[1:9]

script = """PARAMS = {}
body = Box(20.0, 20.0, 5.0)
part.geometry = body

CHECKS = {
    "torque_floor": lambda m: %s > 0.2,
    "plain": lambda m: 7.5 > 1.0,
}
""" % torque

data = (ComponentDatum(value=float(torque), component=part_id, claim=claim_id),)
findings = [f.to_json() for f in lint_script(script, ledger_ids=[], component_data=data)]

facts = {part_id: ComponentClaimFacts(frozenset({claim_id}), good)}
entry = {
    "id": "R1", "text": "t", "source": "specified",
    "cite": {"reference": name, "page": 1, "quote": "q",
             "component": part_id, "claim": claim_id},
}
plain = {"id": "R2", "text": "t", "source": "specified",
         "cite": {"reference": name, "page": 1, "quote": "q"}}
fires = [f.to_json() for f in lint_component_citations(
    [entry], reference_digests={name: drifted}, components=facts)]
silent = [f.to_json() for f in lint_component_citations(
    [plain], reference_digests={name: drifted}, components=facts)]

registries = RegistrySet(
    {"hephaestus-parts": load_registry(Path(shipped)),
     "vendor-parts": load_registry(Path(vendor))}
)
try:
    registries.parts.get("bearing_608")
    ambiguous = None
except RegistryError as exc:
    ambiguous = {"reason": exc.reason, "data": exc.data, "message": str(exc)}

print(json.dumps({
    "uncited": findings,
    "mismatch": fires,
    "silent": silent,
    "ids": list(registries.parts.ids()),
    "search": registries.parts.search("bearing", 10),
    "resolved": registries.parts.get("vendor-parts/bearing_608").registry,
    "ambiguous": ambiguous,
}, sort_keys=True))
'''


def _run(child: Path, vendor: Path) -> str:
    result = subprocess.run(
        [
            sys.executable,
            str(child),
            str(SHIPPED_PARTS),
            str(vendor),
            PART_ID,
            CLAIM_ID,
            repr(HOLDING_TORQUE_NM),
            DATASHEET_SHA256,
            sha256_of(OTHER_BYTES),
            DATASHEET_NAME,
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    return result.stdout


def _vendor_tree(tmp_path: Path) -> Path:
    import shutil

    root = component_tree(tmp_path / "vendor", registry_name="vendor-parts")
    shutil.copytree(SHIPPED_PARTS / "bearing_608", root / "bearing_608")
    manifest = root / "registry.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + '\n[[parts]]\nid = "bearing_608"\ndir = "bearing_608"\n',
        encoding="utf-8",
    )
    return root


def test_two_processes_agree_byte_for_byte(tmp_path: Path) -> None:
    """Clauses 5, 6, 7 and 9, from two interpreters, compared as bytes.

    One assertion over the whole payload rather than one per rule: the clause is
    that the *output* is reproducible, and comparing field by field would let a
    key-order difference — which is a real wire difference to any consumer
    diffing two runs — go unnoticed.
    """
    child = tmp_path / "child.py"
    child.write_text(_CHILD, encoding="utf-8")
    vendor = _vendor_tree(tmp_path)
    first = _run(child, vendor)
    second = _run(child, vendor)
    assert first == second


def test_the_child_really_produced_every_clauses_evidence(tmp_path: Path) -> None:
    """The control: byte equality of two empty results would also be equal.

    A determinism clause that never checks its subject fired is the emptiest
    kind of green, so this reads the payload back and asserts each of the four
    behaviours actually happened.
    """
    child = tmp_path / "child.py"
    child.write_text(_CHILD, encoding="utf-8")
    payload = json.loads(_run(child, _vendor_tree(tmp_path)))

    # clause 5: the retyped datum was reported, the unrelated literal was not.
    codes = [f["code"] for f in payload["uncited"]]
    assert codes.count("uncited_component_datum") == 1
    uncited = next(f for f in payload["uncited"] if f["code"] == "uncited_component_datum")
    assert uncited["name"] == "torque_floor"

    # clause 6: the declared join on drifted bytes fired exactly once…
    assert [f["code"] for f in payload["mismatch"]] == ["datasheet_digest_mismatch"]
    # …clause 7: and the same drifted reference with no component cite is silent.
    assert payload["silent"] == []

    # clause 9: the unique id resolved, the colliding one refused, both named.
    assert payload["resolved"] == "vendor-parts"
    assert payload["ambiguous"] is not None
    assert payload["ambiguous"]["reason"] == "ambiguous_component_id"
    assert sorted(payload["ambiguous"]["data"]["candidates"]) == [
        "hephaestus-parts/bearing_608",
        "vendor-parts/bearing_608",
    ]
    assert "bearing_608" not in payload["ids"]


def test_the_federated_search_rows_are_identical_across_processes(tmp_path: Path) -> None:
    """Search order included, since a federated result is two trees interleaved.

    §9 lists "the registry Merkle root and its leaf list" as bit-reproducible, so
    each row's ``registry_digest`` is too — which is what makes clause 10's
    provenance auditable rather than merely present.
    """
    child = tmp_path / "child.py"
    child.write_text(_CHILD, encoding="utf-8")
    vendor = _vendor_tree(tmp_path)
    rows_a = json.loads(_run(child, vendor))["search"]
    rows_b = json.loads(_run(child, vendor))["search"]
    assert rows_a == rows_b
    assert {row["registry"] for row in rows_a} == {"hephaestus-parts", "vendor-parts"}
    assert all(row["registry_digest"].startswith("sha256:") for row in rows_a)
