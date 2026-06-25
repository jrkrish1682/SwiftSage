"""
Unit tests for the XML Comparator and related components.

Run with:  python -m pytest tests/ -v
"""
import sys
from pathlib import Path

import pytest

# Make sure src is importable
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Fixtures ───────────────────────────────────────────────────────────────────

SAMPLE_DIR = Path(__file__).parent.parent / "data" / "samples"

PAIN001_V1 = SAMPLE_DIR / "pain001_v1.xml"
PAIN001_V2 = SAMPLE_DIR / "pain001_v2.xml"
PACS008 = SAMPLE_DIR / "pacs008_sample.xml"

SIMPLE_XML_A = """<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.09">
  <CstmrCdtTrfInitn>
    <GrpHdr>
      <MsgId>MSG-001</MsgId>
      <NbOfTxs>1</NbOfTxs>
      <CtrlSum>1000.00</CtrlSum>
    </GrpHdr>
    <PmtInf>
      <PmtMtd>TRF</PmtMtd>
      <CdtTrfTxInf>
        <Amt><InstdAmt Ccy="EUR">1000.00</InstdAmt></Amt>
        <CdtrAcct><Id><IBAN>DE89370400440532013000</IBAN></Id></CdtrAcct>
      </CdtTrfTxInf>
    </PmtInf>
  </CstmrCdtTrfInitn>
</Document>"""

SIMPLE_XML_B_AMOUNT_CHANGE = """<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.09">
  <CstmrCdtTrfInitn>
    <GrpHdr>
      <MsgId>MSG-002</MsgId>
      <NbOfTxs>1</NbOfTxs>
      <CtrlSum>1500.00</CtrlSum>
    </GrpHdr>
    <PmtInf>
      <PmtMtd>TRF</PmtMtd>
      <CdtTrfTxInf>
        <Amt><InstdAmt Ccy="EUR">1500.00</InstdAmt></Amt>
        <CdtrAcct><Id><IBAN>DE89370400440532013000</IBAN></Id></CdtrAcct>
      </CdtTrfTxInf>
    </PmtInf>
  </CstmrCdtTrfInitn>
</Document>"""

SIMPLE_XML_C_ID_ONLY = """<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.09">
  <CstmrCdtTrfInitn>
    <GrpHdr>
      <MsgId>MSG-999</MsgId>
      <NbOfTxs>1</NbOfTxs>
      <CtrlSum>1000.00</CtrlSum>
    </GrpHdr>
    <PmtInf>
      <PmtMtd>TRF</PmtMtd>
      <CdtTrfTxInf>
        <Amt><InstdAmt Ccy="EUR">1000.00</InstdAmt></Amt>
        <CdtrAcct><Id><IBAN>DE89370400440532013000</IBAN></Id></CdtrAcct>
      </CdtTrfTxInf>
    </PmtInf>
  </CstmrCdtTrfInitn>
</Document>"""


@pytest.fixture
def comparator():
    from src.comparator.xml_comparator import XMLComparator
    return XMLComparator(ignore_tags=["MsgId", "CreDtTm", "EndToEndId", "UETR", "InstrId"])


@pytest.fixture
def tmp_xml(tmp_path):
    """Write inline XML strings to temp files and return paths."""
    def _write(content: str, name: str) -> Path:
        p = tmp_path / name
        p.write_text(content, encoding="utf-8")
        return p
    return _write


# ── Canonicalizer tests ────────────────────────────────────────────────────────

class TestCanonicalize:
    def test_whitespace_normalized(self):
        from lxml import etree
        from src.comparator.canonicalizer import canonicalize

        xml = b"<Root><Name>  Hello   World  </Name></Root>"
        root = etree.fromstring(xml)
        canon = canonicalize(root)
        assert canon.find("Name").text == "Hello World"

    def test_ignored_tags_replaced(self):
        from lxml import etree
        from src.comparator.canonicalizer import canonicalize

        xml = b"<Root><MsgId>ABC-123</MsgId><Amt>1000</Amt></Root>"
        root = etree.fromstring(xml)
        canon = canonicalize(root, ignore_tags=["MsgId"])
        assert canon.find("MsgId").text == "__IGNORED__"
        assert canon.find("Amt").text == "1000"


# ── Classifier tests ───────────────────────────────────────────────────────────

class TestDiffClassifier:
    def test_amount_change_is_breaking(self):
        from src.comparator.diff_classifier import ChangeType, DiffClassifier, Severity
        clf = DiffClassifier()
        result = clf.classify("/Document/PmtInf/CdtTrfTxInf/Amt/InstdAmt",
                              ChangeType.MODIFIED, "1000.00", "1500.00")
        assert result == Severity.BREAKING

    def test_msgid_change_is_benign(self):
        from src.comparator.diff_classifier import ChangeType, DiffClassifier, Severity
        clf = DiffClassifier()
        result = clf.classify("/Document/GrpHdr/MsgId",
                              ChangeType.MODIFIED, "MSG-001", "MSG-002")
        assert result == Severity.BENIGN

    def test_mandatory_field_removed_is_breaking(self):
        from src.comparator.diff_classifier import ChangeType, DiffClassifier, Severity
        clf = DiffClassifier()
        result = clf.classify("/Document/PmtInf/CdtTrfTxInf/CdtrAcct/Id/IBAN",
                              ChangeType.REMOVED, "DE89370400440532013000", None,
                              is_mandatory=True)
        assert result == Severity.BREAKING

    def test_optional_field_added_is_info(self):
        from src.comparator.diff_classifier import ChangeType, DiffClassifier, Severity
        clf = DiffClassifier()
        result = clf.classify("/Document/PmtInf/CdtTrfTxInf/RgltryRptg",
                              ChangeType.ADDED, None, "<...>",
                              is_mandatory=False)
        assert result == Severity.INFO

    def test_breaking_score_all_benign_is_zero(self):
        from src.comparator.diff_classifier import DiffClassifier, Severity
        clf = DiffClassifier()
        score = clf.breaking_score([Severity.BENIGN, Severity.BENIGN])
        assert score == 0.0

    def test_breaking_score_all_breaking_is_100(self):
        from src.comparator.diff_classifier import DiffClassifier, Severity
        clf = DiffClassifier()
        score = clf.breaking_score([Severity.BREAKING, Severity.BREAKING])
        assert score == 100.0


# ── Comparator tests ───────────────────────────────────────────────────────────

class TestXMLComparator:
    def test_identical_files_no_diffs(self, comparator, tmp_xml):
        a = tmp_xml(SIMPLE_XML_A, "a.xml")
        b = tmp_xml(SIMPLE_XML_A, "b.xml")
        result = comparator.compare(a, b)
        # Only benign diffs (MsgId is in both and identical → no diff at all)
        non_benign = [d for d in result.diffs
                      if d.severity.value not in ("BENIGN", "INFO")]
        assert len(non_benign) == 0

    def test_id_only_change_is_benign(self, comparator, tmp_xml):
        """Changing only MsgId should result in only benign diffs."""
        a = tmp_xml(SIMPLE_XML_A, "a.xml")
        c = tmp_xml(SIMPLE_XML_C_ID_ONLY, "c.xml")
        result = comparator.compare(a, c)
        # MsgId is in ignore list → should be 0 non-benign diffs
        breaking = result.breaking
        assert len(breaking) == 0

    def test_amount_change_detected_as_breaking(self, comparator, tmp_xml):
        a = tmp_xml(SIMPLE_XML_A, "a.xml")
        b = tmp_xml(SIMPLE_XML_B_AMOUNT_CHANGE, "b.xml")
        result = comparator.compare(a, b)
        assert result.breaking_score > 0
        assert len(result.breaking) > 0

    def test_sample_pain001_diff(self, comparator):
        """Integration test: compare the two pre-built sample files."""
        if not PAIN001_V1.exists() or not PAIN001_V2.exists():
            pytest.skip("Sample files not found")
        result = comparator.compare(PAIN001_V1, PAIN001_V2)
        # v2 has BREAKING changes (amount + IBAN) → score > 0
        assert result.breaking_score > 0
        assert len(result.diffs) > 0

    def test_to_json_roundtrip(self, comparator, tmp_xml):
        import json
        a = tmp_xml(SIMPLE_XML_A, "a.xml")
        b = tmp_xml(SIMPLE_XML_B_AMOUNT_CHANGE, "b.xml")
        result = comparator.compare(a, b)
        raw = json.loads(result.to_json())
        assert "diffs" in raw
        assert "breaking_score" in raw


# ── Helpers tests ──────────────────────────────────────────────────────────────

class TestHelpers:
    def test_message_type_from_namespace(self):
        from src.utils.helpers import message_type_from_namespace
        ns = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.12"
        assert message_type_from_namespace(ns) == "pain.001.001.12"

    def test_message_type_unknown_ns(self):
        from src.utils.helpers import message_type_from_namespace
        assert message_type_from_namespace("http://example.com/foo") is None

    def test_message_family(self):
        from src.utils.helpers import message_family_from_type
        assert message_family_from_type("pacs.008.001.10") == "Payments Clearing and Settlement"
        assert message_family_from_type("camt.053.001.08") == "Cash Management"

    def test_detect_namespace_from_sample(self):
        from src.utils.helpers import detect_namespace
        if not PAIN001_V1.exists():
            pytest.skip("Sample file not found")
        ns = detect_namespace(PAIN001_V1)
        assert ns is not None
        assert "pain.001" in ns
