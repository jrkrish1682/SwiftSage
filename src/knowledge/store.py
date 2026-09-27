"""
The SwiftSage knowledge store — a local, typed knowledge graph in SQLite.

The vendored XSDs and the curated glossary make SwiftSage accurate about the
*published* standard. They say nothing about a particular institution: which
internal field feeds `UETR`, that a guarantee amendment without the original
reference goes to manual checking, or that last quarter's rejects came from a
truncated `RmtInf`. That second body of facts is the tribal knowledge held by a
handful of specialists, and this module is where it accumulates.

Why a typed graph in SQLite rather than a vector store: a business rule must be
enumerable, inspectable and editable by a BA, and an answer must be able to name
the rule it came from. Embeddings give none of that, and at demo scale keyword
and structured search are sufficient. Nothing here needs a network or a key.

Two invariants matter more than the schema:

* **Provenance.** Every node can answer "why do you believe this?" through its
  `evidence` rows — a citation and the run that produced it.
* **Candidate vs confirmed.** Anything the model infers lands as `candidate` and
  is rendered as unconfirmed everywhere it appears. Only a human promotes it to
  `confirmed`. If the model could confirm its own inferences the store would
  drift, and the provenance guarantee would be worth nothing.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence

from src.utils.helpers import get_logger

log = get_logger(__name__)

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "knowledge" / "knowledge.db"

# ── Node kinds ────────────────────────────────────────────────────────────────
RULE = "business_rule"
ISO_ELEMENT = "iso_element"
INTERNAL_FIELD = "internal_field"
MAPPING = "mapping_decision"
MESSAGE_TYPE = "message_type"
DEFECT = "defect"
TEST_SCENARIO = "test_scenario"
SYSTEM = "system"

# ── Edge relations ────────────────────────────────────────────────────────────
GOVERNS = "governs"
MAPS_TO = "maps_to"
DERIVED_FROM = "derived_from"
DEPENDS_ON = "depends_on"
CONTRADICTS = "contradicts"
CAUSED = "caused"
VERIFIES = "verifies"
OWNED_BY = "owned_by"
LEARNED_FROM = "learned_from"

# ── Status lifecycle ──────────────────────────────────────────────────────────
SEEDED = "seeded"
CANDIDATE = "candidate"
CONFIRMED = "confirmed"
RETIRED = "retired"

#: Statuses an answer may quote as institutional policy.
AUTHORITATIVE = (SEEDED, CONFIRMED)

DOMAINS = ("Payments", "Cash", "Trade", "Securities/Settlement")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    name        TEXT NOT NULL,
    domain      TEXT NOT NULL DEFAULT '',
    summary     TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'candidate',
    confidence  INTEGER NOT NULL DEFAULT 50,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edges (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    src        TEXT NOT NULL,
    dst        TEXT NOT NULL,
    relation   TEXT NOT NULL,
    confidence INTEGER NOT NULL DEFAULT 50,
    source     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (src, dst, relation)
);
CREATE TABLE IF NOT EXISTS evidence (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id    TEXT NOT NULL,
    citation   TEXT NOT NULL,
    run_id     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (node_id, citation)
);
CREATE TABLE IF NOT EXISTS rules (
    node_id       TEXT PRIMARY KEY,
    condition     TEXT NOT NULL DEFAULT '',
    action        TEXT NOT NULL DEFAULT '',
    severity      TEXT NOT NULL DEFAULT 'MEDIUM',
    message_types TEXT NOT NULL DEFAULT '',
    source_kind   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_nodes_kind   ON nodes (kind);
CREATE INDEX IF NOT EXISTS idx_nodes_domain ON nodes (domain);
CREATE INDEX IF NOT EXISTS idx_edges_src    ON edges (src);
CREATE INDEX IF NOT EXISTS idx_edges_dst    ON edges (dst);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Node:
    """One fact in the graph."""

    id: str
    kind: str
    name: str
    domain: str = ""
    summary: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    status: str = CANDIDATE
    confidence: int = 50
    created_at: str = ""
    updated_at: str = ""

    @property
    def authoritative(self) -> bool:
        """Whether this may be quoted as institutional policy."""
        return self.status in AUTHORITATIVE

    @property
    def status_label(self) -> str:
        return {
            SEEDED: "seeded (mocked policy, not published ISO)",
            CANDIDATE: "candidate — inferred, awaiting confirmation",
            CONFIRMED: "confirmed by a specialist",
            RETIRED: "retired",
        }.get(self.status, self.status)


@dataclass(frozen=True)
class Rule:
    """A business rule: its node plus the structured condition/action."""

    node: Node
    condition: str = ""
    action: str = ""
    severity: str = "MEDIUM"
    message_types: tuple[str, ...] = ()
    source_kind: str = ""

    @property
    def id(self) -> str:
        return self.node.id

    @property
    def name(self) -> str:
        return self.node.name

    @property
    def domain(self) -> str:
        return self.node.domain

    @property
    def elements(self) -> tuple[str, ...]:
        raw = self.node.detail.get("elements") or ()
        return tuple(str(e) for e in raw)

    def applies_to(self, message_type: str) -> bool:
        """True when the rule names this message type, its version-less form or
        its family — or names no message type at all, which means domain-wide."""
        if not self.message_types:
            return True
        wanted = (message_type or "").strip().lower()
        if not wanted:
            return True
        return any(
            wanted.startswith(m.lower()) or m.lower().startswith(wanted)
            for m in self.message_types
        )

    def render(self) -> str:
        """Plain-text form used in prompts and exports, provenance included."""
        scope = ", ".join(self.message_types) or "all messages in the domain"
        return (
            f"{self.id} — {self.name} [{self.severity}]\n"
            f"  Domain    : {self.domain}\n"
            f"  Applies to: {scope}\n"
            f"  Condition : {self.condition}\n"
            f"  Action    : {self.action}\n"
            f"  Status    : {self.node.status_label} (confidence {self.node.confidence})"
        )


@dataclass(frozen=True)
class Edge:
    """A typed, directed relationship."""

    src: str
    dst: str
    relation: str
    confidence: int = 50
    source: str = ""


@dataclass(frozen=True)
class Neighbourhood:
    """One node plus the nodes reachable from it, for the graph view."""

    centre: Node
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]


def db_path() -> Path:
    """Where the graph lives. `KNOWLEDGE_DB_PATH` overrides, mainly for tests."""
    override = os.environ.get("KNOWLEDGE_DB_PATH", "").strip()
    return Path(override) if override else _DEFAULT_PATH


class KnowledgeStore:
    """
    SQLite-backed knowledge graph.

    A connection is opened per operation rather than held: Streamlit reruns the
    script on every interaction and may do so from a different thread, and a
    long-lived `sqlite3.Connection` is not safe across threads.
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    # ── Opening ────────────────────────────────────────────────────────────

    @classmethod
    def open(cls, path: Optional[Path] = None, seed: bool = True) -> "KnowledgeStore":
        """Open the store, seeding the mocked rule set when it is still empty."""
        store = cls(path)
        if seed and not store.counts()["nodes"]:
            from src.knowledge.seeds import seed

            seed(store)
        return store

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── Writing ────────────────────────────────────────────────────────────

    def put_node(
        self,
        node_id: str,
        kind: str,
        name: str,
        *,
        domain: str = "",
        summary: str = "",
        detail: Optional[dict[str, Any]] = None,
        status: str = CANDIDATE,
        confidence: int = 50,
    ) -> Node:
        """
        Insert or update a node.

        An existing node is never *downgraded*: re-observing a confirmed fact
        leaves it confirmed, so the automatic capture loop cannot quietly undo a
        specialist's confirmation.
        """
        existing = self.node(node_id)
        if existing is not None and existing.status in AUTHORITATIVE and status == CANDIDATE:
            status = existing.status
            confidence = max(confidence, existing.confidence)
        payload = json.dumps(detail or {}, ensure_ascii=False)
        now = _now()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO nodes (id, kind, name, domain, summary, detail_json,
                                   status, confidence, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    kind=excluded.kind, name=excluded.name, domain=excluded.domain,
                    summary=excluded.summary, detail_json=excluded.detail_json,
                    status=excluded.status, confidence=excluded.confidence,
                    updated_at=excluded.updated_at
                """,
                (node_id, kind, name, domain, summary, payload, status,
                 int(confidence), now, now),
            )
        return self.node(node_id)  # type: ignore[return-value]

    def put_rule(
        self,
        rule_id: str,
        name: str,
        *,
        domain: str,
        condition: str,
        action: str,
        severity: str = "MEDIUM",
        message_types: Sequence[str] = (),
        elements: Sequence[str] = (),
        summary: str = "",
        status: str = CANDIDATE,
        confidence: int = 50,
        source_kind: str = "",
        detail: Optional[dict[str, Any]] = None,
    ) -> Rule:
        """Insert or update a business rule and its structured fields."""
        payload = dict(detail or {})
        payload["elements"] = list(elements)
        node = self.put_node(
            rule_id, RULE, name,
            domain=domain,
            summary=summary or f"{condition} → {action}",
            detail=payload,
            status=status,
            confidence=confidence,
        )
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO rules (node_id, condition, action, severity,
                                   message_types, source_kind)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(node_id) DO UPDATE SET
                    condition=excluded.condition, action=excluded.action,
                    severity=excluded.severity,
                    message_types=excluded.message_types,
                    source_kind=excluded.source_kind
                """,
                (rule_id, condition, action, severity.upper(),
                 ",".join(message_types), source_kind),
            )
        return self.rule(node.id)  # type: ignore[return-value]

    def merge_detail(self, node_id: str, **values: Any) -> None:
        """Add or replace keys in a node's detail, leaving the rest intact."""
        node = self.node(node_id)
        if node is None:
            return
        detail = dict(node.detail)
        detail.update(values)
        with self._conn() as conn:
            conn.execute(
                "UPDATE nodes SET detail_json=?, updated_at=? WHERE id=?",
                (json.dumps(detail, ensure_ascii=False), _now(), node_id),
            )

    def link(
        self,
        src: str,
        dst: str,
        relation: str,
        *,
        confidence: int = 50,
        source: str = "",
    ) -> None:
        """Relate two nodes. Repeating an existing edge refreshes its metadata."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO edges (src, dst, relation, confidence, source, created_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(src, dst, relation) DO UPDATE SET
                    confidence=excluded.confidence, source=excluded.source
                """,
                (src, dst, relation, int(confidence), source, _now()),
            )

    def add_evidence(self, node_id: str, citation: str, run_id: str = "") -> None:
        """Record why a node is believed. Duplicate citations collapse."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO evidence (node_id, citation, run_id, created_at)
                VALUES (?,?,?,?)
                ON CONFLICT(node_id, citation) DO NOTHING
                """,
                (node_id, citation[:400], run_id, _now()),
            )

    def set_status(self, node_id: str, status: str, confidence: Optional[int] = None) -> None:
        """Promote, retire or otherwise restate a node's standing."""
        with self._conn() as conn:
            if confidence is None:
                conn.execute(
                    "UPDATE nodes SET status=?, updated_at=? WHERE id=?",
                    (status, _now(), node_id),
                )
            else:
                conn.execute(
                    "UPDATE nodes SET status=?, confidence=?, updated_at=? WHERE id=?",
                    (status, int(confidence), _now(), node_id),
                )

    def next_id(self, prefix: str) -> str:
        """Next free sequential id for a prefix, e.g. `BR-013`, `DEF-004`."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id FROM nodes WHERE id LIKE ?", (f"{prefix}-%",)
            ).fetchall()
        highest = 0
        for row in rows:
            tail = str(row["id"]).rsplit("-", 1)[-1]
            if tail.isdigit():
                highest = max(highest, int(tail))
        return f"{prefix}-{highest + 1:03d}"

    def reset(self, seed: bool = True) -> None:
        """Wipe the graph — the demo operator's reset between rehearsals."""
        with self._conn() as conn:
            conn.executescript(
                "DELETE FROM evidence; DELETE FROM rules; "
                "DELETE FROM edges; DELETE FROM nodes;"
            )
        if seed:
            from src.knowledge.seeds import seed as seed_fn

            seed_fn(self)

    # ── Reading ────────────────────────────────────────────────────────────

    def node(self, node_id: str) -> Optional[Node]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        return _node(row) if row else None

    def nodes(
        self,
        *,
        kind: str = "",
        domain: str = "",
        statuses: Sequence[str] = (),
        limit: int = 500,
    ) -> list[Node]:
        sql = "SELECT * FROM nodes WHERE 1=1"
        args: list[Any] = []
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        if domain:
            sql += " AND domain=?"
            args.append(domain)
        if statuses:
            sql += f" AND status IN ({','.join('?' * len(statuses))})"
            args.extend(statuses)
        sql += " ORDER BY id LIMIT ?"
        args.append(int(limit))
        with self._conn() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [_node(r) for r in rows]

    def search(self, query: str, *, kind: str = "", domain: str = "",
               statuses: Sequence[str] = (), limit: int = 40) -> list[Node]:
        """
        Nodes matching *query* across id, name, summary and the rule text.

        Keyword search, deliberately: a BA needs to see the whole rule set and
        edit it, which a similarity score over embeddings would not give.
        """
        needle = f"%{(query or '').strip().lower()}%"
        sql = """
            SELECT n.* FROM nodes n
            LEFT JOIN rules r ON r.node_id = n.id
            WHERE (LOWER(n.id) LIKE ? OR LOWER(n.name) LIKE ?
                   OR LOWER(n.summary) LIKE ? OR LOWER(n.detail_json) LIKE ?
                   OR LOWER(COALESCE(r.condition,'')) LIKE ?
                   OR LOWER(COALESCE(r.action,'')) LIKE ?)
        """
        args: list[Any] = [needle] * 6
        if kind:
            sql += " AND n.kind=?"
            args.append(kind)
        if domain:
            sql += " AND n.domain=?"
            args.append(domain)
        if statuses:
            sql += f" AND n.status IN ({','.join('?' * len(statuses))})"
            args.extend(statuses)
        sql += " ORDER BY n.kind, n.id LIMIT ?"
        args.append(int(limit))
        with self._conn() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [_node(r) for r in rows]

    def rule(self, node_id: str) -> Optional[Rule]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT n.*, r.condition, r.action, r.severity, r.message_types,
                       r.source_kind
                FROM nodes n JOIN rules r ON r.node_id = n.id
                WHERE n.id=?
                """,
                (node_id,),
            ).fetchone()
        return _rule(row) if row else None

    def rules(
        self,
        *,
        domain: str = "",
        message_type: str = "",
        statuses: Sequence[str] = AUTHORITATIVE,
        limit: int = 200,
    ) -> list[Rule]:
        """
        Business rules, narrowed to what is in play.

        `statuses` defaults to the authoritative set, so a caller that forgets
        to filter cannot inject an unconfirmed guess into a prompt or a report.
        """
        sql = """
            SELECT n.*, r.condition, r.action, r.severity, r.message_types,
                   r.source_kind
            FROM nodes n JOIN rules r ON r.node_id = n.id
            WHERE 1=1
        """
        args: list[Any] = []
        if domain:
            sql += " AND n.domain=?"
            args.append(domain)
        if statuses:
            sql += f" AND n.status IN ({','.join('?' * len(statuses))})"
            args.extend(statuses)
        sql += " ORDER BY n.id LIMIT ?"
        args.append(int(limit))
        with self._conn() as conn:
            rows = conn.execute(sql, args).fetchall()
        found = [_rule(r) for r in rows]
        if message_type:
            found = [r for r in found if r.applies_to(message_type)]
        return found

    def search_rules(
        self,
        query: str,
        *,
        domain: str = "",
        statuses: Sequence[str] = AUTHORITATIVE,
        limit: int = 20,
    ) -> list[Rule]:
        """Business rules matching *query*, authoritative ones by default."""
        nodes = self.search(
            query, kind=RULE, domain=domain, statuses=statuses, limit=limit
        )
        found = [self.rule(n.id) for n in nodes]
        return [r for r in found if r is not None]

    def evidence(self, node_id: str) -> list[tuple[str, str]]:
        """`(citation, run_id)` pairs, newest last."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT citation, run_id FROM evidence WHERE node_id=? ORDER BY id",
                (node_id,),
            ).fetchall()
        return [(r["citation"], r["run_id"]) for r in rows]

    def edges(self, node_id: str = "", relation: str = "") -> list[Edge]:
        sql = "SELECT * FROM edges WHERE 1=1"
        args: list[Any] = []
        if node_id:
            sql += " AND (src=? OR dst=?)"
            args.extend([node_id, node_id])
        if relation:
            sql += " AND relation=?"
            args.append(relation)
        with self._conn() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [
            Edge(src=r["src"], dst=r["dst"], relation=r["relation"],
                 confidence=r["confidence"], source=r["source"])
            for r in rows
        ]

    def neighbourhood(self, node_id: str, hops: int = 1) -> Optional[Neighbourhood]:
        """
        The node plus everything within *hops* edges of it.

        A neighbourhood rather than the whole graph, because the whole graph
        renders as an unreadable hairball the moment it is useful.
        """
        centre = self.node(node_id)
        if centre is None:
            return None
        frontier = {node_id}
        seen = {node_id}
        edges: dict[tuple[str, str, str], Edge] = {}
        for _ in range(max(1, hops)):
            nxt: set[str] = set()
            for current in frontier:
                for edge in self.edges(current):
                    edges[(edge.src, edge.dst, edge.relation)] = edge
                    for other in (edge.src, edge.dst):
                        if other not in seen:
                            seen.add(other)
                            nxt.add(other)
            frontier = nxt
            if not frontier:
                break
        nodes = [n for n in (self.node(i) for i in sorted(seen)) if n is not None]
        return Neighbourhood(centre=centre, nodes=tuple(nodes), edges=tuple(edges.values()))

    def counts(self) -> dict[str, Any]:
        """Totals for the growth story — nodes, edges, and the status split."""
        with self._conn() as conn:
            nodes = conn.execute("SELECT COUNT(*) c FROM nodes").fetchone()["c"]
            edges = conn.execute("SELECT COUNT(*) c FROM edges").fetchone()["c"]
            by_status = {
                r["status"]: r["c"]
                for r in conn.execute(
                    "SELECT status, COUNT(*) c FROM nodes GROUP BY status"
                ).fetchall()
            }
            by_kind = {
                r["kind"]: r["c"]
                for r in conn.execute(
                    "SELECT kind, COUNT(*) c FROM nodes GROUP BY kind"
                ).fetchall()
            }
            by_domain = {
                r["domain"]: r["c"]
                for r in conn.execute(
                    "SELECT domain, COUNT(*) c FROM nodes "
                    "WHERE domain <> '' GROUP BY domain"
                ).fetchall()
            }
        return {
            "nodes": nodes,
            "edges": edges,
            "by_status": by_status,
            "by_kind": by_kind,
            "by_domain": by_domain,
            "candidates": by_status.get(CANDIDATE, 0),
            "confirmed": by_status.get(CONFIRMED, 0) + by_status.get(SEEDED, 0),
        }


def _node(row: sqlite3.Row) -> Node:
    try:
        detail = json.loads(row["detail_json"] or "{}")
    except json.JSONDecodeError:
        detail = {}
    return Node(
        id=row["id"],
        kind=row["kind"],
        name=row["name"],
        domain=row["domain"],
        summary=row["summary"],
        detail=detail if isinstance(detail, dict) else {},
        status=row["status"],
        confidence=row["confidence"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _rule(row: sqlite3.Row) -> Rule:
    types = tuple(t.strip() for t in (row["message_types"] or "").split(",") if t.strip())
    return Rule(
        node=_node(row),
        condition=row["condition"],
        action=row["action"],
        severity=row["severity"],
        message_types=types,
        source_kind=row["source_kind"],
    )
