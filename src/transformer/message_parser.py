"""
Parse a bank's internal XML message into a flat field inventory
that the FieldMapper can reason over.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from lxml import etree


@dataclass
class InternalField:
    name: str           # local element / attribute name
    xpath: str          # XPath relative to document root
    value: str          # text content (stripped)
    parent: str         # immediate parent element name
    is_attribute: bool = False
    sample: str = ""    # first 80 chars of value (for display)

    def __post_init__(self):
        self.sample = (self.value or "")[:80]


def _walk(element: etree._Element, xpath_parts: List[str], results: List[InternalField]) -> None:
    tag = etree.QName(element.tag).localname
    current_path = "/".join(xpath_parts + [tag])

    text = (element.text or "").strip()
    if text:
        parent = xpath_parts[-1] if xpath_parts else ""
        results.append(InternalField(
            name=tag,
            xpath=current_path,
            value=text,
            parent=parent,
        ))

    for attr_name, attr_val in element.attrib.items():
        local_attr = etree.QName(attr_name).localname
        results.append(InternalField(
            name=local_attr,
            xpath=f"{current_path}/@{local_attr}",
            value=attr_val,
            parent=tag,
            is_attribute=True,
        ))

    for child in element:
        _walk(child, xpath_parts + [tag], results)


def parse_xml_fields(xml_content: str) -> List[InternalField]:
    """
    Parse internal bank XML and return a flat list of InternalField records.
    Skips structural wrapper elements that contain no text of their own.
    """
    try:
        root = etree.fromstring(xml_content.encode("utf-8"))
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"Cannot parse XML: {exc}") from exc

    results: List[InternalField] = []
    _walk(root, [], results)
    return results


def fields_to_summary(fields: List[InternalField]) -> str:
    """Return a compact human-readable inventory for display / agent context."""
    lines = [f"{'XPath':<60} {'Value'}", "-" * 100]
    for f in fields:
        lines.append(f"{f.xpath:<60} {f.sample}")
    lines.append(f"\nTotal fields extracted: {len(fields)}")
    return "\n".join(lines)
