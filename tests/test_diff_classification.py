"""
Regression tests for business-path resolution and severity classification on
namespaced ISO 20022 documents.

xmldiff reports positional XPaths (/*/*[2]/*[4]) for namespaced trees. When the
comparator does not resolve those back to element names, every tag-based rule
silently stops matching and nothing is ever reported as BREAKING.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

NS = 'xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"'


def _doc(amount="1000.00", ccy="EUR", iban="DE89370400440532013000",
         exec_date="2024-01-05", extra="", drop_iban=False):
    creditor = "" if drop_iban else f"<CdtrAcct><Id><IBAN>{iban}</IBAN></Id></CdtrAcct>"
    return f"""<?xml version="1.0"?>
<Document {NS}>
  <CstmrCdtTrfInitn>
    <GrpHdr>
      <MsgId>MSG-001</MsgId>
      <CreDtTm>2024-01-01T10:00:00</CreDtTm>
      <NbOfTxs>1</NbOfTxs>
    </GrpHdr>
    <PmtInf>
      <PmtMtd>TRF</PmtMtd>
      <ReqdExctnDt><Dt>{exec_date}</Dt></ReqdExctnDt>
      <CdtTrfTxInf>
        <Amt><InstdAmt Ccy="{ccy}">{amount}</InstdAmt></Amt>
        {creditor}
        <RmtInf><Ustrd>Invoice 1</Ustrd></RmtInf>
        {extra}
      </CdtTrfTxInf>
    </PmtInf>
  </CstmrCdtTrfInitn>
</Document>"""


@pytest.fixture
def compare(tmp_path):
    from src.comparator.xml_comparator import XMLComparator

    def _compare(doc_a: str, doc_b: str, schema_path=None):
        a = tmp_path / "a.xml"
        b = tmp_path / "b.xml"
        a.write_text(doc_a, encoding="utf-8")
        b.write_text(doc_b, encoding="utf-8")
        return XMLComparator().compare(a, b, schema_path=schema_path)

    return _compare


def _find(result, element):
    return [d for d in result.diffs if d.element == element]


class TestBusinessPathResolution:
    def test_paths_are_named_not_positional(self, compare):
        result = compare(_doc(), _doc(amount="2000.00"))
        assert result.diffs
        assert all("*" not in d.xpath for d in result.diffs), \
            [d.xpath for d in result.diffs]

    def test_raw_positional_xpath_is_kept_for_traceability(self, compare):
        result = compare(_doc(), _doc(amount="2000.00"))
        assert all(d.raw_xpath for d in result.diffs)

    def test_added_element_reported_under_its_parent(self, compare):
        result = compare(_doc(), _doc(extra="<Purp><Cd>SALA</Cd></Purp>"))
        purp = _find(result, "Purp")
        assert purp, [d.xpath for d in result.diffs]
        assert purp[0].xpath.endswith("/CdtTrfTxInf/Purp")

    def test_added_element_text_folded_into_the_insertion(self, compare):
        result = compare(_doc(), _doc(extra="<Purp><Cd>SALA</Cd></Purp>"))
        cd = _find(result, "Cd")
        assert len(cd) == 1
        assert cd[0].new_value == "SALA"


class TestSeverityOnNamespacedDocuments:
    def test_amount_change_is_breaking(self, compare):
        from src.comparator.diff_classifier import Severity
        result = compare(_doc(), _doc(amount="2000.00"))
        assert result.breaking
        assert _find(result, "InstdAmt")[0].severity == Severity.BREAKING

    def test_currency_attribute_change_is_breaking(self, compare):
        from src.comparator.diff_classifier import Severity
        result = compare(_doc(), _doc(ccy="USD"))
        ccy = [d for d in result.diffs if d.element == "@Ccy"]
        assert ccy, [d.xpath for d in result.diffs]
        assert ccy[0].severity == Severity.BREAKING

    def test_iban_change_is_breaking(self, compare):
        from src.comparator.diff_classifier import Severity
        result = compare(_doc(), _doc(iban="FR7630006000011234567890189"))
        assert _find(result, "IBAN")[0].severity == Severity.BREAKING

    def test_removed_critical_element_is_breaking(self, compare):
        from src.comparator.diff_classifier import Severity
        result = compare(_doc(), _doc(drop_iban=True))
        assert any(d.severity == Severity.BREAKING for d in result.diffs)

    def test_execution_date_change_is_warning(self, compare):
        from src.comparator.diff_classifier import Severity
        result = compare(_doc(), _doc(exec_date="2024-02-09"))
        assert _find(result, "Dt")[0].severity == Severity.WARNING

    def test_ignored_identifiers_produce_no_diffs(self, compare):
        doc_b = _doc().replace("MSG-001", "MSG-777").replace(
            "2024-01-01T10:00:00", "2024-06-06T23:59:00")
        result = compare(_doc(), doc_b)
        assert result.diffs == []
        assert result.breaking_score == 0.0

    def test_score_rises_with_breaking_changes(self, compare):
        benign = compare(_doc(), _doc(extra="<Purp><Cd>SALA</Cd></Purp>"))
        breaking = compare(_doc(), _doc(amount="2000.00", ccy="USD"))
        assert breaking.breaking_score > benign.breaking_score


class TestScoreExplainability:
    def test_breakdown_accounts_for_every_diff(self, compare):
        result = compare(_doc(), _doc(amount="2000.00", exec_date="2024-03-03"))
        assert sum(row["count"] for row in result.score_breakdown) == len(result.diffs)

    def test_contributions_sum_to_the_score(self, compare):
        result = compare(_doc(), _doc(amount="2000.00", exec_date="2024-03-03"))
        total = sum(row["score_contribution"] for row in result.score_breakdown)
        assert abs(total - result.breaking_score) < 0.5

    def test_weights_are_configurable(self):
        from src.comparator.diff_classifier import DiffClassifier, Severity
        strict = DiffClassifier(weights={Severity.WARNING: 10})
        assert strict.breaking_score([Severity.WARNING]) == 100.0
        assert DiffClassifier().breaking_score([Severity.WARNING]) == 30.0


class TestSchemaAwareClassification:
    SCHEMA = """<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="Purp" minOccurs="1"/>
  <xs:element name="Ustrd" minOccurs="0"/>
</xs:schema>"""

    @pytest.fixture
    def schema_file(self, tmp_path):
        p = tmp_path / "schema.xsd"
        p.write_text(self.SCHEMA, encoding="utf-8")
        return p

    def test_cardinality_index_reads_min_occurs(self, schema_file):
        from src.comparator.schema_cardinality import SchemaCardinality
        card = SchemaCardinality.from_xsd(schema_file)
        assert card is not None
        assert card.is_mandatory("/Document/PmtInf/Purp") is True
        assert card.is_mandatory("/Document/PmtInf/RmtInf/Ustrd") is False
        assert card.is_mandatory("/Document/PmtInf/Unknown") is None

    def test_new_mandatory_element_is_breaking(self, compare, schema_file):
        from src.comparator.diff_classifier import Severity
        result = compare(_doc(), _doc(extra="<Purp><Cd>SALA</Cd></Purp>"),
                         schema_path=schema_file)
        assert result.schema_aware is True
        purp = [d for d in result.diffs if d.element == "Purp"]
        assert purp[0].severity == Severity.BREAKING

    def test_without_schema_added_element_is_info(self, compare):
        from src.comparator.diff_classifier import Severity
        result = compare(_doc(), _doc(extra="<Purp><Cd>SALA</Cd></Purp>"))
        assert result.schema_aware is False
        purp = [d for d in result.diffs if d.element == "Purp"]
        assert purp[0].severity == Severity.INFO
