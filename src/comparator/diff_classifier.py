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
    # Payments
    "BIC", "IBAN", "Ccy", "Amt", "InstdAmt", "IntrBkSttlmAmt",
    "SttlmMtd", "PmtMtd", "SvcLvl", "Cd", "MndtRltdInf",
    "PmtTpInf", "ReqdExctnDt", "IntrBkSttlmDt",
    # Trade finance — terms of the bank's undertaking
    "AnyBIC", "BICFI", "IssncTp", "PlusTlrnce", "ConfInd",
    "MltplDmndInd", "PrtlDmndInd", "TrfInd", "RuleId", "AplblLaw",
}

# Trade-finance branches that define who may claim, how much, until when and
# under which rules. Any value change inside them alters the bank's exposure,
# whatever the leaf element happens to be called.
_BREAKING_CONTEXT_TAGS = {
    "UdrtkgAmt", "LclUdrtkgAmt", "XpryDtls", "XpryTerms", "AutoXtnsn",
    "AutomtcAmtVartn",
    "GovncRulesAndLaw", "UdrtkgTermsAndConds", "UdrtkgWrdg",
    "Applcnt", "Bnfcry", "PresntnDtls",
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


# Default score weight per diff, by severity
DEFAULT_WEIGHTS: dict["Severity", float] = {
    Severity.BREAKING: 10,
    Severity.WARNING: 3,
    Severity.INFO: 1,
    Severity.BENIGN: 0,
}


class DiffClassifier:
    """
    Classify a single diff entry into a Severity level.

    Can be sub-classed or configured via custom rule functions.
    """

    def __init__(self, weights: Optional[dict["Severity", float]] = None):
        self.weights: dict[Severity, float] = dict(DEFAULT_WEIGHTS)
        if weights:
            self.weights.update(weights)

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
        local_tag = xpath.split("/")[-1].split("[")[0].lstrip("@")
        segments = {s.split("[")[0].lstrip("@") for s in xpath.split("/")}
        liability_context = bool(segments & _BREAKING_CONTEXT_TAGS)

        # ── Benign first ────────────────────────────────────────────────
        if local_tag in _BENIGN_TAGS:
            return Severity.BENIGN

        # ── Mandatory field removed → always breaking ───────────────────
        if change_type == ChangeType.REMOVED:
            if is_mandatory is True or local_tag in _ALWAYS_BREAKING_TAGS:
                return Severity.BREAKING
            if local_tag in _SIGNIFICANT_OPTIONAL_TAGS or liability_context:
                return Severity.WARNING
            return Severity.INFO

        # ── New mandatory field added → breaking for existing senders ───
        if change_type == ChangeType.ADDED:
            if is_mandatory is True:
                return Severity.BREAKING
            return Severity.WARNING if liability_context else Severity.INFO

        # ── Critical field value changed ────────────────────────────────
        if change_type in (ChangeType.MODIFIED, ChangeType.ATTRIBUTE_CHANGED):
            if local_tag in _ALWAYS_BREAKING_TAGS or liability_context:
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
        total = sum(self.weights[s] for s in classifications)
        max_possible = len(classifications) * max(self.weights.values())
        if max_possible == 0:
            return 0.0
        return round(min(total / max_possible * 100, 100.0), 1)

    def score_breakdown(self, classifications: list[Severity]) -> list[dict]:
        """
        Per-severity contribution to the score, so the number can be explained
        to a business audience instead of being asserted.
        """
        if not classifications:
            return []
        max_possible = len(classifications) * max(self.weights.values())
        rows = []
        for severity in (Severity.BREAKING, Severity.WARNING, Severity.INFO, Severity.BENIGN):
            count = sum(1 for s in classifications if s == severity)
            if not count:
                continue
            points = count * self.weights[severity]
            rows.append({
                "severity": severity.value,
                "count": count,
                "weight": self.weights[severity],
                "points": points,
                "score_contribution": round(points / max_possible * 100, 1) if max_possible else 0.0,
            })
        return rows
