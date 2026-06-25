"""
Local Standards Library — persistent store of downloaded ISO 20022 artifacts.

Each artifact (XSD, MUG/MDR PDF, sample XML) is stored on disk and tracked
via a JSON metadata catalogue at <library_path>/catalogue.json.
"""
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from src.utils.helpers import get_logger

log = get_logger(__name__)


class ArtifactMeta(BaseModel):
    artifact_id: str                   # e.g. "pain.001.001.12-xsd"
    artifact_type: str                 # "xsd" | "mug" | "sample" | "mdr"
    message_type: Optional[str]        # e.g. "pain.001.001.12"
    message_set: Optional[str]         # e.g. "pain"
    version: str                       # e.g. "12" or "2024-11"
    source_url: Optional[str]
    local_path: str                    # relative to library_path
    checksum_sha256: str
    retrieved_at: str                  # ISO-8601
    tags: list[str] = Field(default_factory=list)


class StandardsLibrary:
    """Manages the local artefact catalogue."""

    CATALOGUE_FILE = "catalogue.json"

    def __init__(self, library_path: str | Path):
        self.library_path = Path(library_path)
        self.library_path.mkdir(parents=True, exist_ok=True)
        self._catalogue: dict[str, ArtifactMeta] = {}
        self._load_catalogue()

    # ── Catalogue I/O ─────────────────────────────────────────────────────

    def _catalogue_path(self) -> Path:
        return self.library_path / self.CATALOGUE_FILE

    def _load_catalogue(self) -> None:
        p = self._catalogue_path()
        if p.exists():
            raw = json.loads(p.read_text("utf-8"))
            self._catalogue = {k: ArtifactMeta(**v) for k, v in raw.items()}
            log.info("Loaded %d artifacts from catalogue", len(self._catalogue))

    def _save_catalogue(self) -> None:
        raw = {k: v.model_dump() for k, v in self._catalogue.items()}
        self._catalogue_path().write_text(
            json.dumps(raw, indent=2, default=str), encoding="utf-8"
        )

    # ── CRUD ──────────────────────────────────────────────────────────────

    def add_artifact(
        self,
        artifact_id: str,
        artifact_type: str,
        content: bytes,
        filename: str,
        message_type: Optional[str] = None,
        message_set: Optional[str] = None,
        version: str = "unknown",
        source_url: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> ArtifactMeta:
        dest_dir = self.library_path / (message_set or "misc")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / filename
        dest.write_bytes(content)

        checksum = hashlib.sha256(content).hexdigest()
        meta = ArtifactMeta(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            message_type=message_type,
            message_set=message_set,
            version=version,
            source_url=source_url,
            local_path=str(dest.relative_to(self.library_path)),
            checksum_sha256=checksum,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            tags=tags or [],
        )
        self._catalogue[artifact_id] = meta
        self._save_catalogue()
        log.info("Added artifact: %s → %s", artifact_id, dest)
        return meta

    def get_artifact(self, artifact_id: str) -> Optional[ArtifactMeta]:
        return self._catalogue.get(artifact_id)

    def get_artifact_path(self, artifact_id: str) -> Optional[Path]:
        meta = self.get_artifact(artifact_id)
        if meta is None:
            return None
        return self.library_path / meta.local_path

    def list_artifacts(
        self,
        message_set: Optional[str] = None,
        artifact_type: Optional[str] = None,
    ) -> list[ArtifactMeta]:
        results = list(self._catalogue.values())
        if message_set:
            results = [a for a in results if a.message_set == message_set]
        if artifact_type:
            results = [a for a in results if a.artifact_type == artifact_type]
        return results

    def remove_artifact(self, artifact_id: str) -> bool:
        meta = self._catalogue.pop(artifact_id, None)
        if meta is None:
            return False
        path = self.library_path / meta.local_path
        if path.exists():
            path.unlink()
        self._save_catalogue()
        return True

    # ── What's-new diff ───────────────────────────────────────────────────

    def diff_snapshot(self, previous_catalogue: dict[str, dict]) -> dict:
        """Compare current catalogue against a previous snapshot dict."""
        prev_ids = set(previous_catalogue.keys())
        curr_ids = set(self._catalogue.keys())
        added = curr_ids - prev_ids
        removed = prev_ids - curr_ids
        changed = {
            k
            for k in curr_ids & prev_ids
            if self._catalogue[k].checksum_sha256
            != previous_catalogue[k].get("checksum_sha256")
        }
        return {
            "added": [self._catalogue[k].model_dump() for k in sorted(added)],
            "removed": list(sorted(removed)),
            "changed": [self._catalogue[k].model_dump() for k in sorted(changed)],
        }

    def snapshot(self) -> dict[str, dict]:
        """Return a plain-dict snapshot of the current catalogue."""
        return {k: v.model_dump() for k, v in self._catalogue.items()}

    def summary(self) -> str:
        total = len(self._catalogue)
        by_set: dict[str, int] = {}
        for a in self._catalogue.values():
            ms = a.message_set or "unknown"
            by_set[ms] = by_set.get(ms, 0) + 1
        lines = [f"Standards Library — {total} artifacts"]
        for ms, cnt in sorted(by_set.items()):
            lines.append(f"  {ms}: {cnt}")
        return "\n".join(lines)
