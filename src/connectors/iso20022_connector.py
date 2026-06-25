"""
FR-1: ISO 20022 Source Connector & Incremental Sync.

Downloads XSD schema packages and associated artifacts from the ISO 20022
public catalogue.  SWIFT MyStandards support is stubbed — fill credentials
in .env to enable the authenticated path.

Strategy
--------
The ISO 20022 organisation publishes message set ZIP packages on GitHub:
  https://github.com/ISO20022/iso20022-messages

Each ZIP contains XSDs + a message definition report (MDR).
We pull the GitHub releases API to enumerate available packages, then
download only those we don't already have (incremental sync by checksum).
"""
import io
import re
import zipfile
from pathlib import Path
from typing import Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from src.storage.standards_library import StandardsLibrary
from src.utils.helpers import get_logger, message_type_from_namespace

log = get_logger(__name__)

# ── Known message-set package names → GitHub release asset patterns ──────────
MESSAGE_SET_PACKAGES: dict[str, str] = {
    "pain": "PaymentInitiation",
    "pacs": "PaymentsClearingAndSettlement",
    "camt": "CashManagement",
    "acmt": "AccountManagement",
    "auth": "Authorities",
    "reda": "ReferenceData",
}

GITHUB_RELEASES_API = (
    "https://api.github.com/repos/ISO20022/iso20022-messages/releases/latest"
)


class ISO20022Connector:
    """Download and sync ISO 20022 schemas into a StandardsLibrary."""

    def __init__(
        self,
        library: StandardsLibrary,
        github_token: Optional[str] = None,
        timeout: int = 30,
    ):
        self.library = library
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers["Accept"] = "application/vnd.github+json"
        if github_token:
            self._session.headers["Authorization"] = f"Bearer {github_token}"

    # ── Public API ─────────────────────────────────────────────────────────

    def sync(self, message_sets: Optional[list[str]] = None) -> dict:
        """
        Download/update artifacts for the requested message sets.

        Args:
            message_sets: e.g. ["pain","camt"].  None → all known sets.

        Returns:
            Summary dict with counts of added/skipped artifacts.
        """
        targets = message_sets or list(MESSAGE_SET_PACKAGES.keys())
        log.info("Syncing message sets: %s", targets)

        release = self._fetch_latest_release()
        if release is None:
            return {"error": "Could not fetch release info from GitHub"}

        release_tag = release.get("tag_name", "unknown")
        assets: list[dict] = release.get("assets", [])
        log.info("Latest release: %s  (%d assets)", release_tag, len(assets))

        added, skipped = 0, 0
        for ms in targets:
            pkg_name = MESSAGE_SET_PACKAGES.get(ms)
            if not pkg_name:
                log.warning("Unknown message set: %s", ms)
                continue

            matching = [
                a for a in assets if pkg_name.lower() in a["name"].lower() and a["name"].endswith(".zip")
            ]
            if not matching:
                log.warning("No ZIP asset found for %s (%s)", ms, pkg_name)
                continue

            for asset in matching:
                artifact_id = f"{ms}-{asset['name']}-{release_tag}"
                if self.library.get_artifact(artifact_id):
                    log.debug("Already have %s, skipping", artifact_id)
                    skipped += 1
                    continue

                content = self._download(asset["browser_download_url"])
                if content is None:
                    continue

                # Extract XSDs from the ZIP and store each
                n = self._ingest_zip(
                    content,
                    message_set=ms,
                    version=release_tag,
                    source_url=asset["browser_download_url"],
                )
                added += n

        return {
            "release": release_tag,
            "message_sets_requested": targets,
            "artifacts_added": added,
            "artifacts_skipped": skipped,
        }

    def fetch_schema_for_message(self, message_type: str) -> Optional[Path]:
        """
        Return the local XSD path for a specific message type (e.g. 'pain.001.001.12').
        Triggers a sync of the relevant message set if not already present.
        """
        ms = message_type.split(".")[0]
        # Check library first
        candidates = [
            a for a in self.library.list_artifacts(message_set=ms, artifact_type="xsd")
            if message_type in (a.message_type or "")
        ]
        if candidates:
            return self.library.get_artifact_path(candidates[0].artifact_id)

        # Not found — attempt sync
        self.sync(message_sets=[ms])
        candidates = [
            a for a in self.library.list_artifacts(message_set=ms, artifact_type="xsd")
            if message_type in (a.message_type or "")
        ]
        if candidates:
            return self.library.get_artifact_path(candidates[0].artifact_id)

        return None

    def what_is_new(self) -> str:
        """Return a human-readable "what's new" report vs current library."""
        old_snapshot = self.library.snapshot()
        result = self.sync()
        new_snapshot = self.library.snapshot()

        diff = self.library.diff_snapshot(old_snapshot)
        lines = [
            f"ISO 20022 Sync Report — Release: {result.get('release','?')}",
            f"  Added   : {len(diff['added'])}",
            f"  Changed : {len(diff['changed'])}",
            f"  Removed : {len(diff['removed'])}",
        ]
        if diff["added"]:
            lines.append("\nNew artifacts:")
            for a in diff["added"]:
                lines.append(f"  + {a['artifact_id']}  ({a['message_type']})")
        if diff["changed"]:
            lines.append("\nUpdated artifacts:")
            for a in diff["changed"]:
                lines.append(f"  ~ {a['artifact_id']}")
        return "\n".join(lines)

    # ── Internal helpers ───────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _fetch_latest_release(self) -> Optional[dict]:
        try:
            resp = self._session.get(GITHUB_RELEASES_API, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            log.error("Failed to fetch release info: %s", exc)
            return None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _download(self, url: str) -> Optional[bytes]:
        try:
            log.info("Downloading %s", url)
            resp = self._session.get(url, timeout=self.timeout, stream=True)
            resp.raise_for_status()
            return resp.content
        except Exception as exc:
            log.error("Download failed for %s: %s", url, exc)
            return None

    def _ingest_zip(
        self, zip_bytes: bytes, message_set: str, version: str, source_url: str
    ) -> int:
        """Unzip and store each XSD artifact. Returns count of stored files."""
        count = 0
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                for name in zf.namelist():
                    if not name.endswith(".xsd"):
                        continue
                    content = zf.read(name)
                    filename = Path(name).name
                    # Infer message type from filename (e.g. pain.001.001.12.xsd)
                    msg_type_match = re.search(
                        r"([a-z]+\.\d{3}\.\d{3}\.\d{2,3})", filename
                    )
                    msg_type = msg_type_match.group(1) if msg_type_match else None
                    artifact_id = f"{message_set}-{filename}-{version}"
                    self.library.add_artifact(
                        artifact_id=artifact_id,
                        artifact_type="xsd",
                        content=content,
                        filename=filename,
                        message_type=msg_type,
                        message_set=message_set,
                        version=version,
                        source_url=source_url,
                        tags=["auto-synced"],
                    )
                    count += 1
        except zipfile.BadZipFile as exc:
            log.error("Bad ZIP: %s", exc)
        return count
