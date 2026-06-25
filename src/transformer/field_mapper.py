"""
Map internal bank message fields to ISO 20022 target fields
using Claude as the reasoning engine.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import List

import anthropic

from src.transformer.message_parser import InternalField
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


class FieldMapper:
    """Uses Claude to reason field-by-field and produce a mapping table."""

    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise ValueError("Anthropic API key not set — enter it in the sidebar.")
        self._client = anthropic.Anthropic(api_key=api_key)

    def map(self, fields: List[InternalField], target_message_type: str) -> List[MappedField]:
        """Map internal fields to the target ISO 20022 message type."""
        field_list = "\n".join(
            f"  - {f.xpath} = '{f.sample}'" for f in fields if not f.is_attribute
        )

        prompt = f"""You are an ISO 20022 expert helping a Business Analyst map a bank's internal payment message to {target_message_type}.

{_PAIN001_CONTEXT}

The internal message contains these fields:
{field_list}

For each internal field, determine its ISO 20022 mapping.

Rules:
- Sort codes (format XX-XX-XX) are UK bank routing codes. They cannot map directly to BICFI. Mapping type is DERIVED — BIC must be looked up from a reference data service.
- UK account numbers (8 digits) cannot map directly to IBAN. Mapping type is DERIVED — IBAN must be computed using the UK IBAN algorithm.
- If a field already contains an IBAN (starts with two letters then digits), it maps DIRECTLY to CdtrAcct/Id/IBAN or DbtrAcct/Id/IBAN.
- If a field already contains a BIC (8 or 11 chars, all caps, format XXXXGB22), it maps DIRECTLY to the relevant BICFI element.
- Internal tracking fields (WorkflowId, ApprovalStatus, CostCentre, InternalCustomerId, Channel, BatchRef, ApprovedBy, ApprovalTimestamp, CompanyRegistrationNo) have no ISO 20022 equivalent — mark as UNMAPPED.
- CreationDate and CreationTime should be COMBINED into GrpHdr/CreDtTm.
- TotalAmount maps to GrpHdr/CtrlSum (DIRECT).
- NumberOfPayments maps to GrpHdr/NbOfTxs (DIRECT).

{_MAPPING_SCHEMA}"""

        model = os.environ.get("AGENT_MODEL", "claude-sonnet-4-6")
        log.info("FieldMapper: calling %s with %d fields → %s", model, len(fields), target_message_type)
        message = self._client.messages.create(
            model=model,
            max_tokens=16000,
            messages=[{"role": "user", "content": prompt}],
        )
        log.info("FieldMapper: response stop_reason=%s, output_tokens=%s",
                 message.stop_reason, message.usage.output_tokens)

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

        return [
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
