# SwiftSage — approach

Why this POC exists, who it is for, what it set out to prove, and how far it got. Read
[`README.md`](README.md) for installation and usage, [`docs/DESIGN.md`](docs/DESIGN.md)
for the architecture as built, and [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) for a
walkthrough of the scenarios.

---

## Vision

**SwiftSage** is a domain-expert assistant for **Business Analysts and Product Owners**
in financial institutions adopting or migrating to ISO 20022 messaging.

It reduces the dependency on scarce ISO 20022 specialists by making the repeatable part
of their work — reading schemas, grading version changes, drafting mappings — available
on demand, in business language rather than XML. Specialists still review the output;
they no longer have to author it from scratch.

---

## Who it is for

| Persona | Pain today | What SwiftSage gives them |
|---|---|---|
| **Business Analyst** | Days of manual field mapping and requirements writing | A first-cut mapping, gap analysis and requirements document in minutes |
| **Product Owner** | Cannot easily judge the impact of a schema version upgrade | A plain-English breaking-change summary with a scored business impact |
| **Integration Architect** | No tooling to check whether an internal message round-trips through ISO 20022 | Schema-resolved paths and field-level mismatch warnings before build starts |
| **Compliance / Ops** | Needs a record of what changed between two message versions | A classified diff (BREAKING / WARNING / INFO / BENIGN) with a severity score and an exportable assessment |

---

## Problem statement

Banks exchange ISO 20022 messages daily — payment initiations (`pain.001`), clearing and
settlement (`pacs.008`), account reports (`camt.053`), trade undertakings (`tsrv.001`).
Three recurring problems consume analyst time:

1. **Schema version upgrades** — when a new version lands, teams need to know exactly
   what changed, how severe it is, and whether existing systems break.
2. **Internal-to-ISO 20022 migration** — proprietary internal formats must be mapped
   field by field, gaps identified, and a transformation requirements document written.
   Today that is manual.
3. **Knowledge concentration** — ISO 20022 is large and the expertise sits with a few
   people, so analysis queues behind their availability.

---

## What was built

A Streamlit application with three analysis capabilities and the supporting evidence to
trust them.

### Capability 1 — Expert chat, grounded in the schemas

An ISO 20022 expert tuned for a BA/PO audience: business meaning first, XML only when
asked. Field-level answers are not model recall — the agent looks the element up in the
vendored XSDs by ISO name, path fragment or business phrase, and cites the message
version, path, cardinality, type, constraints and code list it used. Business definitions
come from a curated glossary because the published XSDs carry no documentation; an
element with no glossary entry is returned as structure only, so a guess is never
presented as a definition. Starter questions are grouped into domain packs (Payments,
Cash, Trade, Settlement, Securities & FX).

### Capability 2 — Schema change impact analysis

Two ISO 20022 messages in, a graded and exportable impact assessment out. The comparison
is semantic and resolves each change back to its real element name, because `xmldiff`
reports positional paths such as `/*/*[2]/*[4]` on namespaced production files and no
business rule can classify those. Grading consults the selected XSD, so an element that
became mandatory grades differently from a new optional one, and the 0–100 score carries
the per-rule arithmetic that produced it.

### Capability 3 — Transformation Requirements Advisor

An internal message (XML, JSON, CSV or XLSX field specification) is parsed into a field
inventory, each field is mapped to the chosen ISO 20022 target, every proposed path is
resolved against the target XSD, mandatory targets with no source become gaps, and the
whole thing is exported as a Word requirements document with traceability IDs,
assumptions, open questions and a provenance record.

### Supporting capabilities

- **Standards Library** — nine vendored XSD versions across `pain`, `pacs`, `camt`,
  `tsrv` and `tsmt`, the offline source of truth for every schema-dependent answer.
- **Observability** — a local JSONL run log and a tab that aggregates durations, grounded
  chat share, tool usage and errors, and contrasts measured run time with a stated manual
  baseline. No external service, works offline.
- **Demo scenarios** — four rehearsed business questions, two of which run with no API
  key at all.

---

## Mapping and gap classification

| Mapping type | Meaning | Example |
|---|---|---|
| `DIRECT` | 1:1, same semantics | `AMOUNT` → `InstdAmt` |
| `DERIVED` | Target computed from source | `BIC` derived from `SORT_CODE` via lookup |
| `SPLIT` | One source, multiple targets | `FULL_NAME` → `FrstNm` + `LastNm` |
| `COMBINED` | Multiple sources, one target | `SORT_CODE` + `ACCT_NO` → `IBAN` |
| `UNMAPPED` | No ISO 20022 equivalent | Internal tracking identifier |

| Gap type | Meaning | Example resolution |
|---|---|---|
| `BLOCKING` | Mandatory target with no source | "Generate from UUID at runtime" |
| `ENRICHMENT` | Source exists but needs derivation or reference data | "Derive BIC from SORT_CODE" |
| `CONDITIONAL` | Required only for certain rails or scenarios | "Populate for cross-border payments" |

---

## Requirements document structure

1. **Executive summary** — source and target message types, field counts, complexity.
2. **Field mapping table** — internal field, ISO 20022 path, mapping type, confidence,
   schema-resolution outcome, business rule.
3. **Gap register** — target field, gap type, severity, recommended resolution.
4. **Data enrichment requirements** — reference lookups, derivation logic, defaults.
5. **Business rules and conditional logic** — including constraints read from the XSD.
6. **Assumptions and open questions** — including anything the run deferred.
7. **Provenance** — model, source file, format, content hash, schema, field count,
   timestamp.

---

## Key decisions

1. **Structure comes from schemas, judgement comes from the model.** Cardinality, types,
   code lists and paths are read from the vendored XSDs. The model is used for semantic
   mapping and business explanation — never as a source of schema facts.
2. **Every proposed ISO path is verified.** Mappings are resolved against the target XSD
   and labelled RESOLVED / PARTIAL / UNRESOLVED / UNCHECKED, with confidence downgraded
   when a path cannot be confirmed, so an unverifiable path is never shown as HIGH
   confidence.
3. **Nothing is silently dropped.** A run maps at most 20 source fields to keep token
   cost predictable; the rest are listed as deferred in the UI and carried as an
   assumption in the document.
4. **Ambiguity is surfaced, not defaulted.** What the model cannot resolve becomes an
   open question for the business rather than a quiet assumption.
5. **The demo must survive no network.** Schemas are vendored, observability is local,
   and two scenarios run end to end without an API key.
6. **The API key is session-only.** It is entered in the sidebar, applied explicitly, and
   never written to disk or `.env`.

---

## Technology choices

| Technology | Role | Why |
|---|---|---|
| Claude (`claude-sonnet-4-6`) | Reasoning over mappings and explanations | Handles a full XSD context plus the internal message in one call |
| LangGraph | ReAct agent for chat | Multi-tool orchestration with streaming and conversation memory |
| Streamlit | UI | Fast iteration; file upload, chat and download widgets with no frontend build |
| `xmldiff` | Structural XML diff | Tree-based, tolerant of attribute reordering and namespace normalisation |
| `lxml` | XSD parsing, validation, XPath | Handles the large ISO 20022 schemas |
| `python-docx` | Word export | Requirements and impact documents in a format BAs circulate |
| Pydantic-settings | Configuration | Type-safe environment loading, no secrets in config |

---

## Scope

**In scope, and delivered**

- BA/PO expert chat with schema-grounded, cited field answers and domain prompt packs
- Semantic XML diff with schema-aware breaking-change scoring and Word/Markdown export
- Transformation Advisor: XML / JSON / CSV / XLSX ingestion, target-aware mapping,
  path validation, gap analysis, Word requirements document
- Payments (`pain`, `pacs`, `camt`) plus a trade-finance demo (`tsrv`, `tsmt`), from
  nine vendored schema versions
- Local observability and an effort metric that states its own assumptions
- Four rehearsed demo scenarios, two of them key-free

**Out of scope for this POC**

- Legacy MT message support — ISO 20022 MX only
- Live SWIFT MyStandards portal connection
- Automated code generation (XSLT, mapper services) — requirements only
- Multi-user authentication and session persistence
- Integration with bank systems or an ESB
- Formal audit controls

**Natural next steps**

- MT → MX migration advisory
- MyStandards integration
- Code generation for transformation services
- JIRA / requirements repository integration
- Recorded-response tests for the model-backed paths, plus CI