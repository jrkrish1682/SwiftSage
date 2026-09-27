"""
Tests for the institutional knowledge graph and the RCA engine.

Every test opens its own SQLite file under `tmp_path`, so nothing here touches
the demo database in `data/knowledge/`. No Anthropic key is needed: the store,
the seeds and the RCA ranking are all deterministic.
"""
from __future__ import annotations

import pytest

from src.knowledge import graph as kgraph
from src.knowledge import rca
from src.knowledge import store as ks
from src.knowledge.seeds import SEED_DEFECTS, SEED_RULES


@pytest.fixture()
def store(tmp_path) -> ks.KnowledgeStore:
    return ks.KnowledgeStore.open(tmp_path / "knowledge.db")


@pytest.fixture()
def empty_store(tmp_path) -> ks.KnowledgeStore:
    return ks.KnowledgeStore.open(tmp_path / "empty.db", seed=False)


# ── Store mechanics ───────────────────────────────────────────────────────────

def test_schema_is_created_on_open(empty_store):
    assert empty_store.path.exists()
    assert empty_store.counts()["nodes"] == 0


def test_put_node_round_trips_detail(empty_store):
    empty_store.put_node(
        "IF-1", ks.INTERNAL_FIELD, "AccountNumber",
        domain="Payments", detail={"system": "PaymentHub"},
    )
    node = empty_store.node("IF-1")
    assert node is not None
    assert node.detail["system"] == "PaymentHub"
    assert node.status == ks.CANDIDATE
    assert not node.authoritative


def test_confirmed_node_is_not_downgraded_by_re_observation(empty_store):
    empty_store.put_node("IF-1", ks.INTERNAL_FIELD, "Acct", status=ks.CANDIDATE)
    empty_store.set_status("IF-1", ks.CONFIRMED, confidence=90)
    empty_store.put_node(
        "IF-1", ks.INTERNAL_FIELD, "Acct", status=ks.CANDIDATE, confidence=40
    )
    node = empty_store.node("IF-1")
    assert node is not None
    assert node.status == ks.CONFIRMED
    assert node.confidence == 90


def test_edges_and_evidence_collapse_on_repeat(empty_store):
    empty_store.put_node("A", ks.RULE, "A")
    empty_store.put_node("B", ks.ISO_ELEMENT, "B")
    empty_store.link("A", "B", ks.GOVERNS)
    empty_store.link("A", "B", ks.GOVERNS, confidence=80)
    empty_store.add_evidence("A", "same citation")
    empty_store.add_evidence("A", "same citation")

    edges = empty_store.edges("A")
    assert len(edges) == 1
    assert edges[0].confidence == 80
    assert empty_store.evidence("A") == [("same citation", "")]


def test_next_id_continues_the_sequence(store):
    assert store.next_id("BR") == f"BR-{len(SEED_RULES) + 1:03d}"
    assert store.next_id("DEF") == f"DEF-{len(SEED_DEFECTS) + 1:03d}"


def test_merge_detail_keeps_other_keys(store):
    store.merge_detail("BR-001", note="added")
    node = store.node("BR-001")
    assert node is not None
    assert node.detail["note"] == "added"
    assert node.detail["elements"]


# ── Seeds ─────────────────────────────────────────────────────────────────────

def test_seeding_covers_every_domain(store):
    counts = store.counts()
    assert counts["by_kind"][ks.RULE] == len(SEED_RULES)
    assert counts["by_kind"][ks.DEFECT] == len(SEED_DEFECTS)
    for domain in ks.DOMAINS:
        assert store.rules(domain=domain), f"no rules seeded for {domain}"


def test_seeded_rules_are_authoritative_but_flagged_as_mocked(store):
    rule = store.rule("BR-001")
    assert rule is not None
    assert rule.node.status == ks.SEEDED
    assert rule.node.authoritative
    assert "mocked" in " ".join(c for c, _ in store.evidence("BR-001")).lower()


def test_seeding_is_idempotent(store):
    before = store.counts()
    from src.knowledge.seeds import seed

    seed(store)
    assert store.counts() == before


def test_reset_restores_the_seeded_state(store):
    store.put_rule(
        "BR-900", "Invented", domain="Payments",
        condition="c", action="a", status=ks.CONFIRMED,
    )
    assert store.rule("BR-900") is not None
    store.reset()
    assert store.rule("BR-900") is None
    assert store.counts()["by_kind"][ks.RULE] == len(SEED_RULES)


def test_payments_rules_link_to_vendored_schema_elements(store):
    governed = store.edges("BR-001", relation=ks.GOVERNS)
    assert governed, "BR-001 should govern at least one ISO element"
    linked = [store.node(e.dst) for e in governed]
    assert all(n is not None and n.kind == ks.ISO_ELEMENT for n in linked)


def test_securities_rules_declare_unresolved_elements(store):
    rules = store.rules(domain="Securities/Settlement")
    assert rules
    unresolved = [r for r in rules if r.node.detail.get("unresolved_elements")]
    assert unresolved, (
        "no securities XSD is vendored, so those elements must be recorded as "
        "unresolved rather than linked to an unrelated schema"
    )


# ── Search and traversal ──────────────────────────────────────────────────────

def test_search_rules_finds_by_business_phrase(store):
    found = store.search_rules("iban")
    assert "BR-001" in {r.id for r in found}


def test_search_rules_excludes_candidates_by_default(store):
    store.put_rule(
        "BR-901", "Inferred guess", domain="Payments",
        condition="unicorn corridor", action="do something",
        status=ks.CANDIDATE,
    )
    assert not store.search_rules("unicorn")
    assert store.search_rules(
        "unicorn", statuses=(ks.CANDIDATE,)
    )[0].id == "BR-901"


def test_rules_filter_by_message_type(store):
    ids = {r.id for r in store.rules(message_type="camt.053.001.10")}
    assert {"BR-004", "BR-005", "BR-006"} <= ids
    assert "BR-001" not in ids


def test_neighbourhood_reaches_elements_and_incidents(store):
    hood = store.neighbourhood("BR-001", hops=1)
    assert hood is not None
    assert hood.centre.id == "BR-001"
    ids = {n.id for n in hood.nodes}
    assert "DEF-001" in ids


def test_graph_dot_marks_candidates_and_centre(store):
    store.put_node(
        "IF-9", ks.INTERNAL_FIELD, "GuessedField",
        domain="Payments", status=ks.CANDIDATE,
    )
    store.link("BR-001", "IF-9", ks.MAPS_TO)
    dot = kgraph.to_dot(store.neighbourhood("BR-001", hops=1))
    assert dot.startswith("digraph")
    assert "candidate" in dot
    assert "BR-001" in dot


# ── RCA ───────────────────────────────────────────────────────────────────────

_PACS = (
    '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pacs.008.001.10">'
    "<FIToFICstmrCdtTrf><GrpHdr><MsgId>M1</MsgId></GrpHdr>"
    "</FIToFICstmrCdtTrf></Document>"
)


def test_rca_ranks_the_matching_rule_first(store):
    report = rca.analyse(
        store,
        symptom="Rejected: invalid account identifier, IBAN missing for "
                "cross-border payment",
        message_type="pacs.008.001.10",
    )
    assert report.top is not None
    assert "BR-001" in report.top.rule_ids
    assert report.top.likelihood in ("HIGH", "MEDIUM")
    assert report.top.citations


def test_rca_detects_missing_mandatory_elements(store):
    report = rca.analyse(store, payload=_PACS, symptom="schema validation failed")
    assert report.message_type == "pacs.008.001.10"
    assert report.domain == "Payments"
    assert report.missing_mandatory
    assert any(f.category == rca.MISSING_MANDATORY for f in report.findings)


def test_rca_reports_unparseable_payload(store):
    report = rca.analyse(store, payload="<Document><oops>", symptom="failed")
    assert any(f.category == rca.UNPARSEABLE for f in report.findings)


def test_rca_matches_the_incident_history(store):
    report = rca.analyse(
        store,
        symptom="closing balance did not reconcile, statement quarantined",
        message_type="camt.053.001.10",
    )
    assert any(f.category == rca.PAST_DEFECT for f in report.findings)


def test_rca_finds_nothing_rather_than_guessing(store):
    report = rca.analyse(store, symptom="the printer is out of toner")
    assert report.findings == ()
    assert "No cause could be derived" in report.as_markdown()


def test_record_cause_writes_a_confirmed_incident(store):
    report = rca.analyse(
        store,
        symptom="IBAN missing for cross-border payment",
        message_type="pacs.008.001.10",
    )
    finding = report.top
    assert finding is not None
    defect_id = rca.record_cause(store, report, finding, note="channel sent Othr/Id")

    node = store.node(defect_id)
    assert node is not None
    assert node.status == ks.CONFIRMED
    assert node.kind == ks.DEFECT
    relations = {
        (e.src, e.dst) for e in store.edges(defect_id, relation=ks.CAUSED)
    }
    assert any(dst in finding.rule_ids for _, dst in relations)


def test_rules_in_play_are_authoritative_only(store):
    store.put_rule(
        "BR-902", "Unconfirmed", domain="Payments",
        condition="x", action="y", message_types=("pacs.008.001.10",),
        status=ks.CANDIDATE,
    )
    ids = {r.id for r in rca.rules_in_play(store, "pacs.008.001.10")}
    assert "BR-902" not in ids
    assert ids


def test_summarise_rules_names_status_and_id(store):
    text = rca.summarise_rules(store.rules(domain="Cash"))
    assert "BR-004" in text
    assert "seeded" in text
