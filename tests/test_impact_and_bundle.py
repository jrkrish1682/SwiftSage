"""
Tests for the offline schema bundle, the version-upgrade comparison, and the
business-readable impact assessment.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

ROOT = Path(__file__).parent.parent
BASELINE = ROOT / "data" / "samples" / "pain001_v1.xml"
UPGRADE = ROOT / "data" / "samples" / "pain001_v12_upgrade.xml"
SCHEMA_09 = ROOT / "data" / "standards" / "pain" / "pain.001.001.09.xsd"
SCHEMA_12 = ROOT / "data" / "standards" / "pain" / "pain.001.001.12.xsd"


# ── Vendored schema bundle ────────────────────────────────────────────────────

class TestSchemaBundle:
    def test_bundle_ships_the_demo_message_families(self):
        from src.connectors.schema_bundle import bundle_files
        families = {f.parent.name for f in bundle_files()}
        assert {"pain", "pacs", "camt"} <= families

    def test_seeding_registers_artefacts_and_is_idempotent(self, tmp_path):
        from src.connectors.schema_bundle import bundle_files, seed_library
        from src.storage.standards_library import StandardsLibrary

        library = StandardsLibrary(tmp_path / "library")
        added = seed_library(library)
        assert added == len(bundle_files())
        assert seed_library(library) == 0
        assert library.get_artifact_path("pain.001.001.09-xsd").exists()

    def test_sync_falls_back_to_the_bundle_without_network(self, tmp_path, monkeypatch):
        from src.connectors.iso20022_connector import ISO20022Connector
        from src.storage.standards_library import StandardsLibrary

        library = StandardsLibrary(tmp_path / "library")
        connector = ISO20022Connector(library=library)
        monkeypatch.setattr(connector, "_fetch_latest_release", lambda: None)

        result = connector.sync(message_sets=["pain", "pacs", "camt"])
        assert result["source"] == "vendored bundle"
        assert result["artifacts_added"] > 0
        assert library.list_artifacts(message_set="camt", artifact_type="xsd")

    def test_schema_lookup_resolves_from_the_bundle(self, tmp_path, monkeypatch):
        from src.connectors.iso20022_connector import ISO20022Connector
        from src.storage.standards_library import StandardsLibrary

        connector = ISO20022Connector(library=StandardsLibrary(tmp_path / "library"))
        monkeypatch.setattr(connector, "_fetch_latest_release", lambda: None)
        path = connector.fetch_schema_for_message("pain.001.001.12")
        assert path is not None and path.name == "pain.001.001.12.xsd"


# ── pain.001.001.09 → .12 upgrade scenario ────────────────────────────────────

@pytest.fixture(scope="module")
def upgrade_result():
    from src.comparator.xml_comparator import XMLComparator
    return XMLComparator().compare(BASELINE, UPGRADE, schema_path=SCHEMA_12)


class TestVersionUpgradeScenario:
    def test_samples_validate_against_their_own_schemas(self):
        from lxml import etree
        for sample, schema in ((BASELINE, SCHEMA_09), (UPGRADE, SCHEMA_12)):
            validator = etree.XMLSchema(etree.parse(str(schema)))
            assert validator.validate(etree.parse(str(sample))), \
                f"{sample.name} is not valid against {schema.name}"

    def test_version_change_is_reported_as_breaking(self, upgrade_result):
        from src.comparator.diff_classifier import Severity
        assert upgrade_result.message_type_a == "pain.001.001.09"
        assert upgrade_result.message_type_b == "pain.001.001.12"
        version = [d for d in upgrade_result.diffs if d.element == "@xmlns"]
        assert len(version) == 1
        assert version[0].severity == Severity.BREAKING

    def test_namespace_change_alone_does_not_flood_the_diff(self, upgrade_result):
        """Every reported diff is a real payload change, not a namespace artefact."""
        elements = {d.element for d in upgrade_result.diffs}
        assert elements == {
            "@xmlns", "InitnSrc", "Nm", "Prvdr", "Vrsn",
            "MndtRltdInf", "MndtId", "DtOfSgntr",
        }

    def test_new_optional_elements_are_informational(self, upgrade_result):
        from src.comparator.diff_classifier import Severity
        added = [d for d in upgrade_result.diffs if d.element in ("InitnSrc", "MndtRltdInf")]
        assert added
        assert all(d.severity == Severity.INFO for d in added)


# ── Impact assessment ─────────────────────────────────────────────────────────

class TestImpactReport:
    def test_markdown_covers_summary_score_and_actions(self, upgrade_result):
        from src.comparator.impact_report import markdown_impact_report
        md = markdown_impact_report(upgrade_result)
        for section in ("Executive summary", "How the score is calculated",
                        "Breaking changes and affected business flows",
                        "Severity definitions"):
            assert section in md
        assert "pain.001.001.12" in md
        assert f"{upgrade_result.breaking_score}/100" in md

    def test_markdown_handles_an_identical_pair(self, tmp_path):
        from src.comparator.impact_report import markdown_impact_report
        from src.comparator.xml_comparator import XMLComparator
        result = XMLComparator().compare(BASELINE, BASELINE)
        md = markdown_impact_report(result)
        assert "No breaking changes were found" in md
        assert "no change was classified as BREAKING" in md

    def test_word_report_is_a_docx(self, upgrade_result):
        from src.comparator.impact_report import word_impact_report
        data = word_impact_report(upgrade_result, prepared_for="Payments Programme")
        assert data[:2] == b"PK"
        assert len(data) > 5_000

    def test_business_flow_is_derived_from_the_path(self):
        from src.comparator.diff_classifier import ChangeType, Severity
        from src.comparator.impact_report import business_flow
        from src.comparator.xml_comparator import DiffEntry

        entry = DiffEntry(
            xpath="/Document/CstmrCdtTrfInitn/PmtInf/CdtTrfTxInf/Amt/InstdAmt",
            change_type=ChangeType.MODIFIED, old_value="1", new_value="2",
            severity=Severity.BREAKING, element="InstdAmt",
        )
        assert "instructed amount" in business_flow(entry)

        nested = DiffEntry(
            xpath="/Document/CstmrCdtTrfInitn/PmtInf/CdtTrfTxInf/RmtInf/Ustrd",
            change_type=ChangeType.MODIFIED, old_value="a", new_value="b",
            severity=Severity.INFO, element="Ustrd",
        )
        assert "Remittance" in business_flow(nested)

    def test_malformed_input_reports_a_parse_error_not_an_empty_diff(self, tmp_path):
        """A corrupt document must not read as 'no differences'."""
        from src.comparator.xml_comparator import XMLComparator

        broken = tmp_path / "broken.xml"
        broken.write_text("<Document><GrpHdr></Document>")

        result = XMLComparator().compare(broken, BASELINE)
        assert result.parse_error and str(broken) in result.parse_error
        assert result.diffs == []
        assert result.to_dict()["parse_error"] == result.parse_error

        reverse = XMLComparator().compare(BASELINE, broken)
        assert reverse.parse_error and str(broken) in reverse.parse_error

        assert XMLComparator().compare(BASELINE, BASELINE).parse_error is None

    def test_risk_rating_tracks_the_score(self):
        from src.comparator.impact_report import risk_rating
        assert risk_rating(0.0, 0) == "LOW"
        assert risk_rating(90.0, 5) == "HIGH"
        assert risk_rating(30.0, 2) == "MEDIUM"
        assert risk_rating(10.0, 1) == "LOW-MEDIUM"
