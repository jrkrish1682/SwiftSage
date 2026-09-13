"""
Read element and attribute cardinality out of an ISO 20022 XSD so the diff
classifier can tell a mandatory element apart from an optional one.

ISO 20022 schemas declare every element inside named complexTypes, so a full
path lookup would require resolving type references across the whole schema.
The classifier only needs to know whether the element at the end of a path is
mandatory, which is answered by looking the element name up in the flattened
declaration index. Where a name is declared both ways (mandatory in one type,
optional in another) it is reported as optional, so the classifier degrades to
its rule-based severity instead of over-reporting BREAKING.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from lxml import etree

from src.utils.helpers import get_logger

log = get_logger(__name__)

_XS = "{http://www.w3.org/2001/XMLSchema}"


class SchemaCardinality:
    """Flattened minOccurs / use index for a single XSD."""

    def __init__(self, elements: dict[str, bool], attributes: dict[str, bool]):
        self._elements = elements
        self._attributes = attributes

    # ── Construction ───────────────────────────────────────────────────────

    @classmethod
    def from_xsd(cls, xsd_path: str | Path) -> Optional["SchemaCardinality"]:
        """Build an index from an XSD file, or None if it cannot be read."""
        try:
            doc = etree.parse(str(xsd_path))
        except Exception as exc:
            log.warning("Cannot read cardinality from %s: %s", xsd_path, exc)
            return None

        elements: dict[str, bool] = {}
        for decl in doc.iter(f"{_XS}element"):
            name = decl.get("name")
            if not name:
                continue
            mandatory = decl.get("minOccurs", "1") != "0"
            elements[name] = elements.get(name, True) and mandatory

        attributes: dict[str, bool] = {}
        for decl in doc.iter(f"{_XS}attribute"):
            name = decl.get("name")
            if not name:
                continue
            mandatory = decl.get("use", "optional") == "required"
            attributes[name] = attributes.get(name, True) and mandatory

        log.info(
            "Loaded cardinality for %s: %d elements, %d attributes",
            Path(xsd_path).name, len(elements), len(attributes),
        )
        return cls(elements, attributes)

    # ── Lookup ─────────────────────────────────────────────────────────────

    def is_mandatory(self, path: str) -> Optional[bool]:
        """
        Whether the element or attribute at the end of *path* is mandatory.
        Returns None when the schema does not declare it.
        """
        leaf = path.split("/")[-1].split("[")[0]
        if leaf.startswith("@"):
            return self._attributes.get(leaf[1:])
        return self._elements.get(leaf)

    def __len__(self) -> int:
        return len(self._elements) + len(self._attributes)
