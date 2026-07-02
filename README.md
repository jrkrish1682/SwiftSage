# SwiftSage — ISO 20022 Expert Agent

An AI-powered assistant for Business Analysts and Product Owners at financial institutions migrating to ISO 20022. SwiftSage maps your bank's internal payment XML to ISO 20022 target messages, identifies transformation gaps, and generates a structured requirements document for your development team.

Built with **Claude** (claude-sonnet-4-6), **LangGraph**, and **Streamlit**.

---

## Features

- **Transform Advisor** — Parse your internal XML → map each field to ISO 20022 (DIRECT / DERIVED / SPLIT / COMBINED / UNMAPPED) → identify BLOCKING and ENRICHMENT gaps → generate a Word requirements document
- **AI Agent Chat** — Conversational ISO 20022 expert; ask anything about message types, field rules, payment flows, or version deltas
- **XML Diff** — Semantic comparison of two ISO 20022 XML files; classifies each difference as BREAKING / WARNING / INFO / BENIGN with a 0–100 breaking-change score
- **Standards Library** — Download and browse XSD schemas from the ISO 20022 GitHub repository
- **Built-in samples** — Meridian Bank demo XMLs for pain.001 and pacs.008 to try without uploading your own files

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com)

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

```powershell
.venv\Scripts\streamlit.exe run app.py
```

The app opens at `http://localhost:8501`.

### 6. Enter your API key

Paste your Anthropic API key in the **sidebar**. It is held in session memory only and never written to disk.

---

## Project Structure

```
SwiftSage/
├── app.py                              # Streamlit UI — 5 tabs
├── requirements.txt
├── .env.example
├── config/
│   └── settings.py                     # Pydantic-settings config (no secrets)
├── src/
│   ├── agent/
│   │   ├── swift_agent.py              # LangGraph ReAct agent + streaming
│   │   └── tools.py                    # 12 @tool functions
│   ├── transformer/
│   │   ├── message_parser.py           # Walks internal XML → List[InternalField]
│   │   ├── field_mapper.py             # Calls Claude API → List[MappedField]
│   │   ├── gap_analyzer.py             # Mandatory field gap detection
│   │   └── requirements_generator.py  # Generates Word (.docx) requirements doc
│   ├── comparator/
│   │   ├── xml_comparator.py           # Semantic XML diff engine
│   │   ├── canonicalizer.py            # XML normalisation
│   │   └── diff_classifier.py          # BREAKING / WARNING / BENIGN / INFO rules
│   ├── connectors/
│   │   └── iso20022_connector.py       # Downloads XSDs from ISO 20022 GitHub
│   ├── storage/
│   │   └── standards_library.py        # Local artefact catalogue
│   └── utils/helpers.py
├── data/
│   └── samples/
│       ├── internal/
│       │   ├── sample_bank_payment.xml     # Meridian Bank pain.001 demo (46 fields)
│       │   └── sample_bank_fi_transfer.xml # Meridian Bank pacs.008 demo
│       ├── pain001_v1.xml                  # Baseline pain.001 (XML Diff demo)
│       ├── pain001_v2.xml                  # Modified pain.001 with breaking changes
│       └── pacs008_sample.xml              # ISO 20022 pacs.008 reference
└── tests/
    └── test_comparator.py
```

---

## UI Tabs

| Tab | What it does |
|-----|-------------|
| **💬 Chat** | Conversational ISO 20022 agent — streaming answers, BA/PO persona |
| **🔄 Transform Advisor** | Map internal XML → ISO 20022, gap analysis, download requirements doc |
| **🔍 XML Diff** | Semantic diff of two ISO 20022 XMLs with breaking-change scoring |
| **📚 Library** | Browse downloaded XSD schemas |
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
| 🔴 **BREAKING** | Amount, IBAN, currency changed; mandatory field added or removed | Must fix before deployment |
| 🟠 **WARNING** | Settlement or execution date changed; element reordered | Review with business team |
| ℹ️ **INFO** | Optional field added or removed | Informational — no immediate action |
| ✅ **BENIGN** | MsgId, CreDtTm, UETR, EndToEndId, InstrId | Safe to ignore |

---

## Running Tests

```powershell
.venv\Scripts\python.exe -m pytest tests/ -v
```

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENT_MODEL` | `claude-sonnet-4-6` | Claude model for agent and field mapper |
| `STANDARDS_LIBRARY_PATH` | `data/library` | Where XSD packages are stored |
| `BENIGN_PATTERNS` | `MsgId,CreDtTm,...` | Tags to ignore in XML diff |

---

## Data Sources

| Source | Usage |
|--------|-------|
| [ISO 20022 GitHub](https://github.com/ISO20022/iso20022-messages) | XSD schema packages (auto-synced via Standards Library) |
| [ISO 20022 Catalogue](https://www.iso20022.org/iso-20022-message-definitions) | Reference for message sets and field definitions |
