# SWIFT Message Validator

An ISO 20022 expert agent that validates, compares, and explains SWIFT MX messages using LangChain, Claude AI, and Streamlit.

---

## Features

- **Semantic XML comparison** — diff two ISO 20022 XML instances by business element, not line-by-line; ignores benign fields (IDs, timestamps)
- **Breaking-change scoring** — 0–100 score with BREAKING / WARNING / BENIGN / INFO classification per diff
- **Schema validation** — validate XML instances against XSD schemas
- **Batch comparison** — compare entire folders of XMLs; surfaces top-20 recurring diff patterns
- **Schema sync** — download the latest XSD packages from the ISO 20022 GitHub repository
- **AI agent chat** — ask natural-language questions; agent uses all the above tools automatically
- **Regression test generation** — auto-generate test cases from detected differences
- **Message flow explanation** — roles, steps, downstream messages for any ISO 20022 type

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com)

### 2. Create and activate a virtual environment

**macOS / Linux**
```bash
cd demo2_swiftMsg_Validator
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (Command Prompt)**
```cmd
cd demo2_swiftMsg_Validator
python -m venv .venv
.venv\Scripts\activate
```

**Windows (PowerShell)**
```powershell
cd demo2_swiftMsg_Validator
python -m venv .venv
.venv\Scripts\Activate.ps1
```

To deactivate the venv at any time: `deactivate`

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure (optional — paths only, no API key)

```bash
cp .env.example .env
# Edit .env to change schema/library paths if needed
# Do NOT put your API key in .env — enter it in the UI instead
```

### 5. Run

```bash
streamlit run app.py
```

The app opens at `http://localhost:8501`.

### 6. Enter your API key

Paste your Anthropic API key in the **sidebar** text field. It is held in session memory only and never written to disk.

---

## Project Structure

```
demo2_swiftMsg_Validator/
├── app.py                          # Streamlit UI entry point
├── requirements.txt
├── .env.example
├── config/
│   └── settings.py                 # All config via pydantic-settings
├── src/
│   ├── agent/
│   │   ├── swift_agent.py          # LangChain ReAct agent (Claude)
│   │   └── tools.py                # 8 agent tools
│   ├── comparator/
│   │   ├── xml_comparator.py       # Core semantic diff engine
│   │   ├── canonicalizer.py        # XML normalisation
│   │   └── diff_classifier.py      # Breaking-change rules + scoring
│   ├── connectors/
│   │   └── iso20022_connector.py   # ISO 20022 schema downloader
│   ├── storage/
│   │   └── standards_library.py   # Local artefact catalogue
│   └── utils/helpers.py
├── data/
│   └── samples/
│       ├── pain001_v1.xml          # Baseline pain.001 (2 payments)
│       ├── pain001_v2.xml          # Modified: breaking + warning changes
│       └── pacs008_sample.xml      # Interbank credit transfer
└── tests/
    └── test_comparator.py          # 15 unit tests
```

---

## Running Tests

```bash
python -m pytest tests/ -v
```

---

## UI Tabs

| Tab | What it does |
|-----|-------------|
| **💬 Chat** | Conversational agent — ask anything, upload files, get streaming answers |
| **🔍 XML Diff** | Direct visual comparison — select files, see colour-coded diff table, download reports |
| **📚 Library** | Browse downloaded schemas and artefacts |
| **ℹ️ Help** | Quick reference for tools and classification rules |

---

## Sample Chat Conversations

Copy and paste any of these into the **💬 Chat** tab to test the agent.

---

### 1. Message flow explanation

```
What is pacs.008 used for? Explain the full payment flow including upstream and downstream messages.
```

**Expected:** The agent explains the FI-to-FI credit transfer role, the debtor/creditor agent chain, and that it is typically preceded by pain.001 and followed by pacs.002 and camt.054.

---

### 2. Compare the pre-loaded sample files

```
Compare the two sample pain.001 files (pain001_v1.xml and pain001_v2.xml in data/samples/) and tell me which changes are breaking and why.
```

**Expected:** The agent calls `compare_xml_messages`, identifies:
- 🔴 BREAKING — `InstdAmt` changed from 20000.00 to 18500.00
- 🔴 BREAKING — `CdtrAcct/IBAN` changed (funds would go to wrong account)
- 🟠 WARNING  — `ReqdExctnDt` pushed out by 3 days
- ℹ️ INFO     — `RgltryRptg` block added
- ✅ BENIGN   — MsgId, CreDtTm, UETR, EndToEndId changed (ignored)

---

### 3. Detect message type

```
What ISO 20022 message type is the file data/samples/pacs008_sample.xml?
```

**Expected:** The agent calls `detect_message_type` and returns `pacs.008.001.10` with domain `Payments Clearing and Settlement`.

---

### 4. Generate regression test cases

```
Generate regression test cases for the differences between data/samples/pain001_v1.xml and data/samples/pain001_v2.xml.
```

**Expected:** The agent calls `generate_test_cases` and returns a Markdown checklist — one test case per BREAKING/WARNING diff, each with the XPath, change type, old/new values, and a suggested assertion.

---

### 5. Explain a message you haven't heard of

```
What is camt.056 and when would a bank send it?
```

**Expected:** The agent explains the FI-to-FI Payment Cancellation Request, its relationship to pain.007 (Customer Payment Reversal), and that it is resolved by camt.029.

---

### 6. Validate an uploaded file

Upload one of the sample XMLs via the sidebar, then type:

```
Validate pain001_v1.xml and tell me if it passes schema validation.
```

**Expected:** The agent calls `validate_xml`. If no matching XSD is in the local library yet, it reports the detected namespace and advises running a schema sync.

---

### 7. Sync schemas then validate

```
First sync the pain and pacs schemas from ISO 20022, then validate data/samples/pacs008_sample.xml.
```

**Expected:** The agent chains two tool calls — `fetch_iso20022_schemas` then `validate_xml` — and reports the validation result against the freshly downloaded XSD.

---

### 8. Business impact question

```
Our system receives pain.001 files. If a counterparty starts sending pain.001.001.12 instead of pain.001.001.09, what fields might be new or changed that we need to handle?
```

**Expected:** The agent uses its ISO 20022 domain knowledge to explain the version delta: new LEI field under InitgPty, changes to address types (structured vs unstructured), new UltmtDbtr/UltmtCdtr handling, etc.

---

### 9. Batch folder comparison (advanced)

If you have two folders of XML files (e.g. `data/v1/` and `data/v2/`), ask:

```
Compare all XML files in data/samples/ against themselves as a batch and show me the top recurring diff patterns.
```

**Expected:** The agent calls `batch_compare_xml_folders` and returns a per-file summary table plus the top-N recurring diff patterns across the folder.

---

### 10. Library status check

```
What schemas do I have in my local Standards Library?
```

**Expected:** The agent calls `list_standards_library` and returns a table of downloaded XSD artefacts, or advises running a sync if the library is empty.

---

## Breaking-Change Classification Reference

| Severity | Triggers | Action |
|----------|----------|--------|
| 🔴 **BREAKING** | Amount changed, IBAN changed, mandatory field removed/added, currency changed | Must fix before deployment |
| 🟠 **WARNING** | Settlement/execution date changed, element re-ordered | Review with business team |
| ℹ️ **INFO** | Optional field added or removed | Informational — no immediate action |
| ✅ **BENIGN** | MsgId, CreDtTm, UETR, EndToEndId, InstrId, correlation refs | Safe to ignore |

---

## Adding Custom Ignore Patterns

In the **🔍 XML Diff** tab, expand **⚙️ Ignore patterns** and add any tag name (local name only, no namespace prefix) to treat as benign. To make patterns permanent, edit `benign_patterns` in `config/settings.py`.

---

## Data Sources

| Source | Usage |
|--------|-------|
| [ISO 20022 GitHub](https://github.com/ISO20022/iso20022-messages) | XSD schema packages (auto-synced) |
| [ISO 20022 Catalogue](https://www.iso20022.org/iso-20022-message-definitions) | Reference for message sets |
| [SWIFT MyStandards](https://www.swift.com/our-solutions/standards/swift-mystandards) | Optional authenticated connector (add credentials to `.env`) |
