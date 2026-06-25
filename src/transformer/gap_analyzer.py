"""
Identify mandatory ISO 20022 fields that have no source mapping
and classify each gap by severity and recommended resolution.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

# Mandatory fields for pain.001.001.09 with gap metadata
# Format: (iso_xpath, business_label, gap_type, severity, recommendation)
_PAIN001_MANDATORY = [
    (
        "GrpHdr/MsgId",
        "Message Identification",
        "BLOCKING",
        "CRITICAL",
        "Generate a unique UUID at runtime (e.g. str(uuid.uuid4())[:35]). "
        "Must be unique per message.",
    ),
    (
        "GrpHdr/CreDtTm",
        "Creation Date and Time",
        "BLOCKING",
        "CRITICAL",
        "Combine internal CreationDate + CreationTime fields into ISO 8601 "
        "datetime format (YYYY-MM-DDTHH:MM:SS).",
    ),
    (
        "GrpHdr/NbOfTxs",
        "Number of Transactions",
        "ENRICHMENT",
        "HIGH",
        "Map from internal NumberOfPayments field (count of Payment elements "
        "in the Payments block).",
    ),
    (
        "GrpHdr/CtrlSum",
        "Control Sum",
        "ENRICHMENT",
        "HIGH",
        "Map from internal TotalAmount field. Verify currency consistency "
        "across all payments before populating.",
    ),
    (
        "GrpHdr/InitgPty/Nm",
        "Initiating Party Name",
        "ENRICHMENT",
        "HIGH",
        "Map from OrderingCustomer/CompanyName. Max 140 characters.",
    ),
    (
        "PmtInf/PmtInfId",
        "Payment Information Identification",
        "BLOCKING",
        "CRITICAL",
        "Generate from internal BatchRef or derive as "
        "'{InternalRef}-PMTINF-{sequence}'. Must be unique per PmtInf block.",
    ),
    (
        "PmtInf/PmtMtd",
        "Payment Method",
        "ENRICHMENT",
        "HIGH",
        "Always 'TRF' (Credit Transfer) for this message type. "
        "Hard-code as constant in the transformation.",
    ),
    (
        "PmtInf/PmtTpInf/SvcLvl/Cd",
        "Service Level Code",
        "CONDITIONAL",
        "MEDIUM",
        "Derive from internal PaymentType: BACS → 'NURG', "
        "CHAPS → 'URGP', cross-border → 'SEPA' or 'G004'. "
        "Requires business rule decision.",
    ),
    (
        "PmtInf/PmtTpInf/LclInstrm/Cd",
        "Local Instrument Code",
        "CONDITIONAL",
        "MEDIUM",
        "Optional but required by many clearing systems. "
        "Derive from PaymentType: BACS → 'BACS', CHAPS → 'CHAPS'.",
    ),
    (
        "PmtInf/ReqdExctnDt/Dt",
        "Requested Execution Date",
        "ENRICHMENT",
        "HIGH",
        "Map from Payment/ValueDate. Format: YYYY-MM-DD.",
    ),
    (
        "PmtInf/Dbtr/Nm",
        "Debtor Name",
        "ENRICHMENT",
        "HIGH",
        "Map from OrderingCustomer/CompanyName. Max 140 characters.",
    ),
    (
        "PmtInf/DbtrAcct/Id/IBAN",
        "Debtor Account IBAN",
        "ENRICHMENT",
        "HIGH",
        "Derive IBAN from OrderingCustomer/SortCode + AccountNumber "
        "using UK IBAN algorithm (country code GB + check digits + sort code + account). "
        "Requires reference data lookup.",
    ),
    (
        "PmtInf/DbtrAcct/Ccy",
        "Debtor Account Currency",
        "ENRICHMENT",
        "MEDIUM",
        "Map from OrderingCustomer/Currency. ISO 4217 code (e.g. 'GBP').",
    ),
    (
        "PmtInf/DbtrAgt/FinInstnId/BICFI",
        "Debtor Agent BIC",
        "ENRICHMENT",
        "HIGH",
        "Derive BIC from OrderingCustomer/SortCode using sort-code-to-BIC "
        "reference data table. SortCode 20-00-00 → BARCGB22. "
        "Requires reference data service.",
    ),
    (
        "PmtInf/CdtTrfTxInf/PmtId/EndToEndId",
        "End-to-End Identification",
        "ENRICHMENT",
        "HIGH",
        "Map from Payment/PaymentRef. Max 35 characters. "
        "Must be unique end-to-end and echoed in all downstream messages.",
    ),
    (
        "PmtInf/CdtTrfTxInf/Amt/InstdAmt",
        "Instructed Amount",
        "ENRICHMENT",
        "CRITICAL",
        "Map from Payment/Amount. Currency attribute (Ccy) maps from "
        "Payment/Currency. Must be a valid decimal with max 5 fraction digits.",
    ),
    (
        "PmtInf/CdtTrfTxInf/ChrgBr",
        "Charge Bearer",
        "BLOCKING",
        "CRITICAL",
        "No source field in internal message. Business decision required: "
        "SLEV (follow service level), SHAR (shared), DEBT (debtor pays all), "
        "CRED (creditor pays all). SLEV is recommended for SEPA; SHAR for SWIFT.",
    ),
    (
        "PmtInf/CdtTrfTxInf/CdtrAgt/FinInstnId/BICFI",
        "Creditor Agent BIC",
        "ENRICHMENT",
        "HIGH",
        "For domestic UK: derive from Beneficiary/SortCode using reference data. "
        "For international: map from Beneficiary/BIC if present. "
        "Mandatory for cross-border payments.",
    ),
    (
        "PmtInf/CdtTrfTxInf/Cdtr/Nm",
        "Creditor Name",
        "ENRICHMENT",
        "HIGH",
        "Map from Beneficiary/BeneficiaryName. Max 140 characters.",
    ),
    (
        "PmtInf/CdtTrfTxInf/CdtrAcct/Id/IBAN",
        "Creditor Account IBAN",
        "ENRICHMENT",
        "HIGH",
        "For domestic UK: derive IBAN from Beneficiary/SortCode + AccountNumber. "
        "For international: map directly from Beneficiary/AccountNumber if it is "
        "already an IBAN (e.g. NL91ABNA...).",
    ),
    (
        "PmtInf/CdtTrfTxInf/RmtInf/Ustrd",
        "Remittance Information (Unstructured)",
        "ENRICHMENT",
        "MEDIUM",
        "Map from Payment/RemittanceInfo. Max 140 characters. "
        "Truncate if longer.",
    ),
]

_MANDATORY_BY_TYPE = {
    "pain.001.001.09": _PAIN001_MANDATORY,
}


@dataclass
class GapEntry:
    iso_xpath: str
    business_label: str
    gap_type: str       # BLOCKING | ENRICHMENT | CONDITIONAL | OUT_OF_SCOPE
    severity: str       # CRITICAL | HIGH | MEDIUM | LOW
    recommendation: str
    is_resolved: bool = False   # True if mapping found


def analyze(mappings: list, target_message_type: str) -> List[GapEntry]:
    """
    Cross-reference mapped fields against mandatory ISO 20022 fields.
    Returns gap entries for mandatory fields that have no DIRECT mapping.
    """
    base_type = ".".join(target_message_type.split(".")[:2])
    mandatory = _MANDATORY_BY_TYPE.get(target_message_type) or \
                _MANDATORY_BY_TYPE.get(base_type + ".001.09", _PAIN001_MANDATORY)

    # Build set of ISO xpaths that are already mapped (non-UNMAPPED)
    mapped_iso_xpaths = {
        m.iso20022_xpath.split("/")[-1]
        for m in mappings
        if m.mapping_type != "UNMAPPED" and m.iso20022_xpath
    }
    mapped_labels = {
        m.iso20022_element.lower()
        for m in mappings
        if m.mapping_type != "UNMAPPED" and m.iso20022_element
    }

    gaps: List[GapEntry] = []
    for iso_xpath, label, gap_type, severity, recommendation in mandatory:
        leaf = iso_xpath.split("/")[-1].lower()
        already_mapped = (
            leaf in {x.lower() for x in mapped_iso_xpaths}
            or label.lower() in mapped_labels
            or any(leaf in m.iso20022_xpath.lower() for m in mappings if m.mapping_type != "UNMAPPED")
        )
        gaps.append(GapEntry(
            iso_xpath=iso_xpath,
            business_label=label,
            gap_type=gap_type if not already_mapped else "ENRICHMENT",
            severity=severity if not already_mapped else "LOW",
            recommendation=recommendation,
            is_resolved=already_mapped,
        ))

    return gaps
