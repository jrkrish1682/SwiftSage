"""
Phase 4 — demo scenarios and effort metrics.

The demo scenarios are only useful if their assets exist and their presets
match the option labels the tabs actually offer; a stale label silently leaves
the widget on its default and the presenter demos the wrong pair. The metrics
are only credible if they refuse to credit failed runs.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.connectors.schema_bundle import bundle_files
from src.observability import metrics
from src.observability.run_log import CHAT, DIFF, TOOL, TRANSFORM, RunEvent
from src.ui import demo_scenarios, prompt_packs
from src.ui.demo_scenarios import SCENARIOS, Scenario

APP_SOURCE = (Path(__file__).resolve().parents[1] / "app.py").read_text(
    encoding="utf-8"
)


def _event(kind: str, seconds: float, status: str = "ok",
           **detail: object) -> RunEvent:
    if kind == CHAT and "grounding_tool_calls" not in detail:
        detail["grounding_tool_calls"] = 1
    return RunEvent(
        ts="2026-01-01T00:00:00+00:00",
        kind=kind,
        name="x",
        status=status,
        duration_ms=int(seconds * 1000),
        detail=detail,
    )


# ── Scenario registry ──────────────────────────────────────────────────────────

def test_scenarios_cover_both_domains_and_an_offline_path():
    assert len(SCENARIOS) >= 3
    assert any(not s.needs_key for s in SCENARIOS), "demo must survive no key"
    tabs = {s.tab for s in SCENARIOS}
    assert "🔍 XML Diff" in tabs
    assert "🔄 Transform Advisor" in tabs


def test_scenario_ids_are_unique_and_addressable():
    ids = [s.id for s in SCENARIOS]
    assert len(ids) == len(set(ids))
    for scenario_id in ids:
        assert demo_scenarios.by_id(scenario_id) is not None
    assert demo_scenarios.by_id("no-such-scenario") is None


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_scenario_assets_exist(scenario: Scenario):
    assert demo_scenarios.missing_assets(scenario) == []


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_scenario_is_narratable(scenario: Scenario):
    assert scenario.question.endswith("?")
    assert scenario.talking_points and scenario.watch_for


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_preset_labels_are_offered_by_the_tabs(scenario: Scenario):
    """A preset that no widget offers would leave the demo on its default."""
    for key, value in scenario.presets.items():
        if key == "diff_schema_choice":
            labels = {f"{p.stem} ({p.parent.name})" for p in bundle_files()}
            assert value in labels
        elif key == "chat_prompt_pack":
            assert value in prompt_packs.pack_names()
        else:
            assert f'"{value}"' in APP_SOURCE or f"'{value}'" in APP_SOURCE, key


def test_offline_scenarios_run_a_real_comparison():
    """The no-key scenarios are the ones that must work with no network."""
    from src.comparator.xml_comparator import XMLComparator

    offline = [s for s in SCENARIOS if not s.needs_key and s.diff]
    assert offline
    for scenario in offline:
        baseline, revised, schema = scenario.diff.paths()
        result = XMLComparator().compare(
            str(baseline), str(revised), schema_path=str(schema)
        )
        assert not result.parse_error
        assert result.diffs, f"{scenario.id} shows nothing to discuss"
        assert result.breaking, f"{scenario.id} has no breaking change to show"


def test_key_scenarios_declare_what_they_feed_the_model():
    for scenario in SCENARIOS:
        if scenario.needs_key:
            assert scenario.chat_prompt or scenario.source_asset


# ── Effort metrics ─────────────────────────────────────────────────────────────

def test_effort_summary_contrasts_measured_time_with_the_baseline():
    summary = metrics.effort_summary([
        _event(TRANSFORM, 120),
        _event(DIFF, 2),
    ])
    assert summary["runs"] == 2
    assert summary["automated_minutes"] == pytest.approx(2.03, abs=0.05)
    assert summary["manual_hours"] == pytest.approx(48.0)
    assert summary["manual_days"] == pytest.approx(6.4)
    assert summary["hours_saved"] == pytest.approx(47.97, abs=0.05)
    assert summary["speedup"] > 100
    assert summary["automated_label"] == "2.0 min"


def test_failed_runs_earn_no_credit():
    summary = metrics.effort_summary([
        _event(DIFF, 2, status="error"),
        _event(DIFF, 2),
    ])
    assert summary["runs"] == 1
    assert summary["manual_hours"] == pytest.approx(metrics.BASELINE_HOURS[DIFF])


def test_ungrounded_chat_is_not_a_specialist_question():
    """A chat turn that never touched a schema is not SME time avoided."""
    summary = metrics.effort_summary([
        _event(CHAT, 6, grounding_tool_calls=0),
        _event(CHAT, 6, grounding_tool_calls=2),
    ])
    assert summary["runs"] == 1
    assert summary["manual_hours"] == pytest.approx(metrics.BASELINE_HOURS[CHAT])


def test_tool_calls_are_not_counted_twice():
    """Tool calls sit inside the chat turn that invoked them."""
    summary = metrics.effort_summary([_event(CHAT, 6), _event(TOOL, 1)])
    assert summary["runs"] == 1
    assert [row["kind"] for row in summary["rows"]] == [CHAT]


def test_no_events_yields_no_claim():
    summary = metrics.effort_summary([])
    assert summary["rows"] == []
    assert summary["runs"] == 0
    assert summary["hours_saved"] == 0
    assert summary["speedup"] is None


def test_baseline_is_overridable_for_a_client_who_disputes_it(monkeypatch):
    monkeypatch.setenv("SWIFTSAGE_BASELINE_DIFF_HOURS", "4")
    assert metrics.baseline_hours(DIFF) == 4.0
    summary = metrics.effort_summary([_event(DIFF, 2)])
    assert summary["manual_hours"] == pytest.approx(4.0)


@pytest.mark.parametrize("bad", ["", "nonsense", "0", "-3", "inf", "nan", "1e400"])
def test_unusable_override_falls_back_to_the_documented_baseline(monkeypatch, bad):
    """An infinite baseline would otherwise overflow the whole tab."""
    monkeypatch.setenv("SWIFTSAGE_BASELINE_DIFF_HOURS", bad)
    assert metrics.baseline_hours(DIFF) == metrics.BASELINE_HOURS[DIFF]
    assert metrics.effort_summary([_event(DIFF, 2)])["speedup"] > 0


def test_assumptions_are_stated_for_every_baseline():
    lines = metrics.assumptions()
    assert len(lines) == len(metrics.BASELINE_HOURS) + 2
    assert any("signs off" in line for line in lines), "review time caveat"
    assert any("speed-up" in line for line in lines), "ratio caveat"


@pytest.mark.parametrize("seconds,label", [(0.03, "0.03 s"), (12.4, "12.4 s"),
                                           (61, "1.0 min"), (300, "5.0 min")])
def test_durations_read_in_the_unit_that_fits(seconds, label):
    assert metrics.duration_label(seconds) == label


def test_speedup_is_rounded_so_it_reads_as_an_estimate():
    """A sub-second diff against an 8 h baseline is a six-figure ratio."""
    summary = metrics.effort_summary([_event(DIFF, 0.0376)])
    assert summary["speedup_label"] == "780,000×"
    assert metrics.effort_summary([])["speedup_label"] == "—"
