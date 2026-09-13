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
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from lxml import etree
from xmldiff import formatting, main as xmldiff_main, patch as xmldiff_patch
from xmldiff.actions import (
    DeleteAttrib, DeleteNode, InsertAttrib, InsertNode, MoveNode,
    RenameAttrib, RenameNode, UpdateAttrib, UpdateTextAfter, UpdateTextIn,
)

from src.comparator.canonicalizer import canonicalize, to_canonical_string
from src.comparator.diff_classifier import ChangeType, DiffClassifier, Severity
from src.comparator.schema_cardinality import SchemaCardinality
from src.utils.helpers import (
    get_logger, load_schema, message_type_from_namespace, namespace_of,
    rewrite_namespace, safe_read_xml, xpath_tag,
)

log = get_logger(__name__)


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class DiffEntry:
    xpath: str                      # business path, e.g. /Document/GrpHdr/CtrlSum
    change_type: ChangeType
    old_value: Optional[str]
    new_value: Optional[str]
    severity: Severity
    explanation: str = ""
    raw_xpath: str = ""             # positional path emitted by xmldiff
    element: str = ""               # local element (or @attribute) name

    def to_dict(self) -> dict:
        return {
            "xpath": self.xpath,
            "element": self.element,
            "change_type": self.change_type.value,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "severity": self.severity.value,
            "explanation": self.explanation,
            "raw_xpath": self.raw_xpath,
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
    schema_aware: bool = False
    score_breakdown: list[dict] = field(default_factory=list)
    message_type_a: Optional[str] = None
    message_type_b: Optional[str] = None
    parse_error: Optional[str] = None   # set when a document could not be read

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
            "score_breakdown": self.score_breakdown,
            "schema_aware": self.schema_aware,
            "message_type_a": self.message_type_a,
            "message_type_b": self.message_type_b,
            "parse_error": self.parse_error,
            "summary": self.summary,
            "diffs": [d.to_dict() for d in self.diffs],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def human_report(self) -> str:
        lines = [
            f"Comparison: {self.file_a}  vs  {self.file_b}",
            f"Breaking-change score: {self.breaking_score}/100"
            + (" (schema-aware)" if self.schema_aware else " (rule-based only)"),
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
        severity_weights: Optional[dict[Severity, float]] = None,
    ):
        self.ignore_tags = ignore_tags or [
            "MsgId", "CreDtTm", "InstrId", "EndToEndId", "TxId", "UETR",
            "ClrSysRef", "PrcgDt", "AccptncDtTm",
        ]
        self.classifier = classifier or DiffClassifier(weights=severity_weights)
        self.cardinality: Optional[SchemaCardinality] = None

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

        for label, path, root in (("A", path_a, root_a), ("B", path_b, root_b)):
            if root is None:
                result.parse_error = (
                    f"Document {label} ({path}) is not well-formed XML and could "
                    f"not be compared."
                )
                result.summary = result.parse_error
                return result

        # ── Optional XSD validation + cardinality awareness ────────────
        self.cardinality = None
        if schema_path:
            schema = load_schema(schema_path)
            if schema:
                result.is_valid_a, result.validation_errors_a = self._validate(root_a, schema)
                result.is_valid_b, result.validation_errors_b = self._validate(root_b, schema)
            self.cardinality = SchemaCardinality.from_xsd(schema_path)
            result.schema_aware = self.cardinality is not None

        # ── Align message versions ─────────────────────────────────────
        ns_a, ns_b = namespace_of(root_a), namespace_of(root_b)
        version_entry: Optional[DiffEntry] = None
        result.message_type_a = message_type_from_namespace(ns_a) or ns_a or None
        result.message_type_b = message_type_from_namespace(ns_b) or ns_b or None
        if ns_a != ns_b:
            # A version upgrade (pain.001.001.09 → .12) changes the namespace on
            # every element; xmldiff refuses to diff across namespace URIs, so
            # document B is moved onto A's namespace and the version change is
            # reported once, as its own diff.
            result.message_type_a = message_type_from_namespace(ns_a) or ns_a
            result.message_type_b = message_type_from_namespace(ns_b) or ns_b
            root_b = rewrite_namespace(root_b, ns_b, ns_a)
            version_entry = DiffEntry(
                xpath=f"/{xpath_tag(root_a)}/@xmlns",
                change_type=ChangeType.MODIFIED,
                old_value=result.message_type_a,
                new_value=result.message_type_b,
                severity=Severity.BREAKING,
                explanation=(
                    f"Message version changed from {result.message_type_a} to "
                    f"{result.message_type_b} — receivers validating against the "
                    f"old schema will reject the message."
                ),
                raw_xpath=f"/{xpath_tag(root_a)}/@xmlns",
                element="@xmlns",
            )

        # ── Canonicalize ───────────────────────────────────────────────
        canon_a = canonicalize(root_a, ignore_tags=self.ignore_tags)
        canon_b = canonicalize(root_b, ignore_tags=self.ignore_tags)

        # ── Compute diffs via xmldiff ──────────────────────────────────
        actions = xmldiff_main.diff_trees(canon_a, canon_b)
        entries = self._actions_to_entries(actions, canon_a)
        if version_entry is not None:
            entries.insert(0, version_entry)

        result.diffs = entries
        result.breaking_score = self.classifier.breaking_score(
            [e.severity for e in entries]
        )
        result.score_breakdown = self.classifier.score_breakdown(
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

    # ── XPath resolution ───────────────────────────────────────────────────
    #
    # xmldiff reports XPaths against the canonical tree, and for namespaced
    # ISO 20022 documents those XPaths are positional (e.g. /*/*[2]/*[4]).
    # Classification and reporting need the business element names, so every
    # reported XPath is resolved back to a named path against the tree.
    #
    # Actions are cumulative — a later action can address a node an earlier
    # action inserted — so resolution happens against a working copy that is
    # patched action by action as the diff is walked.

    @staticmethod
    def _business_path(node: etree._Element) -> str:
        parts: list[str] = []
        current: Optional[etree._Element] = node
        while current is not None and isinstance(current.tag, str):
            tag = xpath_tag(current)
            parent = current.getparent()
            if parent is not None:
                sibs = [s for s in parent if isinstance(s.tag, str) and xpath_tag(s) == tag]
                if len(sibs) > 1:
                    tag = f"{tag}[{sibs.index(current) + 1}]"
            parts.append(tag)
            current = parent
        return "/" + "/".join(reversed(parts))

    @staticmethod
    def _resolve(raw_xpath: str, tree: etree._Element) -> Optional[etree._Element]:
        if not raw_xpath:
            return None
        try:
            found = tree.getroottree().xpath(raw_xpath)
        except Exception:
            return None
        if isinstance(found, list):
            found = found[0] if found else None
        return found if isinstance(found, etree._Element) else None

    def _named_path(self, raw_xpath: str, tree: etree._Element) -> str:
        """Resolve a positional XPath to a named business path (best effort)."""
        node = self._resolve(raw_xpath, tree)
        if node is not None:
            return self._business_path(node)
        return raw_xpath

    @staticmethod
    def _inside_added(path: str, added: dict[str, "DiffEntry"]) -> bool:
        """True when `path` sits inside a branch already reported as added."""
        return any(path.startswith(parent + "/") for parent in added)

    def _actions_to_entries(
        self, actions: list, reference_tree: etree._Element
    ) -> list[DiffEntry]:
        entries: list[DiffEntry] = []
        patcher = xmldiff_patch.Patcher()
        working = deepcopy(reference_tree)
        added: dict[str, DiffEntry] = {}

        for action in actions:
            raw_xpath = str(getattr(action, "node", None) or getattr(action, "target", "") or "")

            change_type: ChangeType
            old_val: Optional[str] = None
            new_val: Optional[str] = None
            inherits_optionality = False
            path = self._named_path(raw_xpath, working)

            # Tail text carries no business meaning in ISO 20022 documents.
            if isinstance(action, UpdateTextAfter):
                self._apply(patcher, action, working)
                continue

            if isinstance(action, UpdateTextIn):
                # xmldiff sets the text of a newly inserted element in a
                # separate action; report it as part of the insertion.
                if path in added:
                    added[path].new_value = action.text
                    self._apply(patcher, action, working)
                    continue
                change_type = ChangeType.MODIFIED
                new_val = action.text
                old_val = getattr(action, "oldtext", None)
                if old_val is None:
                    node = self._resolve(raw_xpath, working)
                    old_val = node.text if node is not None else None

            elif isinstance(action, DeleteNode):
                change_type = ChangeType.REMOVED
                node = self._resolve(raw_xpath, working)
                old_val = node.text if node is not None else None

            elif isinstance(action, InsertNode):
                # `target` is the parent in the reference tree; `tag` is the new element.
                change_type = ChangeType.ADDED
                path = f"{self._named_path(str(action.target), working)}/" \
                       f"{etree.QName(action.tag).localname}"
                # Elements that are mandatory *within* a newly added optional
                # branch are not mandatory for the sender: the whole branch is
                # optional, so they must not be graded as breaking.
                if self._inside_added(path, added):
                    inherits_optionality = True

            elif isinstance(action, MoveNode):
                change_type = ChangeType.REORDERED

            elif isinstance(action, RenameNode):
                change_type = ChangeType.MODIFIED
                node = self._resolve(raw_xpath, working)
                if node is not None:
                    old_val = etree.QName(node.tag).localname
                new_val = etree.QName(action.tag).localname

            elif isinstance(action, (UpdateAttrib, InsertAttrib)):
                change_type = ChangeType.ATTRIBUTE_CHANGED
                attr = etree.QName(action.name).localname if "}" in action.name else action.name
                node = self._resolve(raw_xpath, working)
                old_val = node.get(action.name) if node is not None else None
                new_val = str(action.value)
                path = f"{path}/@{attr}"

            elif isinstance(action, DeleteAttrib):
                change_type = ChangeType.REMOVED
                attr = etree.QName(action.name).localname if "}" in action.name else action.name
                node = self._resolve(raw_xpath, working)
                old_val = node.get(action.name) if node is not None else None
                path = f"{path}/@{attr}"

            elif isinstance(action, RenameAttrib):
                change_type = ChangeType.MODIFIED
                path = f"{path}/@{action.oldname}"
                new_val = str(action.newname)

            else:
                change_type = ChangeType.MODIFIED

            element = path.split("/")[-1].split("[")[0]
            severity = self.classifier.classify(
                xpath=path,
                change_type=change_type,
                old_value=old_val,
                new_value=new_val,
                is_mandatory=False if inherits_optionality else self._is_mandatory(path),
            )

            entries.append(
                DiffEntry(
                    xpath=path,
                    change_type=change_type,
                    old_value=old_val,
                    new_value=new_val,
                    severity=severity,
                    explanation=self._explain(path, change_type, severity),
                    raw_xpath=raw_xpath,
                    element=element,
                )
            )
            if change_type == ChangeType.ADDED:
                added[path] = entries[-1]

            self._apply(patcher, action, working)

        return entries

    @staticmethod
    def _apply(patcher: xmldiff_patch.Patcher, action, tree: etree._Element) -> None:
        """Advance the working tree; path resolution degrades but never fails."""
        try:
            patcher.handle_action(action, tree)
        except Exception as exc:
            log.debug("Could not apply %s while resolving paths: %s", action, exc)

    def _is_mandatory(self, path: str) -> Optional[bool]:
        """Schema cardinality for a business path (None when unknown)."""
        if self.cardinality is None:
            return None
        return self.cardinality.is_mandatory(path)

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
