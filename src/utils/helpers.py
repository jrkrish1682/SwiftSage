"""General-purpose utilities for the SWIFT Message Validator."""
import logging
import logging.handlers
import re
from pathlib import Path
from typing import Optional

from lxml import etree

_LOG_FILE = Path(__file__).resolve().parents[2] / "logs" / "swiftsage.log"
_FMT = logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s  %(message)s")
_root_configured = False


def _configure_root() -> None:
    global _root_configured
    if _root_configured:
        return
    _root_configured = True

    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Rotating file — 5 MB per file, keep 3 backups
    fh = logging.handlers.RotatingFileHandler(
        _LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(_FMT)
    fh.setLevel(logging.DEBUG)
    root.addHandler(fh)

    # Keep a console handler too (visible when running from terminal)
    ch = logging.StreamHandler()
    ch.setFormatter(_FMT)
    ch.setLevel(logging.INFO)
    root.addHandler(ch)


def get_logger(name: str) -> logging.Logger:
    """Return a module logger backed by the rotating file handler."""
    _configure_root()
    return logging.getLogger(name)


# ── Namespace / message-type helpers ──────────────────────────────────────────

# e.g. "urn:iso:std:iso:20022:tech:xsd:pain.001.001.12"  →  "pain.001.001.12"
_NS_PATTERN = re.compile(
    r"urn:iso:std:iso:20022:tech:xsd:([a-z]+\.\d+\.\d+\.\d+)"
)

ISO20022_MESSAGE_SETS = {
    "pain": "Payment Initiation",
    "pacs": "Payments Clearing and Settlement",
    "camt": "Cash Management",
    "acmt": "Account Management",
    "auth": "Authorities",
    "reda": "Reference Data",
    "colr": "Collateral Management",
    "sese": "Securities Settlement",
    "seev": "Securities Events",
}


def message_type_from_namespace(namespace: str) -> Optional[str]:
    """Extract 'pain.001.001.12' style identifier from a namespace URI."""
    m = _NS_PATTERN.search(namespace or "")
    return m.group(1) if m else None


def message_family_from_type(msg_type: str) -> Optional[str]:
    """Return the business domain name for a message type prefix."""
    prefix = msg_type.split(".")[0] if msg_type else ""
    return ISO20022_MESSAGE_SETS.get(prefix)


def safe_read_xml(path: str | Path) -> Optional[etree._Element]:
    """Parse an XML file, returning None (not raising) on failure."""
    try:
        tree = etree.parse(str(path))
        return tree.getroot()
    except Exception:
        return None


def detect_namespace(xml_path: str | Path) -> Optional[str]:
    """Return the primary namespace declared on the root element."""
    root = safe_read_xml(xml_path)
    if root is None:
        return None
    ns = root.nsmap.get(None) or (root.tag.split("}")[0].lstrip("{") if root.tag.startswith("{") else None)
    return ns


def xpath_tag(element: etree._Element) -> str:
    """Return the local tag name of an element (strips namespace)."""
    tag = element.tag
    return tag.split("}")[-1] if "}" in tag else tag


def element_to_xpath(element: etree._Element) -> str:
    """Build a simple XPath string for an element relative to its root."""
    parts = []
    node = element
    while node is not None and node.getparent() is not None:
        sibs = [s for s in node.getparent() if xpath_tag(s) == xpath_tag(node)]
        if len(sibs) > 1:
            idx = sibs.index(node) + 1
            parts.append(f"{xpath_tag(node)}[{idx}]")
        else:
            parts.append(xpath_tag(node))
        node = node.getparent()
    parts.reverse()
    return "/" + "/".join(parts)


def load_schema(xsd_path: str | Path) -> Optional[etree.XMLSchema]:
    """Load and compile an XSD schema file."""
    try:
        doc = etree.parse(str(xsd_path))
        return etree.XMLSchema(doc)
    except Exception:
        return None
