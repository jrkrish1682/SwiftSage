"""
XML canonicalization helpers.

Normalization steps applied before comparison:
  1. Strip XML comments and processing instructions
  2. Normalize whitespace in text nodes (collapse runs, strip edges)
  3. Sort element attributes alphabetically (order-independent)
  4. Optionally apply configurable "ignore" patterns (IDs, timestamps)
"""
import re
from copy import deepcopy
from typing import Optional

from lxml import etree

from src.utils.helpers import get_logger, xpath_tag

log = get_logger(__name__)

# Patterns whose text values are replaced with a placeholder when ignored
_PLACEHOLDER = "__IGNORED__"


def canonicalize(
    root: etree._Element,
    ignore_tags: Optional[list[str]] = None,
    normalize_whitespace: bool = True,
) -> etree._Element:
    """
    Return a deep-copied, normalized version of *root* suitable for comparison.

    Args:
        root: The element tree root to normalize.
        ignore_tags: Local tag names whose text content should be zeroed out
                     (e.g. ['MsgId', 'CreDtTm', 'UETR']).
        normalize_whitespace: Collapse and strip whitespace in text nodes.
    """
    node = deepcopy(root)
    ignore_set = set(ignore_tags or [])
    _normalize_subtree(node, ignore_set, normalize_whitespace)
    return node


def _normalize_subtree(
    node: etree._Element,
    ignore_set: set[str],
    normalize_ws: bool,
) -> None:
    # Remove comments and PIs
    for child in list(node):
        if isinstance(child, (etree._Comment, etree._ProcessingInstruction)):
            node.remove(child)
            continue
        _normalize_subtree(child, ignore_set, normalize_ws)

    # Normalize text content
    tag = xpath_tag(node)
    if tag in ignore_set:
        node.text = _PLACEHOLDER
        node.tail = None
    else:
        if normalize_ws and node.text:
            node.text = _collapse_ws(node.text)
        if normalize_ws and node.tail:
            node.tail = _collapse_ws(node.tail)

    # Sort attributes for stable comparison
    if node.attrib:
        sorted_attrib = dict(sorted(node.attrib.items()))
        node.attrib.clear()
        node.attrib.update(sorted_attrib)


def _collapse_ws(text: str) -> str:
    """Collapse multiple whitespace chars into a single space; strip edges."""
    return re.sub(r"\s+", " ", text).strip()


def to_canonical_string(root: etree._Element) -> str:
    """Serialize element to a normalized UTF-8 string (for hashing/display)."""
    return etree.tostring(root, pretty_print=True, encoding="unicode")
