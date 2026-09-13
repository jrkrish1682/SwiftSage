"""
Vendored ISO 20022 schema bundle.

The public ISO 20022 GitHub catalogue is not a stable download source (the
releases endpoint the connector was written against now 404s), which left the
Standards Library empty and every schema-aware feature disabled. A pinned set
of XSDs for the demo message families therefore ships in `data/standards/`,
and is seeded into the Standards Library so the app works with no network.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from src.storage.standards_library import StandardsLibrary
from src.utils.helpers import get_logger

log = get_logger(__name__)

BUNDLE_PATH = Path(__file__).resolve().parents[2] / "data" / "standards"
BUNDLE_VERSION = "vendored-2019-2023"
BUNDLE_TAG = "vendored"

_MSG_TYPE_RE = re.compile(r"([a-z]+\.\d{3}\.\d{3}\.\d{2,3})")


def bundle_files(bundle_path: Optional[Path] = None) -> list[Path]:
    """Every XSD in the vendored bundle, sorted by message type."""
    root = Path(bundle_path or BUNDLE_PATH)
    return sorted(root.glob("*/*.xsd"))


def seed_library(
    library: StandardsLibrary, bundle_path: Optional[Path] = None
) -> int:
    """
    Register the vendored XSDs in *library*. Returns the number newly added;
    artefacts already catalogued are left untouched.
    """
    added = 0
    for xsd in bundle_files(bundle_path):
        match = _MSG_TYPE_RE.search(xsd.name)
        msg_type = match.group(1) if match else xsd.stem
        artifact_id = f"{msg_type}-xsd"
        if library.get_artifact(artifact_id):
            continue
        library.add_artifact(
            artifact_id=artifact_id,
            artifact_type="xsd",
            content=xsd.read_bytes(),
            filename=xsd.name,
            message_type=msg_type,
            message_set=msg_type.split(".")[0],
            version=msg_type.split(".")[-1],
            source_url=None,
            tags=[BUNDLE_TAG, BUNDLE_VERSION],
        )
        added += 1
    log.info("Seeded %d vendored XSDs into the standards library", added)
    return added
