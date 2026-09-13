"""
Retrieval over the vendored ISO 20022 schemas, for grounded chat answers.

Chat previously answered from model recall alone, so a confident-sounding reply
could name an element that does not exist in the version the bank is migrating
to — the failure mode a BA has no way to spot. This index makes the standards
library searchable: it flattens every vendored XSD through `TargetSchema` and
matches a business phrase ("beneficiary bank", "charges") or an ISO short name
("CdtrAgt") onto real declarations, each carrying the message version and the
schema file it came from so the answer can cite its source.

Structural facts (path, occurrence, type, constraints, code lists) come from the
XSD; the business label and definition come from `iso_glossary`. A hit says
which of the two it has, so an element with no curated definition is reported as
structure only instead of being filled in by the model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from src.storage.iso_glossary import GlossaryEntry, lookup as glossary_lookup
from src.transformer.target_schema import SchemaNode, TargetSchema
from src.utils.helpers import get_logger, message_family_from_type

log = get_logger(__name__)

_MSG_TYPE_RE = re.compile(r"([a-z]+\.\d{3}\.\d{3}\.\d{2,3})")
_MAX_CODES = 12

# Match scores, highest first. Ordering matters more than the absolute values:
# an exact ISO short name should always beat a business-phrase substring.
_EXACT_NAME = 100
_EXACT_PATH = 95
_EXACT_TERM = 90
_NAME_PREFIX = 70
_NAME_SUBSTR = 55
_TERM_SUBSTR = 45
_PATH_SUBSTR = 25


@dataclass(frozen=True)
class ElementHit:
    """One element declaration found in a specific message version."""

    message_type: str
    schema_file: str
    node: SchemaNode
    glossary: Optional[GlossaryEntry]
    score: int = 0

    @property
    def business_label(self) -> str:
        return self.glossary.label if self.glossary else self.node.name

    def citation(self) -> str:
        """Where this fact comes from — message version and schema file."""
        return f"{self.message_type} · {self.node.path} · {self.schema_file}"

    def render(self) -> str:
        """Grounded description of the element, business meaning first."""
        lines = [f"{self.business_label} ({self.node.name})"]
        if self.glossary:
            lines.append(f"  Business meaning : {self.glossary.definition}")
        else:
            lines.append(
                "  Business meaning : not in the curated glossary — the "
                "structure below is from the schema; say so rather than "
                "asserting a definition."
            )
        lines.append(f"  Message version  : {self.message_type}"
                     f" ({message_family_from_type(self.message_type) or 'unknown domain'})")
        lines.append(f"  Path             : {self.node.path}")
        lines.append(
            f"  Occurrence       : {self.node.occurrence}"
            f"{' — one of a choice' if self.node.in_choice else ''}"
            f" ({'mandatory' if self.node.mandatory else 'optional'}"
            f"{', repeatable' if self.node.repeatable else ''})"
        )
        if self.node.type_name:
            lines.append(f"  Type             : {self.node.type_name}")
        if self.node.constraint:
            lines.append(f"  Constraints      : {self.node.constraint}")
        if self.node.codes:
            shown = ", ".join(self.node.codes[:_MAX_CODES])
            if len(self.node.codes) > _MAX_CODES:
                shown += f", … ({len(self.node.codes)} codes in total)"
            lines.append(f"  Allowed codes    : {shown}")
        lines.append(f"  Source           : {self.citation()}")
        return "\n".join(lines)


@dataclass(frozen=True)
class VersionPresence:
    """Whether an element appears in one message version, and how."""

    message_type: str
    hit: Optional[ElementHit]

    @property
    def present(self) -> bool:
        return self.hit is not None

    def describe(self) -> str:
        if self.hit is None:
            return f"{self.message_type}: absent — no element of this name in the schema"
        node = self.hit.node
        detail = f"{node.path} {node.occurrence}"
        if node.type_name:
            detail += f", {node.type_name}"
        return f"{self.message_type}: present — {detail}"


class SchemaIndex:
    """Searchable view over every vendored ISO 20022 schema."""

    def __init__(self, schemas: dict[str, tuple[TargetSchema, str]]):
        self._schemas = schemas

    # ── Construction ───────────────────────────────────────────────────────

    @classmethod
    def load(cls) -> "SchemaIndex":
        """Index of the vendored bundle (cached — the outlines are not cheap)."""
        return _cached_index()

    @classmethod
    def from_files(cls, xsd_paths: list[Path]) -> "SchemaIndex":
        schemas: dict[str, tuple[TargetSchema, str]] = {}
        for path in xsd_paths:
            match = _MSG_TYPE_RE.search(path.name)
            if not match:
                continue
            message_type = match.group(1)
            outline = TargetSchema.from_xsd(path, message_type)
            if outline is None:
                continue
            schemas[message_type] = (outline, path.name)
        log.info("Schema index built over %d message versions", len(schemas))
        return cls(schemas)

    # ── Queries ────────────────────────────────────────────────────────────

    def message_types(self) -> list[str]:
        return sorted(self._schemas)

    def search(
        self, query: str, message_type: str = "", limit: int = 6
    ) -> list[ElementHit]:
        """
        Elements matching *query*, which may be an ISO short name, a path
        fragment or a business phrase. Restricted to *message_type* when given,
        otherwise the best match per message version is returned so the caller
        can see how the element differs across versions.
        """
        needle = (query or "").strip().lower().lstrip("@")
        if not needle:
            return []

        scoped = self._scope(message_type)
        hits: list[ElementHit] = []
        for msg_type, (outline, filename) in scoped.items():
            for node in outline.nodes:
                score = _score(node, needle)
                if score:
                    hits.append(
                        ElementHit(
                            message_type=msg_type,
                            schema_file=filename,
                            node=node,
                            glossary=glossary_lookup(node.name),
                            score=score,
                        )
                    )

        hits.sort(key=lambda h: (-h.score, h.node.path.count("/"), len(h.node.path)))
        return _dedupe(hits)[:limit]

    def versions_of(self, query: str, message_type: str = "") -> list[VersionPresence]:
        """
        How the element behind *query* appears in each version of its family —
        the material needed to answer "did this change between versions?"
        without guessing.
        """
        best = self.search(query, message_type=message_type, limit=1)
        if not best:
            return []
        name = best[0].node.name
        family = best[0].message_type.split(".")[0]

        presences: list[VersionPresence] = []
        for msg_type in sorted(self._schemas):
            if msg_type.split(".")[0] != family:
                continue
            outline, filename = self._schemas[msg_type]
            node = _by_name(outline, name)
            hit = (
                ElementHit(
                    message_type=msg_type,
                    schema_file=filename,
                    node=node,
                    glossary=glossary_lookup(node.name),
                    score=_EXACT_NAME,
                )
                if node is not None
                else None
            )
            presences.append(VersionPresence(message_type=msg_type, hit=hit))
        return presences

    # ── Internals ──────────────────────────────────────────────────────────

    def _scope(self, message_type: str) -> dict[str, tuple[TargetSchema, str]]:
        wanted = (message_type or "").strip().lower()
        if not wanted:
            return self._schemas
        exact = self._schemas.get(wanted)
        if exact:
            return {wanted: exact}
        # Accept a prefix such as "pain.001" or a family such as "camt"
        return {
            m: v for m, v in self._schemas.items() if m.startswith(wanted)
        } or self._schemas


def _score(node: SchemaNode, needle: str) -> int:
    name = node.name.lower()
    path = node.path.lower()
    if name == needle:
        return _EXACT_NAME
    if path == needle or path.endswith(f"/{needle}"):
        return _EXACT_PATH

    terms = tuple(t for t in _terms(node.name) if t)
    if needle in terms:
        return _EXACT_TERM
    if name.startswith(needle) and len(needle) >= 3:
        return _NAME_PREFIX
    if len(needle) >= 3 and needle in name:
        return _NAME_SUBSTR
    if len(needle) >= 4 and any(needle in t for t in terms):
        return _TERM_SUBSTR
    if len(needle) >= 4 and needle in path:
        return _PATH_SUBSTR
    return 0


def _terms(name: str) -> tuple[str, ...]:
    entry = glossary_lookup(name)
    if entry is None:
        return ()
    return (entry.label.lower(), *(a.lower() for a in entry.aliases))


def _by_name(outline: TargetSchema, name: str) -> Optional[SchemaNode]:
    matches = [n for n in outline.nodes if n.name.lower() == name.lower()]
    if not matches:
        return None
    return min(matches, key=lambda n: (n.path.count("/"), len(n.path)))


def _dedupe(hits: list[ElementHit]) -> list[ElementHit]:
    seen: set[tuple[str, str]] = set()
    out: list[ElementHit] = []
    for hit in hits:
        key = (hit.message_type, hit.node.path)
        if key in seen:
            continue
        seen.add(key)
        out.append(hit)
    return out


@lru_cache(maxsize=1)
def _cached_index() -> SchemaIndex:
    from src.connectors.schema_bundle import bundle_files

    return SchemaIndex.from_files(bundle_files())
