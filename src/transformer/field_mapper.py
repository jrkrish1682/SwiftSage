"""
Map internal bank message fields to ISO 20022 target fields
using Claude as the reasoning engine.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import List

import anthropic

from src.observability.token_usage import TokenUsage
from src.transformer import mapping_validator
from src.transformer.message_parser import InternalField
from src.transformer.target_schema import UNCHECKED, TargetSchema
from src.utils.helpers import get_logger

log = get_logger(__name__)

_PAIN001_CONTEXT = """
pain.001.001.09 (Customer Credit Transfer Initiation) key elements:

GROUP HEADER (GrpHdr) — once per message:
  MsgId         : Message ID (unique, max 35 chars)
  CreDtTm       : Creation datetime (ISO 8601)
  NbOfTxs       : Total number of individual transactions
  CtrlSum       : Sum of all instructed amounts
  InitgPty/Nm   : Initiating party (company) name

PAYMENT INFO (PmtInf) — one per payment batch:
  PmtInfId              : Payment info ID (unique)
  PmtMtd                : Payment method (always TRF for credit transfer)
  NbOfTxs               : Number of transactions in this batch
  CtrlSum               : Control sum for this batch
  PmtTpInf/SvcLvl/Cd   : Service level (e.g. SEPA, NURG, URGP, G004)
  PmtTpInf/LclInstrm/Cd: Local instrument (e.g. BACS, CHAPS)
  ReqdExctnDt/Dt        : Requested execution date (YYYY-MM-DD)
  Dbtr/Nm               : Debtor (ordering customer) name
  DbtrAcct/Id/IBAN      : Debtor IBAN
  DbtrAcct/Ccy          : Debtor account currency
  DbtrAgt/FinInstnId/BICFI : Debtor bank BIC

CREDIT TRANSFER TRANSACTION INFO (CdtTrfTxInf) — one per payment:
  PmtId/EndToEndId          : End-to-end reference (max 35 chars)
  Amt/InstdAmt + @Ccy       : Instructed amount and currency
  ChrgBr                    : Charge bearer (SLEV/SHAR/DEBT/CRED)
  CdtrAgt/FinInstnId/BICFI  : Creditor bank BIC
  Cdtr/Nm                   : Creditor (beneficiary) name
  CdtrAcct/Id/IBAN          : Creditor IBAN
  RmtInf/Ustrd              : Remittance info (unstructured, max 140 chars)
"""

_PAYMENT_RULES = """\
- Sort codes (format XX-XX-XX) are UK bank routing codes. They cannot map directly to BICFI. Mapping type is DERIVED — BIC must be looked up from a reference data service.
- UK account numbers (8 digits) cannot map directly to IBAN. Mapping type is DERIVED — IBAN must be computed using the UK IBAN algorithm.
- If a field already contains an IBAN (starts with two letters then digits), it maps DIRECTLY to CdtrAcct/Id/IBAN or DbtrAcct/Id/IBAN.
- If a field already contains a BIC (8 or 11 chars, all caps, format XXXXGB22), it maps DIRECTLY to the relevant BICFI element.
- Internal tracking fields (WorkflowId, ApprovalStatus, CostCentre, InternalCustomerId, Channel, BatchRef, ApprovedBy, ApprovalTimestamp, CompanyRegistrationNo) have no ISO 20022 equivalent — mark as UNMAPPED.
- CreationDate and CreationTime should be COMBINED into GrpHdr/CreDtTm.
- TotalAmount maps to GrpHdr/CtrlSum (DIRECT).
- NumberOfPayments maps to GrpHdr/NbOfTxs (DIRECT).
"""

_TSRV001_CONTEXT = """
tsrv.001.001.01 (Undertaking Issuance — the ISO 20022 equivalent of MT 760)
key elements, all under UdrtkgIssnc/UdrtkgIssncDtls:

  Id                          : Undertaking reference (max 35 chars)
  Nm                          : Undertaking name — code list, DGAR (demand
                                guarantee) or STBY (standby letter of credit)
  Tp/Cd                       : Undertaking type (purpose, e.g. APAY advance
                                payment, PERF performance)
  IssncTp                     : Issuance type — ISSU, ISCO, ISAD, CRQL, CRQC
  Applcnt                     : Applicant (party, repeatable)
  Issr                        : Issuing bank (party)
  Bnfcry                      : Beneficiary (party, repeatable)
  DtOfIssnc                   : Date of issuance (YYYY-MM-DD)
  PlcOfIsse                   : Place of issue (postal address)
  AdvsgPty                    : Advising bank (party)
  UdrtkgAmt/Amt + @Ccy        : Undertaking amount and currency
  UdrtkgAmt/PlusTlrnce        : Positive tolerance, as a percentage
  XpryDtls/XpryTerms/DtTm/Dt  : Expiry date
  XpryDtls/XpryTerms/Cond     : Expiry condition (event-based expiry)
  ConfInd                     : Confirmation indicator (true/false)
  GovncRulesAndLaw/RuleId/Cd  : Governing rules — URDG, ISPR, UCPR, NONE
  GovncRulesAndLaw/AplblLaw   : Applicable law (Ctry + Txt)
  GovncRulesAndLaw/Jursdctn   : Jurisdiction (Ctry + Txt)
  UndrlygTx                   : Underlying trade transaction — Tp, Id, TxDt,
                                TxAmt, CtrctAmtPctg
  PresntnDtls/Mdm/Cd          : Presentation medium — PAPR, ELEC, BOTH
  UdrtkgTermsAndConds/Txt     : Undertaking wording (repeatable narrative)
  MltplDmndInd, PrtlDmndInd   : Whether multiple / partial demands are allowed
  ConfChrgsPyblBy, TrfChrgsPyblBy : Which party bears charges
  DlvryChanl                  : Delivery channel
  TrfInd                      : Transferability indicator
  AddtlInf                    : Additional information (max 5 occurrences)

Party structure (PartyIdentification43): Nm, PstlAdr (StrtNm, BldgNb, PstCd,
TwnNm, Ctry) and Id/OrgId/AnyBIC for the BIC.
"""

_TRADE_RULES = """\
- Yes/No flags in the internal message (YES/NO, Y/N) map to ISO 20022 YesNoIndicator booleans — mapping type DERIVED with the conversion stated in the business rule.
- Guarantee product codes map to Nm, which accepts only DGAR or STBY. Anything else (e.g. documentary credit) is out of scope for this message — mark as UNMAPPED and say why.
- Free-text governing rules such as 'URDG758' or 'ISP98' map to GovncRulesAndLaw/RuleId/Cd as URDG / ISPR (DERIVED, code-list normalisation). UCP 600 is UCPR.
- Tolerance percentages map to UdrtkgAmt/PlusTlrnce and MnsTlrnce as percentages, never as amounts.
- Amount plus currency: the amount maps to UdrtkgAmt/Amt and the currency to its Ccy attribute — SPLIT or COMBINED as appropriate.
- 8-character BICs map to Id/OrgId/AnyBIC, which requires 11 characters — DERIVED, padded with 'XXX'.
- Address lines map into PstlAdr; street name and building number are separate elements, so a single internal address line is SPLIT.
- Expiry place has no dedicated element: it belongs in XpryDtls/AddtlXpryInf or the undertaking wording — state which in the business rule.
- Internal credit and workflow fields (CreditApprovalStatus, ApprovedBy, ApprovalTimestamp, RiskRating, CollateralType, LimitReference, CostCentre, WorkflowId, InternalCustomerId, Channel, CompanyRegistrationNo) have no ISO 20022 equivalent — mark as UNMAPPED.
- Delivery method (e.g. SWIFT) maps to DlvryChanl; presentation medium (PAPER / ELECTRONIC) maps to PresntnDtls/Mdm/Cd as PAPR / ELEC.
"""

# Domain mapping rules per message family. The element reference itself comes
# from the target XSD; these are the expert rules the schema cannot state.
_TARGET_RULES: dict[str, str] = {
    "pain": _PAYMENT_RULES,
    "pacs": _PAYMENT_RULES,
    "camt": _PAYMENT_RULES,
    "tsrv": _TRADE_RULES,
    "tsmt": _TRADE_RULES,
    "tsin": _TRADE_RULES,
}

# Used only when a target has no vendored XSD to outline
_FALLBACK_CONTEXT: dict[str, str] = {
    "pain": _PAIN001_CONTEXT,
    "pacs": _PAIN001_CONTEXT,
    "camt": _PAIN001_CONTEXT,
    "tsrv": _TSRV001_CONTEXT,
}


def target_context(target_message_type: str) -> tuple[str, str, str]:
    """
    Reference material, mapping rules and domain label for a target message.
    The element reference is generated from the vendored XSD so any supported
    message is described accurately, falling back to a curated block only when
    the schema is missing.
    """
    family = (target_message_type or "").split(".")[0]
    rules = _TARGET_RULES.get(family, _PAYMENT_RULES)
    domain = "trade finance" if family in ("tsrv", "tsmt", "tsin") else "payment"

    schema = TargetSchema.for_message_type(target_message_type)
    if schema is not None:
        return schema.mapping_context(), rules, domain
    log.info("No outline for %s — using the curated element block", target_message_type)
    return _FALLBACK_CONTEXT.get(family, _PAIN001_CONTEXT), rules, domain

# A mapping run costs roughly one prompt line plus one JSON object per field, so
# a 73-field statement feed is an expensive call. Only the most business-relevant
# fields are sent; the rest are reported as deferred rather than dropped quietly.
MAX_MAPPED_FIELDS = 20

# Vocabulary that earns a field its place in the budget, matched on the leaf
# name so a parent element cannot lend its relevance to every child.
_ESSENTIAL = (
    "amount", "amt", "ccy", "currency", "iban", "acct", "accountnumber", "accountno",
    "bic", "swiftcode", "sortcode", "uetr", "endtoend", "settlement", "valuedate",
    "remittance", "balance", "expiry", "tolerance", "executiondate", "chargeindicator",
)
_USEFUL = (
    "name", "date", "time", "ref", "id", "code", "type", "method", "purpose",
    "status", "charge", "country", "entry", "statement", "bank", "branch",
    "customer", "beneficiary", "applicant", "party", "debtor", "creditor",
    "guarantee", "undertaking", "governing", "period", "number", "count",
)
# Internal plumbing a BA does not need mapped first; matched on the whole path.
_NOISE = (
    "workflow", "approval", "approvedby", "costcentre", "internalcustomer",
    "channel", "batchref", "riskrating", "collateral", "limitreference",
    "companyregistration", "audit", "createdby", "systemid", "sourcesystem",
)

_LIST_INDEX = re.compile(r"\[\d+\]")
_NON_WORD = re.compile(r"[^a-z0-9]")


def _field_score(f: InternalField, depth: int) -> int:
    path = f"{f.xpath} {getattr(f, 'description', '')}".lower()
    leaf = _NON_WORD.sub("", f.xpath.rsplit("/", 1)[-1].lower())
    score = 0
    if any(term in leaf for term in _ESSENTIAL):
        score += 5
    if any(term in leaf for term in _USEFUL):
        score += 3
    if any(term in _NON_WORD.sub("", path) for term in _NOISE):
        score -= 10
    score -= max(0, depth - 2)   # prefer header and summary levels
    if getattr(f, "sample", "") or f.value:
        score += 1               # a field with a sample value maps far better
    return score


def select_fields(
    fields: List[InternalField], limit: int = MAX_MAPPED_FIELDS
) -> tuple[List[InternalField], List[InternalField]]:
    """
    Split an inventory into the fields worth sending to the model and the rest.

    Repeated occurrences of the same structure (`transactions/[7]/amount`) add
    prompt cost without adding a mapping, so only the first occurrence of each
    shape competes for the budget; what remains is ranked on business relevance.
    Returns `(selected, deferred)`, both in their original document order.
    """
    candidates = [f for f in fields if not f.is_attribute]

    seen: set[str] = set()
    first_of_shape: List[InternalField] = []
    repeats: List[InternalField] = []
    for f in candidates:
        shape = _LIST_INDEX.sub("[]", f.xpath)
        (repeats if shape in seen else first_of_shape).append(f)
        seen.add(shape)

    if limit <= 0 or len(first_of_shape) <= limit:
        selected = first_of_shape[:limit] if limit > 0 else []
    else:
        ranked = sorted(
            enumerate(first_of_shape),
            key=lambda pair: (-_field_score(pair[1], pair[1].xpath.count("/")),
                              pair[0]),
        )
        keep = {i for i, _ in ranked[:limit]}
        selected = [f for i, f in enumerate(first_of_shape) if i in keep]

    chosen = {id(f) for f in selected}
    deferred = [f for f in candidates if id(f) not in chosen]
    return selected, deferred


_MAPPING_SCHEMA = """
Return ONLY a JSON array. Each element must have exactly these keys:
{
  "source_field": "<internal element name>",
  "source_xpath": "<full xpath from internal message>",
  "source_value": "<sample value>",
  "iso20022_xpath": "<ISO 20022 XPath e.g. PmtInf/CdtTrfTxInf/Amt/InstdAmt>",
  "iso20022_element": "<ISO 20022 element label e.g. Instructed Amount>",
  "mapping_type": "<DIRECT|DERIVED|SPLIT|COMBINED|UNMAPPED>",
  "confidence": "<HIGH|MEDIUM|LOW>",
  "business_rule": "<one-sentence transformation rule or derivation logic>",
  "notes": "<any caveat, constraint, or open question>"
}

Mapping types:
  DIRECT   - field maps 1:1 with same business meaning
  DERIVED  - target must be computed from source (e.g. IBAN from sort code)
  SPLIT    - one source field maps to multiple target fields
  COMBINED - multiple source fields merge into one target
  UNMAPPED - no ISO 20022 equivalent; note why

For UNMAPPED fields: set iso20022_xpath and iso20022_element to empty string.
"""


def system_prompt(target_message_type: str) -> str:
    """
    The part of the prompt that depends only on the target message.

    Element reference, domain rules and output schema are identical for every
    run against the same target and dwarf the field list, so they are sent as a
    cached system block; only the fields themselves vary per run.
    """
    context, rules, domain = target_context(target_message_type)
    return f"""You are an ISO 20022 expert helping a Business Analyst map a bank's internal {domain} message to {target_message_type}.

{context}

Rules:
{rules}
{_MAPPING_SCHEMA}"""


@dataclass
class MappedField:
    source_field: str
    source_xpath: str
    source_value: str
    iso20022_xpath: str
    iso20022_element: str
    mapping_type: str    # DIRECT | DERIVED | SPLIT | COMBINED | UNMAPPED
    confidence: str      # HIGH | MEDIUM | LOW
    business_rule: str
    notes: str
    validation: str = UNCHECKED       # RESOLVED | PARTIAL | UNRESOLVED | UNCHECKED
    validation_note: str = ""
    resolved_xpath: str = ""


class FieldMapper:
    """Uses Claude to reason field-by-field and produce a mapping table."""

    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise ValueError("Anthropic API key not set — enter it in the sidebar.")
        self._client = anthropic.Anthropic(api_key=api_key)
        # Tokens the last `map()` call cost — read by the caller for the run log.
        self.last_usage = TokenUsage()
        self.last_system_prompt = ""

    def map(self, fields: List[InternalField], target_message_type: str) -> List[MappedField]:
        """
        Map internal fields to the target ISO 20022 message type.

        At most `MAX_MAPPED_FIELDS` fields are sent per call; callers that need
        to report what was left out should call `select_fields` themselves.
        """
        selected, deferred = select_fields(fields)
        field_list = "\n".join(
            f"  - {f.xpath} = '{f.sample}'"
            + (f"  [{f.description}]" if getattr(f, "description", "") else "")
            for f in selected
        )
        system = system_prompt(target_message_type)
        prompt = f"""The internal message contains these fields:
{field_list}

For each internal field, determine its ISO 20022 mapping."""

        model = os.environ.get("AGENT_MODEL", "claude-sonnet-4-6")
        log.info(
            "FieldMapper: calling %s with %d of %d fields (%d deferred) → %s",
            model, len(selected), len(fields), len(deferred), target_message_type,
        )
        message = self._client.messages.create(
            model=model,
            max_tokens=16000,
            # The element reference for a target is large and unchanged between
            # runs, so it is cached rather than re-billed at the full input rate.
            system=[{
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": prompt}],
        )
        self.last_system_prompt = system
        self.last_usage = TokenUsage.from_anthropic(message.usage)
        log.info(
            "FieldMapper: stop_reason=%s, in=%s out=%s (cache read %s / write %s)",
            message.stop_reason,
            self.last_usage.input_tokens,
            self.last_usage.output_tokens,
            self.last_usage.cache_read_tokens,
            self.last_usage.cache_write_tokens,
        )

        raw = message.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Find the JSON array in the response
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start >= 0 and end > start:
                data = json.loads(raw[start:end])
            else:
                raise ValueError(f"Could not parse mapping JSON from Claude response: {raw[:200]}")

        mapped = [
            MappedField(
                source_field=item.get("source_field", ""),
                source_xpath=item.get("source_xpath", ""),
                source_value=item.get("source_value", ""),
                iso20022_xpath=item.get("iso20022_xpath", ""),
                iso20022_element=item.get("iso20022_element", ""),
                mapping_type=item.get("mapping_type", "UNMAPPED"),
                confidence=item.get("confidence", "LOW"),
                business_rule=item.get("business_rule", ""),
                notes=item.get("notes", ""),
            )
            for item in data
        ]
        return mapping_validator.validate(mapped, target_message_type)
