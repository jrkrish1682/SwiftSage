"""Tests for the local run log (src/observability/run_log.py)."""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from src.observability import run_log


@pytest.fixture(autouse=True)
def temp_log(tmp_path, monkeypatch):
    path = tmp_path / "runs.jsonl"
    monkeypatch.setenv("RUN_LOG_PATH", str(path))
    yield path


# ── Writing and reading ────────────────────────────────────────────────────────

def test_record_appends_one_line_per_event(temp_log):
    run_log.record(run_log.DIFF, "a.xml → b.xml", diffs=3)
    run_log.record(run_log.DIFF, "c.xml → d.xml", diffs=0)

    lines = temp_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["detail"]["diffs"] == 3


def test_read_events_returns_newest_first(temp_log):
    run_log.record(run_log.DIFF, "first")
    run_log.record(run_log.DIFF, "second")

    assert [e.name for e in run_log.read_events()] == ["second", "first"]


def test_read_events_filters_by_kind_and_limit():
    run_log.record(run_log.DIFF, "diff-1")
    run_log.record(run_log.TRANSFORM, "pain.001.001.09")
    run_log.record(run_log.TRANSFORM, "pacs.008.001.10")

    events = run_log.read_events(kinds=[run_log.TRANSFORM])
    assert [e.name for e in events] == ["pacs.008.001.10", "pain.001.001.09"]
    assert len(run_log.read_events(limit=1)) == 1


def test_an_empty_kind_filter_shows_nothing_not_everything():
    run_log.record(run_log.DIFF, "diff-1")

    assert run_log.read_events(kinds=[]) == []
    assert len(run_log.read_events(kinds=None)) == 1


def test_read_events_survives_a_corrupt_line(temp_log):
    run_log.record(run_log.DIFF, "good")
    with temp_log.open("a", encoding="utf-8") as fh:
        fh.write("{not json at all\n")
    run_log.record(run_log.DIFF, "also-good")

    assert [e.name for e in run_log.read_events()] == ["also-good", "good"]


def test_read_events_on_missing_file_is_empty(temp_log):
    assert not temp_log.exists()
    assert run_log.read_events() == []


def test_clear_removes_the_log(temp_log):
    run_log.record(run_log.DIFF, "x")
    run_log.clear()
    assert not temp_log.exists()
    assert run_log.read_events() == []


# ── Timing ─────────────────────────────────────────────────────────────────────

def test_track_records_duration_and_detail_set_inside_the_block():
    with run_log.track(run_log.TRANSFORM, "pain.001.001.09") as detail:
        detail["fields_mapped"] = 20

    event = run_log.read_events()[0]
    assert event.status == "ok"
    assert event.detail["fields_mapped"] == 20
    assert event.duration_ms >= 0
    assert event.duration_s == round(event.duration_ms / 1000, 2)


def test_track_honours_a_failure_the_block_reports_without_raising():
    with run_log.track(run_log.DIFF, "a → b") as detail:
        detail["parse_error"] = True
        detail["status"] = "error"

    event = run_log.read_events()[0]
    assert event.status == "error"
    assert event.detail["parse_error"] is True
    assert "status" not in event.detail
    assert run_log.summarise(run_log.read_events())["errors"] == 1


def test_track_records_a_failure_and_reraises():
    with pytest.raises(ValueError):
        with run_log.track(run_log.TRANSFORM, "camt.053.001.10"):
            raise ValueError("schema missing")

    event = run_log.read_events()[0]
    assert event.status == "error"
    assert "schema missing" in event.detail["error"]


# ── Redaction ──────────────────────────────────────────────────────────────────

def test_detail_keys_that_look_like_credentials_are_redacted():
    run_log.record(run_log.CHAT, "claude", api_key="sk-ant-abc123", token="t-1")

    detail = run_log.read_events()[0].detail
    assert detail["api_key"] == "[redacted]"
    assert detail["token"] == "[redacted]"


def test_a_value_that_looks_like_a_key_is_redacted_whatever_the_field_is_called():
    run_log.record(run_log.CHAT, "claude", note="sk-ant-leaked-into-a-note")

    assert run_log.read_events()[0].detail["note"] == "[redacted]"


def test_long_strings_are_truncated_so_message_content_cannot_accumulate():
    run_log.record(run_log.CHAT, "claude", label="x" * 5000)

    assert len(run_log.read_events()[0].detail["label"]) <= 240


def test_non_serialisable_detail_values_do_not_break_recording():
    run_log.record(run_log.CHAT, "claude", schema=object(), paths={"a", "b"})

    detail = run_log.read_events()[0].detail
    assert isinstance(detail["schema"], str)
    assert sorted(detail["paths"]) == ["a", "b"]


def test_record_never_raises_when_the_path_is_unwritable(monkeypatch, tmp_path):
    monkeypatch.setenv("RUN_LOG_PATH", str(tmp_path / "runs.jsonl"))
    blocker = tmp_path / "runs.jsonl"
    blocker.mkdir()  # a directory where the log file should be

    event = run_log.record(run_log.DIFF, "x")
    assert event.name == "x"  # returned to the caller, silently unwritten


# ── Summaries ──────────────────────────────────────────────────────────────────

def test_summarise_counts_runs_errors_and_latency():
    run_log.record(run_log.DIFF, "d1", duration_ms=1000)
    run_log.record(run_log.DIFF, "d2", duration_ms=3000)
    run_log.record(run_log.TRANSFORM, "t1", status="error", duration_ms=500)

    stats = run_log.summarise(run_log.read_events())
    assert stats["events"] == 3
    assert stats["errors"] == 1
    assert stats["by_kind"][run_log.DIFF] == {
        "runs": 2, "median_s": 2.0, "slowest_s": 3.0,
    }


def test_summarise_reports_the_grounded_share_of_chat_turns():
    run_log.record(run_log.CHAT, "claude", grounding_tool_calls=2)
    run_log.record(run_log.CHAT, "claude", grounding_tool_calls=0)
    run_log.record(run_log.TOOL, "lookup_iso20022_element", grounding=True)
    run_log.record(run_log.TOOL, "lookup_iso20022_element", grounding=True)
    run_log.record(run_log.TOOL, "validate_xml", grounding=False)

    stats = run_log.summarise(run_log.read_events())
    assert stats["chat_turns"] == 2
    assert stats["grounded_turns"] == 1
    assert stats["grounded_rate"] == 50
    assert list(stats["tool_counts"]) == ["lookup_iso20022_element", "validate_xml"]
    assert stats["tool_counts"]["lookup_iso20022_element"] == 2


def test_summarise_of_nothing_is_empty_not_an_error():
    stats = run_log.summarise([])
    assert stats["events"] == 0
    assert stats["by_kind"] == {}
    assert stats["grounded_rate"] is None


# ── Agent instrumentation ──────────────────────────────────────────────────────

def test_agent_records_the_shape_of_a_chat_turn_not_its_content():
    from src.agent.swift_agent import SWIFTAgent

    stub = SimpleNamespace(model_name="claude-sonnet-4-6", chat_history=[1, 2, 3, 4])
    SWIFTAgent._record_turn(
        stub,
        "is charge bearer mandatory?",
        "In pain.001.001.09 it is optional...",
        ["lookup_iso20022_element", "validate_xml", "lookup_iso20022_element"],
        time.perf_counter(),
        "ok",
    )

    event = run_log.read_events()[0]
    assert event.kind == run_log.CHAT
    assert event.name == "claude-sonnet-4-6"
    assert event.detail["tool_calls"] == 3
    assert event.detail["grounding_tool_calls"] == 2
    assert event.detail["tools"] == ["lookup_iso20022_element", "validate_xml"]
    assert event.detail["history_turns"] == 2
    # Question and answer are counted, never stored
    assert event.detail["question_chars"] == len("is charge bearer mandatory?")
    assert "charge bearer" not in json.dumps(event.to_dict())


def test_agent_records_each_streamed_tool_call_and_the_turn():
    from langchain_core.messages import AIMessageChunk, ToolMessage

    from src.agent.swift_agent import SWIFTAgent

    stream = [
        (AIMessageChunk(content="Looking it up. "), {"langgraph_node": "agent"}),
        (
            ToolMessage(
                content="ChrgBr — optional in pain.001.001.09",
                name="lookup_iso20022_element",
                tool_call_id="c1",
            ),
            {"langgraph_node": "tools"},
        ),
        (AIMessageChunk(content="It is optional."), {"langgraph_node": "agent"}),
    ]

    agent = object.__new__(SWIFTAgent)
    agent.model_name = "claude-sonnet-4-6"
    agent.chat_history = []
    agent._graph = SimpleNamespace(stream=lambda *a, **k: iter(stream))

    output = "".join(agent.stream("is charge bearer mandatory?"))
    assert "lookup_iso20022_element" in output
    assert "optional in pain.001.001.09" in output

    tool_event, chat_event = (
        run_log.read_events(kinds=[run_log.TOOL])[0],
        run_log.read_events(kinds=[run_log.CHAT])[0],
    )
    assert tool_event.name == "lookup_iso20022_element"
    assert tool_event.detail["grounding"] is True
    assert tool_event.detail["result_chars"] > 0
    assert chat_event.detail["tool_calls"] == 1
    assert chat_event.detail["grounding_tool_calls"] == 1


def test_agent_records_tool_calls_made_by_the_synchronous_path():
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from src.agent.swift_agent import SWIFTAgent

    result = {"messages": [
        HumanMessage(content="is charge bearer mandatory?"),
        ToolMessage(content="...", name="lookup_iso20022_element", tool_call_id="c1"),
        ToolMessage(content="...", name="validate_xml", tool_call_id="c2"),
        AIMessage(content="It is optional."),
    ]}

    agent = object.__new__(SWIFTAgent)
    agent.model_name = "claude-sonnet-4-6"
    agent.chat_history = []
    agent._graph = SimpleNamespace(invoke=lambda *a, **k: result)

    assert agent.run("is charge bearer mandatory?") == "It is optional."

    detail = run_log.read_events(kinds=[run_log.CHAT])[0].detail
    assert detail["tool_calls"] == 2
    assert detail["grounding_tool_calls"] == 1


def test_agent_records_a_failed_turn_with_its_error():
    from src.agent.swift_agent import SWIFTAgent

    stub = SimpleNamespace(model_name="claude-sonnet-4-6", chat_history=[])
    SWIFTAgent._record_turn(
        stub, "q", "", [], time.perf_counter(), "error", error="overloaded_error",
    )

    event = run_log.read_events()[0]
    assert event.status == "error"
    assert event.detail["error"] == "overloaded_error"


# ── Rotation ───────────────────────────────────────────────────────────────────

def test_the_log_rotates_instead_of_growing_without_bound(temp_log, monkeypatch):
    monkeypatch.setattr(run_log, "_MAX_BYTES", 200)
    for i in range(40):
        run_log.record(run_log.DIFF, f"comparison-{i}", note="padding" * 5)

    assert temp_log.with_suffix(".jsonl.1").exists()
    assert temp_log.stat().st_size <= 200 + 1024
