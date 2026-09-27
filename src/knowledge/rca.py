"""
Root-cause analysis over the knowledge graph and the vendored schemas.

A production reject ("invalid account identifier", "statement does not balance")
normally starts a hunt: find someone who knows the flow, find the mapping
spreadsheet, work out which rule was not applied. Everything needed to shortcut
that is already in the repository — the schema says what is mandatory and which
version an element exists in, and the knowledge graph holds the institution's
own rules and what previously failed.

So this module is deliberately **deterministic and offline**: no model call, no
API key, and every finding carries the citation it was derived from. A ranked
list a BA can check beats a fluent paragraph they cannot, and an RCA that only
works when a key is applied is useless during an incident.

Recording the confirmed cause writes a `defect` node back into the graph with a
`caused` edge to the rule, which is what makes the next similar failure faster
to explain — the learning loop, with a human in it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from lxml import etree

from src.knowledge import store as ks
from src.utils.helpers import get_logger, message_type_from_namespace

log = get_logger(__name__)

# Finding categories, in the order a BA would work through them.
MISSING_MANDATORY = "Mandatory element missing"
RULE_NOT_APPLIED = "Business rule not applied"
PAST_DEFECT = "Matches a previous incident"
VERSION_MISMATCH = "Element not in this message version"
UNPARSEABLE = "Payload could not be parsed"

_DOMAIN_BY_FAMILY = {
    "pain": "Payments",
    "pacs": "Payments",
    "camt": "Cash",
    "tsrv": "Trade",
    "tsmt": "Trade",
    "sese": "Securities/Settlement",
    "semt": "Securities/Settlement",
}

_STOP = {
    "the", "and", "for", "with", "this", "that", "was", "not", "has", "have",
    "from", "into", "error", "failed", "failure", "message", "payment", "reject",
    "rejected", "invalid", "missing", "does", "must", "been", "were", "field",
}
_WORD = re.compile(r"[a-zA-Z][a-zA-Z0-9\-\+]{2,}")
_ELEMENT_LIKE = re.compile(r"\b([A-Z][a-zA-Z]{1,3}(?:[A-Z][a-zA-Z]{1,6}){1,4})\b")

_HIGH = 60
_MEDIUM = 30


@dataclass(frozen=True)
class Finding:
    """One ranked probable cause."""

    id: str
    category: str
    title: str
    explanation: str
    score: int
    citations: tuple[str, ...] = ()
    rule_ids: tuple[str, ...] = ()
    node_ids: tuple[str, ...] = ()

    @property
    def likelihood(self) -> str:
        if self.score >= _HIGH:
            return "HIGH"
        return "MEDIUM" if self.score >= _MEDIUM else "LOW"


@dataclass(frozen=True)
class RcaReport:
    """The whole analysis: what was inspected, and what it concluded."""

    message_type: str
    domain: str
    findings: tuple[Finding, ...] = ()
    checks: tuple[str, ...] = ()
    elements_present: int = 0
    missing_mandatory: tuple[str, ...] = ()
    symptom_terms: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default=())

    @property
    def top(self) -> Optional[Finding]:
        return self.findings[0] if self.findings else None

    def as_markdown(self) -> str:
        lines = [
            "# Root cause analysis",
            "",
            f"- Message version: **{self.message_type or 'not identified'}**"
            f" ({self.domain or 'domain not identified'})",
            f"- Elements found in payload: {self.elements_present}",
            f"- Checks run: {', '.join(self.checks) or 'none'}",
            "",
            "## Probable causes",
            "",
        ]
        if not self.findings:
            lines.append(
                "No cause could be derived from the schema or the knowledge "
                "graph. Nothing is asserted rather than guessed."
            )
        for finding in self.findings:
            lines += [
                f"### {finding.id} — {finding.title}",
                f"*{finding.category} · likelihood {finding.likelihood}"
                f" (score {finding.score})*",
                "",
                finding.explanation,
                "",
            ]
            if finding.citations:
                lines.append("Evidence:")
                lines += [f"- {c}" for c in finding.citations]
                lines.append("")
        if self.notes:
            lines += ["## Notes", ""] + [f"- {n}" for n in self.notes]
        return "\n".join(lines)


# ── Payload inspection ────────────────────────────────────────────────────────

def _parse(payload: str) -> tuple[Optional[etree._Element], str]:
    text = (payload or "").strip()
    if not text:
        return None, ""
    try:
        root = etree.fromstring(text.encode("utf-8"))
    except etree.XMLSyntaxError as exc:
        return None, f"{exc}"
    return root, ""


def _paths_and_names(root: etree._Element) -> tuple[set[str], set[str]]:
    """Every element path (namespace-stripped) and short name in the payload."""
    paths: set[str] = set()
    names: set[str] = set()
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        parts: list[str] = []
        node: Optional[etree._Element] = element
        while node is not None and isinstance(node.tag, str):
            parts.append(etree.QName(node).localname)
            node = node.getparent()
        parts.reverse()
        paths.add("/".join(parts))
        names.add(parts[-1])
    return paths, names


def _message_type(root: Optional[etree._Element], hint: str) -> str:
    if hint.strip():
        return hint.strip()
    if root is None:
        return ""
    namespace = etree.QName(root).namespace or ""
    return message_type_from_namespace(namespace) or ""


def _terms(text: str) -> tuple[str, ...]:
    found = [w.lower() for w in _WORD.findall(text or "")]
    return tuple(dict.fromkeys(w for w in found if w not in _STOP))


def _mentioned_elements(text: str) -> tuple[str, ...]:
    """ISO-style short names quoted in an error message (`RmtInf`, `CdtrAcct`)."""
    return tuple(dict.fromkeys(_ELEMENT_LIKE.findall(text or "")))


# ── Checks ────────────────────────────────────────────────────────────────────

def _missing_mandatory(message_type: str, paths: set[str]) -> list[str]:
    """Mandatory leaves of the target schema that the payload does not carry."""
    from src.transformer.target_schema import TargetSchema

    schema = TargetSchema.for_message_type(message_type)
    if schema is None:
        return []
    # Schema paths omit the `Document` root that the payload carries, so both
    # the full and root-stripped payload paths are held.
    present = set(paths) | {p.split("/", 1)[-1] for p in paths if "/" in p}
    missing: list[str] = []
    for node in schema.mandatory_leaves():
        if node.path in present:
            continue
        # An element is only reported missing when its parent is present,
        # otherwise one absent block produces a page of derived noise.
        parent = node.path.rsplit("/", 1)[0] if "/" in node.path else ""
        if parent and parent not in present:
            continue
        missing.append(node.path)
    return missing


def _score_rule(
    rule: ks.Rule,
    terms: Sequence[str],
    mentioned: Sequence[str],
    missing: Sequence[str],
    names: set[str],
) -> tuple[int, list[str]]:
    """How well a rule explains the symptom, and why."""
    score = 0
    reasons: list[str] = []
    keywords = [str(k).lower() for k in (rule.node.detail.get("keywords") or ())]
    hits = [k for k in keywords if any(k in t or t in k for t in terms)]
    blob = " ".join(terms)
    hits += [k for k in keywords if " " in k and k in blob and k not in hits]
    if hits:
        score += 18 * min(len(hits), 3)
        reasons.append("symptom mentions " + ", ".join(f"“{h}”" for h in hits[:3]))

    elements = [str(e) for e in rule.elements]
    named = [e for e in elements if e in mentioned]
    if named:
        score += 25
        reasons.append("error names " + ", ".join(named[:3]) + ", governed by this rule")

    absent = [e for e in elements if e in missing or (names and e not in names)]
    if absent and elements:
        score += 12
        reasons.append("payload does not carry " + ", ".join(absent[:3]))

    if rule.severity == "HIGH":
        score += 6
    return score, reasons


def _rule_findings(
    store: ks.KnowledgeStore,
    message_type: str,
    domain: str,
    terms: Sequence[str],
    mentioned: Sequence[str],
    missing: Sequence[str],
    names: set[str],
) -> list[Finding]:
    rules = store.rules(domain=domain, message_type=message_type)
    if not rules and domain:
        rules = store.rules(message_type=message_type)
    findings: list[Finding] = []
    for rule in rules:
        score, reasons = _score_rule(rule, terms, mentioned, missing, names)
        if score < 20:
            continue
        citations = [f"{rule.id} — {rule.name} ({rule.node.status_label})"]
        citations += [c for c, _ in store.evidence(rule.id)]
        findings.append(
            Finding(
                id=f"RC-{rule.id}",
                category=RULE_NOT_APPLIED,
                title=rule.name,
                explanation=(
                    f"{rule.condition} → {rule.action}\n\n"
                    f"Matched because {'; '.join(reasons)}."
                ),
                score=score,
                citations=tuple(citations),
                rule_ids=(rule.id,),
                node_ids=(rule.id,),
            )
        )
    return findings


def _defect_findings(
    store: ks.KnowledgeStore,
    message_type: str,
    terms: Sequence[str],
) -> list[Finding]:
    findings: list[Finding] = []
    for node in store.nodes(kind=ks.DEFECT, statuses=ks.AUTHORITATIVE):
        keywords = [str(k).lower() for k in (node.detail.get("keywords") or ())]
        symptom = str(node.detail.get("symptom", ""))
        blob = " ".join(terms)
        hits = [k for k in keywords if k in blob or any(k in t for t in terms)]
        same_type = str(node.detail.get("message_type", "")) == message_type
        if not hits and not (same_type and terms):
            continue
        score = 15 * min(len(hits), 3) + (14 if same_type else 0)
        if score < 20:
            continue
        caused = [e.dst for e in store.edges(node.id, relation=ks.CAUSED)]
        citations = [f"{node.id} — {node.summary}"]
        citations += [c for c, _ in store.evidence(node.id)]
        findings.append(
            Finding(
                id=f"RC-{node.id}",
                category=PAST_DEFECT,
                title=f"Same symptom as {node.id}: {node.name}",
                explanation=(
                    f"Reported symptom then: {symptom or 'not recorded'}.\n\n"
                    + (
                        "That incident was attributed to "
                        + ", ".join(caused)
                        + ", so check whether the same rule is unapplied here."
                        if caused
                        else "No rule was attributed to that incident."
                    )
                ),
                score=score,
                citations=tuple(citations),
                rule_ids=tuple(caused),
                node_ids=(node.id, *caused),
            )
        )
    return findings


def _version_findings(message_type: str, mentioned: Sequence[str]) -> list[Finding]:
    """Named elements that do not exist in this version but do in another."""
    if not message_type or not mentioned:
        return []
    try:
        from src.storage.schema_index import SchemaIndex

        index = SchemaIndex.load()
    except Exception as exc:  # noqa: BLE001 — a missing index must not break RCA
        log.warning("Schema index unavailable for RCA: %s", exc)
        return []

    findings: list[Finding] = []
    for name in mentioned:
        here = index.search(name, message_type=message_type, limit=1)
        if here and here[0].message_type == message_type:
            continue
        elsewhere = [
            p for p in index.versions_of(name) if p.present and p.message_type != message_type
        ]
        if not elsewhere:
            continue
        versions = ", ".join(p.message_type for p in elsewhere)
        findings.append(
            Finding(
                id=f"RC-VER-{name}",
                category=VERSION_MISMATCH,
                title=f"{name} does not exist in {message_type}",
                explanation=(
                    f"The error names {name}, but no element of that name is "
                    f"declared in {message_type}. It is declared in {versions}, "
                    "so the sender is probably building the message against a "
                    "different version of the schema."
                ),
                score=55,
                citations=tuple(
                    p.hit.citation() for p in elsewhere if p.hit is not None
                ),
            )
        )
    return findings


# ── Entry point ───────────────────────────────────────────────────────────────

def analyse(
    store: ks.KnowledgeStore,
    *,
    payload: str = "",
    symptom: str = "",
    message_type: str = "",
    domain: str = "",
) -> RcaReport:
    """
    Rank probable causes of a failure from the schema and the knowledge graph.

    `payload` is the failing message (XML; optional), `symptom` the reject or
    error text. Either alone is enough — an incident often arrives as a reject
    reason with no payload attached.
    """
    root, parse_error = _parse(payload)
    resolved_type = _message_type(root, message_type)
    family = resolved_type.split(".")[0] if resolved_type else ""
    resolved_domain = domain or _DOMAIN_BY_FAMILY.get(family, "")

    paths: set[str] = set()
    names: set[str] = set()
    if root is not None:
        paths, names = _paths_and_names(root)

    terms = _terms(symptom)
    mentioned = _mentioned_elements(symptom)
    checks: list[str] = []
    notes: list[str] = []
    findings: list[Finding] = []

    if payload.strip() and root is None:
        findings.append(
            Finding(
                id="RC-PARSE",
                category=UNPARSEABLE,
                title="The payload is not well-formed XML",
                explanation=(
                    "Parsing stopped before any analysis could run, which is "
                    f"itself a likely cause of the failure: {parse_error}"
                ),
                score=70,
            )
        )
        notes.append("Schema checks were skipped — the payload could not be parsed.")

    missing: list[str] = []
    if resolved_type and root is not None:
        missing = _missing_mandatory(resolved_type, paths)
        checks.append("mandatory elements against the vendored XSD")
        for element in missing[:6]:
            named = element.rsplit("/", 1)[-1] in mentioned
            findings.append(
                Finding(
                    id=f"RC-MAND-{element.rsplit('/', 1)[-1]}",
                    category=MISSING_MANDATORY,
                    title=f"Mandatory element absent: {element}",
                    explanation=(
                        f"{resolved_type} declares {element} as mandatory, and "
                        "the payload does not carry it. A receiving bank "
                        "validating against the XSD rejects the whole message."
                    ),
                    score=65 if named else 45,
                    citations=(f"{resolved_type} XSD — {element} is mandatory",),
                )
            )
    elif resolved_type:
        notes.append(
            "No payload supplied, so mandatory-element checks did not run — "
            "the analysis rests on the symptom text and the knowledge graph."
        )

    if terms or mentioned:
        checks.append("business rules in the knowledge graph")
        findings += _rule_findings(
            store, resolved_type, resolved_domain, terms, mentioned, missing, names
        )
        checks.append("previous incidents")
        findings += _defect_findings(store, resolved_type, terms)
        if mentioned:
            checks.append("element presence across message versions")
            findings += _version_findings(resolved_type, mentioned)
    else:
        notes.append(
            "No symptom text supplied, so rule and incident matching did not "
            "run; only the schema checks above contributed."
        )

    if not resolved_type:
        notes.append(
            "The message version could not be identified from the payload "
            "namespace, so schema-derived checks were skipped."
        )

    findings.sort(key=lambda f: (-f.score, f.id))
    return RcaReport(
        message_type=resolved_type,
        domain=resolved_domain,
        findings=tuple(findings),
        checks=tuple(dict.fromkeys(checks)),
        elements_present=len(paths),
        missing_mandatory=tuple(missing),
        symptom_terms=terms,
        notes=tuple(notes),
    )


def record_cause(
    store: ks.KnowledgeStore,
    report: RcaReport,
    finding: Finding,
    *,
    title: str = "",
    note: str = "",
    run_id: str = "",
) -> str:
    """
    Record a confirmed cause as a defect node, linked to the rule it violated.

    This is the only way a defect becomes `confirmed`: a human accepted one of
    the ranked findings. The edge it writes is what makes the next occurrence of
    the same symptom rank higher.
    """
    defect_id = store.next_id("DEF")
    store.put_node(
        defect_id,
        ks.DEFECT,
        title or finding.title,
        domain=report.domain,
        summary=note or finding.explanation.split("\n", 1)[0],
        detail={
            "symptom": " ".join(report.symptom_terms[:12]),
            "message_type": report.message_type,
            "keywords": list(report.symptom_terms[:8]),
            "category": finding.category,
            "resolved": False,
        },
        status=ks.CONFIRMED,
        confidence=90,
    )
    store.add_evidence(
        defect_id,
        f"Confirmed by a specialist from RCA finding {finding.id}"
        + (f" — {note}" if note else ""),
        run_id=run_id,
    )
    for rule_id in finding.rule_ids:
        store.link(defect_id, rule_id, ks.CAUSED, confidence=90, source="rca")
    for node_id in finding.node_ids:
        if node_id not in finding.rule_ids:
            store.link(defect_id, node_id, ks.DEPENDS_ON, confidence=60, source="rca")
    return defect_id


def rules_in_play(
    store: ks.KnowledgeStore, message_type: str, limit: int = 8
) -> list[ks.Rule]:
    """Authoritative rules for a message type — the context other tabs inject."""
    return store.rules(message_type=message_type)[:limit]


def summarise_rules(rules: Iterable[ks.Rule]) -> str:
    """Compact rendering for prompts; kept out of any cached system block."""
    return "\n\n".join(rule.render() for rule in rules)
