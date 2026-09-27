"""
Seed knowledge — mocked institutional rules, so the graph is useful on day one.

An empty knowledge base demonstrates nothing: every consumer (RCA, stories,
tests, review) needs facts to reason over before a single specialist has typed
anything in. These are the rules of a *fictional* institution, written the way a
bank's internal standards document phrases them, and every node is stored with
status `seeded` so nothing here can be mistaken for a published ISO 20022
requirement.

Each rule names the ISO element short names it governs. On seeding, those names
are resolved against the vendored XSDs through `SchemaIndex`, which creates the
`iso_element` nodes and `governs` edges — so the graph is connected to the real
standard from the start rather than being a flat list of sentences. A name that
does not resolve (a family with no vendored schema, such as `sese`) is kept in
the rule's detail and reported, never silently dropped.

The historical defects are seeded for the same reason: root-cause analysis is
only convincing when there is a past to compare against.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from src.knowledge import store as ks
from src.utils.helpers import get_logger

log = get_logger(__name__)

BANK = "Meridian Bank"


@dataclass(frozen=True)
class SeedRule:
    """One mocked internal rule."""

    id: str
    domain: str
    name: str
    condition: str
    action: str
    severity: str
    message_types: tuple[str, ...]
    elements: tuple[str, ...] = ()
    systems: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class SeedDefect:
    """One historical production failure, already attributed to a rule."""

    id: str
    domain: str
    name: str
    summary: str
    symptom: str
    rule_id: str
    message_type: str
    keywords: tuple[str, ...] = field(default=())


SEED_RULES: tuple[SeedRule, ...] = (
    # ── Payments ───────────────────────────────────────────────────────────
    SeedRule(
        id="BR-001",
        domain="Payments",
        name="UK domestic accounts must be converted to IBAN for cross-border ISO traffic",
        condition=(
            "An outbound payment leaves the UK clearing and the debtor or creditor "
            "account is held as a 6-digit sort code plus 8-digit account number"
        ),
        action=(
            "Derive the IBAN (GB + check digits + bank code + sort code + account) "
            "and populate Cdtr/CdtrAcct/Id/IBAN; the domestic pair may only be sent "
            "in Othr/Id for reconciliation"
        ),
        severity="HIGH",
        message_types=("pacs.008.001.08", "pacs.008.001.10", "pain.001.001.09"),
        elements=("IBAN", "Othr", "CdtrAcct", "DbtrAcct"),
        systems=("Core Banking (CBS)", "Payment Gateway"),
        keywords=("iban", "sort code", "account number", "invalid account"),
    ),
    SeedRule(
        id="BR-002",
        domain="Payments",
        name="Charge bearer defaults by corridor",
        condition="No charge bearer is supplied by the originating channel",
        action=(
            "Set ChrgBr=SHAR for EEA corridors and DEBT for all other corridors; "
            "CRED is never sent outbound without Treasury sign-off"
        ),
        severity="MEDIUM",
        message_types=("pacs.008.001.08", "pacs.008.001.10", "pain.001.001.09"),
        elements=("ChrgBr", "ChrgsInf"),
        systems=("Payment Gateway",),
        keywords=("charge", "chrgbr", "shar", "debt", "fees"),
    ),
    SeedRule(
        id="BR-003",
        domain="Payments",
        name="Remittance information is truncated, never split",
        condition="Unstructured remittance information exceeds 140 characters",
        action=(
            "Truncate RmtInf/Ustrd at 140 characters and raise an operations "
            "warning; splitting across repeats is prohibited because the "
            "beneficiary's AP system reads only the first occurrence"
        ),
        severity="MEDIUM",
        message_types=("pacs.008.001.08", "pacs.008.001.10", "pain.001.001.09",
                       "pain.001.001.12"),
        elements=("RmtInf", "Ustrd"),
        systems=("Payment Gateway", "Accounts Payable feed"),
        keywords=("remittance", "rmtinf", "ustrd", "140", "truncat", "too long"),
    ),
    # ── Cash ───────────────────────────────────────────────────────────────
    SeedRule(
        id="BR-004",
        domain="Cash",
        name="Statements must balance before publication",
        condition="A camt.053 statement is assembled for a customer account",
        action=(
            "Opening booked balance plus the sum of entries must equal the closing "
            "booked balance; on a mismatch the statement is quarantined and not "
            "published to the channel"
        ),
        severity="HIGH",
        message_types=("camt.053.001.08", "camt.053.001.10"),
        elements=("Bal", "Amt", "Ntry", "Stmt"),
        systems=("Statement Engine", "Digital Channel"),
        keywords=("balance", "statement", "does not balance", "closing", "opening"),
    ),
    SeedRule(
        id="BR-005",
        domain="Cash",
        name="Internal value date maps to booking date for same-day sweeps",
        condition="A sweep entry settles on the same day it is booked",
        action=(
            "Map the internal ValueDate to Ntry/BookgDt; ValDt is populated only "
            "when the two genuinely differ, because liquidity reporting keys on "
            "BookgDt"
        ),
        severity="MEDIUM",
        message_types=("camt.053.001.08", "camt.053.001.10"),
        elements=("BookgDt", "ValDt", "Ntry"),
        systems=("Liquidity Management",),
        keywords=("value date", "booking date", "bookgdt", "valdt", "sweep"),
    ),
    SeedRule(
        id="BR-006",
        domain="Cash",
        name="Entry references must carry the originating payment reference",
        condition="A statement entry originates from an ISO payment instruction",
        action=(
            "Carry the instruction's end-to-end reference into Ntry/NtryRef so "
            "customer reconciliation can match the entry to the payment"
        ),
        severity="MEDIUM",
        message_types=("camt.053.001.08", "camt.053.001.10"),
        elements=("NtryRef", "Refs", "EndToEndId"),
        systems=("Statement Engine", "Reconciliation"),
        keywords=("reference", "ntryref", "reconcil", "end to end"),
    ),
    # ── Trade ──────────────────────────────────────────────────────────────
    SeedRule(
        id="BR-007",
        domain="Trade",
        name="An amendment must quote the original undertaking reference",
        condition="A guarantee or standby amendment is issued",
        action=(
            "The original undertaking identifier must be present and must match a "
            "live undertaking in the trade system; otherwise the message is routed "
            "to manual checking and not transmitted"
        ),
        severity="HIGH",
        message_types=("tsrv.001.001.01",),
        elements=("UdrtkgIssnc", "Id", "UdrtkgIssncDtls"),
        systems=("Trade Finance Platform",),
        keywords=("amendment", "undertaking", "reference", "guarantee", "original"),
    ),
    SeedRule(
        id="BR-008",
        domain="Trade",
        name="Expiry extension beyond twelve months needs credit approval",
        condition=(
            "An amendment extends the expiry date of a guarantee more than twelve "
            "months beyond the original expiry"
        ),
        action=(
            "Hold the amendment for credit approval and record the approval "
            "reference before issuance; the exposure limit must be re-checked"
        ),
        severity="HIGH",
        message_types=("tsrv.001.001.01",),
        elements=("XpryDtls", "FnlXpryDt", "UdrtkgAmt"),
        systems=("Trade Finance Platform", "Credit Risk"),
        keywords=("expiry", "extension", "xprydt", "credit", "limit"),
    ),
    SeedRule(
        id="BR-009",
        domain="Trade",
        name="Baseline amendments must preserve the transaction identifier",
        condition="A trade services baseline report is re-issued after amendment",
        action=(
            "Keep the transaction identifier stable across versions so the "
            "counterparty's matching engine treats it as an amendment rather than "
            "a new baseline"
        ),
        severity="MEDIUM",
        message_types=("tsmt.011.001.03", "tsmt.011.001.04"),
        elements=("TxId", "UsrTxRef", "RptId"),
        systems=("Trade Matching",),
        keywords=("baseline", "transaction id", "matching", "amendment"),
    ),
    # ── Securities / Settlement ────────────────────────────────────────────
    # No securities XSD is vendored, so these rules stay unlinked to elements —
    # reported as such rather than fabricated against a payments schema.
    SeedRule(
        id="BR-010",
        domain="Securities/Settlement",
        name="Missing place of settlement defaults to the local CSD",
        condition="A settlement instruction arrives with no place of settlement",
        action=(
            "Default PlcOfSttlm to the local CSD BIC for the security's country of "
            "issue and flag the instruction for settlement operations review"
        ),
        severity="HIGH",
        message_types=("sese.023.001.09",),
        elements=("PlcOfSttlm", "SttlmPlc"),
        systems=("Settlement Engine", "Static Data"),
        keywords=("place of settlement", "csd", "plcofsttlm", "depository"),
    ),
    SeedRule(
        id="BR-011",
        domain="Securities/Settlement",
        name="Partial settlement is disallowed on internal accounts",
        condition="A settlement instruction references an internal house account",
        action=(
            "Send SttlmTxCond=NPAR (no partial settlement); a partial allowed "
            "indicator on an internal account is rejected before transmission"
        ),
        severity="MEDIUM",
        message_types=("sese.023.001.09",),
        elements=("SttlmTxCond", "PrtlSttlmInd"),
        systems=("Settlement Engine",),
        keywords=("partial", "npar", "internal account", "settlement condition"),
    ),
    SeedRule(
        id="BR-012",
        domain="Securities/Settlement",
        name="Trade and settlement dates must respect the market cycle",
        condition="A settlement instruction is created for an equity market",
        action=(
            "Settlement date must be trade date plus the market's standard cycle "
            "(T+1 for US and UK equities); anything shorter needs desk approval"
        ),
        severity="MEDIUM",
        message_types=("sese.023.001.09",),
        elements=("SttlmDt", "TradDt"),
        systems=("Settlement Engine", "Market Calendar"),
        keywords=("settlement date", "trade date", "t+1", "cycle", "sttlmdt"),
    ),
)

SEED_DEFECTS: tuple[SeedDefect, ...] = (
    SeedDefect(
        id="DEF-001",
        domain="Payments",
        name="Cross-border batch rejected — account identifier not IBAN",
        summary=(
            "142 payments to Spanish beneficiaries rejected by the correspondent. "
            "The channel sent sort code and account number in Othr/Id with no IBAN."
        ),
        symptom="Rejected by beneficiary bank: invalid account identifier",
        rule_id="BR-001",
        message_type="pacs.008.001.10",
        keywords=("invalid account", "iban", "reject", "othr"),
    ),
    SeedDefect(
        id="DEF-002",
        domain="Cash",
        name="Statement quarantined — closing balance mismatch",
        summary=(
            "Intraday sweep entries were booked after the statement cut-off, so "
            "entries did not sum to the closing balance and the file was held."
        ),
        symptom="Statement rejected: closing balance does not equal opening plus entries",
        rule_id="BR-004",
        message_type="camt.053.001.10",
        keywords=("closing balance", "mismatch", "quarantine", "cut-off"),
    ),
    SeedDefect(
        id="DEF-003",
        domain="Trade",
        name="Guarantee amendment returned — original reference absent",
        summary=(
            "An amendment issued from the new ISO flow omitted the original "
            "undertaking identifier and was returned by the advising bank."
        ),
        symptom="Returned by advising bank: undertaking reference not recognised",
        rule_id="BR-007",
        message_type="tsrv.001.001.01",
        keywords=("undertaking", "reference", "amendment", "returned"),
    ),
)


def _element_node_id(message_type: str, name: str) -> str:
    return f"EL-{message_type}-{name}"


def _link_elements(store: ks.KnowledgeStore, rule: SeedRule) -> list[str]:
    """
    Resolve a rule's element names against the vendored schemas.

    Returns the names that could not be resolved, so the UI can say "governs
    PlcOfSttlm — no vendored schema for sese" instead of showing a rule that
    appears to govern nothing.
    """
    if not rule.elements:
        return []
    try:
        from src.storage.schema_index import SchemaIndex

        index = SchemaIndex.load()
    except Exception as exc:  # noqa: BLE001 — seeding must never fail the app
        log.warning("Schema index unavailable while seeding: %s", exc)
        return list(rule.elements)

    unresolved: list[str] = []
    for name in rule.elements:
        # `SchemaIndex.search` widens to every schema when the requested
        # message type is not vendored, so the hit's own message type is
        # checked: a `sese` rule must not be linked to a payments element that
        # happens to share an element name.
        hits = [
            hit
            for message_type in rule.message_types
            for hit in index.search(name, message_type=message_type, limit=1)
            if hit.node.name.lower() == name.lower()
            and hit.message_type in rule.message_types
        ]
        if not hits:
            unresolved.append(name)
            continue
        for hit in hits:
            node_id = _element_node_id(hit.message_type, hit.node.name)
            store.put_node(
                node_id,
                ks.ISO_ELEMENT,
                hit.node.name,
                domain=rule.domain,
                summary=hit.business_label,
                detail={
                    "path": hit.node.path,
                    "message_type": hit.message_type,
                    "occurrence": hit.node.occurrence,
                    "mandatory": hit.node.mandatory,
                    "schema_file": hit.schema_file,
                },
                status=ks.SEEDED,
                confidence=100,
            )
            store.add_evidence(node_id, hit.citation())
            store.link(rule.id, node_id, ks.GOVERNS, confidence=90, source="seed")
    return unresolved


def seed(store: ks.KnowledgeStore, link_elements: bool = True) -> dict[str, int]:
    """
    Load the mocked rule set, systems and historical defects into *store*.

    Idempotent: node ids are deterministic, so re-seeding refreshes rather than
    duplicating.
    """
    for rule in SEED_RULES:
        store.put_rule(
            rule.id,
            rule.name,
            domain=rule.domain,
            condition=rule.condition,
            action=rule.action,
            severity=rule.severity,
            message_types=rule.message_types,
            elements=rule.elements,
            status=ks.SEEDED,
            confidence=100,
            source_kind="seed",
            detail={"keywords": list(rule.keywords), "systems": list(rule.systems)},
        )
        store.add_evidence(
            rule.id,
            f"{BANK} internal payments & trade standards (mocked demo policy, "
            f"not a published ISO 20022 requirement)",
        )
        unresolved = _link_elements(store, rule) if link_elements else list(rule.elements)
        if unresolved:
            store.merge_detail(rule.id, unresolved_elements=unresolved)
        for system in rule.systems:
            sys_id = f"SYS-{system}"
            store.put_node(
                sys_id, ks.SYSTEM, system,
                domain=rule.domain,
                summary=f"{BANK} application involved in {rule.domain.lower()} flows",
                status=ks.SEEDED,
                confidence=100,
            )
            store.link(rule.id, sys_id, ks.OWNED_BY, confidence=80, source="seed")

    for defect in SEED_DEFECTS:
        store.put_node(
            defect.id, ks.DEFECT, defect.name,
            domain=defect.domain,
            summary=defect.summary,
            detail={
                "symptom": defect.symptom,
                "message_type": defect.message_type,
                "keywords": list(defect.keywords),
                "resolved": True,
            },
            status=ks.SEEDED,
            confidence=100,
        )
        store.add_evidence(
            defect.id, f"{BANK} production incident record (mocked demo history)"
        )
        store.link(defect.id, defect.rule_id, ks.CAUSED, confidence=95, source="seed")

    counts = store.counts()
    log.info("Knowledge seeded: %d nodes, %d edges", counts["nodes"], counts["edges"])
    return {"nodes": counts["nodes"], "edges": counts["edges"]}


def seed_rule(rule_id: str) -> Optional[SeedRule]:
    for rule in SEED_RULES:
        if rule.id == rule_id:
            return rule
    return None


def keywords_for(rule_ids: Sequence[str]) -> tuple[str, ...]:
    """Search keywords of the named seeded rules, for symptom matching."""
    out: list[str] = []
    for rule_id in rule_ids:
        rule = seed_rule(rule_id)
        if rule:
            out.extend(rule.keywords)
    return tuple(dict.fromkeys(out))
