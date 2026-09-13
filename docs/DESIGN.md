# SwiftSage — Design and architecture

How SwiftSage is put together, why it is put together that way, and where to look when
something needs changing. Read [`../README.md`](../README.md) first for what the product
does and [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) for a guided walkthrough of it.

---

## 1. The design problem

ISO 20022 migration work stalls at the business layer, not the technology layer. A BA can
read an XSD but cannot tell you which of 200 differences between two message versions will
stop a payment; a specialist can, and there are not enough of them. So the design goal is
not "answer questions about ISO 20022" — a general-purpose chatbot does that badly and
confidently. The goal is **produce a specialist's artefact that another specialist can
check**: an impact assessment, a mapping, a requirements document, each carrying the
evidence it was derived from.

Three consequences shape everything below.

**Structure comes from the schema, not the model.** Whether an element is mandatory, what
its cardinality is, whether a path exists at all — these are facts in the XSD. A language
model asked to recall them will be right most of the time, which is the worst possible
failure mode for a migration programme. So every structural claim is resolved against a
vendored XSD, and the model is used only for the judgement work: what an internal field
*means* and which ISO element carries that meaning.

**The model's output is validated, not trusted.** Claude proposes ISO paths; the mapping
validator resolves each one against the target schema and downgrades confidence when it
cannot. An unverifiable mapping is still shown — hiding it would be worse — but never as
HIGH confidence.

**Nothing may depend on the network at demo time.** The ISO 20022 GitHub schema
distribution moved and broke schema sync mid-build, which silently emptied the library and
sent every message family down a hardcoded `pain.001` fallback. XSDs are therefore vendored
in the repo and treated as the source of truth; remote sync is an extra, not a dependency.

---

## 2. Components

```
                    Streamlit UI (app.py)
   Demo │ Chat │ Transform Advisor │ XML Diff │ Library │ Observability │ Help
     │      │            │              │          │           │
     │      │            │              │          │           └── observability/metrics.py
     │      │            │              │          │                 measured time vs baseline
     │      │            │              │          │
     │      │            │              │          └── storage/standards_library.py
     │      │            │              │              connectors/iso20022_connector.py
     │      │            │              │
     │      │            │              └── comparator/  xml_comparator → canonicalizer
     │      │            │                               → diff_classifier ← schema_cardinality
     │      │            │                               → impact_report (Word / Markdown)
     │      │            │
     │      │            └── transformer/  message_parser → source_classifier
     │      │                              → field_mapper (Claude) ← target_schema
     │      │                              → mapping_validator → gap_analyzer
     │      │                              → requirements_generator (Word)
     │      │
     │      └── agent/  swift_agent (LangGraph ReAct, streaming)
     │                  tools.py (14 @tool) ← storage/schema_index ← iso_glossary
     │
     └── ui/demo_scenarios.py  (curated scenarios, presets, talking points)

             connectors/schema_bundle.py → data/standards/*.xsd   (offline truth)
             observability/run_log.py     → logs/runs.jsonl        (local telemetry)
```

Layering rule: no `src/` module imports `streamlit` except `ui/theme.py`, which is pure
presentation. The UI orchestrates and renders;
the domain logic is importable from a test or a script, which is why 200 tests run without
a browser or an API key.

---

## 3. The schema layer

Everything factual traces back to `data/standards/` — nine vendored XSD versions across
`pain`, `pacs`, `camt`, `tsrv` and `tsmt`. Three different readers sit on top of them,
because three different questions are being asked:

| Module | Question it answers | Used by |
|---|---|---|
| `comparator/schema_cardinality.py` | Is this element mandatory at this path? | Diff classification |
| `transformer/target_schema.py` | What does this target message look like, and does this path exist? | Mapping prompt context, path validation |
| `storage/schema_index.py` | Which element does this word refer to, across versions? | Chat grounding tools |

`connectors/schema_bundle.py` is the single discovery point (`bundle_files()`), so adding a
family means dropping XSDs into `data/standards/<family>/` — no code change in three places.

The XSDs carry no `xs:documentation`, so business meaning cannot come from them.
`storage/iso_glossary.py` holds curated definitions instead, and an element with no glossary
entry is rendered as **structure only**. That is deliberate: the agent says "I have the path
and cardinality but no sourced definition" rather than filling the gap from model recall.

---

## 4. Capability 1 — XML Diff and impact assessment

```
two XML files ──► canonicalizer ──► xmldiff ──► DiffEntry[]
                  (normalise ws,     (raw edit
                   sort, namespaces)  script)
                        │
                        ▼
                 diff_classifier ──► BREAKING / WARNING / INFO / BENIGN + reasons
                        │  ▲
                        │  └── schema_cardinality (is the element mandatory?)
                        ▼
                 0–100 score with per-rule contributions ──► impact_report (Word / Markdown)
```

The non-obvious part is path resolution. `xmldiff` reports positional XPaths on namespaced
production files — `/*/*[2]/*[4]`, not `/Document/CstmrCdtTrfInitn/PmtInf/Amt` — so
severity rules written against element names matched nothing on real messages while passing
on hand-written test fixtures. `diff_classifier` resolves each positional path back to its
element name before applying rules; this was the single highest-value fix in the project.

Severity is then two inputs, not one: the business meaning of the element (amount, IBAN,
currency, guarantee terms) **and** its cardinality in the selected XSD, so a removed
mandatory element outranks a removed optional one. The score carries the reasons that
produced it, so a reviewer can argue with the weighting instead of arguing with a number.

A parse failure is a failure, not an empty result. An early version reported malformed XML
as "no differences found", which is the most dangerous output the tab could produce;
`ComparisonResult.parse_error` now propagates to the UI and marks the run as an error in
telemetry.

---

## 5. Capability 2 — Transform Advisor

```
upload (XML / JSON / CSV / XLSX)
        │
        ▼
message_parser ──► InternalField[]  (path, name, value, depth)
        │
        ├──► source_classifier ──► inferred family; explicit warning if it disagrees
        │                          with the chosen target
        ▼
select_fields()  ── ranks on business relevance, collapses repeated structures,
        │           caps at MAX_MAPPED_FIELDS (20); the rest are reported as deferred
        ▼
field_mapper ──► Claude (Anthropic SDK, one structured JSON call, max_tokens=16000)
        │   ▲      cached system block: system_prompt() — element reference, rules, schema
        │   │      user message: the selected fields only
        │   └── target_context() ← target_schema.mapping_context() (paths, cardinality,
        │                          types, code lists) + payment/trade business rules
        ▼
MappedField[] (DIRECT / DERIVED / SPLIT / COMBINED / UNMAPPED, confidence, rationale)
        │
        ├──► mapping_validator ──► RESOLVED / PARTIAL / UNRESOLVED / UNCHECKED
        │                          (downgrades confidence on unresolved paths)
        ▼
gap_analyzer ──► GapEntry[] (BLOCKING / ENRICHMENT / CONDITIONAL, origin: expert|schema)
        │
        ▼
requirements_generator ──► Word TRD: TR-nn / GAP-nn / AS-nn / OQ-nn, assumptions,
                           open questions, provenance footer
```

Design notes:

- **The 20-field cap is a product decision, not a technical limit.** A 46-field payload in
  one prompt is affordable; a demo run away with it is not. `select_fields()` ranks on
  business significance (amount, currency, IBAN, BIC, UETR, dates over internal control
  fields) rather than taking the first 20, collapses repeated instances of an
  already-mapped structure, and surfaces the remainder as *deferred* in the UI and as an
  assumption in the document. The honest side effect: gap analysis sees only the mapped
  subset, so a mandatory target field whose source was deferred appears as a gap — the
  document says so explicitly.
- **Gaps prefer expert knowledge, fall back to the schema.** Hand-authored mandatory
  registers exist for `pain.001.001.09`, `pacs.008.001.10`, `camt.053.001.10` and
  `tsrv.001.001.01`; any other target derives them from `TargetSchema.mandatory_leaves()`.
  Each `GapEntry` records which, so a reader can weigh a schema-derived gap differently.
  A per-family default stops an unknown version from borrowing another domain's rules —
  the earlier behaviour, where every unknown target silently used the `pain.001` table.
- **Family mismatch is stated, not inferred by the reader.** A trade guarantee mapped
  against a `camt.053` target used to complete with a generic "paths unconfirmed" note.
  It now raises a red banner naming both families and the vocabulary that triggered it, and
  carries the caveat into the document as an assumption.
- **The document is the deliverable.** Traceability IDs, assumptions and a provenance
  record (model, source file, format, content hash, schema, field count, timestamp) exist
  so the output survives contact with a governance process.

---

## 6. Capability 3 — grounded Chat

`agent/swift_agent.py` runs a LangGraph ReAct agent with streaming; `agent/tools.py`
exposes 14 tools spanning validation, comparison, library sync, mapping and grounding.
The two that matter for trust are `lookup_iso20022_element` and
`compare_element_across_versions`, which search `SchemaIndex` by ISO short name, path
fragment or business phrase and return path, cardinality, type, constraints and code list
**with the message version and schema file as a citation**.

The system prompt requires a lookup before any field-level claim. That is a soft
constraint, so it is verified rather than assumed: the Observability tab reports what share
of chat turns actually called a grounding tool, and the effort metric only credits turns
that did (§8). Starter questions are grouped into domain packs — Payments, Cash, Trade,
Settlement, Securities & FX — in `ui/prompt_packs.py`.

---

## 7. Demo scenarios

`ui/demo_scenarios.py` is a registry of `Scenario` objects: business question, preset
widget values, optional `DiffPair`, optional chat prompt, talking points, what to watch
for, and whether it needs a key. The Demo tab renders the registry; it contains no
per-scenario logic, so adding a scenario is a data change.

Two properties are enforced by tests rather than by review: every referenced asset exists
(`missing_assets()`), and every preset value is actually offered by the widget it targets —
a stale option label would otherwise leave the widget on its default and the presenter
would confidently demo the wrong file pair. Diff scenarios run through the same
`_compare_and_record()` path as the XML Diff tab, so a rehearsed run is telemetered
identically to a real one.

The two offline scenarios (`pain.001.001.09 → .12`, trade guarantee amendment) need no API
key, which is what makes the demo survive a room with no connectivity.

---

## 8. Observability and the effort claim

`observability/run_log.py` appends one JSON line per chat turn, tool call, mapping run and
comparison to `logs/runs.jsonl` (2 MB rotation). Local only — deliberately no LangSmith or
other external service, because the demo must work offline and must not need a second key.

Events record **counts, durations and outcomes only** — never message content, XML
payloads or credentials. Detail values that look like a secret are redacted, long strings
truncated, and `record()` swallows write errors so telemetry can never break a run.
(Numbers are exempt from redaction: a token *count* is not a credential, and its key
contains the word "token".)

### Token usage per request

`observability/token_usage.py` normalises what the two SDKs report into one `TokenUsage`
value, because they disagree on what "input tokens" means: the Anthropic SDK excludes
cached tokens from `input_tokens`, LangChain's `usage_metadata` folds them back in and
splits cache creation across per-TTL keys. In this codebase `input_tokens` always means
the whole prompt, so `cache_read_tokens + cache_write_tokens` is the share of it the cache
accounted for.

Every model-backed event therefore carries `llm_calls`, `input_tokens`, `output_tokens`,
`total_tokens`, `cache_read_tokens`, `cache_write_tokens`, `system_prompt_tokens` and
`system_prompt_measured`. A chat turn sums the several calls the ReAct loop makes; a
mapping run is one call. Events without a model call carry none of these keys rather than
a row of zeroes, and a run log written before this existed still aggregates — `from_detail`
returns no usage for an event with no `llm_calls`.

The API reports no separate figure for the system prompt, so it is not invented:
`system_prompt_tokens` is the **cached prefix the API reported**, which is exactly the
system block because nothing else is cached, and `system_prompt_measured` is true. Only
when nothing was cached at all (a prompt below the model's cacheable minimum) does it fall
back to a character-count estimate, with the flag false and the UI saying so.

### Prompt caching

Both model callers send their stable instructions as a system block marked
`cache_control: {"type": "ephemeral"}`:

- **Chat** — `SYSTEM_PROMPT` is long, identical every turn, and re-sent with the whole
  history on each iteration of the ReAct loop, so it is the cheapest thing in the app to
  cache.
- **Transform Advisor** — `field_mapper.system_prompt()` holds the element reference,
  business rules and output schema for the selected target. These depend only on the
  target message and dwarf the field list, so the prompt was split: stable context in the
  cached system block, the source fields in the user message. A prefix that varied per run
  would never be served from cache, so a test asserts the split holds.

Nothing user-specific, secret or per-run is cached. A cache read is billed at 10% of the
input rate and writing the cache at 125%, so the Observability tab expresses the saving as
the equivalent number of uncached request tokens — negative on the first run, positive
once the prefix is being read back.

`observability/metrics.py` turns that log into the "weeks to minutes" claim, and its whole
design is about not overstating it:

- Baselines are stated on screen, not buried: 40 h for a requirements document, 8 h for an
  impact assessment, 0.5 h for a grounded field question. Each is overridable via
  `SWIFTSAGE_BASELINE_*_HOURS`, so a sceptical client can substitute their own number
  live. Non-finite and non-positive overrides fall back to the default.
- Only runs that delivered something count. A failed comparison produced nothing, and a
  chat turn only replaces a question to a specialist if it actually consulted the
  schemas — so an ungrounded turn earns nothing.
- Tool calls are not counted separately; they sit inside the chat turn that invoked them.
- Review time is not deducted, and the assumption says so: SwiftSage produces a draft a
  specialist still signs off.
- Units stay honest. A 30 ms comparison reads `0.03 s`, not `0.0 min`, and a six-figure
  ratio is rounded to two significant figures — `770,000×` rather than a spurious
  `765,957×`.

---

## 9. UI and session decisions

- **The API key is session-only and applied explicitly.** The sidebar field sits in an
  `st.form` and only reaches `os.environ["ANTHROPIC_API_KEY"]` when *Apply key* is pressed,
  which also drops the cached agent so it is rebuilt against the new key. `.env` must never
  contain it.
- **No call path uses `st.stop()`.** It aborts the whole script run, leaving every other
  tab blank until reload — trivially reachable by clicking a starter chip with no key.
  Missing-key and bad-input paths set a flag or `None` and let the run finish.
- **A queued demo question survives a missing key.** The Demo tab stores the scenario
  question in `_pending_chat`; it is read, not popped, so loading the grounded-chat
  scenario before applying a key does not throw the question away.
- **Streamlit reruns the script on every interaction**, so anything expensive is cached
  (`@st.cache_resource` for the agent and schema index) and anything durable lives in
  `st.session_state` or on disk.

---

## 10. Testing strategy

200 tests, no API key required, no browser required. The Claude call in `field_mapper.py`
is the only part not covered — it is mocked, and everything downstream of it is tested
against real fixtures.

| Suite | Guards |
|---|---|
| `test_comparator.py` | Canonicalisation, diff mechanics, parse-failure propagation |
| `test_diff_classification.py` | Positional-path resolution and severity rules on namespaced files |
| `test_impact_and_bundle.py` | Impact report content, score explainability, vendored bundle discovery |
| `test_transform_advisor.py` | Parsing four formats, field selection and cap, validation, gaps, TRD |
| `test_trade_domain.py` | tsrv/tsmt samples, trade vocabulary, trade gap register |
| `test_chat_grounding.py` | Schema index lookups, version comparison, glossary-less rendering |
| `test_observability.py` | Event scrubbing, rotation, aggregation, filter semantics |
| `test_token_usage.py` | Usage normalisation per SDK, cache arithmetic, legacy events, cached system block |
| `test_demo_assets.py` | Scenario assets and preset labels, real offline runs, metric arithmetic |

The load-bearing ones are the *contract* tests — preset labels matching real widget
options, assets existing, offline scenarios producing the documented figures — because
those break silently in a live demo rather than loudly in CI.

---

## 11. Deliberate non-goals

| Not built | Why |
|---|---|
| MT (legacy FIN) support | The migration question is about MX; MT adds a second parser family for no demo value |
| Live MyStandards connection | Licensed portal; vendored XSDs answer the same structural questions offline |
| Code generation | The bottleneck is requirements, not implementation |
| Multi-user auth / persistence | Single-presenter prototype; session state is enough |
| Audit trail | Explicitly out of scope for the demo, though the run log and provenance footer are where it would start |
| External tracing (LangSmith) | Second key and a network dependency for data the local run log already provides |

## 12. Where this would go next

The honest gaps, in the order they would matter: recorded-response tests around the Claude
calls so mapping quality is regression-tested rather than eyeballed; CI and pinned
requirements; retrieval over the full ISO 20022 catalogue rather than a vendored subset;
and mapping reuse, where an approved mapping becomes reference data for the next
programme — the point at which the tribal-knowledge capture stops being a side effect and
becomes the product.
