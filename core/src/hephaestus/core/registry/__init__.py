"""Hash-pinned registries: format, Merkle digest, verify-on-load, tool backing.

One format for every registry type (architecture §3.6): a versioned directory
holding a ``registry.toml`` manifest plus content, pinned in the project's
``hephaestus.toml`` ``[registries]`` table **by a Merkle digest over the tree**.
``heph registry update`` is the only re-pin path — nothing re-pins implicitly, and
a tree whose bytes no longer hash to the pin refuses to load with a typed
``registry_integrity`` error.

Two untrusted-content classes are handled differently, as the threat model
requires (architecture §7.2):

*Contextual* content (skills markdown, materials notes) never becomes an ambient
Pi extension or privileged skill; it reaches the model only as a tool result
wrapped in the provenance delimiters of :func:`wrap_reference`, under the §5 dual
text cap (bytes AND lines), with absolute snapshot-bound byte cursors on any
truncation so a page is never silently misleading.

*Executable* content (parts-store generators) is a part script with **no
additional capabilities**: :meth:`RegistryOps.instance_store_part` runs it through
the ordinary :func:`~hephaestus.core.executor.runner.run_build` pipeline with
``origin="registry"``, which the injected-namespace whitelist bounds and the
unsafe local backend refuses outright — registry code only ever executes under a
probed secure sandbox.

Store generators additionally obey a small *fragment contract* (see
:func:`parse_generator`) so instancing can emit a placed, collision-free
``script_fragment`` that is the generator's own body verbatim: three marker
regions (``params`` / ``bind`` / ``body``), parameters reaching the body only
through ``_name = p.name`` binds, every module-scope name underscore-prefixed,
and a final ``part.geometry = <name>`` statement naming the instance root.

This module is the package facade; the implementation is split by concern:
:mod:`._digest` (Merkle tree hashing), :mod:`._layout` (``registry.toml`` and
verify-on-load), :mod:`._pins` (``hephaestus.toml`` pinning), :mod:`._skills` /
:mod:`._parts` / :mod:`._materials` / :mod:`._dfm` (per-kind content indexes),
:mod:`._publish` (end-to-end validation + the publication record), :mod:`._set`
(project-wide resolution), :mod:`._reference` (provenance-delimited paging),
:mod:`._generator` (the fragment contract) and :mod:`._ops` (the tool surface).
"""

from __future__ import annotations

from ._dfm import (
    PACK_FILENAME,
    SEVERITIES,
    DfmIndex,
    DfmPack,
    DfmParam,
    DfmRule,
    load_pack,
)
from ._dfm import DfmSeverity as DfmSeverity  # re-exported, not in __all__
from ._digest import merkle_digest, tree_leaves
from ._errors import RegistryError, RegistryIntegrityError
from ._generator import (
    BIND_MARKER,
    BODY_MARKER,
    PARAMS_MARKER,
    GeneratorSource,
    instance_prefix,
    parse_generator,
    render_fragment,
)
from ._layout import (
    BUNDLED_KINDS,
    MANIFEST_FILENAME,
    Registry,
    RegistryManifest,
    load_registry,
    parse_manifest,
)
from ._layout import RegistryKind as RegistryKind  # re-exported, not in __all__
from ._materials import Material, MaterialsIndex
from ._ops import RegistryOps
from ._parts import PartsIndex, StorePart
from ._pins import (
    REGISTRIES_TABLE,
    RegistryPin,
    bundled_pins,
    bundled_registries_root,
    read_pins,
    write_pins,
)
from ._publish import (
    PUBLICATION_VERSION,
    LeafDrift,
    PublicationRecord,
    publication_drift,
    publish_registry,
    validate_content,
    verify_publication,
)
from ._reference import (
    REFERENCE_END,
    REFERENCE_START,
    TEXT_MAX_BYTES,
    TEXT_MAX_LINES,
    wrap_reference,
)
from ._set import RegistrySet
from ._skills import SKILL_ARTIFACT_KIND as SKILL_ARTIFACT_KIND  # re-exported, not in __all__
from ._skills import SkillEntry, SkillsIndex

__all__ = [
    "BIND_MARKER",
    "BODY_MARKER",
    "BUNDLED_KINDS",
    "MANIFEST_FILENAME",
    "PACK_FILENAME",
    "PARAMS_MARKER",
    "PUBLICATION_VERSION",
    "REFERENCE_END",
    "REFERENCE_START",
    "REGISTRIES_TABLE",
    "SEVERITIES",
    "TEXT_MAX_BYTES",
    "TEXT_MAX_LINES",
    "DfmIndex",
    "DfmPack",
    "DfmParam",
    "DfmRule",
    "GeneratorSource",
    "LeafDrift",
    "Material",
    "MaterialsIndex",
    "PartsIndex",
    "PublicationRecord",
    "Registry",
    "RegistryError",
    "RegistryIntegrityError",
    "RegistryManifest",
    "RegistryOps",
    "RegistryPin",
    "RegistrySet",
    "SkillEntry",
    "SkillsIndex",
    "StorePart",
    "bundled_pins",
    "bundled_registries_root",
    "instance_prefix",
    "load_pack",
    "load_registry",
    "merkle_digest",
    "parse_generator",
    "parse_manifest",
    "publication_drift",
    "publish_registry",
    "read_pins",
    "render_fragment",
    "tree_leaves",
    "validate_content",
    "verify_publication",
    "wrap_reference",
    "write_pins",
]
