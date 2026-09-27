# SwiftSage — Project details

## What this project is

SwiftSage is an AI-powered ISO 20022 / SWIFT expert agent built for Business Analysts and
Product Owners at financial institutions. It runs as a Streamlit web app backed by a
LangGraph ReAct agent using Claude (claude-sonnet-4-6).

Primary demo target: mapping a UK bank's internal payment XML → **pain.001.001.09**.
Trade demo target: mapping an internal guarantee application → **tsrv.001.001.01**
(Undertaking Issuance — the MX equivalent of MT 760), plus a guarantee amendment and a
`tsmt.011.001.03 → .04` upgrade in the XML Diff tab.

Beyond the migration project, the product goal is to accumulate the **institution's own**
business logic and tribal SME knowledge — rules, mappings, systems, incidents — as a
local, cited, human-confirmed graph, and to read it five ways: as an in-house SME, for
BA/PO requirements and stories, as a UAT/regression test generator, as a reviewer of
transformation and mapping logic, and for RCA of production defects. Knowledge and RCA
are built; Stories, Tests and Review are pending modes of the same tab. Intent and
guarantees: [`docs/VISION.md`](docs/VISION.md).

Architecture, data flows and the reasoning behind each design decision:
[`docs/DESIGN.md`](docs/DESIGN.md). User-facing usage: [`README.md`](README.md). Demo
walkthrough: [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md).

---

## How to run the app

```powershell
.venv\Scripts\streamlit.exe run app.py
```

(macOS/Linux: `.venv/bin/streamlit run app.py`)

App opens at http://localhost:8501. Enter the Anthropic API key in the sidebar and press
**Apply key** — it is **never written to disk**, held in session memory only. Only Chat and
the Transform Advisor need it; XML Diff, Library, Observability and the two offline demo
scenarios work without one.

Use the `/run` skill to start the app from Claude Code.

---

## Project structure

```
app.py                          # Streamlit UI — 8 tabs (Demo, Chat, Transform Advisor,
                                #   XML Diff, SME Knowledge, Library,
                                #   Observability, Help)
config/settings.py              # Pydantic-settings config (no secrets)
src/
  agent/
    swift_agent.py              # LangGraph ReAct agent + streaming
    tools.py                    # 17 @tool functions
  transformer/
    message_parser.py           # Internal XML / JSON / CSV / XLSX → List[InternalField]
    target_schema.py            # Flattens a vendored XSD → prompt context + path lookup
    field_mapper.py             # Calls Claude API → List[MappedField]
    mapping_validator.py        # Checks proposed ISO paths against the target XSD
    source_classifier.py        # Profiles the source family; warns on target mismatch
    gap_analyzer.py             # Mandatory target fields → List[GapEntry]
    requirements_generator.py   # python-docx Word doc generator
  comparator/
    xml_comparator.py           # Semantic XML diff engine
    diff_classifier.py          # BREAKING/WARNING/BENIGN/INFO rules
    schema_cardinality.py       # Mandatory/optional lookup from the XSD
    impact_report.py            # Business-readable impact assessment (Word + Markdown)
  connectors/
    iso20022_connector.py       # Downloads XSDs from ISO 20022 GitHub
    schema_bundle.py            # Vendored XSD bundle — the offline source of truth
  storage/
    standards_library.py        # Local artefact catalogue
    schema_index.py             # Searchable index over the vendored XSDs (chat grounding)
    iso_glossary.py             # Curated business definitions for ISO element names
  knowledge/
    store.py                    # SQLite knowledge graph — typed nodes, edges, evidence
    seeds.py                    # 12 mocked business rules + 3 historical incidents
    rca.py                      # Deterministic root-cause ranking over rules/schema/defects
    graph.py                    # Neighbourhood → Graphviz DOT
  observability/
    run_log.py                  # Local JSONL run log — durations, counts, outcomes
    token_usage.py              # Normalises Anthropic/LangChain token usage; cache maths
    metrics.py                  # Measured run time vs stated manual baselines
  ui/
    theme.py                    # CSS, hero and section helpers
    demo_scenarios.py           # Rehearsed demo scenarios — assets, presets, talking points
    knowledge_tab.py            # SME Knowledge tab — Knowledge and RCA modes
    prompt_packs.py             # Chat starter questions per business domain
  utils/helpers.py              # get_logger(), XML helpers
data/
  knowledge/knowledge.db        # Knowledge graph — created on first run (git-ignored)
  samples/internal/
    sample_bank_payment.xml     # Meridian Bank demo XML (46 fields)
    sample_bank_fi_transfer.xml # FI credit transfer → pacs.008
    sample_bank_statement.json  # Internal statement feed (JSON) → camt.053
    sample_bank_fi_transfer_spec.csv  # Field specification (CSV) → pacs.008
    sample_bank_guarantee.xml   # Guarantee application → tsrv.001
  samples/                      # XML Diff scenarios
    pain001_v1.xml / _v2.xml    # Baseline + breaking-change pair
    pain001_v12_upgrade.xml     # pain.001.001.09 → .12 version upgrade
    trade/tsrv001_guarantee_v1.xml / _v2.xml  # Guarantee amendment pair
    trade/tsmt011_baseline_v3.xml / _v4.xml   # tsmt.011 .03 → .04 upgrade
  standards/                    # Vendored XSDs — pain, pacs, camt, tsrv, tsmt (9 versions)
docs/
  VISION.md                     # The AI-SME vision, the five uses, knowledge lifecycle
  DESIGN.md                     # Architecture, data flows, design decisions, non-goals
  DEMO_SCRIPT.md                # Guided walkthrough, common questions, troubleshooting
logs/
  swiftsage.log                 # Rotating log — 5MB × 3 files
  runs.jsonl                    # Local run log — one JSON event per run (git-ignored)
```

---

## Key architectural decisions

- **API key is session-only and applied explicitly** — the sidebar field sits in an
  `st.form` and only reaches `os.environ["ANTHROPIC_API_KEY"]` when "Apply key" is
  pressed, which also drops the cached agent so it is rebuilt with the new key. The `.env`
  file must NOT contain it.
- **No Streamlit call path uses `st.stop()`** — it aborts the whole script run, so every
  other tab renders blank until reload. Missing-key and bad-input paths set a flag or
  `None` and let the run finish instead.
- **Field mapper uses Claude directly** (Anthropic SDK) — not LangChain — for a single
  structured JSON call. `max_tokens=16000` to avoid truncation on 46-field payloads. The
  stable part of the prompt (`system_prompt()` — element reference, business rules, output
  schema) is sent as a cached system block; only the field list goes in the user message.
- **Both model callers cache their system prompt** — the block carries
  `cache_control: {"type": "ephemeral"}`. Nothing per-run, user-specific or secret is ever
  put in a cached block, because a prefix that varies is never served from cache.
- **Token usage is recorded per request** — `src/observability/token_usage.py` normalises
  what each SDK reports (the Anthropic SDK excludes cached tokens from `input_tokens`,
  LangChain folds them in) so `input_tokens` always means the whole prompt. Model-backed
  events carry `llm_calls`, `input_tokens`, `output_tokens`, `total_tokens`,
  `cache_read_tokens`, `cache_write_tokens`, `system_prompt_tokens` and
  `system_prompt_measured`. The API reports no separate system-prompt figure, so
  `system_prompt_tokens` is the cached prefix it *did* report — the system block is the
  only cached content — and falls back to a flagged character-count estimate only when
  nothing was cached. Numeric detail values bypass secret redaction, or every count under a
  `*_tokens` key would be written as `[redacted]`.
- **A run maps at most `MAX_MAPPED_FIELDS` (20) source fields** — `select_fields()` in
  `field_mapper.py` drops repeated occurrences of an already-mapped structure and ranks
  the rest on business relevance. The remainder are reported as deferred in the UI and as
  an assumption in the exported document; they are never silently dropped.
- **Gap analyzer prefers expert tables, falls back to the schema** — expert-authored
  mandatory registers exist for pain.001.001.09, pacs.008.001.10, camt.053.001.10 and
  tsrv.001.001.01 (`_MANDATORY_BY_TYPE`), with a per-family default in
  `_MANDATORY_BY_FAMILY` so an unknown version never falls back to another domain. Any
  other target derives its mandatory fields from `TargetSchema.mandatory_leaves()`, and
  each `GapEntry` records its `origin` (`expert` or `schema`).
- **Field mapper context comes from the XSD** — `target_context()` in `field_mapper.py`
  builds the element reference from `TargetSchema.mapping_context()` for the selected
  target (with cardinality, types and code lists) and adds the payment or trade business
  rules. The curated `_PAIN001_CONTEXT` / `_TSRV001_CONTEXT` blocks are only a fallback
  for targets with no vendored XSD.
- **Every proposed ISO path is validated** — `mapping_validator.validate()` resolves each
  mapping against the target XSD and annotates it RESOLVED / PARTIAL / UNRESOLVED /
  UNCHECKED, downgrading confidence when the path cannot be confirmed. The UI and the
  requirements document both show the result, so an unverifiable path is never presented
  as HIGH confidence.
- **Diff classification resolves real element names** — `xmldiff` reports positional XPaths
  (`/*/*[2]/*[4]`) on namespaced production files, so `diff_classifier` resolves each path
  back to its element name before applying the severity rules; otherwise every rule misses.
  Cardinality comes from `schema_cardinality` against the selected XSD, so a removed
  mandatory element grades differently from a removed optional one, and the 0-100 score
  carries the per-rule reasons that produced it.
- **The source family is profiled and checked against the target** — `source_classifier`
  infers the family from the root element and namespace (XML) or field-name vocabulary
  (JSON/CSV) and raises an explicit mismatch warning, surfaced as a red banner and carried
  into the exported document as an assumption, when it disagrees with the chosen target.
- **Requirements documents carry traceability and provenance** — TR-nn / GAP-nn / AS-nn /
  OQ-nn IDs, an assumptions section derived from the run, and a `Provenance` record
  (model, source file, format, content hash, schema, field count, timestamp).
- **Chat answers about fields are grounded in the vendored XSDs** — `lookup_iso20022_element`
  and `compare_element_across_versions` search `SchemaIndex` (built from `data/standards/`)
  by ISO short name, path fragment or business phrase, and return the path, cardinality,
  type, constraints and code list with the message version and schema file as a citation.
  Business meaning comes from `iso_glossary` because the vendored XSDs carry no
  `xs:documentation`; an element with no glossary entry is rendered as structure only, so
  the agent never presents an invented definition as sourced. The system prompt requires
  these tools before any field-level claim.
- **Observability is local only** — `src/observability/run_log.py` appends one JSON line per
  chat turn, tool call, mapping run and comparison to `logs/runs.jsonl` (2MB rotation), and
  the Observability tab aggregates it. Deliberately no LangSmith or other external service:
  the demo must work offline and needs no extra key. Events record counts, durations and
  outcomes only — never message content, XML payloads or credentials; detail values that
  look like a secret are redacted and long strings truncated. `record()` swallows write
  errors so telemetry can never break a demo run.
- **Institutional knowledge is a typed SQLite graph, not embeddings** —
  `src/knowledge/store.py` holds business rules, ISO elements, internal fields, systems
  and defects as nodes with typed edges (`governs`, `maps_to`, `caused`, `owned_by`, …).
  A BA has to be able to enumerate, inspect and edit a rule, and an answer has to name
  the rule it came from; a similarity score over embeddings gives neither. A connection
  is opened per operation rather than held, because Streamlit reruns the script on every
  interaction and possibly from another thread.
- **Candidate vs confirmed is the load-bearing invariant** — anything SwiftSage infers
  lands as `candidate` and is rendered as unconfirmed everywhere it appears; only a human
  promotes it. `rules()` and `search_rules()` default to `AUTHORITATIVE` (`seeded`,
  `confirmed`), so a caller that forgets to filter cannot inject a guess into a prompt or
  a report, and `put_node()` never downgrades an already-confirmed node when the same fact
  is re-observed. Seeded rules carry evidence saying they are mocked demo policy for a
  fictional bank, not published ISO 20022 requirements.
- **Securities/Settlement rules stay unlinked rather than mislinked** — no sese/semt XSD
  is vendored, and `SchemaIndex.search()` widens to other schemas when a message type is
  absent, so seed linking requires the hit's message type to be one the rule names. The
  unresolved element names are kept in the node's detail and shown as such in the UI.
- **RCA is deterministic and offline** — `src/knowledge/rca.py` ranks probable causes from
  four evidence sources (mandatory leaves missing from the payload, internal rules whose
  keywords match the symptom, matching past incidents, elements that exist only in another
  message version) and returns findings with citations and a HIGH/MEDIUM/LOW likelihood.
  No model call, so it works with no key and can be argued with; a fluent unsourced
  explanation would be worse than a ranked list. `record_cause()` is the only way an
  incident becomes `confirmed`, and only a human can trigger it.
- **Payload paths are compared against schema paths on both forms** — a payload path
  includes the `Document` root, `TargetSchema.mandatory_leaves()` paths do not, so RCA
  matches the full path and the root-stripped path and skips a leaf whose parent is absent
  (an absent optional block does not make its children missing).
- **The SME Knowledge tab lives in `src/ui/knowledge_tab.py`** — one tab with modes rather
  than a tab each, because Knowledge, Stories, Tests, Review and RCA are all views of the
  same graph. The store is held in `st.cache_resource`, so a reset must clear that cache.
- **Chat history renders directly on the main page** (no fixed-height container) so the page
  scrolls naturally. Auto-scroll JS injected via `components.html(height=0)`.
- **Demo scenarios are data, not UI code** — `src/ui/demo_scenarios.py` holds each
  scenario's assets, widget presets, business question and talking points; the Demo tab
  only renders them. A preset key must match the `key=` of the widget it drives
  (`src_a`, `src_b`, `diff_schema_choice`, `sample_choice`, `target_msg_type`,
  `chat_prompt_pack`), and `test_demo_assets.py` fails if a preset label is no longer
  offered or an asset is missing. The two XML Diff scenarios run with no API key, which is
  what makes the demo safe without network access; the Demo tab and the Compare button
  share `_compare_and_record()` so both produce identical results and telemetry.
- **The weeks-to-minutes number is derived, with its assumptions on screen** —
  `src/observability/metrics.py` compares measured durations from the run log against
  stated manual baselines (`BASELINE_HOURS`, overridable via
  `SWIFTSAGE_BASELINE_<KIND>_HOURS`, with non-finite and non-positive overrides rejected so
  an `inf` cannot overflow the tab). Only runs that delivered something count: `status ==
  "ok"`, and for a chat turn a positive `grounding_tool_calls`, so a general question never
  earns the specialist baseline. Tool events are excluded because they sit inside the chat
  turn that invoked them. `assumptions()` renders next to the figures so the estimate is
  arguable rather than asserted.
- **A queued demo question survives a missing key** — the Demo tab writes the grounded-chat
  scenario's question to `st.session_state._pending_chat`; the Chat tab reads it without
  popping it and only clears it once a keyed run accepts it, so loading that scenario before
  applying a key does not discard the question.

---

## Mapping types (Transform Advisor)

| Type | Meaning |
|------|---------|
| DIRECT | 1-to-1 same business meaning |
| DERIVED | Must be computed (e.g. IBAN from UK sort code + account) |
| SPLIT | One source → multiple target fields |
| COMBINED | Multiple source → one target (e.g. Date + Time → CreDtTm) |
| UNMAPPED | No ISO 20022 equivalent (e.g. CostCentre, WorkflowId) |

## Gap types

| Type | Meaning |
|------|---------|
| BLOCKING | No source field — requires business decision before go-live |
| ENRICHMENT | Source exists but needs transformation or reference data |
| CONDITIONAL | Only required for certain payment rails or scenarios |

---

## Running tests

```powershell
.venv\Scripts\python.exe -m pytest tests/ -v
```

(macOS/Linux: `.venv/bin/python -m pytest tests/ -q`)

244 tests across `test_knowledge.py`, `test_comparator.py`, `test_observability.py`, `test_token_usage.py`, `test_diff_classification.py`,
`test_impact_and_bundle.py`, `test_trade_domain.py`, `test_transform_advisor.py`,
`test_chat_grounding.py` and `test_demo_assets.py`. They run without an Anthropic API key — the Claude calls in
`field_mapper.py` are the only part not covered.

---

## Logs

All runtime logs write to `logs/swiftsage.log` (rotating, UTF-8).
Tail live: `Get-Content logs\swiftsage.log -Wait -Tail 50`

---

## Environment variables (never put secrets here)

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENT_MODEL` | claude-sonnet-4-6 | LLM model for agent and field mapper |
| `STANDARDS_LIBRARY_PATH` | data/library | Where XSD packages are stored |
| `BENIGN_PATTERNS` | MsgId,CreDtTm,... | Comma-separated tags to ignore in XML diff |
| `SWIFTSAGE_BASELINE_TRANSFORM_HOURS` | 40 | Manual baseline per requirements document |
| `SWIFTSAGE_BASELINE_DIFF_HOURS` | 8 | Manual baseline per impact assessment |
| `SWIFTSAGE_BASELINE_CHAT_HOURS` | 0.5 | Manual baseline per grounded field question |
| `KNOWLEDGE_DB_PATH` | data/knowledge/knowledge.db | SME knowledge graph location |

---

## Skills (slash commands)

| Command | What it does |
|---------|-------------|
| `/run` | Start the Streamlit app |
| `/logs` | Tail the SwiftSage log file live |
| `/test` | Run the pytest test suite |
| `/analyse` | Run Transform Advisor on the sample XML and print a summary |
