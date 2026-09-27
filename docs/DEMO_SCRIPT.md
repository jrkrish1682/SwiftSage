# SwiftSage — guided walkthrough

A self-contained tour of what SwiftSage does, in the order the **🎬 Demo** tab
presents it. Each section states what the scenario runs, what appears on screen,
and what that output means. Nothing here needs a presenter — run the scenario
and read along.

Scenarios 1 and 2 run entirely from the vendored XSDs: no network, no API key.
Scenarios 3 and 4 call Claude and need a key applied in the sidebar.

---

## Setup

| Step | Effect |
|------|--------|
| `streamlit run app.py` from `SwiftSage-main/` | App opens on http://localhost:8501 |
| Paste an Anthropic key in the sidebar, press **Apply key** | Enables scenarios 3 and 4; the key is held in session memory only, never written to disk |
| **📈 Observability → 🗑️ Clear run log** | Later figures then cover this walkthrough only |
| **📚 Library** lists 9 artefacts | Confirms the offline schema bundle loaded |

Without internet, scenarios 1 and 2 still run to completion — that half of the
product is deterministic and depends only on the vendored schemas.

---

## The problem being solved

ISO 20022 adoption is mandated, but the constraint is knowledge, not
technology: the people who understand both a bank's internal formats and the
standard are a small group whose time is shared across every programme. So
mapping specifications live in spreadsheets, requirements quality varies by
author, and each schema version bump restarts the analysis.

SwiftSage performs the repeatable part of that analysis, so a specialist
reviews a draft rather than authoring one — and keeps what the specialist
confirms, so the institution stops re-deriving it (§ *the knowledge that
outlasts the programme*, below).

---

## Scenario 1 — a counterparty upgrades pain.001: what breaks?

**Run:** Demo tab → scenario 1 → open **🔍 XML Diff**.

Manually, this is two schema exports, a spreadsheet diff, and a specialist
session to interpret the result.

What the tool does:

1. Compares the two messages semantically and resolves every change back to its
   real element name. Production ISO files are namespaced, so a naive diff
   reports positional paths such as `/*/*[2]/*[4]`, which no business rule can
   classify.
2. Grades each change against the XSD: a field that became **mandatory** in the
   new version is BREAKING; a newly added optional field is not.

Result on screen: **pain.001.001.09 → pain.001.001.12** is recognised as a
version upgrade (so the namespace change is reported once rather than on every
element), giving **8 differences, 1 breaking, score 21.2/100, LOW-MEDIUM risk**.

Two outputs show how that conclusion was reached:

- **🧮 How the score was calculated** — per-rule arithmetic, not a model's
  opinion.
- **📥 Impact Assessment (.docx)** — the business-readable deliverable that
  would otherwise be written by hand.

---

## Scenario 2 — a guarantee was amended: is the change material?

**Run:** Demo tab → scenario 2 → **🔍 XML Diff**.

The same engine applied to trade finance: `tsrv.001.001.01` is the MX
equivalent of MT 760.

Result: **6 differences, 5 breaking, score 85/100, HIGH risk** — driven by the
undertaking amount and expiry rather than by the number of changes. The
explanations use trade vocabulary, so the classifier is not payments-only.

Read against scenario 1, the contrast is the point: 8 differences scored 21,
6 differences scored 85. The score reflects consequence, not change count.

---

## Scenario 3 — internal format to build-ready requirements

**Run:** Demo tab → scenario 3 → **🔄 Transform Advisor** → **🔍 Analyse & Map**.
Needs a key; takes a minute or two.

This is the weeks-to-minutes capability. The run parses the proprietary
message, maps each field to ISO 20022, checks every proposed path against the
target XSD, and identifies the gaps.

The output has four parts:

1. **Mapping types** — DIRECT / DERIVED / SPLIT / COMBINED / UNMAPPED. DERIVED
   is where the real work sits: a UK sort code and account number become an
   IBAN.
2. **Schema-check cards** — every proposed ISO path is resolved against the
   vendored XSD. An unconfirmed path is downgraded rather than presented as
   HIGH confidence, which answers "how do I know it didn't invent a path?".
3. **Gap register** — mandatory target fields with no source become BLOCKING
   gaps with a recommended resolution. The register is the agenda for the next
   business workshop.
4. **The Word document** — traceability IDs (TR-nn, GAP-nn, AS-nn, OQ-nn), an
   assumptions section, and a provenance record: model, input hash, schema,
   field count, timestamp.

Known limit: a run maps at most 20 source fields to stay inside a token budget.
Deferred fields are listed in the UI and carried as an assumption in the
document — never silently dropped.

---

## Scenario 4 — a field question answered without booking an SME

**Run:** Demo tab → scenario 4 → **💬 Chat**. The question is submitted
automatically, so the answer is already streaming on arrival:

> Is the charge bearer mandatory in pain.001.001.09, and what do the codes mean
> for our customers?

The tool call appears inline *before* the answer, and the answer carries a
citation: the message version plus the schema file it read. Structure comes
from the XSD; business meaning comes from a curated glossary. An element with
no glossary entry is rendered as structure only, so a guess is never presented
as a definition.

Switching the domain pack to **Trade** or **Settlement** shows the same
grounding across domains.

---

## The knowledge that outlasts the programme

The four scenarios all reason about the *published* standard. The **🧠 SME
Knowledge** tab holds the other half: the institution's own rules, the ISO
elements they govern, the systems that own them and the incidents they caused.
It needs no API key. This part has no one-click scenario — walk it as follows.

**What the institution knows** — mode **Knowledge**. Twelve rules ship seeded,
three each for Payments, Cash, Trade and Securities/Settlement, plus three
historical incidents. Open `BR-001` (derive an IBAN from sort code and account
number for cross-border traffic): its condition and action, the real ISO paths
it governs, the systems that own it, its evidence, and a graph of everything
linked to it — including the incident it caused. The seeded rules are **mocked
policy for a fictional bank**, and say so in their own evidence; they are not
published ISO requirements.

**Why a payment failed in production** — mode **RCA**. Paste a reject reason,
e.g. *"Rejected by beneficiary bank: invalid account identifier, IBAN missing
for cross-border payment"*, and optionally the failing XML. **Analyse** ranks
probable causes from four independent sources: internal rules that were not
applied, mandatory elements absent from the payload, matching past incidents,
and elements that exist only in a different version of the message. Each
finding carries its citations and a HIGH / MEDIUM / LOW likelihood rather than
a verdict, and it is deterministic — no model call, so it can be argued with.
A clean payload with a nonsense symptom produces no findings instead of a
plausible guess.

**How it improves** — expand **This was the cause — record it** on the finding
the team agrees with. That writes a *confirmed* incident linked to the rule,
and the graph counts on the tab go up. The same symptom is then explained from
precedent next time. SwiftSage never promotes its own ranking: anything it
infers stays a *candidate* until a human confirms it, and retrieval defaults to
the confirmed set — so a guess cannot reach a prompt or a report as policy.
*Reset the knowledge graph* returns it to the seeded state before a rehearsal.

The modes **Stories**, **Tests** and **Review** are the next increments on this
same graph — stories and acceptance criteria for the BA/PO, UAT and regression
packs, and review of a proposed transformation. They currently render as
pending. [`VISION.md`](VISION.md) explains why those five uses are one
knowledge base read five ways.

---

## The measured numbers

**📈 Observability** times everything that was just run, in a local JSONL log —
no external service, works offline.

- **Latency by activity** — what each deliverable cost in seconds.
- **Effort vs the manual baseline** — measured time against a stated estimate
  for the same deliverable by hand (40 h for a requirements document, 8 h for
  an impact assessment, 30 min for a specialist field answer). The assumptions
  expander shows those estimates; they are overridable via
  `SWIFTSAGE_BASELINE_*_HOURS`.
- **Grounded chat turns** — the share of answers that consulted the schemas
  instead of relying on model recall.
- **Model token usage** — for the runs that called Claude (Chat, Transform
  Advisor), the tokens the API charged: request tokens, response tokens, the
  size of the cached system prompt, and how much of each request was read from
  the prompt cache instead of being billed again. Scenarios 1 and 2 call no
  model, so they appear in the latency table and not in this one. The first
  model run *writes* the cache, so the hit rate starts at 0% and rises on the
  runs after it.

In short: the minutes are measured, the weeks are an arguable estimate, and the
ratio is the business case.

---

## Common questions

| Question | Answer |
|----------|--------|
| Could it invent an ISO path? | Every path is resolved against the vendored XSD and labelled RESOLVED / PARTIAL / UNRESOLVED; unconfirmed paths are downgraded. The schema-check cards show the result. |
| Where does the business meaning come from? | A curated glossary, cited per element. The ISO XSDs carry no documentation, so an element with no glossary entry shows structure only. |
| Is this auditable? | Each document carries a provenance record and traceability IDs, and every run is logged locally. Formal audit controls are out of scope for the prototype. |
| Why only 20 fields? | A deliberate token-budget cap with business-relevance ranking; deferred fields are disclosed in the UI and the document. Removing it is a configuration change. |
| Does it cover other domains? | Payments (pain / pacs / camt) and trade finance (tsrv / tsmt) are demonstrated from nine vendored schema versions. Adding a family means vendoring its XSD plus a mandatory-field register. |
| What about MT? | Out of scope for the MVP — ISO 20022 MX only. MT → MX advisory is a phase 2 opportunity. |
| Are the business rules real? | No — the twelve seeded rules and three incidents are mocked policy for a fictional bank so the tab is useful on first run, and their evidence says so. A real deployment accumulates its own. |
| Could it quote a rule it invented as policy? | No. Inferred knowledge is stored as a *candidate* and rendered as unconfirmed; retrieval defaults to the seeded-or-confirmed set, and only a human promotes a candidate. |
| Does RCA need a key? | No. It is deterministic over the rules, the incident history and the vendored schemas, so it works offline. |

---

## Troubleshooting

| Symptom | Resolution |
|---------|------------|
| Chat or Advisor errors on the key | Re-paste the key and press **Apply key** — it only takes effect on submit. Other tabs keep working. |
| Schema sync reports a GitHub error | Expected without internet or when rate-limited; it falls back to the vendored bundle, and **📚 Library** still lists 9 artefacts. |
| A scenario card shows a missing asset | The demo file was moved; `pytest tests/test_demo_assets.py` identifies which one. |
| A mapping run feels slow | It is parsing, mapping, validating and running gap analysis; the Observability tab shows the measured duration afterwards. |
| RCA returns no probable causes | Expected when nothing matches — it declines to guess. Add the failing payload, or the message version, so the schema and history checks have something to work with. |
| The knowledge graph carries a previous rehearsal's incidents | **🧠 SME Knowledge → Reset the knowledge graph** returns it to the seeded twelve rules and three incidents. |
