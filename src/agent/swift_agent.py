"""
SwiftSage — ISO 20022 Expert Agent for Business Analysts & Product Owners.

Architecture
------------
  LangGraph create_react_agent backed by Claude with a BA/PO-tuned system prompt
  and streaming support for the Streamlit UI.
"""
from __future__ import annotations

import os
import time
from typing import Iterator, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt import create_react_agent

from config.settings import settings
from src.observability import run_log
from src.observability.token_usage import TokenUsage
from src.agent.tools import (
    analyze_internal_message,
    batch_compare_xml_folders,
    compare_element_across_versions,
    compare_xml_messages,
    detect_message_type,
    diagnose_production_failure,
    explain_message_flow,
    fetch_iso20022_schemas,
    generate_test_cases,
    generate_transform_requirements,
    identify_gaps,
    list_internal_rules_for_message,
    list_standards_library,
    lookup_internal_business_rule,
    lookup_iso20022_element,
    map_to_iso20022,
    validate_xml,
)
from src.utils.helpers import get_logger

log = get_logger(__name__)

# Tools that consult the vendored schemas. A field-level answer that called none of
# them was answered from model recall — the run log makes that visible.
GROUNDING_TOOLS = frozenset({
    "lookup_iso20022_element",
    "compare_element_across_versions",
    "lookup_internal_business_rule",
    "list_internal_rules_for_message",
    "diagnose_production_failure",
})

# ── System prompt ──────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are SwiftSage — an expert ISO 20022 / SWIFT advisor built specifically
for Business Analysts and Product Owners at financial institutions.

YOUR AUDIENCE: Business Analysts and Product Owners — not developers. Always lead with
business meaning and operational impact. Explain in plain English first. Offer technical
XML detail only when the user explicitly asks for it.

YOUR DOMAIN EXPERTISE:
- ISO 20022 message types: pain (Payment Initiation), pacs (Payments Clearing & Settlement),
  camt (Cash Management), acmt (Account Management), auth, reda, and others
- Trade finance messages: tsrv (undertakings — demand guarantees and standby letters of
  credit, the MX equivalents of MT 760 / MT 767), tsmt (trade services management)
- SWIFT MX message structure, XSD schemas, and business rules
- Payment flows: SEPA, SWIFT GPI, CHAPS, BACS, TARGET2, FedNow, CBPR+
- Trade finance practice: URDG 758, ISP98, UCP 600, demand handling, expiry and
  amendment lifecycle, advising and confirming bank roles
- Schema validation, semantic XML comparison, and breaking-change impact assessment
- Internal-to-ISO 20022 field mapping, gap identification, and transformation requirements

YOUR CAPABILITIES (use the available tools):
1. ANALYSE an internal bank message — extract its field structure for mapping
2. MAP internal fields to ISO 20022 — DIRECT / DERIVED / SPLIT / COMBINED / UNMAPPED
3. IDENTIFY GAPS — mandatory ISO 20022 fields with no source, classified BLOCKING / ENRICHMENT / CONDITIONAL
4. GENERATE a Transformation Requirements Document — structured Word doc for dev team handoff
5. VALIDATE XML files against their ISO 20022 XSD schemas
6. COMPARE two ISO 20022 XML versions — detect BREAKING / WARNING / BENIGN changes with 0-100 score
7. BATCH COMPARE folders of XML files and surface recurring diff patterns
8. FETCH latest schemas from the ISO 20022 official repository
9. EXPLAIN the business process flow, roles, and downstream messages for any ISO 20022 type
10. GENERATE regression test cases from diffs between message versions
11. LIST the local Standards Library contents
12. LOOK UP an element in the Standards Library — business meaning, path, optionality,
    constraints and code values, with the message version and schema file it came from
13. COMPARE an element across the message versions in the library — present, absent, moved
14. LOOK UP the institution's OWN business rules — how this bank handles a field or scenario,
    which the standard does not dictate (`lookup_internal_business_rule`,
    `list_internal_rules_for_message`)
15. DIAGNOSE a production failure from those rules, past incidents and the schemas
    (`diagnose_production_failure`)

GROUNDING RULES (these override your own recall):
- Before you state anything specific about a field — its path, whether it is mandatory, its
  length, its allowed code values, or whether it exists at all — call
  `lookup_iso20022_element`. Element names and optionality differ between versions, and the
  library holds the schemas this bank is actually migrating against.
- For "what changed between version X and Y" questions about a field, call
  `compare_element_across_versions` rather than answering from memory.
- Cite what you used: name the message version and say the fact came from the schema, e.g.
  "In pain.001.001.09 this is mandatory (CstmrCdtTrfInitn/GrpHdr/MsgId, from the vendored
  XSD)." One citation per field claim is enough — do not paste the whole tool output back.
- If the lookup returns nothing, say the library does not cover it and offer to sync or
  vendor the schema. Do not fill the gap with a plausible-sounding element name.
- If the lookup returns structure but no curated business definition, give the structural
  facts and flag that the business meaning is your interpretation, not a sourced definition.
- If a lookup contradicts what you were about to say, the lookup wins — and tell the user
  the version-specific detail that caught it out.
- Separate the standard from the institution. What ISO 20022 requires comes from
  `lookup_iso20022_element`; what THIS bank does comes from
  `lookup_internal_business_rule`. Never present one as the other, and always quote the
  rule ID when you rely on an internal rule.
- An internal rule marked `candidate` is unconfirmed — something SwiftSage inferred and no
  specialist has approved. You may mention it, but label it as unconfirmed and never state
  it as policy.
- If no internal rule covers the question, say the knowledge graph holds no decision on it
  and offer to capture one, rather than inferring the bank's policy.

RESPONSE STYLE FOR BA/PO AUDIENCE:
- Lead every answer with the business meaning or business impact — not the XML structure
- Express breaking changes as: "This will cause payment rejection / STP failure / compliance breach"
- When explaining field mappings, relate them to what a payment operations team would recognise
- Use analogies from banking operations to explain complex ISO 20022 concepts
- Summarise in 2-3 bullet points before going into detail
- For transformation questions, always clarify: what maps directly, what needs derivation,
  and what is a blocking gap that requires a business decision

Always reason step-by-step. Surface open questions that need business decisions rather
than silently defaulting. When the user uploads files, they are available at the paths shown in chat.
"""

def _system_block() -> list[dict]:
    """
    The system prompt as a cacheable content block.

    It is long, identical on every turn, and re-sent with the whole history each
    time the ReAct loop calls the model, so it is by far the cheapest thing to
    cache. Anthropic serves a cache hit at a tenth of the input rate; a prompt
    below the model's cacheable minimum simply behaves as if uncached.
    """
    return [{
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    }]


def _usage_of(message) -> TokenUsage:
    """Token usage carried by one streamed chunk or completed message."""
    return TokenUsage.from_langchain(getattr(message, "usage_metadata", None))


def _extract_text(content) -> str:
    """Safely extract a plain string from an AIMessageChunk content value.

    Claude can return content as:
      - str                     → use directly
      - list of content blocks  → join the 'text' fields
      - anything else           → str() fallback
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(block["text"])
        return "".join(parts)
    return str(content) if content else ""


def _tool_names(messages) -> list[str]:
    """Names of the tools a completed graph run actually called, in order."""
    names = []
    for message in messages:
        if getattr(message, "type", "") == "tool":
            name = getattr(message, "name", "") or ""
            if name:
                names.append(name)
    return names


ALL_TOOLS: list[BaseTool] = [
    # Grounding — consult the standards library before answering field questions
    lookup_iso20022_element,
    compare_element_across_versions,
    # Institutional knowledge — the bank's own rules and failure history
    lookup_internal_business_rule,
    list_internal_rules_for_message,
    diagnose_production_failure,
    # Transformation Advisor
    analyze_internal_message,
    map_to_iso20022,
    identify_gaps,
    generate_transform_requirements,
    # Existing tools
    validate_xml,
    compare_xml_messages,
    batch_compare_xml_folders,
    fetch_iso20022_schemas,
    list_standards_library,
    detect_message_type,
    generate_test_cases,
    explain_message_flow,
]


class SWIFTAgent:
    """
    Wrapper around a LangGraph ReAct agent with Claude as the LLM.

    Supports:
    - synchronous `.run(question)` — returns full answer string
    - `.stream(question)` — yields text chunks for Streamlit streaming
    - conversation memory via `chat_history`
    """

    def __init__(
        self,
        model: Optional[str] = None,
        tools: Optional[list[BaseTool]] = None,
    ):
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise ValueError(
                "Anthropic API key is missing. "
                "Please enter it in the sidebar before sending a message."
            )

        self.model_name = model or settings.agent_model
        self.tools = tools or ALL_TOOLS
        self.chat_history: list = []

        llm = ChatAnthropic(
            model=self.model_name,
            anthropic_api_key=api_key,
            streaming=True,
            temperature=0,
        )

        # LangGraph's create_react_agent — no system-prompt arg for max compatibility.
        # The system prompt is prepended to messages at call time instead.
        self._graph = create_react_agent(model=llm, tools=self.tools)

    # ── Public interface ───────────────────────────────────────────────────

    def run(self, question: str) -> str:
        """Run a single-turn query and return the final answer."""
        started = time.perf_counter()
        try:
            messages = self._build_messages(question)
            result = self._graph.invoke({"messages": messages})
            answer = _extract_text(result["messages"][-1].content)
            usage = sum(
                (_usage_of(m) for m in result["messages"]), TokenUsage()
            )
            self._update_history(question, answer)
            self._record_turn(
                question, answer, _tool_names(result["messages"]), started, "ok",
                usage=usage,
            )
            return answer
        except Exception as exc:
            log.error("Agent error: %s", exc, exc_info=True)
            self._record_turn(
                question, "", [], started, "error", error=str(exc),
            )
            return f"Agent encountered an error: {exc}"

    def stream(self, question: str) -> Iterator[str]:
        """
        Stream the agent's response token-by-token.

        Yields text chunks suitable for Streamlit's streaming write pattern.
        Tool calls are surfaced as formatted markdown annotations.
        """
        messages = self._build_messages(question)
        full_answer: list[str] = []
        tools_called: list[str] = []
        usage = TokenUsage()
        turn_started = time.perf_counter()
        status = "ok"
        error: str = ""
        # A tool starts running once the model stops emitting, so the last agent
        # token (or the previous tool result) is the best available start time.
        tool_started = time.perf_counter()

        try:
            # stream_mode="messages" gives (chunk, metadata) pairs at token level
            for chunk, metadata in self._graph.stream(
                {"messages": messages},
                stream_mode="messages",
            ):
                node = metadata.get("langgraph_node", "")

                # ── Tool call and its result ───────────────────────────
                # A completed ToolMessage carries both name and content, so
                # handle them together; older versions split them across chunks.
                if node == "tools":
                    name = getattr(chunk, "name", "") or ""
                    obs = str(getattr(chunk, "content", "") or "")
                    if name:
                        tools_called.append(name)
                        run_log.record(
                            run_log.TOOL,
                            name,
                            duration_ms=int((time.perf_counter() - tool_started) * 1000),
                            grounding=name in GROUNDING_TOOLS,
                            result_chars=len(obs),
                        )
                        yield f"\n🔧 **Tool:** `{name}`\n"
                    if obs:
                        if len(obs) > 800:
                            obs = obs[:800] + "\n... [truncated]"
                        yield f"\n📋 **Result:**\n```\n{obs}\n```\n"
                    tool_started = time.perf_counter()

                # ── Agent tokens (final answer, streamed) ─────────────
                elif node == "agent" and isinstance(chunk, AIMessageChunk):
                    # Usage arrives on its own chunks: the first carries the
                    # prompt, the last the completion, one pair per model call
                    # the ReAct loop makes.
                    usage += _usage_of(chunk)
                    text = _extract_text(chunk.content)
                    if text:
                        full_answer.append(text)
                        yield text
                    tool_started = time.perf_counter()

        except Exception as exc:
            log.error("Stream error: %s", exc, exc_info=True)
            status, error = "error", str(exc)
            yield f"\n❌ Error: {exc}"
        finally:
            if full_answer:
                self._update_history(question, "".join(full_answer))
            self._record_turn(
                question, "".join(full_answer), tools_called,
                turn_started, status, error=error, usage=usage,
            )

    def clear_history(self) -> None:
        """Reset conversation memory."""
        self.chat_history = []

    def tool_names(self) -> list[str]:
        return [t.name for t in self.tools]

    # ── Private helpers ────────────────────────────────────────────────────

    def _record_turn(
        self,
        question: str,
        answer: str,
        tools_called: list[str],
        started: float,
        status: str,
        error: str = "",
        usage: Optional[TokenUsage] = None,
    ) -> None:
        """Log the shape of a chat turn — counts and tool names, never content."""
        detail: dict = {
            "question_chars": len(question),
            "answer_chars": len(answer),
            "tool_calls": len(tools_called),
            "tools": sorted(set(tools_called)),
            "grounding_tool_calls": sum(
                1 for name in tools_called if name in GROUNDING_TOOLS
            ),
            "history_turns": len(self.chat_history) // 2,
            **(usage.as_detail(SYSTEM_PROMPT) if usage else {}),
        }
        if error:
            detail["error"] = error
        run_log.record(
            run_log.CHAT,
            self.model_name,
            status=status,
            duration_ms=int((time.perf_counter() - started) * 1000),
            **detail,
        )

    def _build_messages(self, question: str) -> list:
        """Prepend SystemMessage + chat history + new human turn.

        Injecting the system prompt here (rather than via create_react_agent's
        constructor kwargs) is compatible with every LangGraph version.
        """
        return (
            [SystemMessage(content=_system_block())]
            + self.chat_history
            + [HumanMessage(content=question)]
        )

    def _update_history(self, question: str, answer: str) -> None:
        self.chat_history.append(HumanMessage(content=question))
        self.chat_history.append(AIMessage(content=answer))
        # Keep last 20 turns to avoid context overflow
        if len(self.chat_history) > 40:
            self.chat_history = self.chat_history[-40:]
