"""
SwiftSage — ISO 20022 Expert Agent for Business Analysts & Product Owners.

Architecture
------------
  LangGraph create_react_agent backed by Claude with a BA/PO-tuned system prompt
  and streaming support for the Streamlit UI.
"""
from __future__ import annotations

import os
from typing import Iterator, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt import create_react_agent

from config.settings import settings
from src.agent.tools import (
    analyze_internal_message,
    batch_compare_xml_folders,
    compare_xml_messages,
    detect_message_type,
    explain_message_flow,
    fetch_iso20022_schemas,
    generate_test_cases,
    generate_transform_requirements,
    identify_gaps,
    list_standards_library,
    map_to_iso20022,
    validate_xml,
)
from src.utils.helpers import get_logger

log = get_logger(__name__)

# ── System prompt ──────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are SwiftSage — an expert ISO 20022 / SWIFT advisor built specifically
for Business Analysts and Product Owners at financial institutions.

YOUR AUDIENCE: Business Analysts and Product Owners — not developers. Always lead with
business meaning and operational impact. Explain in plain English first. Offer technical
XML detail only when the user explicitly asks for it.

YOUR DOMAIN EXPERTISE:
- ISO 20022 message types: pain (Payment Initiation), pacs (Payments Clearing & Settlement),
  camt (Cash Management), acmt (Account Management), auth, reda, and others
- SWIFT MX message structure, XSD schemas, and business rules
- Payment flows: SEPA, SWIFT GPI, CHAPS, BACS, TARGET2, FedNow, CBPR+
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


ALL_TOOLS: list[BaseTool] = [
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
        try:
            messages = self._build_messages(question)
            result = self._graph.invoke({"messages": messages})
            answer = _extract_text(result["messages"][-1].content)
            self._update_history(question, answer)
            return answer
        except Exception as exc:
            log.error("Agent error: %s", exc, exc_info=True)
            return f"Agent encountered an error: {exc}"

    def stream(self, question: str) -> Iterator[str]:
        """
        Stream the agent's response token-by-token.

        Yields text chunks suitable for Streamlit's streaming write pattern.
        Tool calls are surfaced as formatted markdown annotations.
        """
        messages = self._build_messages(question)
        full_answer: list[str] = []

        try:
            # stream_mode="messages" gives (chunk, metadata) pairs at token level
            for chunk, metadata in self._graph.stream(
                {"messages": messages},
                stream_mode="messages",
            ):
                node = metadata.get("langgraph_node", "")

                # ── Tool call announcement ─────────────────────────────
                if node == "tools" and hasattr(chunk, "name") and chunk.name:
                    text = f"\n🔧 **Tool:** `{chunk.name}`\n"
                    yield text

                # ── Tool result ────────────────────────────────────────
                elif node == "tools" and hasattr(chunk, "content") and not hasattr(chunk, "name"):
                    obs = str(chunk.content)
                    if len(obs) > 800:
                        obs = obs[:800] + "\n... [truncated]"
                    text = f"\n📋 **Result:**\n```\n{obs}\n```\n"
                    yield text

                # ── Agent tokens (final answer, streamed) ─────────────
                elif node == "agent" and isinstance(chunk, AIMessageChunk):
                    text = _extract_text(chunk.content)
                    if text:
                        full_answer.append(text)
                        yield text

        except Exception as exc:
            log.error("Stream error: %s", exc, exc_info=True)
            yield f"\n❌ Error: {exc}"
        finally:
            if full_answer:
                self._update_history(question, "".join(full_answer))

    def clear_history(self) -> None:
        """Reset conversation memory."""
        self.chat_history = []

    def tool_names(self) -> list[str]:
        return [t.name for t in self.tools]

    # ── Private helpers ────────────────────────────────────────────────────

    def _build_messages(self, question: str) -> list:
        """Prepend SystemMessage + chat history + new human turn.

        Injecting the system prompt here (rather than via create_react_agent's
        constructor kwargs) is compatible with every LangGraph version.
        """
        return (
            [SystemMessage(content=SYSTEM_PROMPT)]
            + self.chat_history
            + [HumanMessage(content=question)]
        )

    def _update_history(self, question: str, answer: str) -> None:
        self.chat_history.append(HumanMessage(content=question))
        self.chat_history.append(AIMessage(content=answer))
        # Keep last 20 turns to avoid context overflow
        if len(self.chat_history) > 40:
            self.chat_history = self.chat_history[-40:]
