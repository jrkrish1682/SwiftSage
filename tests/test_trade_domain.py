"""
Tests for the trade-finance demo: vendored tsrv/tsmt schemas, the guarantee
amendment and baseline-report upgrade scenarios, and the tsrv gap register.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

ROOT = Path(__file__).parent.parent
TRADE = ROOT / "data" / "samples" / "trade"
GUARANTEE_V1 = TRADE / "tsrv001_guarantee_v1.xml"
GUARANTEE_V2 = TRADE / "tsrv001_guarantee_v2.xml"
BASELINE_V3 = TRADE / "tsmt011_baseline_v3.xml"
BASELINE_V4 = TRADE / "tsmt011_baseline_v4.xml"
TSRV_XSD = ROOT / "data" / "standards" / "tsrv" / "tsrv.001.001.01.xsd"
TSMT_V3_XSD = ROOT / "data" / "standards" / "tsmt" / "tsmt.011.001.03.xsd"
TSMT_V4_XSD = ROOT / "data" / "standards" / "tsmt" / "tsmt.011.001.04.xsd"
INTERNAL_GUARANTEE = ROOT / "data" / "samples" / "internal" / "sample_bank_guarantee.xml"


@pytest.fixture(scope="module")
def amendment():
    from src.comparator.xml_comparator import XMLComparator
    return XMLComparator().compare(GUARANTEE_V1, GUARANTEE_V2, schema_path=TSRV_XSD)


@pytest.fixture(scope="module")
def tsmt_upgrade():
    from src.comparator.xml_comparator import XMLComparator
    return XMLComparator().compare(BASELINE_V3, BASELINE_V4, schema_path=TSMT_V4_XSD)


class TestTradeSchemasAndSamples:
    def test_bundle_ships_the_trade_families(self):
        from src.connectors.schema_bundle import bundle_files
        families = {f.parent.name for f in bundle_files()}
        assert {"tsrv", "tsmt"} <= families

    def test_schema_lookup_resolves_trade_messages_offline(self, tmp_path, monkeypatch):
        from src.connectors.iso20022_connector import ISO20022Connector
        from src.storage.standards_library import StandardsLibrary

        connector = ISO20022Connector(library=StandardsLibrary(tmp_path / "library"))
        monkeypatch.setattr(connector, "_fetch_latest_release", lambda: None)
        path = connector.fetch_schema_for_message("tsrv.001.001.01")
        assert path is not None and path.name == "tsrv.001.001.01.xsd"

    def test_samples_validate_against_their_own_schemas(self):
        from lxml import etree
        pairs = (
            (GUARANTEE_V1, TSRV_XSD), (GUARANTEE_V2, TSRV_XSD),
            (BASELINE_V3, TSMT_V3_XSD), (BASELINE_V4, TSMT_V4_XSD),
        )
        for sample, schema in pairs:
            validator = etree.XMLSchema(etree.parse(str(schema)))
            assert validator.validate(etree.parse(str(sample))), \
                f"{sample.name} is not valid against {schema.name}"

    def test_trade_families_are_named_in_business_terms(self):
        from src.utils.helpers import ISO20022_MESSAGE_SETS
        assert "Trade Services" in ISO20022_MESSAGE_SETS["tsrv"]
        assert "Trade Services" in ISO20022_MESSAGE_SETS["tsmt"]

    def test_internal_guarantee_sample_parses_into_mappable_fields(self):
        from src.transformer.message_parser import parse_xml_fields
        fields = parse_xml_fields(INTERNAL_GUARANTEE.read_text(encoding="utf-8"))
        names = {f.name for f in fields}
        assert {"GuaranteeAmount", "ExpiryDate", "GoverningRules"} <= names


class TestGuaranteeAmendment:
    def test_message_types_are_detected(self, amendment):
        assert amendment.message_type_a == "tsrv.001.001.01"
        assert amendment.message_type_b == "tsrv.001.001.01"

    def test_terms_of_the_undertaking_are_breaking(self, amendment):
        from src.comparator.diff_classifier import Severity
        breaking = {
            d.element for d in amendment.diffs if d.severity == Severity.BREAKING
        }
        # amount, tolerance, wording, governing rules and expiry date
        assert {"Amt", "PlusTlrnce", "Txt", "Cd", "Dt"} <= breaking

    def test_additional_information_is_not_breaking(self, amendment):
        from src.comparator.diff_classifier import Severity
        note = [d for d in amendment.diffs if d.element == "AddtlInf"]
        assert len(note) == 1
        assert note[0].severity != Severity.BREAKING

    def test_changes_are_reported_in_trade_finance_language(self, amendment):
        from src.comparator.impact_report import business_flow
        flows = {d.element: business_flow(d) for d in amendment.diffs}
        assert flows["Amt"] == "Guarantee amount and bank exposure"
        assert flows["Dt"] == "Expiry and claim window"
        assert "Governing rules" in flows["Cd"]
        assert "Undertaking wording" in flows["Txt"]

    def test_impact_report_names_the_trade_message(self, amendment):
        from src.comparator.impact_report import markdown_impact_report
        md = markdown_impact_report(amendment)
        assert "tsrv.001.001.01" in md
        assert "Guarantee amount and bank exposure" in md


class TestBaselineReportUpgrade:
    def test_version_change_is_breaking(self, tsmt_upgrade):
        from src.comparator.diff_classifier import Severity
        assert tsmt_upgrade.message_type_a == "tsmt.011.001.03"
        assert tsmt_upgrade.message_type_b == "tsmt.011.001.04"
        version = [d for d in tsmt_upgrade.diffs if d.element == "@xmlns"]
        assert len(version) == 1 and version[0].severity == Severity.BREAKING

    def test_new_mandatory_wrapper_is_breaking(self, tsmt_upgrade):
        from src.comparator.diff_classifier import Severity
        from src.comparator.impact_report import business_flow
        added = [d for d in tsmt_upgrade.diffs if d.element == "UnitOfMeasr"]
        assert added
        assert all(d.severity == Severity.BREAKING for d in added)
        assert all("units of measure" in business_flow(d) for d in added)


class TestTradeGapAnalysis:
    def test_trade_target_uses_the_trade_mandatory_fields(self):
        from src.transformer import gap_analyzer
        gaps = gap_analyzer.analyze([], "tsrv.001.001.01")
        labels = {g.business_label for g in gaps}
        assert {"Undertaking Amount", "Expiry Date", "Governing Rules"} <= labels
        assert not any("Debtor" in label for label in labels)
        assert all(g.iso_xpath.startswith("UdrtkgIssncDtls/") for g in gaps)

    def test_unknown_trade_version_falls_back_within_its_own_family(self):
        from src.transformer import gap_analyzer
        gaps = gap_analyzer.analyze([], "tsrv.001.001.99")
        assert {g.business_label for g in gaps} == {
            g.business_label for g in gap_analyzer.analyze([], "tsrv.001.001.01")
        }

    def test_payment_targets_are_unchanged(self):
        from src.transformer import gap_analyzer
        labels = {g.business_label for g in gap_analyzer.analyze([], "pain.001.001.09")}
        assert "Debtor Name" in labels

    def test_mapper_prompt_context_is_target_specific(self):
        from src.transformer.field_mapper import target_context
        trade_context, trade_rules, trade_domain = target_context("tsrv.001.001.01")
        assert "UdrtkgAmt" in trade_context and "URDG" in trade_rules
        assert trade_domain == "trade finance"
        assert "IBAN" in target_context("pain.001.001.09")[0]
