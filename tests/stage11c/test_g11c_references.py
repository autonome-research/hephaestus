"""G11C clause 8: a core-only install refuses a PDF rather than degrading.

``PARTS_STORE.md`` §7.4 step 1 is deliberate about where the capability boundary
falls: registration is operator-side and content-addressed, and "PDFs require the
server package's extractor and a core-only install refuses with a named
``capability_not_available`` rather than degrading". The degradation this
forecloses is concrete — registering the payload with no extracted text — and it
would be silent: ``list_references`` would show the document, ``read_reference``
would show nothing, and ``heph lint``'s ``unsourced_requirement`` check would then
verify every citation against an empty string and pass all of them.

The clause's second half — "the component's pointer block is unaffected" — is the
one worth stating: the ``datasheet`` pointer is provenance the *registry* carries,
and it has nothing to do with whether this installation can read a PDF. A record
that became invalid on a machine without pypdf would have made a registry's
validity depend on the reader.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from _g11c import PART_ID, component_tree, datasheet_block, make_project, motor_component
from hephaestus.core.project_store.references import ReferenceCapabilityError
from hephaestus.core.registry import PartsIndex, load_registry

#: The smallest thing ``classify`` calls a PDF and ``_MAGIC`` accepts: the
#: refusal must come from the missing extractor, not from a rejected payload.
PDF_BYTES: bytes = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def test_registering_a_pdf_without_an_extractor_is_capability_not_available(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path / "project")
    with pytest.raises(ReferenceCapabilityError) as caught:
        project.references().add_bytes(PDF_BYTES, name="stepper.pdf")
    error = caught.value
    assert error.reason == "capability_not_available"
    assert "hephaestus-server" in str(error)


def test_nothing_was_registered_by_the_refused_call(tmp_path: Path) -> None:
    """ "Nothing was registered" is the half that makes the refusal honest.

    A refusal that still recorded the payload would leave a document in the
    registry whose extracted text is absent — and every citation of it would
    then pass ``unsourced_requirement`` against an empty haystack.
    """
    project = make_project(tmp_path / "project")
    with pytest.raises(ReferenceCapabilityError):
        project.references().add_bytes(PDF_BYTES, name="stepper.pdf")
    assert project.references().list_references() == ()


def test_a_text_document_still_registers_on_the_same_install(tmp_path: Path) -> None:
    """The refusal is scoped to the capability, not to registration.

    ``text/plain`` and ``text/markdown`` are decoded in core with no dependency
    and no ambiguity, which is why every other clause in this suite can use a
    real registered document without needing the server package.
    """
    from _g11c import DATASHEET_BYTES, DATASHEET_NAME

    project = make_project(tmp_path / "project")
    entry = project.references().add_bytes(DATASHEET_BYTES, name=DATASHEET_NAME)
    assert entry.kind == "document"
    assert entry.pages == 1
    assert [e.name for e in project.references().list_references()] == [DATASHEET_NAME]


def test_the_components_pointer_block_is_unaffected(tmp_path: Path) -> None:
    """Clause 8's second half, asserted after the refusal has happened.

    The record still parses, still carries all six §7.3 fields, and still names
    the document to obtain. A registry's validity may not depend on which
    optional dependency the reader installed.
    """
    tree = component_tree(tmp_path / "registry")
    project = make_project(tmp_path / "project", registries={"fixture-parts": tree})
    with pytest.raises(ReferenceCapabilityError):
        project.references().add_bytes(PDF_BYTES, name="stepper.pdf")

    component = PartsIndex(load_registry(tree)).get(PART_ID).component
    assert component is not None
    assert component.datasheet is not None
    assert component.datasheet.to_json() == datasheet_block()
    # …and the URL is still provenance rather than a fetch target: nothing in
    # this path went looking for it (§7.3).
    assert component.datasheet.url.startswith("https://example.invalid/")


def test_a_record_whose_pointer_names_a_pdf_indexes_on_a_core_only_install(
    tmp_path: Path,
) -> None:
    """The generalisation, stated as its own case.

    §7.3's pointer is a *pointer*: it names a publisher, a title, a revision, a
    URL, a digest and a date. Nothing retrieves it — the sandbox denies network
    by construction and a registry that fetched at load would break the offline,
    content-addressed determinism the trust model rests on — so a record naming
    a PDF is exactly as valid here as one naming a text file.
    """
    pointer = datasheet_block()
    pointer["url"] = "https://example.invalid/stepper-datasheet.pdf"
    tree = component_tree(tmp_path / "registry", component=motor_component(datasheet=pointer))
    component = PartsIndex(load_registry(tree)).get(PART_ID).component
    assert component is not None and component.datasheet is not None
    assert cast("str", component.datasheet.url).endswith(".pdf")
