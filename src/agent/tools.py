"""
LangChain tools exposed to the SwiftSage expert agent.

Each tool wraps a capability from the comparator / connector / storage /
transformer layers and returns a plain-text result that Claude can reason over.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

from config.settings import settings
from src.comparator.xml_comparator import XMLComparator
from src.connectors.iso20022_connector import ISO20022Connector
from src.storage.standards_library import StandardsLibrary
from src.utils.helpers import (
    detect_namespace,
    get_logger,
    message_family_from_type,
    message_type_from_namespace,
    safe_read_xml,
)

log = get_logger(__name__)

# ── Shared singletons (initialised lazily) ────────────────────────────────────
_library: Optional[StandardsLibrary] = None
_connector: Optional[ISO20022Connector] = None
_comparator: Optional[XMLComparator] = None


def _get_library() -> StandardsLibrary:
    global _library
    if _library is None:
        _library = StandardsLibrary(settings.standards_library_path)
    return _library


def _get_connector() -> ISO20022Connector:
    global _connector
    if _connector is None:
        _connector = ISO20022Connector(library=_get_library())
    return _connector


def _get_comparator() -> XMLComparator:
    global _comparator
    if _comparator is None:
        _comparator = XMLComparator(ignore_tags=settings.benign_patterns)
    return _comparator


# ── Tools ──────────────────────────────────────────────────────────────────────

@tool
def validate_xml(xml_path: str, schema_path: str = "") -> str:
    """
    Validate an ISO 20022 XML file against its XSD schema.

    Args:
        xml_path:    Path to the XML file to validate.
        schema_path: Path to the XSD schema.  If empty, tries to locate the
                     schema automatically from the Standards Library.

    Returns:
        Validation result: "VALID" or a list of errors.
    """
    from lxml import etree
    from src.utils.helpers import load_schema

    root = safe_read_xml(xml_path)
    if root is None:
        return f"ERROR: Cannot parse XML at {xml_path}"

    # Auto-detect schema from namespace if not provided
    if not schema_path:
        ns = detect_namespace(xml_path)
        msg_type = message_type_from_namespace(ns or "") if ns else None
        if msg_type:
            p = _get_connector().fetch_schema_for_message(msg_type)
            if p:
                schema_path = str(p)

    if not schema_path or not Path(schema_path).exists():
        return (
            "Schema not found — XML parsed successfully but not validated against XSD.\n"
            f"Detected namespace: {detect_namespace(xml_path)}"
        )

    schema = load_schema(schema_path)
    if schema is None:
        return f"ERROR: Cannot load schema {schema_path}"

    valid = schema.validate(root)
    errors = [str(e) for e in schema.error_log]
    if valid:
        return "VALID — XML conforms to the schema."
    return "INVALID — Errors:\n" + "\n".join(f"  • {e}" for e in errors)


@tool
def compare_xml_messages(
    xml_path_a: str,
    xml_path_b: str,
    schema_path: str = "",
    output_format: str = "text",
) -> str:
    """
    Semantically compare two ISO 20022 XML instances.

    Ignores benign differences (message IDs, timestamps, correlation refs).
    Classifies each difference as BREAKING / WARNING / BENIGN / INFO.

    Args:
        xml_path_a:    Path to the baseline XML file (e.g. version 1).
        xml_path_b:    Path to the new XML file (e.g. version 2).
        schema_path:   Optional XSD path for pre-comparison validation.
        output_format: "text" (human report) | "json" (structured diff).

    Returns:
        Diff report with breaking-change score.
    """
    cmp = _get_comparator()
    sp = schema_path if schema_path and Path(schema_path).exists() else None
    result = cmp.compare(xml_path_a, xml_path_b, schema_path=sp)

    if output_format == "json":
        return result.to_json()
    return result.human_report()


@tool
def batch_compare_xml_folders(
    folder_a: str,
    folder_b: str,
    schema_path: str = "",
) -> str:
    """
    Compare all matching XML files across two folders.

    Reports the top-20 recurring diff patterns and a per-file summary table.

    Args:
        folder_a:    Path to the baseline folder.
        folder_b:    Path to the new folder.
        schema_path: Optional XSD path for validation.

    Returns:
        Batch comparison report.
    """
    if not Path(folder_a).is_dir():
        return f"ERROR: {folder_a} is not a directory"
    if not Path(folder_b).is_dir():
        return f"ERROR: {folder_b} is not a directory"

    cmp = _get_comparator()
    sp = schema_path if schema_path and Path(schema_path).exists() else None
    batch = cmp.compare_folders(folder_a, folder_b, schema_path=sp)

    lines = [
        f"Batch comparison: {folder_a}  vs  {folder_b}",
        f"Files compared: {len(batch.results)}",
        "",
        batch.summary_table(),
    ]
    if batch.top_patterns:
        lines.append("\nTop recurring diff patterns:")
        for p in batch.top_patterns:
            lines.append(f"  {p['count']:>4}×  {p['pattern']}")
    return "\n".join(lines)


@tool
def fetch_iso20022_schemas(message_sets: str = "pain,pacs,camt") -> str:
    """
    Download / sync the latest ISO 20022 XSD schemas from the official repo.

    Args:
        message_sets: Comma-separated list of message sets to sync
                      (e.g. "pain,pacs,camt").

    Returns:
        Sync report with counts of added / skipped artifacts.
    """
    sets = [s.strip() for s in message_sets.split(",") if s.strip()]
    connector = _get_connector()
    result = connector.sync(message_sets=sets)
    return json.dumps(result, indent=2)


@tool
def list_standards_library(
    message_set: str = "",
    artifact_type: str = "",
) -> str:
    """
    List artifacts currently in the local Standards Library.

    Args:
        message_set:   Filter by message set (e.g. "pain", "camt").  Empty = all.
        artifact_type: Filter by type (e.g. "xsd", "sample").  Empty = all.

    Returns:
        Summary table of matching artifacts.
    """
    library = _get_library()
    ms = message_set.strip() or None
    at = artifact_type.strip() or None
    artifacts = library.list_artifacts(message_set=ms, artifact_type=at)

    if not artifacts:
        return "No artifacts found matching the filter."

    lines = [f"{'ID':<50} {'Type':<8} {'Version':<12} {'Retrieved'}", "-" * 100]
    for a in artifacts:
        lines.append(
            f"{a.artifact_id:<50} {a.artifact_type:<8} {a.version:<12} {a.retrieved_at[:10]}"
        )
    lines.append(f"\nTotal: {len(artifacts)}")
    return "\n".join(lines)


@tool
def detect_message_type(xml_path: str) -> str:
    """
    Detect the ISO 20022 message type of an XML file from its namespace.

    Args:
        xml_path: Path to the XML file.

    Returns:
        Message type (e.g. "pain.001.001.12") and business domain.
    """
    root = safe_read_xml(xml_path)
    if root is None:
        return f"ERROR: Cannot parse {xml_path}"

    ns = root.nsmap.get(None) or ""
    msg_type = message_type_from_namespace(ns)
    family = message_family_from_type(msg_type or "") if msg_type else None

    if msg_type:
        return (
            f"Message type : {msg_type}\n"
            f"Business domain: {family or 'Unknown'}\n"
            f"Namespace : {ns}"
        )
    return f"Could not detect ISO 20022 message type from namespace: {ns}"


@tool
def generate_test_cases(
    xml_path_a: str,
    xml_path_b: str,
    schema_path: str = "",
) -> str:
    """
    Generate a set of recommended regression test cases based on the diff
    between two XML instances.

    For each BREAKING or WARNING difference, produces a test case description
    covering: what to test, expected behaviour, and suggested assertion.

    Args:
        xml_path_a:  Baseline XML path.
        xml_path_b:  New XML path.
        schema_path: Optional XSD path.

    Returns:
        Markdown-formatted test case list.
    """
    cmp = _get_comparator()
    sp = schema_path if schema_path and Path(schema_path).exists() else None
    result = cmp.compare(xml_path_a, xml_path_b, schema_path=sp)

    significant = result.breaking + result.warnings
    if not significant:
        return "No significant differences found — no new test cases recommended."

    lines = ["# Recommended Regression Test Cases\n"]
    lines.append(
        f"Based on comparison of `{Path(xml_path_a).name}` vs `{Path(xml_path_b).name}`"
        f" (score {result.breaking_score}/100)\n"
    )

    for i, diff in enumerate(significant, 1):
        tag = diff.xpath.split("/")[-1].split("[")[0]
        lines.append(f"## TC-{i:03d}: [{diff.severity.value}] {tag}")
        lines.append(f"**XPath:** `{diff.xpath}`")
        lines.append(f"**Change:** {diff.change_type.value}")
        if diff.old_value:
            lines.append(f"**Old value:** `{diff.old_value}`")
        if diff.new_value:
            lines.append(f"**New value:** `{diff.new_value}`")
        lines.append(f"**What to test:** {diff.explanation}")
        lines.append(
            "**Suggested assertion:** Verify that downstream system handles "
            f"`{tag}` {diff.change_type.value} without errors.\n"
        )

    return "\n".join(lines)


# ── Transformation Advisor Tools ──────────────────────────────────────────────

@tool
def analyze_internal_message(xml_content: str) -> str:
    """
    Parse a bank's internal XML payment message and extract a structured
    field inventory suitable for ISO 20022 mapping.

    Args:
        xml_content: Raw XML string of the internal bank message.

    Returns:
        Field inventory table (xpath, value for each element).
    """
    from src.transformer.message_parser import parse_xml_fields, fields_to_summary
    try:
        fields = parse_xml_fields(xml_content)
        return fields_to_summary(fields)
    except Exception as exc:
        return f"ERROR parsing internal message: {exc}"


@tool
def map_to_iso20022(xml_content: str, target_message_type: str = "pain.001.001.09") -> str:
    """
    Map fields from a bank's internal XML message to their ISO 20022 equivalents.

    Uses Claude's ISO 20022 domain knowledge to reason about each field's
    business meaning and identify the correct target element, mapping type
    (DIRECT / DERIVED / SPLIT / COMBINED / UNMAPPED), and confidence level.

    Args:
        xml_content:         Raw XML string of the internal bank message.
        target_message_type: Target ISO 20022 message type (default: pain.001.001.09).

    Returns:
        JSON mapping table with source field, ISO 20022 target, mapping type,
        confidence, and business rule for each field.
    """
    import json
    from src.transformer.message_parser import parse_xml_fields
    from src.transformer.field_mapper import FieldMapper
    try:
        fields = parse_xml_fields(xml_content)
        mapper = FieldMapper()
        mappings = mapper.map(fields, target_message_type)
        result = [
            {
                "source_field":    m.source_field,
                "source_xpath":    m.source_xpath,
                "source_value":    m.source_value,
                "iso20022_target": m.iso20022_element or m.iso20022_xpath,
                "mapping_type":    m.mapping_type,
                "confidence":      m.confidence,
                "business_rule":   m.business_rule,
                "notes":           m.notes,
            }
            for m in mappings
        ]
        return json.dumps(result, indent=2)
    except Exception as exc:
        return f"ERROR during mapping: {exc}"


@tool
def identify_gaps(xml_content: str, target_message_type: str = "pain.001.001.09") -> str:
    """
    Identify mandatory ISO 20022 fields that have no source mapping
    in the internal message and classify each gap by severity.

    Gap types:
      BLOCKING    — message will be rejected without this field (must resolve before build)
      ENRICHMENT  — field can be derived or defaulted (needs business rule)
      CONDITIONAL — field required only under certain conditions
      OUT_OF_SCOPE — internal field with no ISO 20022 equivalent

    Args:
        xml_content:         Raw XML string of the internal bank message.
        target_message_type: Target ISO 20022 message type (default: pain.001.001.09).

    Returns:
        Gap register table with ISO field, gap type, severity, and recommendation.
    """
    import json
    from src.transformer.message_parser import parse_xml_fields
    from src.transformer.field_mapper import FieldMapper
    from src.transformer import gap_analyzer
    try:
        fields = parse_xml_fields(xml_content)
        mapper = FieldMapper()
        mappings = mapper.map(fields, target_message_type)
        gaps = gap_analyzer.analyze(mappings, target_message_type)
        open_gaps = [g for g in gaps if not g.is_resolved]
        result = [
            {
                "iso_field":      g.iso_xpath,
                "business_label": g.business_label,
                "gap_type":       g.gap_type,
                "severity":       g.severity,
                "recommendation": g.recommendation,
            }
            for g in open_gaps
        ]
        summary = (
            f"Total gaps: {len(open_gaps)}  |  "
            f"BLOCKING: {sum(1 for g in open_gaps if g.gap_type=='BLOCKING')}  |  "
            f"ENRICHMENT: {sum(1 for g in open_gaps if g.gap_type=='ENRICHMENT')}  |  "
            f"CONDITIONAL: {sum(1 for g in open_gaps if g.gap_type=='CONDITIONAL')}"
        )
        return summary + "\n\n" + json.dumps(result, indent=2)
    except Exception as exc:
        return f"ERROR during gap analysis: {exc}"


@tool
def generate_transform_requirements(
    xml_content: str,
    target_message_type: str = "pain.001.001.09",
    output_path: str = "",
) -> str:
    """
    Generate a complete Transformation Requirements Document (.docx) mapping
    a bank's internal message to an ISO 20022 target message type.

    The document includes:
      - Executive summary with complexity rating
      - Field mapping table (DIRECT / DERIVED / SPLIT / COMBINED / UNMAPPED)
      - Gap register (BLOCKING / ENRICHMENT / CONDITIONAL gaps)
      - Unmapped internal fields register
      - Open questions for business decision
      - Recommended next steps

    Args:
        xml_content:         Raw XML string of the internal bank message.
        target_message_type: Target ISO 20022 message type (default: pain.001.001.09).
        output_path:         File path to write the .docx (optional).

    Returns:
        Summary of the generated document content.
    """
    from src.transformer.message_parser import parse_xml_fields
    from src.transformer.field_mapper import FieldMapper
    from src.transformer import gap_analyzer
    from src.transformer.requirements_generator import generate_requirements_doc
    try:
        fields = parse_xml_fields(xml_content)
        mapper = FieldMapper()
        mappings = mapper.map(fields, target_message_type)
        gaps = gap_analyzer.analyze(mappings, target_message_type)
        doc_bytes = generate_requirements_doc(mappings, gaps, target_message_type)

        if output_path:
            Path(output_path).write_bytes(doc_bytes)
            saved = f" Saved to: {output_path}"
        else:
            saved = " (use the Transform Advisor tab to download the .docx)"

        direct   = sum(1 for m in mappings if m.mapping_type == "DIRECT")
        derived  = sum(1 for m in mappings if m.mapping_type == "DERIVED")
        unmapped = sum(1 for m in mappings if m.mapping_type == "UNMAPPED")
        blocking = sum(1 for g in gaps if g.gap_type == "BLOCKING" and not g.is_resolved)

        return (
            f"Transformation Requirements Document generated.{saved}\n"
            f"  Fields analysed : {len(mappings)}\n"
            f"  DIRECT mappings : {direct}\n"
            f"  DERIVED mappings: {derived}\n"
            f"  UNMAPPED fields : {unmapped}\n"
            f"  BLOCKING gaps   : {blocking}\n"
            f"  Total gaps      : {len([g for g in gaps if not g.is_resolved])}"
        )
    except Exception as exc:
        return f"ERROR generating requirements document: {exc}"


@tool
def explain_message_flow(message_type: str) -> str:
    """
    Explain the ISO 20022 business process flow for a given message type,
    including roles, steps, and downstream messages.

    This tool returns embedded domain knowledge — use it to answer questions
    like "What is pacs.008 used for?" or "What messages follow a pain.001?".

    Args:
        message_type: ISO 20022 message type (e.g. "pacs.008", "pain.001").

    Returns:
        Business process explanation with flow diagram in text form.
    """
    # Embedded ISO 20022 domain knowledge
    flows: dict[str, str] = {
        "pain.001": textwrap.dedent("""\
            ## pain.001 — Customer Credit Transfer Initiation

            **Roles:** Debtor (Ordering Customer) → Debtor Agent (Bank)

            **Purpose:** The debtor instructs its bank to execute one or more
            credit transfers on its behalf.

            **Typical flow:**
            1. Corporate/debtor creates pain.001 with payment details
            2. Sends to Debtor Agent (bank)
            3. Debtor Agent validates and executes; may forward as pacs.008
            4. On completion/rejection:
               - pain.002 (Payment Status Report) returned to debtor
               - camt.054 (Bank-to-Customer Debit/Credit Notification) sent

            **Key fields:** MsgId, PmtInfId, PmtMtd, ReqdExctnDt,
            DbtrAcct, CdtrAcct, InstdAmt

            **Downstream messages:** pacs.008, pain.002, camt.054
        """),
        "pacs.008": textwrap.dedent("""\
            ## pacs.008 — FI-to-FI Customer Credit Transfer

            **Roles:** Instructing Agent → Instructed Agent (interbank)

            **Purpose:** Moves funds between financial institutions as part of
            a customer credit transfer chain.  Often initiated by a pain.001.

            **Typical flow:**
            1. Debtor Agent issues pacs.008 to next agent (or CSM)
            2. Message may chain through multiple correspondent banks
            3. Each leg acknowledges via pacs.002
            4. On final credit: camt.054 to beneficiary bank

            **Key fields:** MsgId, IntrBkSttlmAmt, IntrBkSttlmDt,
            DbtrAgt, CdtrAgt, EndToEndId, UETR

            **Downstream messages:** pacs.002, camt.054, camt.056 (recall)
        """),
        "pacs.002": textwrap.dedent("""\
            ## pacs.002 — Payment Status Report

            **Roles:** Instructed Agent → Instructing Agent (or Debtor)

            **Purpose:** Reports the processing status of a payment —
            accepted, pending, or rejected.

            **Key statuses:** ACSC (AcceptedSettlementCompleted),
            RJCT (Rejected), PDNG (Pending), ACCP (AcceptedCustomerProfile)

            **Downstream:** camt.029 (Resolution of Investigation) if RJCT
        """),
        "camt.053": textwrap.dedent("""\
            ## camt.053 — Bank-to-Customer Statement

            **Roles:** Account Servicer → Account Owner

            **Purpose:** Provides a detailed end-of-period statement of
            transactions on a customer's account.

            **Key fields:** Stmt/Id, Stmt/CreDtTm, Stmt/Acct, Ntry (entries)

            **Upstream messages:** pacs.008, pacs.004, pacs.009
        """),
        "camt.056": textwrap.dedent("""\
            ## camt.056 — FI-to-FI Payment Cancellation Request

            **Roles:** Instructing Agent → Instructed Agent

            **Purpose:** Request to cancel a previously sent payment.
            Originates from a pain.007 (Customer Payment Reversal) or
            directly from a bank.

            **Downstream:** camt.029 (Resolution of Investigation)
        """),
        "camt.029": textwrap.dedent("""\
            ## camt.029 — Resolution of Investigation

            **Purpose:** Final answer to a cancellation (camt.056) or
            investigation (camt.027) request.

            **Key statuses:** CNCL (Cancelled), RJCR (Rejected),
            CWFW (Cancellation Will Follow)
        """),
    }

    # Normalize — accept both "pain.001" and "pain.001.001.12"
    key = ".".join(message_type.split(".")[:2])
    explanation = flows.get(key)
    if explanation:
        return explanation

    # Fallback for unknown types
    family = message_family_from_type(message_type)
    if family:
        return (
            f"**{message_type}** belongs to the **{family}** message set.\n\n"
            "Detailed flow not yet in the knowledge base.  Use "
            "`fetch_iso20022_schemas` to download the MUG/MDR for this "
            "message set, then ask me to summarize it."
        )
    return (
        f"'{message_type}' is not a recognised ISO 20022 message type prefix.\n"
        "Valid prefixes: pain, pacs, camt, acmt, auth, reda, colr, sese, seev."
    )
