"""
Breaking-change classification for ISO 20022 XML diffs.

Rules are applied in priority order; the first matching rule wins.
Classification is based on the XPath, change type, and (optionally) schema
cardinality information obtained from the loaded XSD.
"""
from enum import Enum
from typing import Optional


class Severity(str, Enum):
    BREAKING = "BREAKING"      # must-fix before production
    WARNING = "WARNING"        # investigate — may be breaking depending on impl
    BENIGN = "BENIGN"          # safe to ignore (IDs, timestamps, correlation refs)
    INFO = "INFO"              # informational only (added optional field, etc.)


class ChangeType(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    REORDERED = "reordered"
    ATTRIBUTE_CHANGED = "attr_changed"


# Tags whose removal/modification is always breaking
_ALWAYS_BREAKING_TAGS = {
    "BIC", "IBAN", "Ccy", "Amt", "InstdAmt", "IntrBkSttlmAmt",
    "SttlmMtd", "PmtMtd", "SvcLvl", "Cd", "MndtRltdInf",
    "PmtTpInf", "ReqdExctnDt", "IntrBkSttlmDt",
}

# Tags that are benign when changed (correlation IDs, timestamps, etc.)
_BENIGN_TAGS = {
    "MsgId", "CreDtTm", "InstrId", "EndToEndId", "TxId",
    "UETR", "ClrSysRef", "PrcgDt", "AccptncDtTm",
}

# Tags that trigger a WARNING when removed (optional but significant)
_SIGNIFICANT_OPTIONAL_TAGS = {
    "RmtInf", "Purp", "RgltryRptg", "Splmtry", "AddtlInf",
}


class DiffClassifier:
    """
    Classify a single diff entry into a Severity level.

    Can be sub-classed or configured via custom rule functions.
    """

    def classify(
        self,
        xpath: str,
        change_type: ChangeType,
        old_value: Optional[str] = None,
        new_value: Optional[str] = None,
        is_mandatory: Optional[bool] = None,
    ) -> Severity:
        """
        Classify a single XPath diff into a Severity.

        Args:
            xpath: XPath of the changed node (e.g. /Document/GrpHdr/MsgId).
            change_type: Type of change.
            old_value: Previous text value (for MODIFIED).
            new_value: New text value (for MODIFIED).
            is_mandatory: Whether the element is mandatory per schema
                          (None = unknown).
        """
        local_tag = xpath.split("/")[-1].split("[")[0]

        # ── Benign first ────────────────────────────────────────────────
        if local_tag in _BENIGN_TAGS:
            return Severity.BENIGN

        # ── Mandatory field removed → always breaking ───────────────────
        if change_type == ChangeType.REMOVED:
            if is_mandatory is True or local_tag in _ALWAYS_BREAKING_TAGS:
                return Severity.BREAKING
            if local_tag in _SIGNIFICANT_OPTIONAL_TAGS:
                return Severity.WARNING
            return Severity.INFO

        # ── New mandatory field added → breaking for existing senders ───
        if change_type == ChangeType.ADDED:
            if is_mandatory is True:
                return Severity.BREAKING
            return Severity.INFO

        # ── Critical field value changed ────────────────────────────────
        if change_type == ChangeType.MODIFIED:
            if local_tag in _ALWAYS_BREAKING_TAGS:
                return Severity.BREAKING
            # Amount / currency changes are always breaking
            if "Amt" in local_tag or "Ccy" in local_tag:
                return Severity.BREAKING
            # Date changes are a WARNING (may affect settlement)
            if "Dt" in local_tag or "Date" in local_tag:
                return Severity.WARNING
            return Severity.INFO

        # ── Element re-ordering ─────────────────────────────────────────
        if change_type == ChangeType.REORDERED:
            return Severity.WARNING

        return Severity.INFO

    def breaking_score(self, classifications: list[Severity]) -> float:
        """
        Return a 0-100 breaking-change score.

        100 = all diffs are BREAKING, 0 = all BENIGN/INFO.
        """
        if not classifications:
            return 0.0
        weights = {
            Severity.BREAKING: 10,
            Severity.WARNING: 3,
            Severity.INFO: 1,
            Severity.BENIGN: 0,
        }
        total = sum(weights[s] for s in classifications)
        max_possible = len(classifications) * 10
        return round(min(total / max_possible * 100, 100.0), 1)
