"""
Tests for the chat grounding layer: schema index, glossary and lookup tools.
"""
from __future__ import annotations

import pytest

from src.agent.tools import compare_element_across_versions, lookup_iso20022_element
from src.connectors.schema_bundle import bundle_files
from src.storage import iso_glossary
from src.storage.schema_index import SchemaIndex
from src.ui import prompt_packs


@pytest.fixture(scope="module")
def index() -> SchemaIndex:
    return SchemaIndex.load()


# ── Index construction ─────────────────────────────────────────────────────


def test_index_covers_every_vendored_schema(index):
    assert len(index.message_types()) == len(bundle_files())
    for expected in ("pain.001.001.09", "pacs.008.001.10", "camt.053.001.10",
                     "tsrv.001.001.01", "tsmt.011.001.04"):
        assert expected in index.message_types()


def test_index_is_cached(index):
    assert SchemaIndex.load() is index


# ── Search ─────────────────────────────────────────────────────────────────


def test_exact_short_name_wins_over_substring(index):
    hits = index.search("ChrgBr", message_type="pain.001.001.09")
    assert hits[0].node.name == "ChrgBr"
    assert hits[0].message_type == "pain.001.001.09"


def test_business_phrase_resolves_to_iso_element(index):
    hits = index.search("beneficiary bank", message_type="pacs.008.001.10")
    assert hits[0].node.name == "CdtrAgt"


def test_path_fragment_resolves(index):
    hits = index.search("PmtId/EndToEndId", message_type="pain.001.001.09")
    assert hits[0].node.path.endswith("PmtId/EndToEndId")


def test_trade_phrase_resolves_in_tsrv(index):
    hits = index.search("guarantee amount", message_type="tsrv.001.001.01")
    assert hits[0].node.name == "UdrtkgAmt"


def test_scope_accepts_family_prefix(index):
    hits = index.search("Ntry", message_type="camt")
    assert hits
    assert {h.message_type.split(".")[0] for h in hits} == {"camt"}


def test_unknown_term_returns_no_hits(index):
    assert index.search("SanctionsHitFlag") == []


def test_empty_query_returns_no_hits(index):
    assert index.search("   ") == []


def test_single_character_query_does_not_match_everything(index):
    # A one-character needle must not substring-match the whole schema.
    assert len(index.search("a", limit=50)) <= 50
    assert all(h.node.name.lower() == "a" or h.node.path.lower() == "a"
               for h in index.search("a", limit=50))


# ── Hit rendering and citations ────────────────────────────────────────────


def test_hit_renders_structure_and_citation(index):
    hit = index.search("ChrgBr", message_type="pain.001.001.09")[0]
    rendered = hit.render()
    assert "Charge Bearer" in rendered
    assert "pain.001.001.09" in rendered
    assert "pain.001.001.09.xsd" in rendered
    assert "SHAR" in rendered           # code list came from the XSD
    assert hit.citation().count("·") == 2


def test_hit_without_glossary_entry_says_so(index):
    hit = next(
        h for h in index.search("Rcncltn", limit=5) + index.search("SplmtryData", limit=5)
        if h.glossary is None
    )
    assert "not in the curated glossary" in hit.render()


def test_mandatory_flag_comes_from_the_schema(index):
    hit = index.search("MsgId", message_type="pain.001.001.09")[0]
    assert hit.node.mandatory
    assert "mandatory" in hit.render()


# ── Version comparison ─────────────────────────────────────────────────────


def test_versions_of_reports_every_version_in_the_family(index):
    presences = index.versions_of("ChrgBr", message_type="pain")
    assert [p.message_type for p in presences] == ["pain.001.001.09", "pain.001.001.12"]
    assert all(p.present for p in presences)


def test_versions_of_stays_within_one_family(index):
    presences = index.versions_of("UdrtkgAmt")
    assert {p.message_type.split(".")[0] for p in presences} == {"tsrv"}


def test_versions_of_unknown_term_is_empty(index):
    assert index.versions_of("SanctionsHitFlag") == []


# ── Glossary ───────────────────────────────────────────────────────────────


def test_glossary_lookup_is_case_and_attribute_insensitive():
    assert iso_glossary.lookup("uetr") is iso_glossary.lookup("UETR")
    assert iso_glossary.lookup("@Ccy") is iso_glossary.lookup("Ccy")


def test_glossary_names_are_unique():
    names = [e.name.lower() for e in iso_glossary.entries()]
    assert len(names) == len(set(names))


def test_glossary_search_terms_include_aliases():
    terms = iso_glossary.search_terms("Cdtr")
    assert "creditor" in terms
    assert "beneficiary" in terms


# ── Tools ──────────────────────────────────────────────────────────────────


def test_lookup_tool_returns_grounded_text():
    out = lookup_iso20022_element.invoke(
        {"term": "charges", "message_type": "pain.001.001.09"}
    )
    assert "Charge Bearer" in out
    assert "pain.001.001.09.xsd" in out


def test_lookup_tool_refuses_to_invent_unknown_elements():
    out = lookup_iso20022_element.invoke({"term": "SanctionsHitFlag"})
    assert "matches no element" in out
    assert "rather than" in out          # instructs the model not to improvise


def test_version_tool_lists_presence_per_version():
    out = compare_element_across_versions.invoke(
        {"term": "UETR", "message_type": "pacs.008"}
    )
    assert "pacs.008.001.08" in out
    assert "pacs.008.001.10" in out
    assert "present" in out


def test_version_tool_handles_unknown_term():
    out = compare_element_across_versions.invoke({"term": "SanctionsHitFlag"})
    assert "matches no element" in out


# ── Prompt packs ───────────────────────────────────────────────────────────


def test_every_pack_has_questions():
    assert prompt_packs.pack_names()[0] == prompt_packs.DEFAULT_PACK
    for name in prompt_packs.pack_names():
        prompts = prompt_packs.prompts_for(name)
        assert len(prompts) == 3
        assert all(p.endswith("?") for p in prompts)


def test_unknown_pack_falls_back_to_default():
    assert prompt_packs.prompts_for("Nonexistent") == prompt_packs.prompts_for(
        prompt_packs.DEFAULT_PACK
    )
