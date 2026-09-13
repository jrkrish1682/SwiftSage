"""
Expand an ISO 20022 XSD into a path-addressable outline of the target message.

The Transformation Advisor previously described its target with a hand-written
block of pain.001 elements, which meant every other target — pacs.008, camt.053,
any trade message — was mapped against the wrong reference material, and nothing
verified that a proposed ISO 20022 XPath existed at all. This module flattens a
schema into `SchemaNode` records so the mapper prompt, the gap register and the
mapping validator all read the same structure straight out of the XSD.

ISO 20022 declares every element inside named complexTypes, so the outline is
built by walking type references from the `Document` root. Recursive types are
cut off when a type reappears on the current branch, and the walk is depth
limited, which keeps a message like pain.001.001.09 to a few thousand paths.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Iterator, Optional

from lxml import etree

from src.utils.helpers import get_logger

log = get_logger(__name__)

_XS = "{http://www.w3.org/2001/XMLSchema}"
_PARTICLES = (f"{_XS}sequence", f"{_XS}choice", f"{_XS}all", f"{_XS}group")
_MAX_DEPTH = 7
_MAX_CODES = 14

# Validation outcomes for a proposed ISO 20022 XPath
RESOLVED = "RESOLVED"        # path found in the schema
RENAMED = "PARTIAL"          # element exists but not at the proposed path
UNRESOLVED = "UNRESOLVED"    # element does not exist in the target schema
UNCHECKED = "UNCHECKED"      # no schema available for the target message


@dataclass(frozen=True)
class SchemaNode:
    """One element or attribute declaration, addressed by its path."""

    name: str
    path: str                       # path from the message root, e.g. GrpHdr/MsgId
    type_name: str
    mandatory: bool                 # minOccurs != 0 / use="required"
    repeatable: bool
    is_attribute: bool = False
    in_choice: bool = False
    is_leaf: bool = True
    codes: tuple[str, ...] = ()
    constraint: str = ""

    @property
    def occurrence(self) -> str:
        return f"[{0 if not self.mandatory else 1}..{'n' if self.repeatable else 1}]"

    def describe(self) -> str:
        """One prompt-friendly line: path, occurrence, type and constraints."""
        parts = [f"{self.path} {self.occurrence}"]
        detail = self.type_name or ""
        if self.constraint:
            detail = f"{detail}, {self.constraint}" if detail else self.constraint
        if self.codes:
            shown = ", ".join(self.codes[:_MAX_CODES])
            if len(self.codes) > _MAX_CODES:
                shown += ", …"
            detail = f"{detail} — codes: {shown}" if detail else f"codes: {shown}"
        if self.in_choice:
            detail = f"{detail} (choice)" if detail else "(choice)"
        if detail:
            parts.append(detail)
        return " : ".join(parts)


class TargetSchema:
    """Flattened outline of a single ISO 20022 message schema."""

    def __init__(self, message_type: str, nodes: list[SchemaNode]):
        self.message_type = message_type
        self._nodes = nodes
        self._by_path = {n.path: n for n in nodes}
        self._by_name: dict[str, list[SchemaNode]] = {}
        for node in nodes:
            self._by_name.setdefault(node.name.lower(), []).append(node)

    # ── Construction ───────────────────────────────────────────────────────

    @classmethod
    def from_xsd(cls, xsd_path: str | Path, message_type: str = "") -> Optional["TargetSchema"]:
        """Build an outline from an XSD file, or None if it cannot be read."""
        try:
            doc = etree.parse(str(xsd_path))
        except Exception as exc:
            log.warning("Cannot outline %s: %s", xsd_path, exc)
            return None

        complex_types = {
            t.get("name"): t for t in doc.iter(f"{_XS}complexType") if t.get("name")
        }
        simple_types = {
            t.get("name"): t for t in doc.iter(f"{_XS}simpleType") if t.get("name")
        }

        root_decl = next(
            (
                e for e in doc.getroot()
                if e.tag == f"{_XS}element" and e.get("name") == "Document"
            ),
            None,
        )
        if root_decl is None:
            log.warning("%s has no Document root element", xsd_path)
            return None

        builder = _Outline(complex_types, simple_types)
        nodes = list(builder.walk(root_decl.get("type", ""), prefix="", depth=0, branch=()))
        name = message_type or _message_type_from_name(Path(xsd_path).name)
        log.info("Outlined %s: %d paths", name or xsd_path, len(nodes))
        return cls(name, nodes)

    @classmethod
    def for_message_type(cls, message_type: str) -> Optional["TargetSchema"]:
        """Outline for a message type, from the vendored schema bundle."""
        return _cached_for_message_type(message_type)

    # ── Lookup ─────────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._nodes)

    @property
    def nodes(self) -> list[SchemaNode]:
        return list(self._nodes)

    def get(self, path: str) -> Optional[SchemaNode]:
        """Node at *path*, matching on a path suffix so a caller can pass a
        partial path such as `Amt/InstdAmt` or the full `Document/...` path."""
        norm = _normalise(path)
        if not norm:
            return None
        if norm in self._by_path:
            return self._by_path[norm]
        suffix = f"/{norm}"
        matches = [n for n in self._nodes if n.path.endswith(suffix)]
        if matches:
            return min(matches, key=lambda n: len(n.path))
        return None

    def resolve(self, path: str) -> tuple[str, Optional[SchemaNode]]:
        """
        Classify a proposed ISO 20022 XPath as RESOLVED, PARTIAL or UNRESOLVED,
        returning the matched node where there is one.
        """
        node = self.get(path)
        if node is not None:
            return RESOLVED, node
        leaf = _normalise(path).split("/")[-1].lstrip("@").lower()
        by_name = self._by_name.get(leaf)
        if by_name:
            return RENAMED, min(by_name, key=lambda n: len(n.path))
        return UNRESOLVED, None

    def mandatory_leaves(self) -> list[SchemaNode]:
        """
        Leaf nodes that are mandatory all the way up their branch, excluding
        members of a choice (where only one alternative is required).
        """
        mandatory_paths = {n.path for n in self._nodes if n.mandatory and not n.in_choice}
        out: list[SchemaNode] = []
        for node in self._nodes:
            if not node.is_leaf or not node.mandatory or node.in_choice:
                continue
            parents = node.path.split("/")[:-1]
            if all(
                "/".join(parents[: i + 1]) in mandatory_paths
                for i in range(len(parents))
            ):
                out.append(node)
        return out

    def mapping_context(self, max_depth: int = 5, max_lines: int = 320) -> str:
        """
        Reference material for the mapper prompt: the message outline, mandatory
        paths first so they survive truncation, then the optional detail.
        """
        selected = [n for n in self._nodes if n.path.count("/") < max_depth]
        mandatory = [n for n in selected if n.mandatory and not n.in_choice]
        optional = [n for n in selected if not (n.mandatory and not n.in_choice)]

        budget = max(max_lines - len(mandatory), 0)
        kept = set(id(n) for n in mandatory) | set(id(n) for n in optional[:budget])
        lines = [n.describe() for n in selected if id(n) in kept]

        omitted = len(self._nodes) - len(lines)
        header = (
            f"{self.message_type} structure, taken from the vendored XSD. "
            f"Paths are relative to the Document root; [0..1] is optional, "
            f"[1..n] is mandatory and repeatable; @Name is an attribute."
        )
        body = "\n".join(f"  {line}" for line in lines)
        footer = (
            f"\n  … {omitted} further optional or deeper paths omitted."
            if omitted > 0 else ""
        )
        return f"{header}\n{body}{footer}\n"


# ── Internals ──────────────────────────────────────────────────────────────


class _Outline:
    """Depth-limited walk over an XSD's type graph."""

    def __init__(self, complex_types: dict, simple_types: dict):
        self._complex = complex_types
        self._simple = simple_types

    def walk(
        self, type_name: str, prefix: str, depth: int, branch: tuple[str, ...]
    ) -> Iterator[SchemaNode]:
        complex_type = self._complex.get(type_name)
        if complex_type is None or depth >= _MAX_DEPTH or type_name in branch:
            return
        for decl, in_choice in _particles(complex_type):
            if decl.tag == f"{_XS}attribute":
                name = decl.get("name")
                if not name:
                    continue
                yield SchemaNode(
                    name=name,
                    path=f"{prefix}@{name}" if prefix else f"@{name}",
                    type_name=decl.get("type", ""),
                    mandatory=decl.get("use", "optional") == "required",
                    repeatable=False,
                    is_attribute=True,
                    constraint=self._constraint(decl.get("type", "")),
                    codes=self._codes(decl.get("type", "")),
                )
                continue

            name = decl.get("name")
            if not name:
                continue
            child_type = decl.get("type", "")
            path = f"{prefix}{name}"
            is_complex = child_type in self._complex
            node = SchemaNode(
                name=name,
                path=path,
                type_name=child_type,
                mandatory=decl.get("minOccurs", "1") != "0",
                repeatable=decl.get("maxOccurs", "1") not in ("1", "0"),
                in_choice=in_choice,
                is_leaf=not is_complex,
                codes=() if is_complex else self._codes(child_type),
                constraint="" if is_complex else self._constraint(child_type),
            )
            yield node
            if is_complex:
                yield from self.walk(
                    child_type, f"{path}/", depth + 1, branch + (type_name,)
                )

    def _codes(self, type_name: str) -> tuple[str, ...]:
        simple = self._simple.get(type_name)
        if simple is None:
            return ()
        return tuple(
            e.get("value", "") for e in simple.iter(f"{_XS}enumeration")
        )

    def _constraint(self, type_name: str) -> str:
        simple = self._simple.get(type_name)
        if simple is None:
            # ActiveCurrencyAndAmount and friends are complexTypes wrapping a
            # simple base plus a Ccy attribute; their base carries the facets.
            complex_type = self._complex.get(type_name)
            if complex_type is None:
                return ""
            extension = complex_type.find(f"{_XS}simpleContent/{_XS}extension")
            base = extension.get("base") if extension is not None else None
            return self._constraint(base) if base else ""

        bits: list[str] = []
        for facet, label in (
            ("maxLength", "max %s chars"),
            ("minLength", "min %s chars"),
            ("pattern", "pattern %s"),
            ("fractionDigits", "%s decimal places"),
            ("totalDigits", "%s digits"),
        ):
            found = simple.find(f".//{_XS}{facet}")
            if found is not None:
                bits.append(label % found.get("value", ""))
        restriction = simple.find(f"{_XS}restriction")
        if restriction is not None and not bits:
            base = restriction.get("base", "")
            if base.startswith("xs:") or base in self._simple:
                bits.append(self._constraint(base) or base.replace("xs:", ""))
        return ", ".join(b for b in bits if b)


def _particles(node: etree._Element) -> Iterable[tuple[etree._Element, bool]]:
    """Element and attribute declarations of a complexType, flagging choices."""
    for child in node:
        if child.tag in (f"{_XS}element", f"{_XS}attribute"):
            yield child, node.tag == f"{_XS}choice"
        elif child.tag in _PARTICLES or child.tag in (
            f"{_XS}complexContent", f"{_XS}simpleContent",
            f"{_XS}extension", f"{_XS}restriction",
        ):
            yield from _particles(child)


_INDEX_RE = re.compile(r"\[[^\]]*\]")
_MSG_TYPE_RE = re.compile(r"([a-z]+\.\d{3}\.\d{3}\.\d{2,3})")


def _normalise(path: str) -> str:
    """Strip indices, namespace prefixes, the Document root and stray slashes."""
    cleaned = _INDEX_RE.sub("", (path or "").strip()).strip("/")
    segments = [s.split(":")[-1] for s in cleaned.split("/") if s]
    if segments and segments[0] == "Document":
        segments = segments[1:]
    return "/".join(segments)


def _message_type_from_name(filename: str) -> str:
    match = _MSG_TYPE_RE.search(filename)
    return match.group(1) if match else ""


@lru_cache(maxsize=None)
def _cached_for_message_type(message_type: str) -> Optional[TargetSchema]:
    from src.connectors.schema_bundle import bundle_files

    for xsd in bundle_files():
        if _message_type_from_name(xsd.name) == message_type:
            return TargetSchema.from_xsd(xsd, message_type)
    log.info("No vendored schema for %s — outline unavailable", message_type)
    return None
