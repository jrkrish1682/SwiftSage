"""
Check every proposed ISO 20022 XPath against the target schema.

A mapping table is only useful to a development team if the target paths exist.
The mapper is an LLM, so it can propose an element that belongs to a different
version of the message, sits at the wrong level, or simply does not exist. Each
mapping is therefore resolved against the vendored XSD outline: exact hits are
confirmed, an element found at a different path is flagged and downgraded, and
an element the schema does not declare at all is downgraded to LOW confidence
with the reason recorded, so the requirements document never presents an
unverifiable path as high confidence.
"""
from __future__ import annotations

from typing import Iterable, List, Optional

from src.transformer.target_schema import (
    RENAMED,
    RESOLVED,
    UNCHECKED,
    UNRESOLVED,
    TargetSchema,
)
from src.utils.helpers import get_logger

log = get_logger(__name__)

_DOWNGRADE = {"HIGH": "MEDIUM", "MEDIUM": "LOW", "LOW": "LOW"}


def validate(
    mappings: Iterable, target_message_type: str,
    schema: Optional[TargetSchema] = None,
) -> List:
    """
    Annotate *mappings* in place with their validation status and return them.
    Mappings are left untouched when no schema is available for the target.
    """
    schema = schema or TargetSchema.for_message_type(target_message_type)
    result = list(mappings)
    if schema is None:
        for m in result:
            m.validation = UNCHECKED
            m.validation_note = (
                f"No vendored schema for {target_message_type} — path not verified."
            )
        return result

    for m in result:
        if m.mapping_type == "UNMAPPED" or not m.iso20022_xpath:
            m.validation = UNCHECKED
            m.validation_note = ""
            continue

        status, node = schema.resolve(m.iso20022_xpath)
        m.validation = status
        if status == RESOLVED and node is not None:
            m.resolved_xpath = node.path
            m.validation_note = ""
            if node.codes and m.source_value:
                m.validation_note = _code_note(node.codes, m.source_value)
        elif status == RENAMED and node is not None:
            m.resolved_xpath = node.path
            m.confidence = _DOWNGRADE.get(m.confidence, "LOW")
            m.validation_note = (
                f"Element exists in {schema.message_type} at {node.path}, not at "
                f"the proposed path — confirm the target level before build."
            )
        else:
            m.resolved_xpath = ""
            m.confidence = "LOW"
            m.validation_note = (
                f"{m.iso20022_xpath} is not declared in {schema.message_type} — "
                "the path needs review by an ISO 20022 specialist."
            )

    counts = summarise(result)
    log.info(
        "Mapping validation against %s: %s",
        schema.message_type,
        ", ".join(f"{k}={v}" for k, v in counts.items()),
    )
    return result


def summarise(mappings: Iterable) -> dict[str, int]:
    """Count of mappings per validation status."""
    counts = {RESOLVED: 0, RENAMED: 0, UNRESOLVED: 0, UNCHECKED: 0}
    for m in mappings:
        status = getattr(m, "validation", UNCHECKED) or UNCHECKED
        counts[status] = counts.get(status, 0) + 1
    return counts


def _code_note(codes: tuple[str, ...], value: str) -> str:
    """Warn when a mapped value is outside the target element's code list."""
    candidate = (value or "").strip().upper()
    if not candidate or candidate in codes:
        return ""
    return (
        f"Source value '{value}' is not one of the permitted codes "
        f"({', '.join(codes[:8])}) — a conversion rule is required."
    )
