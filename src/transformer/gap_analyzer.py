"""
Identify mandatory ISO 20022 fields that have no source mapping
and classify each gap by severity and recommended resolution.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from src.transformer.target_schema import TargetSchema

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

# Mandatory fields for tsrv.001.001.01 (Undertaking Issuance — MT 760 equivalent)
_TSRV001_MANDATORY = [
    (
        "UdrtkgIssncDtls/Id",
        "Undertaking Identification",
        "ENRICHMENT",
        "CRITICAL",
        "Map from the internal guarantee reference (e.g. MessageHeader/"
        "InternalRef). Max 35 characters and unique per undertaking.",
    ),
    (
        "UdrtkgIssncDtls/Nm",
        "Undertaking Name",
        "CONDITIONAL",
        "CRITICAL",
        "Code list of two values only: DGAR (demand guarantee) or STBY "
        "(standby letter of credit). Derive from the internal product code; "
        "any other product must be excluded from scope.",
    ),
    (
        "UdrtkgIssncDtls/IssncTp",
        "Issuance Type",
        "CONDITIONAL",
        "HIGH",
        "ISSU for a straight issuance, ISCO/ISAD for issuance of a "
        "counter-guarantee, CRQL/CRQC for a request to a correspondent. "
        "Derive from the internal issue mode — business rule decision.",
    ),
    (
        "UdrtkgIssncDtls/Issr",
        "Issuer (issuing bank)",
        "ENRICHMENT",
        "HIGH",
        "Map from the issuing branch. Name plus BIC under Id/OrgId/AnyBIC; "
        "an 8-character BIC must be padded to 11 with 'XXX'.",
    ),
    (
        "UdrtkgIssncDtls/Bnfcry",
        "Beneficiary",
        "ENRICHMENT",
        "CRITICAL",
        "Map name and address from the internal beneficiary block. Repeatable "
        "in ISO 20022 — decide whether multiple beneficiaries are supported.",
    ),
    (
        "UdrtkgIssncDtls/DtOfIssnc",
        "Date of Issuance",
        "ENRICHMENT",
        "HIGH",
        "Map from the internal issue date. Format YYYY-MM-DD, no time part.",
    ),
    (
        "UdrtkgIssncDtls/UdrtkgAmt/Amt",
        "Undertaking Amount",
        "ENRICHMENT",
        "CRITICAL",
        "Map the guarantee amount; the Ccy attribute takes the ISO 4217 "
        "currency. Tolerances map to PlusTlrnce / MnsTlrnce as percentages, "
        "not amounts.",
    ),
    (
        "UdrtkgIssncDtls/XpryDtls/XpryTerms/DtTm/Dt",
        "Expiry Date",
        "ENRICHMENT",
        "CRITICAL",
        "Map from the internal expiry date. If the guarantee expires on an "
        "event rather than a date, populate XpryTerms/Cond instead — "
        "open-ended guarantees need a business decision.",
    ),
    (
        "UdrtkgIssncDtls/GovncRulesAndLaw/RuleId/Cd",
        "Governing Rules",
        "CONDITIONAL",
        "CRITICAL",
        "Code list: URDG (URDG 758), ISPR (ISP98), UCPR (UCP 600), NONE. "
        "Internal free-text values such as 'URDG758' must be normalised; "
        "unknown rule sets map to Prtry.",
    ),
    (
        "UdrtkgIssncDtls/GovncRulesAndLaw/AplblLaw",
        "Applicable Law",
        "ENRICHMENT",
        "HIGH",
        "Map the governing law country (Ctry) and free text (Txt) from the "
        "internal governing-law clause.",
    ),
    (
        "UdrtkgIssncDtls/UdrtkgTermsAndConds/Txt",
        "Undertaking Terms and Conditions",
        "ENRICHMENT",
        "CRITICAL",
        "Map the guarantee wording. Narrative1/Txt is Max20000Text and "
        "repeatable — split long wording across occurrences rather than "
        "truncating, and keep Tp coded (e.g. TERM).",
    ),
    (
        "UdrtkgIssncDtls/Applcnt",
        "Applicant",
        "ENRICHMENT",
        "HIGH",
        "Optional in the schema but expected by beneficiaries: map the "
        "internal applicant name, address and BIC where held.",
    ),
    (
        "UdrtkgIssncDtls/AdvsgPty",
        "Advising Party",
        "CONDITIONAL",
        "MEDIUM",
        "Populate when the undertaking is advised through a correspondent. "
        "Requires the advising bank BIC from the internal delivery "
        "instructions.",
    ),
    (
        "UdrtkgIssncDtls/UndrlygTx",
        "Underlying Trade Transaction",
        "ENRICHMENT",
        "MEDIUM",
        "Map the underlying contract reference, date, amount and the "
        "guaranteed percentage. Tp is a code list (e.g. CONS) — map from the "
        "internal contract type.",
    ),
    (
        "UdrtkgIssncDtls/PresntnDtls",
        "Presentation Details",
        "CONDITIONAL",
        "MEDIUM",
        "Presentation medium (PAPR / ELEC / BOTH) and place of presentation "
        "drive claim handling. Derive from the internal presentation "
        "requirements.",
    ),
]

# Mandatory fields for pacs.008.001.10 (FI to FI Customer Credit Transfer)
_PACS008_MANDATORY = [
    (
        "GrpHdr/MsgId",
        "Message Identification",
        "BLOCKING",
        "CRITICAL",
        "Generate a unique reference per message, max 35 characters. "
        "Interbank messages are rejected on duplicate MsgId within the "
        "clearing system's duplicate-check window.",
    ),
    (
        "GrpHdr/CreDtTm",
        "Creation Date and Time",
        "BLOCKING",
        "CRITICAL",
        "Combine the internal creation date and time into ISO 8601. Use the "
        "sending institution's time zone offset explicitly.",
    ),
    (
        "GrpHdr/NbOfTxs",
        "Number of Transactions",
        "ENRICHMENT",
        "HIGH",
        "Count of CdtTrfTxInf blocks in the message. Must agree with the "
        "actual number of transactions or the message fails validation.",
    ),
    (
        "GrpHdr/SttlmInf/SttlmMtd",
        "Settlement Method",
        "BLOCKING",
        "CRITICAL",
        "Business decision: INDA / INGA (settlement on the agent's books), "
        "CLRG (clearing system) or COVE (cover method). Drives whether "
        "SttlmAcct or ClrSys must also be populated.",
    ),
    (
        "GrpHdr/SttlmInf/ClrSys/Cd",
        "Clearing System",
        "CONDITIONAL",
        "HIGH",
        "Required when SttlmMtd is CLRG. Derive from the payment rail "
        "(e.g. TGT for TARGET2, RTGS for domestic RTGS).",
    ),
    (
        "CdtTrfTxInf/PmtId/InstrId",
        "Instruction Identification",
        "ENRICHMENT",
        "HIGH",
        "Point-to-point reference between the two agents. Map from the "
        "internal transaction reference, max 35 characters.",
    ),
    (
        "CdtTrfTxInf/PmtId/EndToEndId",
        "End-to-End Identification",
        "ENRICHMENT",
        "CRITICAL",
        "Carry the originating customer reference unchanged end to end. "
        "Use NOTPROVIDED only where the debtor supplied none.",
    ),
    (
        "CdtTrfTxInf/PmtId/UETR",
        "Unique End-to-End Transaction Reference",
        "BLOCKING",
        "CRITICAL",
        "UUIDv4, mandatory on the SWIFT network for gpi tracking. Generate "
        "at the point of instruction and never regenerate on repair.",
    ),
    (
        "CdtTrfTxInf/IntrBkSttlmAmt",
        "Interbank Settlement Amount",
        "ENRICHMENT",
        "CRITICAL",
        "Amount actually settled between agents, with the Ccy attribute. "
        "Distinct from InstdAmt where charges are deducted — confirm which "
        "internal amount field represents settlement.",
    ),
    (
        "CdtTrfTxInf/IntrBkSttlmDt",
        "Interbank Settlement Date",
        "ENRICHMENT",
        "HIGH",
        "Value date of settlement (YYYY-MM-DD). Derive from the internal "
        "value date, adjusted for clearing-system cut-offs.",
    ),
    (
        "CdtTrfTxInf/ChrgBr",
        "Charge Bearer",
        "BLOCKING",
        "CRITICAL",
        "Business decision: DEBT, CRED, SHAR or SLEV. Must be consistent "
        "with any ChrgsInf deductions carried in the message.",
    ),
    (
        "CdtTrfTxInf/DbtrAgt/FinInstnId/BICFI",
        "Debtor Agent BIC",
        "ENRICHMENT",
        "HIGH",
        "BIC of the debtor's bank. Derive from the internal routing code via "
        "reference data; 8-character BICs pad to 11 with 'XXX'.",
    ),
    (
        "CdtTrfTxInf/CdtrAgt/FinInstnId/BICFI",
        "Creditor Agent BIC",
        "ENRICHMENT",
        "CRITICAL",
        "BIC of the beneficiary's bank, used for routing. Missing or invalid "
        "BICs are the most common cause of interbank rejection.",
    ),
    (
        "CdtTrfTxInf/Dbtr/Nm",
        "Debtor Name",
        "ENRICHMENT",
        "CRITICAL",
        "Mandatory for sanctions screening. Structured address elements are "
        "expected from the 2025 CBPR+ profile — plan for PstlAdr/StrtNm, "
        "TwnNm and Ctry rather than address lines.",
    ),
    (
        "CdtTrfTxInf/Cdtr/Nm",
        "Creditor Name",
        "ENRICHMENT",
        "CRITICAL",
        "Mandatory for sanctions screening, as for the debtor. Truncate at "
        "140 characters and never abbreviate to initials.",
    ),
]

# Mandatory fields for camt.053.001.10 (Bank to Customer Statement)
_CAMT053_MANDATORY = [
    (
        "GrpHdr/MsgId",
        "Message Identification",
        "BLOCKING",
        "CRITICAL",
        "Unique statement message reference, max 35 characters. Consumers "
        "deduplicate on it, so it must be stable across retransmission.",
    ),
    (
        "GrpHdr/CreDtTm",
        "Creation Date and Time",
        "BLOCKING",
        "CRITICAL",
        "Timestamp of statement generation in ISO 8601, not the statement "
        "period end.",
    ),
    (
        "Stmt/Id",
        "Statement Identification",
        "ENRICHMENT",
        "CRITICAL",
        "Statement number from the internal statement record. Must be unique "
        "per account and increment predictably for gap detection.",
    ),
    (
        "Stmt/LglSeqNb",
        "Legal Sequence Number",
        "CONDITIONAL",
        "HIGH",
        "Required where the customer relies on sequence continuity to prove "
        "no statement was missed. Business decision per market.",
    ),
    (
        "Stmt/FrToDt",
        "Statement Period",
        "ENRICHMENT",
        "HIGH",
        "From and to datetimes of the reporting period. Reconciliation "
        "engines reject statements without an explicit period.",
    ),
    (
        "Stmt/Acct/Id/IBAN",
        "Account Identification",
        "ENRICHMENT",
        "CRITICAL",
        "IBAN where one exists, otherwise Othr/Id with a scheme name. "
        "Derive the IBAN from the internal sort code and account number.",
    ),
    (
        "Stmt/Acct/Ccy",
        "Account Currency",
        "ENRICHMENT",
        "HIGH",
        "ISO 4217 code of the account. Required for multi-currency accounts "
        "so balances are unambiguous.",
    ),
    (
        "Stmt/Bal/Tp/CdOrPrtry/Cd",
        "Balance Type",
        "BLOCKING",
        "CRITICAL",
        "At least OPBD (opening booked) and CLBD (closing booked) must be "
        "reported; ITBD and CLAV are expected by many corporates. Map from "
        "the internal balance types — a business decision on coverage.",
    ),
    (
        "Stmt/Bal/Amt",
        "Balance Amount",
        "ENRICHMENT",
        "CRITICAL",
        "Balance amount with its Ccy attribute. Always positive: direction "
        "is carried in CdtDbtInd, not by a negative sign.",
    ),
    (
        "Stmt/Bal/CdtDbtInd",
        "Balance Credit/Debit Indicator",
        "ENRICHMENT",
        "CRITICAL",
        "CRDT or DBIT. Derive from the sign of the internal balance and "
        "invert nothing downstream.",
    ),
    (
        "Stmt/Bal/Dt/Dt",
        "Balance Date",
        "ENRICHMENT",
        "HIGH",
        "Date the balance applies to (YYYY-MM-DD), which for CLBD is the "
        "statement period end.",
    ),
    (
        "Stmt/Ntry/Amt",
        "Entry Amount",
        "ENRICHMENT",
        "CRITICAL",
        "Booked amount per transaction with its currency. Where the entry "
        "was converted, also populate AmtDtls/InstdAmt and CntrValAmt.",
    ),
    (
        "Stmt/Ntry/Sts/Cd",
        "Entry Status",
        "ENRICHMENT",
        "HIGH",
        "BOOK for booked items, PDNG for pending. camt.053 normally carries "
        "booked entries only — confirm whether pending items are in scope.",
    ),
    (
        "Stmt/Ntry/BkTxCd/Domn",
        "Bank Transaction Code",
        "CONDITIONAL",
        "HIGH",
        "ISO external code set (Domn/Cd, Fmly/Cd, SubFmlyCd) drives "
        "auto-reconciliation. Requires a mapping table from internal "
        "transaction codes — the largest single effort in camt.053 work.",
    ),
    (
        "Stmt/Ntry/NtryDtls/TxDtls/Refs/EndToEndId",
        "Entry End-to-End Reference",
        "ENRICHMENT",
        "CRITICAL",
        "Carry the original payment reference so the customer can match the "
        "entry to their instruction. Without it, statements cannot be "
        "auto-reconciled.",
    ),
]

_MANDATORY_BY_TYPE = {
    "pain.001.001.09": _PAIN001_MANDATORY,
    "pacs.008.001.10": _PACS008_MANDATORY,
    "camt.053.001.10": _CAMT053_MANDATORY,
    "tsrv.001.001.01": _TSRV001_MANDATORY,
}

# Fallback per message family, so an unknown version of a supported message
# is never analysed against another domain's mandatory fields.
_MANDATORY_BY_FAMILY = {
    "pain": _PAIN001_MANDATORY,
    "pacs": _PACS008_MANDATORY,
    "camt": _CAMT053_MANDATORY,
    "tsrv": _TSRV001_MANDATORY,
}


@dataclass
class GapEntry:
    iso_xpath: str
    business_label: str
    gap_type: str       # BLOCKING | ENRICHMENT | CONDITIONAL | OUT_OF_SCOPE
    severity: str       # CRITICAL | HIGH | MEDIUM | LOW
    recommendation: str
    is_resolved: bool = False   # True if mapping found
    origin: str = "expert"      # expert (curated table) | schema (derived from XSD)


def _schema_derived_mandatory(
    schema: TargetSchema,
) -> List[tuple[str, str, str, str, str]]:
    """
    Mandatory-field rows read out of the XSD, for a target with no curated
    table. Every row is an ENRICHMENT gap with a recommendation built from the
    schema's own constraints, so an unsupported target still gets a register
    grounded in the standard rather than another message's fields.
    """
    rows: list[tuple[str, str, str, str, str]] = []
    for node in schema.mandatory_leaves():
        detail = node.type_name or "element"
        if node.constraint:
            detail += f" ({node.constraint})"
        codes = (
            f" Permitted values: {', '.join(node.codes)}." if node.codes else ""
        )
        rows.append((
            node.path,
            node.name,
            "ENRICHMENT",
            "HIGH",
            f"Mandatory in {schema.message_type} as {detail}. Identify the "
            f"internal source field or a derivation rule.{codes}",
        ))
    return rows


def mandatory_fields(
    target_message_type: str,
) -> tuple[Sequence[tuple[str, str, str, str, str]], str]:
    """
    The mandatory-field table for a target and where it came from: a curated
    expert table where one exists, otherwise derived from the vendored XSD.
    """
    curated = _MANDATORY_BY_TYPE.get(target_message_type)
    if curated is not None:
        return curated, "expert"

    schema: Optional[TargetSchema] = TargetSchema.for_message_type(target_message_type)
    if schema is not None:
        derived = _schema_derived_mandatory(schema)
        if derived:
            return derived, "schema"

    family = (target_message_type or "").split(".")[0]
    return _MANDATORY_BY_FAMILY.get(family, _PAIN001_MANDATORY), "expert"


def analyze(mappings: list, target_message_type: str) -> List[GapEntry]:
    """
    Cross-reference mapped fields against mandatory ISO 20022 fields.
    Returns gap entries for mandatory fields that have no DIRECT mapping.
    """
    mandatory, origin = mandatory_fields(target_message_type)

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
            origin=origin,
        ))

    return gaps
