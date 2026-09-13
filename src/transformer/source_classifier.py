"""
Work out which ISO 20022 message family an internal source message belongs to.

A BA can select any target in the Transform Advisor, so a statement feed can be
mapped against pacs.008 or a guarantee application against camt.053 by mistake.
The mapping then looks merely weak rather than wrong, so the source is profiled
from its own vocabulary and the UI can say plainly that source and target do not
belong together.
"""
from __future__ import annotations

from typing import Iterable, Optional

FAMILY_LABELS = {
    "pain": "customer-initiated payment instruction",
    "pacs": "interbank payment / clearing and settlement message",
    "camt": "cash management or account statement message",
    "tsrv": "trade finance undertaking (guarantee or standby LC)",
    "tsmt": "trade services management message",
}

# Vocabulary that is characteristic of each family in a bank's own message
# formats, weighted so an unambiguous term outvotes a generic one.
_SIGNALS: dict[str, tuple[tuple[str, int], ...]] = {
    "pain": (
        ("paymentinstruction", 3), ("orderingcustomer", 2), ("paymentref", 2),
        ("requestedexecution", 2), ("valuedate", 1), ("remittance", 1),
        ("beneficiaryname", 1), ("numberofpayments", 2), ("sortcode", 1),
    ),
    "pacs": (
        ("settlementmethod", 3), ("interbank", 3), ("settlementamount", 2),
        ("clearingsystem", 3), ("uetr", 3), ("orderingbank", 2),
        ("beneficiarybank", 2), ("chargeindicator", 1), ("transactionref", 1),
    ),
    "camt": (
        ("statement", 3), ("openingbalance", 3), ("closingbalance", 3),
        ("balance", 2), ("bookingdate", 2), ("entryref", 2),
        ("transactions", 1), ("narrative", 1), ("accounttype", 1),
    ),
    "tsrv": (
        ("guarantee", 3), ("undertaking", 3), ("standby", 3), ("applicant", 2),
        ("advisingbank", 2), ("governingrules", 2), ("expirydate", 1),
        ("issuingbank", 2), ("underlyingtransaction", 2),
    ),
    "tsmt": (
        ("baseline", 3), ("purchaseorder", 2), ("commercialdata", 2),
        ("transactionstatus", 1), ("shipment", 1),
    ),
}

_MIN_SCORE = 4


def detect_family(fields: Iterable) -> tuple[Optional[str], str]:
    """
    Best guess at the source message family, with the evidence behind it.

    Returns `(None, "")` whenever the vocabulary is inconclusive — a wrong
    accusation of a mismatch is worse than staying quiet.
    """
    haystack = " ".join(
        f"{getattr(f, 'xpath', '')} {getattr(f, 'description', '')}".lower()
        for f in fields
    ).replace("_", "").replace("-", "").replace(" ", "")

    scores: dict[str, int] = {}
    hits: dict[str, list[str]] = {}
    for family, signals in _SIGNALS.items():
        for term, weight in signals:
            if term in haystack:
                scores[family] = scores.get(family, 0) + weight
                hits.setdefault(family, []).append(term)

    if not scores:
        return None, ""

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, best_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    if best_score < _MIN_SCORE or best_score == runner_up:
        return None, ""
    return best, ", ".join(sorted(set(hits[best]))[:5])


def mismatch_warning(
    source_family: Optional[str], target_message_type: str, evidence: str = ""
) -> str:
    """
    Message to show when the source and target belong to different families,
    or an empty string when they are compatible or the source is unclear.
    """
    target_family = (target_message_type or "").split(".")[0]
    if not source_family or not target_family or source_family == target_family:
        return ""
    # Trade families are mapped between each other often enough to be plausible
    if {source_family, target_family} <= {"tsrv", "tsmt", "tsin"}:
        return ""

    note = (
        f"This source looks like a {FAMILY_LABELS.get(source_family, source_family)} "
        f"({source_family}), but the selected target is {target_message_type}, a "
        f"{FAMILY_LABELS.get(target_family, target_family)}. Mapping across message "
        "families produces requirements a development team cannot build — check the "
        "target selection before using this output."
    )
    if evidence:
        note += f" Source vocabulary that led to this: {evidence}."
    return note
