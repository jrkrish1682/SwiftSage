# SwiftSage — Project details

## What this project is

SwiftSage is an AI-powered ISO 20022 / SWIFT expert agent built for Business Analysts and
Product Owners at financial institutions. It runs as a Streamlit web app backed by a
LangGraph ReAct agent using Claude (claude-sonnet-4-6).

Primary demo target: mapping a UK bank's internal payment XML → **pain.001.001.09**.

---

## How to run the app

```powershell
.venv\Scripts\streamlit.exe run app.py
```

App opens at http://localhost:8501. Enter the Anthropic API key in the sidebar — it is
**never written to disk**, held in session memory only.

Use the `/run` skill to start the app from Claude Code.

---

## Project structure

```
app.py                          # Streamlit UI — 5 tabs
config/settings.py              # Pydantic-settings config (no secrets)
src/
  agent/
    swift_agent.py              # LangGraph ReAct agent + streaming
    tools.py                    # 12 @tool functions
  transformer/
    message_parser.py           # Walks internal XML → List[InternalField]
    field_mapper.py             # Calls Claude API → List[MappedField]
    gap_analyzer.py             # Hardcoded mandatory pain.001 fields → List[GapEntry]
    requirements_generator.py   # python-docx Word doc generator
  comparator/
    xml_comparator.py           # Semantic XML diff engine
    diff_classifier.py          # BREAKING/WARNING/BENIGN/INFO rules
  connectors/
    iso20022_connector.py       # Downloads XSDs from ISO 20022 GitHub
  storage/
    standards_library.py        # Local artefact catalogue
  utils/helpers.py              # get_logger(), XML helpers
data/
  samples/internal/
    sample_bank_payment.xml     # Meridian Bank demo XML (46 fields)
logs/
  swiftsage.log                 # Rotating log — 5MB × 3 files
```

---

## Key architectural decisions

- **API key is session-only** — loaded via `st.text_input(type="password")` into
  `os.environ["ANTHROPIC_API_KEY"]`. The `.env` file must NOT contain it.
- **Field mapper uses Claude directly** (Anthropic SDK) — not LangChain — for a single
  structured JSON call. `max_tokens=16000` to avoid truncation on 46-field payloads.
- **Gap analyzer is hardcoded** — 21 mandatory pain.001.001.09 fields with expert-authored
  recommendations in `_PAIN001_MANDATORY`. Add other message types to `_MANDATORY_BY_TYPE`.
- **Streamlit chat** renders messages directly on the main page (no fixed-height container)
  so the page scrolls naturally. Auto-scroll JS injected via `components.html(height=0)`.

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

---

## Skills (slash commands)

| Command | What it does |
|---------|-------------|
| `/run` | Start the Streamlit app |
| `/logs` | Tail the SwiftSage log file live |
| `/test` | Run the pytest test suite |
| `/analyse` | Run Transform Advisor on the sample XML and print a summary |
