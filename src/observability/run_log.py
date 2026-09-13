"""
Append-only run log — the observability substrate for the SwiftSage demo.

Every user-visible unit of work (a chat turn, a grounding tool call, a Transform
Advisor run, an XML comparison) writes one JSON line to `logs/runs.jsonl`:

    {"ts": "...", "kind": "transform", "name": "pain.001.001.09",
     "status": "ok", "duration_ms": 8412, "detail": {...}}

Deliberately local and dependency-free: no account, no network egress, and the
demo still produces evidence when run offline. Detail payloads carry counts,
names and outcomes only — never message content and never credentials — so the
file can be shared alongside a demo recording.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterator, Optional, Sequence

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "logs" / "runs.jsonl"
_MAX_BYTES = 2 * 1024 * 1024

CHAT = "chat"
TOOL = "tool"
TRANSFORM = "transform"
DIFF = "diff"

_MAX_STR = 240
_SECRET_HINTS = ("key", "token", "secret", "password", "authorization", "credential")
_SECRET_VALUE_HINTS = ("sk-ant-", "sk-", "bearer ")


@dataclass(frozen=True)
class RunEvent:
    """One recorded unit of work."""

    ts: str
    kind: str
    name: str
    status: str = "ok"
    duration_ms: int = 0
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def when(self) -> datetime:
        try:
            return datetime.fromisoformat(self.ts)
        except ValueError:
            return datetime.fromtimestamp(0, tz=timezone.utc)

    @property
    def duration_s(self) -> float:
        return round(self.duration_ms / 1000, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "kind": self.kind,
            "name": self.name,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RunEvent":
        detail = raw.get("detail")
        return cls(
            ts=str(raw.get("ts", "")),
            kind=str(raw.get("kind", "unknown")),
            name=str(raw.get("name", "")),
            status=str(raw.get("status", "ok")),
            duration_ms=int(raw.get("duration_ms") or 0),
            detail=detail if isinstance(detail, dict) else {},
        )


# ── Location ───────────────────────────────────────────────────────────────────

def log_path() -> Path:
    """Where events are written. `RUN_LOG_PATH` overrides, mainly for tests."""
    override = os.environ.get("RUN_LOG_PATH", "").strip()
    return Path(override) if override else _DEFAULT_PATH


def clear() -> None:
    """Drop the log — the demo operator's reset button between rehearsals."""
    path = log_path()
    if path.exists():
        path.unlink()


# ── Redaction ──────────────────────────────────────────────────────────────────

def _looks_secret(key: str, value: Any) -> bool:
    if any(hint in key.lower() for hint in _SECRET_HINTS):
        return True
    if isinstance(value, str):
        low = value.lower()
        return any(hint in low for hint in _SECRET_VALUE_HINTS)
    return False


def _scrub(value: Any, depth: int = 0) -> Any:
    """Reduce a detail value to something safe and JSON-serialisable."""
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value[:_MAX_STR]
    if depth >= 3:
        return str(value)[:_MAX_STR]
    if isinstance(value, dict):
        return {
            str(k): ("[redacted]" if _looks_secret(str(k), v) else _scrub(v, depth + 1))
            for k, v in list(value.items())[:40]
        }
    if isinstance(value, (list, tuple, set)):
        return [_scrub(v, depth + 1) for v in list(value)[:40]]
    return str(value)[:_MAX_STR]


def _scrub_detail(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        str(k): ("[redacted]" if _looks_secret(str(k), v) else _scrub(v))
        for k, v in detail.items()
    }


# ── Writing ────────────────────────────────────────────────────────────────────

def _rotate_if_needed(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > _MAX_BYTES:
            path.replace(path.with_suffix(path.suffix + ".1"))
    except OSError:
        pass


def record(
    kind: str,
    name: str,
    *,
    status: str = "ok",
    duration_ms: int = 0,
    **detail: Any,
) -> RunEvent:
    """Append one event. Never raises — telemetry must not break a demo."""
    event = RunEvent(
        ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        kind=kind,
        name=name,
        status=status,
        duration_ms=max(0, int(duration_ms)),
        detail=_scrub_detail(detail),
    )
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_if_needed(path)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError):
        pass
    return event


@contextmanager
def track(kind: str, name: str, **detail: Any) -> Iterator[dict[str, Any]]:
    """
    Time a block and record it on the way out, whether it succeeded or not.

    The yielded dict is the event detail — mutate it as facts become known:

        with track(TRANSFORM, target) as d:
            d["fields_mapped"] = len(mappings)

    Set `d["status"]` for a failure the block reports without raising (a parse
    error returned as a result, say); a raised exception always wins.
    """
    payload: dict[str, Any] = dict(detail)
    started = time.perf_counter()
    status = "ok"
    try:
        yield payload
    except BaseException as exc:  # noqa: BLE001 - recorded, then re-raised
        status = "error"
        payload.setdefault("error", f"{type(exc).__name__}: {exc}")
        raise
    finally:
        reported = str(payload.pop("status", status))
        record(
            kind,
            name,
            status=status if status == "error" else reported,
            duration_ms=int((time.perf_counter() - started) * 1000),
            **payload,
        )


# ── Reading ────────────────────────────────────────────────────────────────────

def read_events(
    limit: int = 200,
    kinds: Optional[Sequence[str]] = None,
) -> list[RunEvent]:
    """
    Most recent events first. Malformed lines are skipped, not fatal.

    `kinds=None` means every kind; an empty sequence means none, so a UI filter
    with nothing selected shows nothing rather than everything.
    """
    if kinds is not None and not kinds:
        return []
    path = log_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    wanted = set(kinds) if kinds is not None else None
    events: list[RunEvent] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        event = RunEvent.from_dict(raw)
        if wanted and event.kind not in wanted:
            continue
        events.append(event)
        if len(events) >= limit:
            break
    return events


def summarise(events: Sequence[RunEvent]) -> dict[str, Any]:
    """Roll events up into the numbers the demo needs to quote."""
    by_kind: dict[str, dict[str, Any]] = {}
    for kind in (CHAT, TOOL, TRANSFORM, DIFF):
        durations = [e.duration_ms for e in events if e.kind == kind]
        if not durations:
            continue
        by_kind[kind] = {
            "runs": len(durations),
            "median_s": round(median(durations) / 1000, 2),
            "slowest_s": round(max(durations) / 1000, 2),
        }

    tool_counts: dict[str, int] = {}
    for event in events:
        if event.kind == TOOL:
            tool_counts[event.name] = tool_counts.get(event.name, 0) + 1

    chat_turns = [e for e in events if e.kind == CHAT]
    grounded = [e for e in chat_turns if e.detail.get("grounding_tool_calls")]

    return {
        "events": len(events),
        "errors": sum(1 for e in events if e.status == "error"),
        "by_kind": by_kind,
        "tool_counts": dict(sorted(tool_counts.items(), key=lambda kv: -kv[1])),
        "chat_turns": len(chat_turns),
        "grounded_turns": len(grounded),
        "grounded_rate": (
            round(100 * len(grounded) / len(chat_turns)) if chat_turns else None
        ),
    }
