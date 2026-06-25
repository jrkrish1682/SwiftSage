"""
FR-2: ISO 20022 Schema-Aware XML Comparator.

Compares two XML instances (or two folders of instances) at the semantic
level — by XPath and business element, not line-by-line text.

Key features
------------
* XSD validation before comparison (optional)
* Canonicalization (namespace/whitespace/ordering normalization)
* Configurable ignore list (IDs, timestamps, correlation refs)
* Diff classification: BREAKING / WARNING / BENIGN / INFO
* Batch mode: compare folders, deduplicate recurring diff patterns
* Breaking-change score (0–100, rule-based, explainable)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from lxml import etree
from xmldiff import formatting, main as xmldiff_main
from xmldiff.actions import (
    DeleteNode, InsertNode, MoveNode, RenameNode,
    UpdateAttrib, UpdateTextIn,
)

from src.comparator.canonicalizer import canonicalize, to_canonical_string
from src.comparator.diff_classifier import ChangeType, DiffClassifier, Severity
from src.utils.helpers import get_logger, load_schema, safe_read_xml, xpath_tag

log = get_logger(__name__)


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class DiffEntry:
    xpath: str
    change_type: ChangeType
    old_value: Optional[str]
    new_value: Optional[str]
    severity: Severity
    explanation: str = ""

    def to_dict(self) -> dict:
        return {
            "xpath": self.xpath,
            "change_type": self.change_type.value,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "severity": self.severity.value,
            "explanation": self.explanation,
        }


@dataclass
class ComparisonResult:
    file_a: str
    file_b: str
    is_valid_a: Optional[bool] = None
    is_valid_b: Optional[bool] = None
    validation_errors_a: list[str] = field(default_factory=list)
    validation_errors_b: list[str] = field(default_factory=list)
    diffs: list[DiffEntry] = field(default_factory=list)
    breaking_score: float = 0.0
    summary: str = ""

    # ── Convenience filters ────────────────────────────────────────────────
    @property
    def breaking(self) -> list[DiffEntry]:
        return [d for d in self.diffs if d.severity == Severity.BREAKING]

    @property
    def warnings(self) -> list[DiffEntry]:
        return [d for d in self.diffs if d.severity == Severity.WARNING]

    @property
    def benign(self) -> list[DiffEntry]:
        return [d for d in self.diffs if d.severity == Severity.BENIGN]

    def to_dict(self) -> dict:
        return {
            "file_a": self.file_a,
            "file_b": self.file_b,
            "valid_a": self.is_valid_a,
            "valid_b": self.is_valid_b,
            "validation_errors_a": self.validation_errors_a,
            "validation_errors_b": self.validation_errors_b,
            "breaking_score": self.breaking_score,
            "summary": self.summary,
            "diffs": [d.to_dict() for d in self.diffs],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def human_report(self) -> str:
        lines = [
            f"Comparison: {self.file_a}  vs  {self.file_b}",
            f"Breaking-change score: {self.breaking_score}/100",
            f"Total diffs: {len(self.diffs)}  "
            f"(BREAKING={len(self.breaking)}, WARNING={len(self.warnings)}, "
            f"BENIGN={len(self.benign)})",
        ]
        if self.validation_errors_a:
            lines.append(f"\n⚠ Validation errors in A: {self.validation_errors_a}")
        if self.validation_errors_b:
            lines.append(f"⚠ Validation errors in B: {self.validation_errors_b}")
        if self.breaking:
            lines.append("\nBREAKING changes:")
            for d in self.breaking:
                lines.append(
                    f"  [{d.change_type.value}] {d.xpath}\n"
                    f"    old={d.old_value!r}  new={d.new_value!r}"
                )
        if self.warnings:
            lines.append("\nWARNINGS:")
            for d in self.warnings:
                lines.append(f"  [{d.change_type.value}] {d.xpath}")
        return "\n".join(lines)


@dataclass
class BatchComparisonResult:
    results: list[ComparisonResult] = field(default_factory=list)
    top_patterns: list[dict] = field(default_factory=list)

    def summary_table(self) -> str:
        rows = [
            f"{'File A':<40} {'File B':<40} {'Score':>6}  {'BREAK':>5}  {'WARN':>5}"
        ]
        rows.append("-" * 100)
        for r in self.results:
            a = Path(r.file_a).name
            b = Path(r.file_b).name
            rows.append(
                f"{a:<40} {b:<40} {r.breaking_score:>6.1f}  "
                f"{len(r.breaking):>5}  {len(r.warnings):>5}"
            )
        return "\n".join(rows)


# ── Main comparator class ──────────────────────────────────────────────────────

class XMLComparator:
    """
    Schema-aware ISO 20022 XML comparator.

    Usage::
        cmp = XMLComparator(ignore_tags=["MsgId","CreDtTm","UETR"])
        result = cmp.compare("v1/pain001.xml", "v2/pain001.xml", schema_path="pain.001.001.12.xsd")
        print(result.human_report())
    """

    def __init__(
        self,
        ignore_tags: Optional[list[str]] = None,
        classifier: Optional[DiffClassifier] = None,
    ):
        self.ignore_tags = ignore_tags or [
            "MsgId", "CreDtTm", "InstrId", "EndToEndId", "TxId", "UETR",
            "ClrSysRef", "PrcgDt", "AccptncDtTm",
        ]
        self.classifier = classifier or DiffClassifier()

    # ── Single-file comparison ─────────────────────────────────────────────

    def compare(
        self,
        path_a: str | Path,
        path_b: str | Path,
        schema_path: Optional[str | Path] = None,
    ) -> ComparisonResult:
        """Compare two ISO 20022 XML files."""
        result = ComparisonResult(file_a=str(path_a), file_b=str(path_b))

        root_a = safe_read_xml(path_a)
        root_b = safe_read_xml(path_b)

        if root_a is None:
            result.summary = f"Cannot parse {path_a}"
            return result
        if root_b is None:
            result.summary = f"Cannot parse {path_b}"
            return result

        # ── Optional XSD validation ────────────────────────────────────
        if schema_path:
            schema = load_schema(schema_path)
            if schema:
                result.is_valid_a, result.validation_errors_a = self._validate(root_a, schema)
                result.is_valid_b, result.validation_errors_b = self._validate(root_b, schema)

        # ── Canonicalize ───────────────────────────────────────────────
        canon_a = canonicalize(root_a, ignore_tags=self.ignore_tags)
        canon_b = canonicalize(root_b, ignore_tags=self.ignore_tags)

        # ── Compute diffs via xmldiff ──────────────────────────────────
        actions = xmldiff_main.diff_trees(canon_a, canon_b)
        entries = self._actions_to_entries(actions, canon_a)

        result.diffs = entries
        result.breaking_score = self.classifier.breaking_score(
            [e.severity for e in entries]
        )
        result.summary = self._make_summary(result)
        return result

    # ── Batch comparison ───────────────────────────────────────────────────

    def compare_folders(
        self,
        folder_a: str | Path,
        folder_b: str | Path,
        schema_path: Optional[str | Path] = None,
        glob_pattern: str = "*.xml",
    ) -> BatchComparisonResult:
        """
        Compare matching XML files across two folders.

        Files are matched by name — only files present in both folders are
        compared.  Missing files are logged as warnings.
        """
        fa, fb = Path(folder_a), Path(folder_b)
        files_a = {f.name: f for f in fa.glob(glob_pattern)}
        files_b = {f.name: f for f in fb.glob(glob_pattern)}

        common = sorted(set(files_a) & set(files_b))
        only_in_a = sorted(set(files_a) - set(files_b))
        only_in_b = sorted(set(files_b) - set(files_a))

        if only_in_a:
            log.warning("Only in A (not compared): %s", only_in_a)
        if only_in_b:
            log.warning("Only in B (not compared): %s", only_in_b)

        batch = BatchComparisonResult()
        pattern_counts: dict[str, int] = {}

        for name in common:
            r = self.compare(files_a[name], files_b[name], schema_path=schema_path)
            batch.results.append(r)
            for d in r.diffs:
                key = f"[{d.change_type.value}] {d.xpath}"
                pattern_counts[key] = pattern_counts.get(key, 0) + 1

        # Top-20 recurring diff patterns
        top = sorted(pattern_counts.items(), key=lambda x: -x[1])[:20]
        batch.top_patterns = [{"pattern": p, "count": c} for p, c in top]
        return batch

    # ── Helpers ────────────────────────────────────────────────────────────

    def _validate(
        self, root: etree._Element, schema: etree.XMLSchema
    ) -> tuple[bool, list[str]]:
        try:
            valid = schema.validate(root)
            errors = [str(e) for e in schema.error_log]
            return valid, errors
        except Exception as exc:
            return False, [str(exc)]

    def _actions_to_entries(
        self, actions: list, reference_tree: etree._Element
    ) -> list[DiffEntry]:
        entries: list[DiffEntry] = []

        for action in actions:
            xpath = getattr(action, "node", None) or ""
            if hasattr(xpath, "__class__") and not isinstance(xpath, str):
                xpath = str(xpath)

            change_type: ChangeType
            old_val: Optional[str] = None
            new_val: Optional[str] = None

            if isinstance(action, UpdateTextIn):
                change_type = ChangeType.MODIFIED
                new_val = action.text
                # Try to get old value from reference tree
                try:
                    old_node = reference_tree.xpath(str(action.node))
                    if old_node:
                        n = old_node[0] if isinstance(old_node, list) else old_node
                        old_val = n.text if hasattr(n, "text") else None
                except Exception:
                    pass

            elif isinstance(action, (DeleteNode,)):
                change_type = ChangeType.REMOVED

            elif isinstance(action, (InsertNode,)):
                change_type = ChangeType.ADDED
                new_val = getattr(action, "value", None)
                if new_val is not None:
                    new_val = str(new_val)

            elif isinstance(action, MoveNode):
                change_type = ChangeType.REORDERED

            elif isinstance(action, UpdateAttrib):
                change_type = ChangeType.ATTRIBUTE_CHANGED
                old_val = getattr(action, "oldval", None)
                new_val = getattr(action, "value", None)
                if new_val is not None:
                    new_val = str(new_val)

            elif isinstance(action, RenameNode):
                change_type = ChangeType.MODIFIED
                new_val = str(getattr(action, "newname", ""))

            else:
                change_type = ChangeType.MODIFIED

            # Derive local tag from XPath for classification
            xpath_str = str(xpath)
            severity = self.classifier.classify(
                xpath=xpath_str,
                change_type=change_type,
                old_value=old_val,
                new_value=new_val,
            )

            entries.append(
                DiffEntry(
                    xpath=xpath_str,
                    change_type=change_type,
                    old_value=old_val,
                    new_value=new_val,
                    severity=severity,
                    explanation=self._explain(xpath_str, change_type, severity),
                )
            )

        return entries

    def _explain(self, xpath: str, change_type: ChangeType, severity: Severity) -> str:
        tag = xpath.split("/")[-1].split("[")[0]
        if severity == Severity.BREAKING:
            return f"Breaking: '{tag}' is a critical field — its {change_type.value} will break processing."
        if severity == Severity.WARNING:
            return f"Warning: '{tag}' change may affect settlement or routing — review required."
        if severity == Severity.BENIGN:
            return f"Benign: '{tag}' is a correlation/timestamp field — safe to ignore."
        return f"Info: '{tag}' — {change_type.value} of optional/informational field."

    @staticmethod
    def _make_summary(result: ComparisonResult) -> str:
        return (
            f"{len(result.diffs)} diff(s) found — "
            f"score {result.breaking_score}/100 — "
            f"{len(result.breaking)} BREAKING, "
            f"{len(result.warnings)} WARNING, "
            f"{len(result.benign)} BENIGN"
        )
