# SwiftSage — ISO 20022 Expert Agent

An AI-powered assistant for Business Analysts and Product Owners at financial institutions migrating to ISO 20022. SwiftSage maps your bank's internal messages to ISO 20022 target messages, identifies transformation gaps, generates a structured requirements document for your development team, and assesses the business impact of schema-version upgrades.

Covers the payment families (`pain`, `pacs`, `camt`) and a trade-finance demo (`tsrv` undertakings, `tsmt` trade services). All schema analysis runs against XSDs vendored in `data/standards/`, so nothing depends on network access at demo time.

Built with **Claude** (claude-sonnet-4-6), **LangGraph**, and **Streamlit**.

**Where to go next:** [Quick Start](#quick-start) to run it · [Using SwiftSage](#using-swiftsage) for a task-by-task walkthrough · [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) to present it · [`docs/DESIGN.md`](docs/DESIGN.md) for the architecture and the reasoning behind it.

### What works without an Anthropic API key

| Works offline, no key | Needs a key |
|---|---|
| XML Diff, breaking-change score, Word/Markdown impact assessment | AI Agent Chat (including grounded field answers) |
| Standards Library browsing of the vendored XSDs | Transform Advisor field mapping |
| Observability tab and effort metrics | — |
| The two XML Diff demo scenarios | The mapping and grounded-chat demo scenarios |

---

## Features

- **Transform Advisor** — Parse an internal message (XML, JSON, CSV or XLSX field spec) → map each field to your chosen ISO 20022 target (DIRECT / DERIVED / SPLIT / COMBINED / UNMAPPED) → identify BLOCKING and ENRICHMENT gaps → generate a Word requirements document. The prompt context, including cardinality and code lists, is derived from the target XSD; every proposed ISO path is resolved against that schema and confidence is downgraded when it cannot be confirmed. A run maps at most 20 source fields (ranked on business relevance) to keep token cost predictable; the remainder are reported as deferred, never silently dropped. Uploading a source from the wrong family for the selected target raises an explicit mismatch warning.
- **AI Agent Chat** — Conversational ISO 20022 expert for a BA/PO audience. Answers about specific fields are **grounded in the vendored XSDs**: the agent looks the element up by ISO name, path or business phrase and cites the message version, path, cardinality, type, constraints and code list it used. If the library does not cover the element, it says so instead of inventing one. Starter questions are grouped into domain packs — Payments, Cash, Trade, Settlement, Securities & FX.
- **XML Diff** — Semantic comparison of two ISO 20022 XML files; classifies each difference as BREAKING / WARNING / INFO / BENIGN with an explainable 0–100 breaking-change score. Classification resolves real element names (so it works on namespaced production files) and consults the target XSD for cardinality, so removing a mandatory element grades differently from removing an optional one. Exports a business-readable impact assessment as Word or Markdown.
- **Standards Library** — Browse the vendored XSD packages, or sync additional ones from the ISO 20022 GitHub repository.
- **Observability** — Every chat turn, grounding lookup, mapping run and comparison is timed and appended to a local JSONL run log. The Observability tab shows run counts, median and slowest duration per activity, how many chat turns actually called a grounding tool, tool usage and errors. It also contrasts measured run time with a stated manual baseline (40 h for a requirements document, 8 h for an impact assessment, 30 min for a specialist field answer, each overridable via `SWIFTSAGE_BASELINE_*_HOURS`) so the "weeks to minutes" claim comes with its assumptions on screen. Only runs that delivered something are credited — a failed comparison earns nothing, and a chat turn only counts if it actually consulted the schemas. No external service, no key, works offline.
- **Demo scenarios** — Four rehearsed scenarios in the Demo tab, each phrased as the business question it answers and carrying its own talking points. The two XML Diff scenarios (a `pain.001` version upgrade and a trade guarantee amendment) run on one click with no API key; the mapping and grounded-chat scenarios preload their inputs. Narration for the whole demo is in [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md).
- **Built-in samples** — Meridian Bank internal messages for pain.001, pacs.008 (XML and CSV spec), camt.053 (JSON) and a trade guarantee, plus XML Diff scenarios: a `pain.001.001.09 → .12` version upgrade, a guarantee amendment, and a `tsmt.011.001.03 → .04` upgrade.

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com) — only for Chat and the Transform Advisor; everything else runs without one

### 2. Create a virtual environment

**Windows (PowerShell)**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure (optional — paths only, no secrets)

```bash
cp .env.example .env
# Edit .env to change model or library paths if needed
# Do NOT put your API key in .env — enter it in the UI instead
```

### 5. Run

**Windows (PowerShell)**
```powershell
.venv\Scripts\streamlit.exe run app.py
```

**macOS / Linux**
```bash
.venv/bin/streamlit run app.py
```

The app opens at `http://localhost:8501`.

### 6. Apply your API key

Paste your Anthropic API key in the **sidebar** and press **Apply key** — it only takes effect when you press it, and changing it rebuilds the agent. The key is held in session memory only, never written to disk. Leave it empty to use the offline capabilities.

---

## Using SwiftSage

### Assess the impact of a schema-version upgrade (no key needed)

1. **🔍 XML Diff** → pick a built-in scenario (e.g. *pain.001.001.09 → .12 upgrade*) or upload two XML files in the sidebar.
2. Choose the matching schema so classification can tell a mandatory element from an optional one — the score is schema-aware, and picking the wrong XSD changes the grading.
3. Read the severity breakdown: each difference carries the rule that graded it, and the 0–100 score shows its contributions.
4. Download the impact assessment as **Word** or **Markdown** for circulation.

### Produce transformation requirements from an internal message

1. **🔄 Transform Advisor** → choose a built-in sample or upload your own internal message (`.xml`, `.json`, `.csv`, `.xlsx` field spec).
2. Select the ISO 20022 **target message**. If the source looks like a different family, SwiftSage says so before you spend a run on it.
3. Run the mapping. At most 20 source fields are mapped per run, ranked on business relevance; anything beyond that is listed as **deferred**, never dropped silently.
4. Review mappings (type, confidence, and whether the proposed ISO path resolved against the schema) and gaps (`BLOCKING` / `ENRICHMENT` / `CONDITIONAL`).
5. Download the **Transformation Requirements Document** — traceability IDs, assumptions, open questions and a provenance footer included.

### Ask a field question and get a cited answer

1. **💬 Chat** → pick a domain pack (Payments, Cash, Trade, Settlement, Securities & FX) or type your own question.
2. Ask about a specific element ("what is charge bearer in pain.001.001.09?"). The answer cites the message version, path, cardinality, type, constraints and code list it used.
3. If the vendored library does not cover the element, SwiftSage says so rather than inventing a definition.
4. Confirm it really looked things up: **📈 Observability** reports the share of chat turns that called a grounding tool.

### Present it

**🎬 Demo** → four rehearsed scenarios, each phrased as the business question it answers, with talking points and what to point at. The two XML Diff scenarios run on a single click with no key. Full narration in [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md).

---

## Project Structure

```
SwiftSage/
├── app.py                              # Streamlit UI — 7 tabs
├── requirements.txt
├── .env.example
├── config/
│   └── settings.py                     # Pydantic-settings config (no secrets)
├── src/
│   ├── agent/
│   │   ├── swift_agent.py              # LangGraph ReAct agent + streaming
│   │   └── tools.py                    # 14 @tool functions
│   ├── transformer/
│   │   ├── message_parser.py           # Internal XML / JSON / CSV / XLSX → List[InternalField]
│   │   ├── target_schema.py            # Flattens a vendored XSD → prompt context + path lookup
│   │   ├── field_mapper.py             # Calls Claude API → List[MappedField] (20-field cap)
│   │   ├── mapping_validator.py        # Resolves proposed ISO paths against the target XSD
│   │   ├── source_classifier.py        # Profiles the source family; warns on target mismatch
│   │   ├── gap_analyzer.py             # Mandatory field gap detection (expert + schema-derived)
│   │   └── requirements_generator.py  # Generates Word (.docx) requirements doc
│   ├── comparator/
│   │   ├── xml_comparator.py           # Semantic XML diff engine
│   │   ├── canonicalizer.py            # XML normalisation
│   │   ├── diff_classifier.py          # BREAKING / WARNING / BENIGN / INFO rules
│   │   ├── schema_cardinality.py       # Mandatory/optional lookup from the XSD
│   │   └── impact_report.py            # Business-readable impact assessment (Word + Markdown)
│   ├── connectors/
│   │   ├── iso20022_connector.py       # Downloads XSDs from ISO 20022 GitHub
│   │   └── schema_bundle.py            # Vendored XSD bundle for offline operation
│   ├── storage/
│   │   ├── standards_library.py        # Local artefact catalogue
│   │   ├── schema_index.py             # Searchable index over the vendored XSDs (chat grounding)
│   │   └── iso_glossary.py             # Curated business definitions for ISO element names
│   ├── observability/
│   │   ├── run_log.py                  # Local JSONL run log (durations, counts, outcomes)
│   │   └── metrics.py                  # Measured run time vs stated manual baselines
│   ├── ui/
│   │   ├── theme.py                    # CSS, hero and section helpers
│   │   ├── demo_scenarios.py           # One-click demo scenarios + talking points
│   │   └── prompt_packs.py             # Chat starter questions per business domain
│   └── utils/helpers.py
├── data/
│   ├── standards/                          # Vendored XSDs: pain, pacs, camt, tsrv, tsmt
│   └── samples/
│       ├── internal/
│       │   ├── sample_bank_payment.xml          # pain.001 demo (46 fields)
│       │   ├── sample_bank_fi_transfer.xml      # pacs.008 demo
│       │   ├── sample_bank_fi_transfer_spec.csv # pacs.008 demo as a field specification
│       │   ├── sample_bank_statement.json       # camt.053 demo (JSON feed)
│       │   └── sample_bank_guarantee.xml        # Guarantee application → tsrv.001
│       ├── trade/
│       │   ├── tsrv001_guarantee_v1.xml / _v2.xml   # Guarantee amendment pair
│       │   └── tsmt011_baseline_v3.xml / _v4.xml    # tsmt.011 .03 → .04 upgrade
│       ├── pain001_v1.xml                  # Baseline pain.001 (XML Diff demo)
│       ├── pain001_v2.xml                  # Modified pain.001 with breaking changes
│       ├── pain001_v12_upgrade.xml         # pain.001.001.12 upgrade of the baseline
│       └── pacs008_sample.xml              # ISO 20022 pacs.008 reference
├── docs/
│   ├── DEMO_SCRIPT.md                       # 12-minute demo narration and objection handling
│   └── DESIGN.md                            # Architecture, data flows and design decisions
├── logs/
│   ├── swiftsage.log                       # Rotating application log
│   └── runs.jsonl                          # Local run log (git-ignored)
└── tests/                                  # 200 tests
```

---

## UI Tabs

| Tab | What it does |
|-----|-------------|
| **🎬 Demo** | Four rehearsed scenarios — one click loads (and for the diff scenarios, runs) the inputs, with talking points and what to point at |
| **💬 Chat** | Conversational ISO 20022 agent — streaming answers, BA/PO persona, schema-grounded field answers, domain starter packs |
| **🔄 Transform Advisor** | Map an internal message (XML / JSON / CSV / XLSX) → ISO 20022, gap analysis, download requirements doc |
| **🔍 XML Diff** | Semantic diff of two ISO 20022 XMLs with breaking-change scoring and impact-assessment export |
| **📚 Library** | Browse the vendored and downloaded XSD schemas |
| **📈 Observability** | Local run log — durations, effort saved vs the manual baseline, grounded-chat share, tool usage, errors; download or clear the JSONL |
| **ℹ️ Help** | Quick-start guide and classification reference |

---

## Mapping Types

| Type | Meaning |
|------|---------|
| `DIRECT` | 1-to-1, same business meaning |
| `DERIVED` | Must be computed — e.g. IBAN from UK sort code + account number |
| `SPLIT` | One source field → multiple target fields |
| `COMBINED` | Multiple source fields → one target — e.g. Date + Time → CreDtTm |
| `UNMAPPED` | No ISO 20022 equivalent — e.g. CostCentre, WorkflowId |

## Gap Types

| Type | Meaning |
|------|---------|
| `BLOCKING` | Mandatory field with no source — requires a business decision before go-live |
| `ENRICHMENT` | Source exists but needs transformation or external reference data |
| `CONDITIONAL` | Only required for certain payment rails or scenarios |

---

## Breaking-Change Classification (XML Diff)

| Severity | Triggers | Action |
|----------|----------|--------|
| 🔴 **BREAKING** | Amount, IBAN, currency or guarantee terms changed; mandatory element (per the XSD) added or removed | Must fix before deployment |
| 🟠 **WARNING** | Settlement or execution date changed; element reordered | Review with business team |
| ℹ️ **INFO** | Optional field added or removed | Informational — no immediate action |
| ✅ **BENIGN** | MsgId, CreDtTm, UETR, EndToEndId, InstrId | Safe to ignore |

---

## Running Tests

**Windows (PowerShell)**
```powershell
.venv\Scripts\python.exe -m pytest tests/ -v
```

**macOS / Linux**
```bash
.venv/bin/python -m pytest tests/ -q
```

200 tests. They need no Anthropic API key and no browser — the Claude call in `field_mapper.py` is the only part not covered.

---

## Environment Variables

Never put secrets here — the API key belongs in the sidebar.

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENT_MODEL` | `claude-sonnet-4-6` | Claude model for agent and field mapper |
| `STANDARDS_LIBRARY_PATH` | `data/library` | Where synced XSD packages are stored |
| `BENIGN_PATTERNS` | `MsgId,CreDtTm,...` | Tags to ignore in XML diff |
| `SWIFTSAGE_BASELINE_TRANSFORM_HOURS` | `40` | Manual baseline per requirements document, used by the effort metric |
| `SWIFTSAGE_BASELINE_DIFF_HOURS` | `8` | Manual baseline per impact assessment |
| `SWIFTSAGE_BASELINE_CHAT_HOURS` | `0.5` | Manual baseline per specialist field question |

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| "Please enter your Anthropic API Key" | The key was typed but not applied — press **Apply key** in the sidebar. Other tabs keep working without one. |
| XML Diff reports no differences | Check for a parse error message: malformed XML is reported as a failure, not as "identical". |
| A change grades lower than expected | Cardinality comes from the schema you selected. Pick the XSD that matches the messages being compared. |
| Mapping skipped fields | Expected: a run maps at most 20 fields. The deferred list shows the rest; split the message or map in two runs. |
| An unexpected "family mismatch" banner | The source vocabulary disagrees with the selected target message — usually the wrong target, occasionally an unusual internal schema. |
| Standards Library sync fails | Network-dependent and optional. The vendored XSDs in `data/standards/` cover every demo path offline. |
| Observability tab is empty | No runs recorded yet in `logs/runs.jsonl`, or it was cleared from the tab. |

---

## Data Sources

| Source | Usage |
|--------|-------|
| `data/standards/` | Vendored XSD packages — the offline source of truth for classification, mapping context and chat grounding |
| [ISO 20022 GitHub](https://github.com/ISO20022/iso20022-messages) | Additional XSD schema packages (synced via Standards Library) |
| [ISO 20022 Catalogue](https://www.iso20022.org/iso-20022-message-definitions) | Reference for message sets and field definitions |
