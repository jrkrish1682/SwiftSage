# SwiftSage — demo script

A 12-minute demo for Business Analysts, Product Owners and programme leads on a
SWIFT / ISO 20022 migration. The four scenarios are pre-loaded in the app's
**🎬 Demo** tab: press the button on the card, then switch to the tab it names.

Everything in scenarios 1 and 2 runs from the vendored XSDs — no network, no
API key. Scenarios 3 and 4 call Claude and need a key applied in the sidebar.

---

## Before you start (2 minutes)

| Step | Why |
|------|-----|
| `streamlit run app.py` from `SwiftSage-main/` | Opens on http://localhost:8501 |
| Paste your Anthropic key in the sidebar and press **Apply key** | Only scenarios 3 and 4 need it; it is never written to disk |
| **📈 Observability → 🗑️ Clear run log** | The numbers you quote at the end are then this demo's, not yesterday's |
| Check **📚 Library** shows 9 artefacts | Proves the offline schema bundle is loaded |

If the venue has no internet: skip the key, run scenarios 1 and 2, and say so
— "this half of the product is deterministic and needs nothing but the
schemas" is a strength, not an apology.

---

## The problem, in their words (1 minute)

> Regulators are forcing ISO 20022 adoption. The blocker is not technology — it
> is that the people who understand both the bank's internal formats and the
> standard are a handful of specialists whose time is rationed across every
> programme. So mapping specs sit in spreadsheets, requirements quality varies
> by author, and every schema version bump restarts the analysis.

SwiftSage does not replace those specialists. It does the repeatable analysis
so they review a draft instead of authoring one.

---

## Scenario 1 — "Our counterparty is upgrading pain.001. What breaks?" (3 min)

**Run:** Demo tab → scenario 1 → open **🔍 XML Diff**.

Narration:

1. Today this is two schema exports, a spreadsheet diff, and a booked hour with
   an ISO 20022 specialist to interpret it.
2. SwiftSage compares the messages semantically and resolves every change back
   to its real element name — production ISO files are namespaced, and a naive
   diff reports `/*/*[2]/*[4]`, which no business rule can classify.
3. Grading is schema-aware: a field that became **mandatory** in the new
   version is BREAKING; a new optional field is not.

Expected on screen: **pain.001.001.09 → pain.001.001.12** detected as a version
upgrade (so the namespace change is reported once, not on every element),
**8 differences, 1 breaking, score 21.2/100, LOW-MEDIUM risk**.

Then do the two things that earn trust:

- Open **🧮 How the score was calculated** — the score is per-rule arithmetic,
  not a model's opinion.
- Download **📥 Impact Assessment (.docx)** — the deliverable that used to be a
  day of writing.

---

## Scenario 2 — "A guarantee was amended. Is it material?" (2 min)

**Run:** Demo tab → scenario 2 → **🔍 XML Diff**.

This is the breadth question every bank asks after the payments demo. Same
engine, trade finance: `tsrv.001.001.01` is the MX equivalent of MT 760.

Expected: **6 differences, 5 breaking, score 85/100, HIGH risk** — driven by
undertaking amount and expiry, not by diff volume. Point out that the
explanations use trade vocabulary: the classifier is not payments-only.

Contrast with scenario 1 deliberately: 8 differences scored 21, 6 differences
scored 85. The score reflects consequence, not change count.

---

## Scenario 3 — "Turn our internal format into build-ready requirements" (3 min)

**Run:** Demo tab → scenario 3 → **🔄 Transform Advisor** → **🔍 Analyse & Map**.
Needs a key; takes a minute or two.

This is the weeks-to-minutes claim. While it runs, explain what it is doing:
parse the proprietary message, map each field to ISO 20022, check every
proposed path against the target XSD, and identify the gaps.

When it lands, point at four things:

1. **Mapping types** — DIRECT / DERIVED / SPLIT / COMBINED / UNMAPPED. DERIVED
   is where the real work is: a UK sort code and account number become an IBAN.
2. **Schema-check cards** — every proposed ISO path is resolved against the
   vendored XSD. An unconfirmed path is downgraded, never shown as HIGH
   confidence. This is the answer to "how do I know it didn't invent a path?"
3. **Gap register** — mandatory target fields with no source become BLOCKING
   gaps with a recommended resolution. That register is the agenda for the next
   business workshop.
4. **The Word document** — traceability IDs (TR-nn, GAP-nn, AS-nn, OQ-nn), an
   assumptions section, and a provenance record: model, input hash, schema,
   field count, timestamp. Reviewable, not a black box.

Say the limit out loud before anyone finds it: a run maps at most 20 source
fields to stay inside a token budget. The deferred fields are listed in the UI
and carried as an assumption in the document — never silently dropped.

---

## Scenario 4 — "Answer a field question without booking an SME" (2 min)

**Run:** Demo tab → scenario 4 → **💬 Chat**. The question is submitted for
you — the answer is already streaming when you arrive, nothing sits in the
input box:

> Is the charge bearer mandatory in pain.001.001.09, and what do the codes mean
> for our customers?

Point at the tool call appearing inline *before* the answer, and at the
citation: message version plus the schema file it read. Structure comes from
the XSD; business meaning from a curated glossary. An element with no glossary
entry is rendered as structure only — the agent will not dress up a guess as a
definition.

Optional: switch the domain pack to **Trade** or **Settlement** to show the
same grounding across domains.

---

## Close on the numbers (1 minute)

Open **📈 Observability**. Everything you just ran is timed in a local JSONL
log — no external service, works offline.

- **Latency by activity** — what each deliverable actually cost in seconds.
- **Effort vs the manual baseline** — measured time against a stated estimate
  of the same deliverable by hand (40 h for a requirements document, 8 h for an
  impact assessment, 30 min for a specialist field answer). Open the
  assumptions expander and say the estimates out loud; they are overridable per
  demo via `SWIFTSAGE_BASELINE_*_HOURS`.
- **Grounded chat turns** — the share of answers that consulted the schemas
  rather than model recall.

Land it as: *the minutes are measured, the weeks are an estimate you can argue
with, and the ratio is the business case.*

---

## Objection handling

| Objection | Answer |
|-----------|--------|
| "Did it invent that ISO path?" | Every path is resolved against the vendored XSD and labelled RESOLVED / PARTIAL / UNRESOLVED; unconfirmed paths are downgraded. Show the schema-check cards. |
| "Where does the business meaning come from?" | A curated glossary, cited per element. The ISO XSDs carry no documentation, so an element with no glossary entry shows structure only. |
| "Is this auditable?" | Each document carries a provenance record and traceability IDs, and every run is logged locally. Formal audit controls are out of scope for the prototype. |
| "Only 20 fields?" | A deliberate token-budget cap with business-relevance ranking; deferred fields are disclosed in the UI and the document. Removing it is a configuration change. |
| "Does it work for our domain?" | Payments (pain / pacs / camt) and trade finance (tsrv / tsmt) are demonstrated from nine vendored schema versions. Adding a family is vendoring its XSD plus a mandatory-field register. |
| "What about MT?" | Out of scope for the MVP — ISO 20022 MX only. MT → MX advisory is a phase 2 opportunity. |

---

## If something goes wrong

| Symptom | Recovery |
|---------|----------|
| Chat or Advisor errors on the key | Re-paste the key and press **Apply key** — it only takes effect on submit. Other tabs keep working. |
| Schema sync reports a GitHub error | Expected without internet or when rate-limited; it falls back to the vendored bundle. Show **📚 Library** still listing 9 artefacts. |
| A scenario card shows a missing asset | The demo file was moved; run `pytest tests/test_demo_assets.py` to see which one. |
| Mapping run feels slow | Say what it is doing (parse → map → validate → gap analysis) and move to the Observability tab afterwards to show the measured duration. |
