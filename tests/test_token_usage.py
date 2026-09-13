"""Tests for model token accounting and prompt caching."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.observability import run_log
from src.observability.token_usage import TokenUsage, approx_tokens, from_detail


@pytest.fixture(autouse=True)
def temp_log(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_LOG_PATH", str(tmp_path / "runs.jsonl"))
    yield


# ── Normalising what the SDKs report ──────────────────────────────────────────

def test_anthropic_usage_folds_cached_tokens_into_the_input_total():
    """The SDK excludes cached tokens from input_tokens; the full prompt is both."""
    usage = TokenUsage.from_anthropic(SimpleNamespace(
        input_tokens=300,
        output_tokens=900,
        cache_read_input_tokens=1800,
        cache_creation_input_tokens=0,
    ))

    assert usage.input_tokens == 2100
    assert usage.output_tokens == 900
    assert usage.cache_read_tokens == 1800
    assert usage.uncached_input_tokens == 300
    assert usage.cached_prefix_tokens == 1800
    assert usage.total_tokens == 3000
    assert usage.calls == 1


def test_langchain_usage_is_taken_as_the_total_and_not_double_counted():
    usage = TokenUsage.from_langchain({
        "input_tokens": 2100,
        "output_tokens": 400,
        "input_token_details": {"cache_read": 1800, "cache_creation": 0},
    })

    assert usage.input_tokens == 2100
    assert usage.cache_read_tokens == 1800
    assert usage.uncached_input_tokens == 300


def test_langchain_per_ttl_cache_creation_keys_are_summed():
    usage = TokenUsage.from_langchain({
        "input_tokens": 2000,
        "output_tokens": 10,
        "input_token_details": {
            "cache_read": 0,
            "cache_creation": 0,
            "ephemeral_5m_input_tokens": 1700,
        },
    })

    assert usage.cache_write_tokens == 1700
    assert usage.cached_prefix_tokens == 1700


def test_missing_or_malformed_usage_reports_no_calls():
    assert TokenUsage.from_anthropic(None).calls == 0
    assert TokenUsage.from_langchain(None).calls == 0
    assert TokenUsage.from_langchain({}).calls == 0
    assert TokenUsage.from_langchain(
        {"input_tokens": None, "output_tokens": None}
    ).calls == 0


def test_usage_adds_up_and_keeps_the_largest_cached_prefix():
    first = TokenUsage(
        input_tokens=2000, output_tokens=100,
        cache_write_tokens=1800, cached_prefix_tokens=1800, calls=1,
    )
    second = TokenUsage(
        input_tokens=2200, output_tokens=300,
        cache_read_tokens=1800, cached_prefix_tokens=1800, calls=1,
    )
    total = first + second

    assert (total.calls, total.input_tokens, total.output_tokens) == (2, 4200, 400)
    assert total.cached_prefix_tokens == 1800  # the block, not the sum of its uses
    assert total.cache_hit_rate == round(100 * 1800 / 4200)


def test_cache_saving_is_negative_while_the_cache_is_only_being_written():
    written_only = TokenUsage(
        input_tokens=2000, cache_write_tokens=1800,
        cached_prefix_tokens=1800, calls=1,
    )
    assert written_only.tokens_saved_by_cache < 0

    after_reads = written_only + TokenUsage(
        input_tokens=2000, cache_read_tokens=1800,
        cached_prefix_tokens=1800, calls=1,
    ) + TokenUsage(
        input_tokens=2000, cache_read_tokens=1800,
        cached_prefix_tokens=1800, calls=1,
    )
    assert after_reads.tokens_saved_by_cache > 0


def test_no_prompt_means_no_hit_rate_rather_than_a_division_error():
    assert TokenUsage().cache_hit_rate is None


# ── Run-log detail ────────────────────────────────────────────────────────────

def test_detail_is_empty_when_no_model_was_called():
    assert TokenUsage().as_detail("system prompt") == {}


def test_detail_reports_the_cached_prefix_as_the_system_prompt_size():
    detail = TokenUsage(
        input_tokens=2100, output_tokens=400, cache_read_tokens=1800,
        cached_prefix_tokens=1800, calls=1,
    ).as_detail("x" * 8000)

    assert detail["system_prompt_tokens"] == 1800
    assert detail["system_prompt_measured"] is True
    assert detail["total_tokens"] == 2500


def test_detail_estimates_the_system_prompt_when_nothing_was_cached():
    detail = TokenUsage(input_tokens=300, output_tokens=50, calls=1).as_detail("x" * 400)

    assert detail["system_prompt_tokens"] == approx_tokens("x" * 400) == 100
    assert detail["system_prompt_measured"] is False


def test_token_counts_are_recorded_not_redacted_as_secrets():
    """The keys contain "token", which the secret filter would otherwise catch."""
    usage = TokenUsage(
        input_tokens=2100, output_tokens=400, cache_read_tokens=1800,
        cached_prefix_tokens=1800, calls=1,
    )
    run_log.record(run_log.CHAT, "claude-sonnet-4-6", **usage.as_detail())

    detail = run_log.read_events()[0].detail
    assert detail["input_tokens"] == 2100
    assert detail["output_tokens"] == 400
    assert detail["cache_read_tokens"] == 1800


def test_a_secret_string_under_a_token_key_is_still_redacted():
    run_log.record(run_log.CHAT, "model", api_token="sk-ant-abc123")

    assert run_log.read_events()[0].detail["api_token"] == "[redacted]"


def test_from_detail_round_trips_a_recorded_event():
    usage = TokenUsage(
        input_tokens=2100, output_tokens=400, cache_read_tokens=1800,
        cached_prefix_tokens=1800, calls=2,
    )
    assert from_detail(usage.as_detail()) == usage


def test_from_detail_ignores_an_event_that_never_called_a_model():
    assert from_detail({"diffs": 3}).calls == 0


# ── Aggregation for the Observability tab ─────────────────────────────────────

def test_summarise_totals_tokens_per_activity():
    run_log.record(
        run_log.CHAT, "claude-sonnet-4-6",
        **TokenUsage(
            input_tokens=2100, output_tokens=400, cache_read_tokens=1800,
            cached_prefix_tokens=1800, calls=1,
        ).as_detail(),
    )
    run_log.record(
        run_log.TRANSFORM, "pain.001.001.09",
        **TokenUsage(
            input_tokens=9000, output_tokens=6000, cache_write_tokens=7000,
            cached_prefix_tokens=7000, calls=1,
        ).as_detail(),
    )
    run_log.record(run_log.DIFF, "a.xml → b.xml", diffs=4)

    stats = run_log.summarise(run_log.read_events())

    assert stats["tokens"].calls == 2
    assert stats["tokens"].input_tokens == 11100
    assert stats["tokens"].output_tokens == 6400
    assert set(stats["tokens_by_kind"]) == {run_log.CHAT, run_log.TRANSFORM}
    assert stats["tokens_by_kind"][run_log.CHAT].cache_read_tokens == 1800


def test_summarise_reports_no_tokens_for_a_log_written_before_this_feature():
    run_log.record(run_log.DIFF, "a.xml → b.xml", diffs=4)
    run_log.record(run_log.CHAT, "model", tool_calls=2, grounding_tool_calls=1)

    stats = run_log.summarise(run_log.read_events())

    assert stats["tokens"].calls == 0
    assert stats["tokens_by_kind"] == {}
    assert stats["chat_turns"] == 1  # legacy metrics unaffected


# ── Prompt caching is actually requested ──────────────────────────────────────

def test_agent_sends_the_system_prompt_as_a_cacheable_block():
    from src.agent import swift_agent

    block = swift_agent._system_block()

    assert len(block) == 1
    assert block[0]["cache_control"] == {"type": "ephemeral"}
    assert block[0]["text"] == swift_agent.SYSTEM_PROMPT


def test_field_mapper_system_prompt_holds_the_stable_context_only(monkeypatch):
    from src.transformer import field_mapper
    from src.transformer.message_parser import InternalField

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    captured: dict = {}

    class _Messages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(text="[]")],
                stop_reason="end_turn",
                usage=SimpleNamespace(
                    input_tokens=120,
                    output_tokens=30,
                    cache_read_input_tokens=0,
                    cache_creation_input_tokens=2400,
                ),
            )

    monkeypatch.setattr(
        field_mapper.anthropic, "Anthropic",
        lambda api_key: SimpleNamespace(messages=_Messages()),
    )

    mapper = field_mapper.FieldMapper()
    mapper.map(
        [InternalField(
            name="SortCode", xpath="/Pmt/SortCode", value="20-00-00", parent="Pmt",
        )],
        "pain.001.001.09",
    )

    system = captured["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    # The reference and rules are cached; the field list must stay out of them.
    assert "pain.001.001.09" in system[0]["text"]
    assert "SortCode" not in system[0]["text"]
    assert "SortCode" in captured["messages"][0]["content"]

    assert mapper.last_usage.cache_write_tokens == 2400
    assert mapper.last_usage.input_tokens == 2520
    assert mapper.last_usage.as_detail()["system_prompt_tokens"] == 2400


def test_field_mapper_system_prompt_is_identical_across_runs_for_a_target():
    """A prefix that varies per run would never be served from cache."""
    from src.transformer.field_mapper import system_prompt

    assert system_prompt("pain.001.001.09") == system_prompt("pain.001.001.09")
    assert system_prompt("pain.001.001.09") != system_prompt("camt.053.001.10")
