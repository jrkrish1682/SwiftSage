"""
Starter-question packs for the chat tab, grouped by business domain.

SwiftSage is pitched across Cash, Payments, Trade, Settlement and Securities,
but the chat tab opened with three payment-initiation questions, so a demo to a
trade or securities audience had nothing to click. Each pack asks questions the
grounded lookup tools can actually answer against the vendored schemas, so the
starters double as a tour of the standards library.
"""
from __future__ import annotations

# Ordered — the first pack is the default selection in the UI.
PROMPT_PACKS: dict[str, list[str]] = {
    "Payments": [
        "What is pain.001 used for in business terms?",
        "Is the charge bearer mandatory in pain.001.001.09, and what do the "
        "codes mean for our customers?",
        "What changed between pain.001.001.09 and pain.001.001.12, and what "
        "is the business impact?",
    ],
    "Cash": [
        "What does a camt.053 statement give our reconciliation team?",
        "How is a statement entry structured in camt.053.001.10, and which "
        "parts are mandatory?",
        "Which balance types can appear on a camt.053 statement and what does "
        "each one tell operations?",
    ],
    "Trade": [
        "How does an MT 760 guarantee map to ISO 20022 tsrv.001 in business "
        "terms?",
        "What are the mandatory fields of a tsrv.001.001.01 undertaking "
        "issuance, and which need a business decision?",
        "How are expiry terms and governing rules expressed in tsrv.001, and "
        "why do they matter operationally?",
    ],
    "Settlement": [
        "What does pacs.008 do that pain.001 does not, and who exchanges it?",
        "Is UETR mandatory in pacs.008.001.10, and what breaks in gpi "
        "tracking without it?",
        "What is the difference between the instructed amount and the "
        "interbank settlement amount for our operations team?",
    ],
    "Securities & FX": [
        "Which ISO 20022 message sets cover securities settlement and FX, and "
        "which of them are in our standards library today?",
        "What would we need to add to SwiftSage to run a sese.023 settlement "
        "instruction impact assessment?",
        "How does the breaking-change scoring we use for payments apply to a "
        "securities message upgrade?",
    ],
}

DEFAULT_PACK = next(iter(PROMPT_PACKS))


def pack_names() -> list[str]:
    return list(PROMPT_PACKS)


def prompts_for(pack: str) -> list[str]:
    """Questions for *pack*, falling back to the default pack."""
    return PROMPT_PACKS.get(pack, PROMPT_PACKS[DEFAULT_PACK])
