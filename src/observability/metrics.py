"""
Turn the run log into the "weeks, not months" number — with its assumptions
stated on screen.

The pitch claims transformation-requirements effort drops from weeks to
minutes. The run log measures the minutes precisely; the weeks are an estimate
of what the same deliverable costs by hand. Rather than bury that estimate in a
slide, every baseline below is an explicit, overridable constant that the UI
prints next to the result, so a reviewer can argue with the assumption instead
of doubting the arithmetic.

Baselines are per completed run and deliberately conservative — the low end of
what a BA plus an ISO 20022 specialist spend producing the same artefact.
"""
from __future__ import annotations

import math
import os
from typing import Any, Sequence

from .run_log import CHAT, DIFF, TRANSFORM, RunEvent

# Manual effort per deliverable, in hours.
BASELINE_HOURS: dict[str, float] = {
    TRANSFORM: 40.0,  # mapping workshops + gap analysis + writing the TRD
    DIFF: 8.0,        # schema diff read by hand and written up as an impact note
    CHAT: 0.5,        # a field question routed to a specialist and answered
}

BASELINE_LABELS: dict[str, str] = {
    TRANSFORM: (
        "Transformation requirements document — mapping workshops, gap "
        "analysis and drafting"
    ),
    DIFF: "Schema-version impact assessment produced by hand",
    CHAT: "One grounded field question routed to an ISO 20022 specialist",
}

_HOURS_PER_DAY = 7.5


def duration_label(seconds: float) -> str:
    """
    Seconds are the honest unit for a diff; minutes for a mapping run.

    Sub-second runs keep two decimals so a 30 ms comparison reads `0.03 s`
    rather than a `0.0 s` that looks like nothing was measured.
    """
    if seconds < 1:
        return f"{seconds:.2f} s"
    if seconds < 60:
        return f"{seconds:.1f} s"
    return f"{seconds / 60:.1f} min"


def _speedup_label(value: float) -> str:
    """
    Two significant figures.

    A comparison that takes 30 ms against an eight-hour baseline is honestly a
    six-figure ratio, and printing `765,957×` reads as a spreadsheet accident.
    Rounding to `770,000×` says the same thing without implying the last digit
    means anything.
    """
    if value < 100:
        return f"{value:,.0f}×"
    magnitude = 10 ** (len(f"{int(value)}") - 2)
    return f"{round(value / magnitude) * magnitude:,.0f}×"


def baseline_hours(kind: str) -> float:
    """
    Manual baseline for one run of `kind`.

    `SWIFTSAGE_BASELINE_<KIND>_HOURS` overrides it, so a client who thinks 40
    hours is generous (or mean) can set their own number before the demo.
    """
    raw = os.environ.get(f"SWIFTSAGE_BASELINE_{kind.upper()}_HOURS", "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            value = 0.0
        if math.isfinite(value) and value > 0:
            return value
    return BASELINE_HOURS.get(kind, 0.0)


def _counts(event: RunEvent) -> bool:
    """
    Whether this run produced the deliverable its baseline is priced on.

    Failures produced nothing. A chat turn only replaces a question to a
    specialist if it actually consulted the schemas — "summarise what SwiftSage
    does" is not half an hour of SME time, so an ungrounded turn earns nothing.
    """
    if event.status != "ok":
        return False
    if event.kind == CHAT:
        return bool(event.detail.get("grounding_tool_calls"))
    return True


def effort_summary(events: Sequence[RunEvent]) -> dict[str, Any]:
    """
    Compare measured run time against the manual baseline.

    Only runs that delivered something count (see `_counts`). Tool calls are
    excluded because they are already inside the chat turn that invoked them.
    """
    rows: list[dict[str, Any]] = []
    automated_s = 0.0
    manual_h = 0.0

    for kind in (TRANSFORM, DIFF, CHAT):
        done = [e for e in events if e.kind == kind and _counts(e)]
        if not done:
            continue
        seconds = sum(e.duration_ms for e in done) / 1000
        hours = baseline_hours(kind) * len(done)
        automated_s += seconds
        manual_h += hours
        rows.append({
            "kind": kind,
            "deliverable": BASELINE_LABELS.get(kind, kind),
            "runs": len(done),
            "automated_minutes": round(seconds / 60, 1),
            "automated_label": duration_label(seconds),
            "baseline_hours_each": baseline_hours(kind),
            "manual_hours": round(hours, 1),
            "hours_saved": round(hours - seconds / 3600, 1),
        })

    automated_h = automated_s / 3600
    speedup = manual_h / automated_h if automated_h > 0 and manual_h else None
    return {
        "rows": rows,
        "runs": sum(row["runs"] for row in rows),
        "automated_minutes": round(automated_s / 60, 1),
        "automated_label": duration_label(automated_s),
        "manual_hours": round(manual_h, 1),
        "manual_days": round(manual_h / _HOURS_PER_DAY, 1),
        "hours_saved": round(manual_h - automated_h, 1),
        "speedup": round(speedup) if speedup else None,
        "speedup_label": _speedup_label(speedup) if speedup else "—",
    }


def assumptions() -> list[str]:
    """The estimates behind the saving, for display next to it."""
    lines = [
        f"{BASELINE_LABELS[kind]} — {baseline_hours(kind):g} h manually."
        for kind in (TRANSFORM, DIFF, CHAT)
        if baseline_hours(kind)
    ]
    lines.append(
        "Only successful runs count — and a chat turn only counts if it "
        "consulted the schemas, so general questions earn nothing. A working "
        f"day is {_HOURS_PER_DAY:g} hours, and review time is not deducted: "
        "SwiftSage produces a draft a specialist still signs off."
    )
    lines.append(
        "The speed-up compares measured machine time with estimated human "
        "effort, so it is very large for small deliverables — the hours "
        "avoided are the figure worth quoting."
    )
    return lines
