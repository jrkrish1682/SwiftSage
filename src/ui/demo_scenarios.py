"""
Curated demo scenarios — one click each, phrased as the business question.

A SwiftSage demo previously depended on the presenter remembering which sample
pairs with which target and schema, and clicking through three tabs while
talking. Each scenario here carries the business question it answers, the
presets that configure the relevant tab, and the numbers to expect, so the
operator narrates instead of navigating.

Scenarios that only need the vendored XSDs (`needs_key = False`) run offline
with no Anthropic key; the mapping and chat scenarios need a key because they
call Claude.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Repo root — scenario asset paths are relative to it so they resolve wherever
# Streamlit is launched from.
ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class DiffPair:
    """An XML comparison a scenario can run without any credentials."""

    baseline: str
    revised: str
    schema: str
    schema_label: str

    def paths(self) -> tuple[Path, Path, Path]:
        return ROOT / self.baseline, ROOT / self.revised, ROOT / self.schema


@dataclass(frozen=True)
class Scenario:
    """One rehearsed demo beat."""

    id: str
    title: str
    question: str
    tab: str
    needs_key: bool
    talking_points: tuple[str, ...]
    watch_for: tuple[str, ...]
    presets: dict[str, str] = field(default_factory=dict)
    diff: Optional[DiffPair] = None
    chat_prompt: str = ""
    source_asset: str = ""

    def assets(self) -> list[Path]:
        """Files the scenario needs on disk."""
        paths: list[Path] = []
        if self.diff is not None:
            paths.extend(self.diff.paths())
        if self.source_asset:
            paths.append(ROOT / self.source_asset)
        return paths


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        id="payment_upgrade",
        title="1 · Our counterparty is upgrading pain.001 — what breaks?",
        question=(
            "A correspondent moves from pain.001.001.09 to pain.001.001.12. "
            "Which of our payments start failing, and what has to change before "
            "the cutover?"
        ),
        tab="🔍 XML Diff",
        needs_key=False,
        talking_points=(
            "Today a BA exports both schemas, diffs them in a spreadsheet and "
            "books time with an ISO 20022 specialist to interpret the result.",
            "SwiftSage compares the two messages semantically, resolves each "
            "change back to its real element name, and grades it against the "
            "target XSD — a field that became mandatory grades BREAKING, an "
            "added optional field does not.",
            "The 0-100 score is explainable: open 'How the score was "
            "calculated' and every rule that contributed is listed.",
        ),
        watch_for=(
            "Version upgrade is detected, so the namespace change is reported "
            "once rather than on every element.",
            "A breaking-change score with the per-severity calculation behind it.",
            "A business-readable impact assessment downloads as Word or Markdown "
            "— the deliverable that used to take a day to write.",
        ),
        presets={
            "src_a": "Payment sample (pain.001.001.09)",
            "src_b": "Payment sample (upgrade to pain.001.001.12)",
            "diff_schema_choice": "pain.001.001.12 (pain)",
        },
        diff=DiffPair(
            baseline="data/samples/pain001_v1.xml",
            revised="data/samples/pain001_v12_upgrade.xml",
            schema="data/standards/pain/pain.001.001.12.xsd",
            schema_label="pain.001.001.12 (pain)",
        ),
    ),
    Scenario(
        id="trade_amendment",
        title="2 · A guarantee was amended — is the change material?",
        question=(
            "Operations amended an outbound tsrv.001 undertaking. Does the "
            "amendment change our exposure or the applicant's obligations, or "
            "is it administrative?"
        ),
        tab="🔍 XML Diff",
        needs_key=False,
        talking_points=(
            "Same engine, different domain — trade finance rather than "
            "payments, which is the breadth question every bank asks after the "
            "payments demo.",
            "tsrv.001.001.01 is the MX equivalent of MT 760, so this is the "
            "message a trade migration programme has to reason about.",
            "Undertaking amount, expiry and governing rules grade BREAKING; "
            "message identifiers and timestamps are benign by configuration.",
        ),
        watch_for=(
            "A high score driven by amount and expiry changes, not by volume "
            "of diffs.",
            "Trade vocabulary in the explanations — the classifier is not "
            "payments-only.",
        ),
        presets={
            "src_a": "Trade sample (tsrv.001.001.01 guarantee)",
            "src_b": "Trade sample (amended guarantee)",
            "diff_schema_choice": "tsrv.001.001.01 (tsrv)",
        },
        diff=DiffPair(
            baseline="data/samples/trade/tsrv001_guarantee_v1.xml",
            revised="data/samples/trade/tsrv001_guarantee_v2.xml",
            schema="data/standards/tsrv/tsrv.001.001.01.xsd",
            schema_label="tsrv.001.001.01 (tsrv)",
        ),
    ),
    Scenario(
        id="payment_mapping",
        title="3 · Turn our internal payment format into build-ready requirements",
        question=(
            "We send payments in a proprietary XML. What are the transformation "
            "requirements to emit pain.001.001.09, and what must the business "
            "decide before development starts?"
        ),
        tab="🔄 Transform Advisor",
        needs_key=True,
        talking_points=(
            "This is the weeks-to-minutes claim: the same output a BA and an "
            "SME produce over a sprint of workshops.",
            "Every proposed ISO path is checked against the vendored XSD — an "
            "unverifiable path is downgraded, never presented as HIGH "
            "confidence.",
            "Mandatory target fields with no source become BLOCKING gaps with a "
            "recommended resolution: the agenda for the next business workshop.",
            "A run maps at most 20 source fields to stay inside a token budget; "
            "the deferred ones are listed in the UI and recorded as an "
            "assumption in the document, never silently dropped.",
        ),
        watch_for=(
            "DIRECT / DERIVED / SPLIT / UNMAPPED classification per field.",
            "The gap register, and the schema-check cards above the table.",
            "The Word document's traceability IDs (TR-nn, GAP-nn, AS-nn, OQ-nn) "
            "and its provenance record — model, input hash, schema, timestamp.",
        ),
        presets={
            "sample_choice": (
                "pain.001 — Meridian Bank payment initiation (XML, 46 fields)"
            ),
            "target_msg_type": "pain.001.001.09",
        },
        source_asset="data/samples/internal/sample_bank_payment.xml",
    ),
    Scenario(
        id="grounded_answer",
        title="4 · Answer a field question without booking an SME",
        question=(
            "Is the charge bearer mandatory in pain.001.001.09, and what do the "
            "codes mean for our customers?"
        ),
        tab="💬 Chat",
        needs_key=True,
        talking_points=(
            "The question a BA would otherwise queue behind a specialist's "
            "calendar for two days.",
            "The answer is grounded: the agent must call the lookup tools "
            "before making a field-level claim, and cites the message version "
            "and the schema file it read.",
            "Business meaning comes from a curated glossary, structure from the "
            "XSD — an element with no glossary entry is rendered as structure "
            "only, so the agent never presents an invented definition as "
            "sourced.",
        ),
        watch_for=(
            "The tool call appearing inline before the answer.",
            "A citation naming the message version and schema file.",
            "The Observability tab counting the turn as grounded.",
        ),
        presets={"chat_prompt_pack": "Payments"},
        chat_prompt=(
            "Is the charge bearer mandatory in pain.001.001.09, and what do the "
            "codes mean for our customers?"
        ),
    ),
)


def by_id(scenario_id: str) -> Optional[Scenario]:
    for scenario in SCENARIOS:
        if scenario.id == scenario_id:
            return scenario
    return None


def missing_assets(scenario: Scenario) -> list[Path]:
    """Assets the scenario references that are not on disk."""
    return [path for path in scenario.assets() if not path.exists()]
