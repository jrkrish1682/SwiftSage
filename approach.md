# SwiftSage — SWIFT ISO 20022 Expert Agent Approach

## Vision

**SwiftSage** is a domain-expert AI assistant purpose-built for **Business Analysts and Product Owners** in large financial institutions who are adopting, integrating, or migrating to ISO 20022 messaging standards.

SwiftSage removes the dependency on scarce ISO 20022 specialists by giving every BA and PO an always-available, authoritative expert that speaks in business language — not XML.

---

## Who Are We Building For?

| Persona | Pain Today | What the Agent Does for Them |
|---|---|---|
| **Business Analyst** | Spends days manually mapping internal fields to ISO 20022 schemas, writing transformation requirement docs | Gets a first-cut mapping + gap analysis + requirements document in minutes |
| **Product Owner** | Can't easily assess impact of a schema version upgrade on in-flight projects | Gets a plain-English breaking-change summary with business impact scoring |
| **Integration Architect** | No tooling to validate whether a proposed internal message will round-trip cleanly through ISO 20022 | Gets structural validation + field-level mismatch warnings before build begins |
| **Compliance / Ops** | Needs to know what changed between two message versions for audit trail | Gets a classified diff report (BREAKING / WARNING / INFO) with a severity score |

---

## Problem Statement

Financial institutions exchange millions of ISO 20022 XML messages daily — payment initiations (`pain.001`), clearing & settlement (`pacs.008`), account reports (`camt.053`), and more. Three recurring problems consume enormous analyst time:

1. **Schema version upgrades** — When ISO 20022 releases a new version, teams need to know exactly what changed, how severe it is, and whether existing systems will break.
2. **Internal-to-ISO 20022 migration** — Banks run proprietary internal message formats (XML, JSON, flat files, legacy MT). Migrating to ISO 20022 requires field-by-field mapping, gap identification, and a formal transformation requirements document — all done manually today.
3. **Knowledge gap** — ISO 20022 is vast (500+ message types, complex XSD schemas, business rules). Most BAs and POs lack the deep expertise to work confidently with it without specialist support.

---

## What We Are Building

A **two-capability expert agent** delivered via a Streamlit UI:

### Capability 1 — SWIFT ISO 20022 Expert Chat (existing, enhanced)
An always-available expert that answers questions about ISO 20022 in plain business language:
- What does this field mean in business terms?
- What changed between pain.001 v3 and v9?
- Is this message valid against the schema?
- Show me the payment flow for a cross-border SEPA transaction.

### Capability 2 — Internal-to-ISO 20022 Transformation Advisor (new)
Upload a bank's internal message (XML, JSON, flat-file spec, or field list). The agent:
1. **Parses** the internal message structure and infers field semantics
2. **Maps** each internal field to its ISO 20022 equivalent using domain reasoning
3. **Identifies gaps** — mandatory ISO 20022 fields with no internal source, and internal fields with no ISO 20022 target
4. **Classifies gaps by risk** — blocking (message will be rejected), enrichment-needed (must be derived/defaulted), informational
5. **Generates a Transformation Requirements Document** — a structured, business-readable artefact ready for handoff to a development team

---

## Core Functional Requirements

### Existing (retained and enhanced)

| # | Requirement | How it's solved |
|---|---|---|
| FR-1 | Sync ISO 20022 schemas from official source | `ISO20022Connector` — GitHub XSD package download |
| FR-2 | Semantic XML diff with breaking-change scoring | `XMLComparator` + `DiffClassifier` → 0–100 score |
| FR-3 | XSD schema validation | `lxml` validates against synced XSD files |
| FR-4 | Batch folder comparison | `batch_compare_xml_folders` tool |
| FR-5 | Regression test case generation | Agent generates before/after test pairs |
| FR-6 | Business-language message flow explanation | Agent explains ISO 20022 types in plain English |
| FR-7 | Natural language chat interface | Streamlit chat + streaming LangGraph agent |

### New — Transformation Advisor

| # | Requirement | Detail |
|---|---|---|
| FR-8 | Accept bank internal message as input | XML, JSON, CSV field list, or free-text field description |
| FR-9 | Parse and infer internal message semantics | Extract field names, types, optionality, sample values |
| FR-10 | Map internal fields → ISO 20022 target fields | Agent reasons using ISO 20022 domain knowledge + loaded XSD |
| FR-11 | Classify each mapping by confidence and type | DIRECT / DERIVED / SPLIT / COMBINED / UNMAPPED |
| FR-12 | Identify ISO 20022 mandatory fields with no source | Flag as BLOCKING gap with suggested population strategy |
| FR-13 | Identify internal fields with no ISO 20022 target | Flag as OUT-OF-SCOPE with explanation |
| FR-14 | Generate Transformation Requirements Document | Structured markdown/Word doc with field mapping table, gap register, business rules |
| FR-15 | Suggest data enrichment strategies for gaps | E.g. "Derive BIC from sort code via reference data lookup" |
| FR-16 | Support target message type selection | User specifies pain.001, pacs.008, etc. as the migration target |

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                         Streamlit UI (app.py)                       │
│  [Chat]  [XML Diff]  [Transform Advisor]  [Library]  [Help]        │
└──────┬──────────────────┬──────────────────────────────────────────┘
       │                  │
       ▼                  ▼
┌────────────┐    ┌───────────────────┐
│   SWIFT    │    │   XMLComparator   │  ← direct diff (no agent)
│   Agent    │    └───────────────────┘
│ (LangGraph)│
└─────┬──────┘
      │  ReAct loop (think → tool → observe → repeat)
      ▼
┌──────────────────────────────────────────────────────────┐
│                      Tool Registry                        │
│                                                           │
│  EXISTING TOOLS                NEW TOOLS                 │
│  ─────────────────              ───────────────────────  │
│  validate_xml                   analyze_internal_message │
│  compare_xml_messages           map_to_iso20022          │
│  batch_compare_folders          identify_gaps            │
│  fetch_iso20022_schemas         generate_transform_reqs  │
│  list_standards_library         suggest_enrichment       │
│  detect_message_type                                      │
│  generate_test_cases                                      │
│  explain_message_flow                                     │
└──────┬───────────────────────────────┬───────────────────┘
       │                               │
       ▼                               ▼
┌──────────────┐             ┌─────────────────────┐
│  Standards   │             │  ISO20022Connector  │
│  Library     │             │  (GitHub XSD sync)  │
│ (JSON index) │             └─────────────────────┘
└──────────────┘
```

---

## New Capability Deep Dive — Transformation Advisor

### Inputs the Agent Accepts

| Input Type | Example | How Agent Handles It |
|---|---|---|
| Internal XML message | Bank's proprietary XML payload | Parse element tree, extract tags + types + values |
| JSON message | Internal REST API payload | Flatten JSON keys, infer types from values |
| Field specification (CSV/table) | FieldName, Type, Mandatory, Description | Parse as structured field list |
| Free-text description | "We have a field called SORT_CODE which is the 6-digit UK bank routing code" | NLP extraction of field semantics |

### Mapping Classification

Each internal field is mapped to one of:

| Mapping Type | Meaning | Example |
|---|---|---|
| `DIRECT` | 1:1 match, same semantics | `AMOUNT` → `InstdAmt` |
| `DERIVED` | Target field computed from source | `BIC` derived from `SORT_CODE` via lookup |
| `SPLIT` | One source field splits into multiple targets | `FULL_NAME` → `FrstNm` + `LastNm` |
| `COMBINED` | Multiple source fields merge into one target | `SORT_CODE` + `ACCT_NO` → `IBAN` |
| `UNMAPPED` | No ISO 20022 equivalent found | Internal tracking ID with no MX equivalent |

### Gap Classification

| Gap Type | Severity | Example | Agent Suggestion |
|---|---|---|---|
| `BLOCKING` | Critical | `GrpHdr/MsgId` mandatory, no source field | "Generate from UUID at runtime" |
| `ENRICHMENT` | High | `CdtrAgt/FinInstnId/BIC` required but not in source | "Derive BIC from SORT_CODE via reference data" |
| `CONDITIONAL` | Medium | Field required only for cross-border payments | "Populate when `CtryOfRes` ≠ destination country" |
| `OUT_OF_SCOPE` | Info | Internal field has no ISO 20022 target | "Document as bank-internal extension; consider private element or proprietary block" |

### Transformation Requirements Document Structure

The agent generates a structured document with these sections:

```
1. Executive Summary
   - Source message type (bank internal)
   - Target ISO 20022 message type (e.g. pain.001.001.09)
   - Total fields: X source → Y mapped, Z gaps
   - Overall migration complexity: LOW / MEDIUM / HIGH

2. Field Mapping Table
   | Internal Field | ISO 20022 XPath | Mapping Type | Confidence | Business Rule |

3. Gap Register
   | ISO 20022 Field | Gap Type | Severity | Recommended Resolution |

4. Data Enrichment Requirements
   - Reference data lookups needed
   - Derivation logic
   - Default value strategies

5. Business Rules & Conditional Logic
   - Rules that control field population
   - Validation constraints from ISO 20022 XSD

6. Open Questions for Business
   - Ambiguous mappings requiring SME decision
   - Policy decisions (e.g. how to handle missing BIC)

7. Next Steps
   - Recommended actions for development team
   - Suggested test scenarios
```

---

## Data Flow — Transformation Advisor

```
User uploads internal message + selects target ISO 20022 type
        │
        ▼
analyze_internal_message tool
→ extracts field inventory (name, type, optionality, sample value)
        │
        ▼
fetch_iso20022_schemas tool
→ loads XSD for target message type (e.g. pain.001.001.09)
→ extracts all elements with mandatory/optional status
        │
        ▼
map_to_iso20022 tool
→ Claude reasons field-by-field: semantics, data type, cardinality
→ produces mapping table with confidence score per field
        │
        ▼
identify_gaps tool
→ cross-references: which mandatory ISO fields have no source?
→ which internal fields have no ISO target?
→ classifies each gap by type and severity
        │
        ▼
suggest_enrichment tool
→ for each BLOCKING/ENRICHMENT gap, suggests resolution strategy
        │
        ▼
generate_transform_reqs tool
→ assembles all outputs into structured Transformation Requirements Doc
→ streams to UI, optionally exports as Word/Markdown
```

---

## Data Flow — Expert Chat (enhanced)

```
User types question (BA/PO persona)
        │
        ▼
SWIFTAgent — system prompt includes BA/PO expert context:
"Explain in business terms, avoid raw XML unless asked,
 relate answers to payment operations and compliance impact"
        │
        ▼
Claude reasons and calls tools as needed
        │
        ├─→ explain_message_flow  → plain-English payment flow narrative
        ├─→ compare_xml_messages  → diff rendered as business impact table
        ├─→ validate_xml          → validation errors explained in business terms
        ├─→ map_to_iso20022       → field mapping reasoning for ad-hoc questions
        └─→ … (other tools as needed)
        │
        ▼
Response framed for BA/PO: business terms first, technical detail on request
Tokens streamed to Streamlit chat UI
```

---

## Key Design Decisions

### 1. Agent persona tuned for BA/PO audience
The system prompt instructs the agent to:
- Always lead with business meaning, not XML structure
- Express impact in operational terms (payment rejection, STP failure, compliance breach)
- Offer to go deeper technically only when asked
- Use analogies from banking operations when explaining complex concepts

### 2. Transformation mapping uses ISO 20022 XSD as ground truth
Rather than hard-coding a mapping dictionary, the agent loads the actual XSD for the target message type and reasons against it. This means:
- Mappings are always accurate to the specific version the bank is targeting
- Mandatory/optional status is derived from the schema, not assumed
- As ISO 20022 versions evolve, the agent stays current via schema sync

### 3. Confidence scoring on mappings
Each field mapping gets a confidence score (HIGH / MEDIUM / LOW) so BAs can prioritise which mappings need SME review vs. which are clear-cut.

### 4. Human-in-the-loop for ambiguous gaps
Mappings the agent cannot confidently resolve are surfaced as **Open Questions** in the requirements document — not silently defaulted. The BA/PO decides; the agent documents the decision.

### 5. Output formats designed for handoff
The Transformation Requirements Document is structured to be handed directly to a development team or systems integrator — not just a chat response. It includes actionable business rules, not just field names.

---

## Technology Choices

| Technology | Role | Why |
|---|---|---|
| Claude (`claude-sonnet-4-6`) | LLM backbone | Strong reasoning over ISO 20022 domain knowledge; large context handles full XSD + internal message simultaneously |
| LangGraph | ReAct agent framework | Multi-tool orchestration, streaming, conversation memory |
| Streamlit | UI | Fast iteration; built-in file upload, chat, and download widgets; no frontend build step |
| `xmldiff` | Structural XML diff | Tree-based; correct for attribute reordering, namespace normalisation |
| `lxml` | XSD validation + XPath | Handles large ISO 20022 XSD schemas; XPath for field extraction |
| `python-docx` | Word document export | Transformation Requirements Doc exported as .docx for BA handoff |
| Pydantic-settings | Configuration | Type-safe env loading |

---

## Updated Project Structure

```
demo2_swiftMsg_Validator/
├── app.py                              # Streamlit entry point (5 tabs)
├── requirements.txt
├── .env.example
├── approach.md                         # This document
├── config/
│   └── settings.py
├── src/
│   ├── agent/
│   │   ├── swift_agent.py              # LangGraph ReAct agent (BA/PO persona)
│   │   └── tools.py                    # 8 existing + 5 new transformation tools
│   ├── comparator/
│   │   ├── xml_comparator.py
│   │   ├── canonicalizer.py
│   │   └── diff_classifier.py
│   ├── transformer/                    # NEW
│   │   ├── message_parser.py           # Parse XML/JSON/CSV internal messages
│   │   ├── field_mapper.py             # Internal → ISO 20022 field mapping logic
│   │   ├── gap_analyzer.py             # Gap identification and classification
│   │   └── requirements_generator.py  # Assemble and export requirements doc
│   ├── connectors/
│   │   └── iso20022_connector.py
│   └── storage/
│       └── standards_library.py
├── data/
│   └── samples/
│       ├── pain001_v1.xml
│       ├── pain001_v2.xml
│       ├── pacs008.xml
│       └── internal/                   # NEW — sample bank internal messages
│           ├── sample_internal_payment.xml
│           └── sample_internal_payment.json
└── tests/
```

---

## Scope

### In Scope (Phase 1)
- Expert chat tuned for BA/PO audience (business-first language)
- Semantic XML diff with breaking-change scoring and business impact framing
- XSD validation with business-friendly error explanations
- ISO 20022 schema sync (pain, pacs, camt, acmt, auth, reda families)
- **Transformation Advisor** — internal message upload → field mapping → gap analysis → requirements doc
- Word document export of Transformation Requirements Document
- Batch comparison for regression analysis
- Regression test case generation

### Out of Scope (Phase 1)
- Live SWIFT MyStandards portal connection
- Legacy MT message support (MX/ISO 20022 only)
- Automated code generation (XSLT, Java mapper, etc.) — requirements only
- Multi-user auth / session persistence
- Integration with bank's internal systems or ESB
- Real-time message routing or interception
