# SwiftSage — vision: an AI SME that grows inside the institution

What SwiftSage is for beyond the migration project that justified building it, what it is
able to do today, and what each remaining step adds. Read [`../README.md`](../README.md)
for installation and usage, [`DESIGN.md`](DESIGN.md) for the architecture as built, and
[`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) for a guided walkthrough.

---

## 1. The idea

ISO 20022 knowledge is published. It sits in XSDs, message usage guides and code lists,
and anyone can read it — SwiftSage already answers from a vendored copy of it and cites
the version and path it read.

The knowledge that actually decides whether a payment clears is **not** published. It is
the institution's own:

- *we derive the IBAN from sort code and account number for cross-border traffic, because
  the beneficiary bank rejects `Othr/Id`*
- *remittance information is truncated at 140 characters rather than split across
  occurrences, because the downstream reconciliation engine reads only the first*
- *a guarantee amendment without the original undertaking reference goes to manual
  checking*
- *last quarter's statement quarantines were all the same closing-balance mismatch*

That body of facts lives in a few specialists' heads, in Confluence pages nobody
maintains, in spreadsheet mapping tabs and in the reasoning attached to closed defect
tickets. It is rediscovered, at cost, on every programme.

**The vision: SwiftSage captures that business logic and tribal SME knowledge as it is
used, holds it as structured, cited, human-confirmed knowledge, and becomes progressively
more useful as an in-house subject-matter expert — one that does not leave, does not
queue and can show its working.**

The published standard tells you what `ChrgBr` is. The institution's knowledge tells you
what *your* bank puts in it, for which corridor, and what broke the last time somebody
got it wrong. SwiftSage is designed to hold both, and to keep them visibly separate.

---

## 2. Why this is worth doing — the five uses

The single knowledge base is the asset; these are the five ways it pays back. Each one is
the *same* rules, mappings, systems and incidents read by a different consumer.

| # | Use | What it means in practice | Status |
|---|---|---|---|
| 1 | **An SME inside the organisation** | Ask why a field is populated the way it is and get the institution's own rule, the ISO element it governs, the system that owns it and the incidents it caused — with the evidence behind it, not a fluent guess | **Live** — SME Knowledge tab, and the chat agent can look internal rules up |
| 2 | **Requirements and stories with the BA/PO** | Turn a confirmed rule and its mapping into a user story with Given/When/Then acceptance criteria that cite the rule ID, so the story arrives at refinement already grounded | Next — *Stories* mode |
| 3 | **An expert test agent for UAT and regression** | Generate UAT and regression packs from the rules: positive, negative and boundary cases per rule, expected outcome each, so a regression pack exists for logic that previously had none | Next — *Tests* mode |
| 4 | **A code reviewer for transformation and mapping logic** | Check a proposed mapping, spec or transformation against confirmed mappings, mandatory target fields and contradicting rules, and return severity-rated findings with citations — the review a specialist would have done | Next — *Review* mode |
| 5 | **RCA of production defects** | Take a production reject reason and the failing payload and rank probable causes from the institution's rules, its incident history and the schemas — and get better at it every time a cause is confirmed | **Live** — *RCA* mode |

Use 5 is the one that compounds. Every confirmed root cause is written back into the
graph, so the next occurrence of that symptom is explained from precedent rather than
from first principles. The knowledge base is not a deliverable the programme produces; it
is a by-product of the work the team was doing anyway.

---

## 3. How knowledge gets in, and why it can be trusted

```
    the work the team already does                    what it deposits
    ────────────────────────────────                  ─────────────────
    Transform Advisor mapping run      ─────►   internal field → ISO element mappings,
                                                derivation logic, deferred decisions
    XML Diff / impact assessment       ─────►   which elements this institution cares
                                                about, which versions are in play
    Grounded chat Q&A                  ─────►   the questions being asked, the rules
                                                quoted back in the answers
    RCA on a production defect         ─────►   a confirmed incident linked to the rule
                                                it breached
    "Teach SwiftSage" (a specialist)   ─────►   a rule stated outright, in one place,
                                                once
                                    │
                                    ▼
                    SQLite knowledge graph (data/knowledge/knowledge.db)
            rules · ISO elements · internal fields · systems · incidents · tests
              typed edges: governs · maps_to · caused · owned_by · contradicts
                     every node carrying evidence and the run behind it
```

Two rules make the store worth reading rather than merely large:

**Candidate versus confirmed.** Anything SwiftSage infers itself lands as a *candidate*
and is rendered as unconfirmed everywhere it appears. Retrieval defaults to the
authoritative set (seeded or human-confirmed), so an inference cannot leak into a prompt,
a story, a test pack or an RCA finding as if it were policy. Only a human promotes a
candidate. If the model could confirm its own guesses, the store would drift and its
provenance would be worth nothing — and an SME whose answers cannot be traced is not an
SME.

**Institutional policy is never dressed up as the standard.** Internal rules and the
vendored ISO 20022 schemas are separate layers, separately cited, and the agent is
required to say which it is speaking from. A bank's convention presented as an ISO
requirement is a worse error than no answer.

The twelve rules and three incidents that ship seeded (three rules each for Payments,
Cash, Trade and Securities/Settlement) are **mocked policy for a fictional bank**, there
so the tab is useful on first run. They say so in their own evidence.

---

## 4. What it looks like as it matures

| | Month 1 | After a programme or two |
|---|---|---|
| **Content** | 12 seeded demo rules, 3 incidents | Hundreds of confirmed rules, the mappings actually built, every production incident and the rule it breached |
| **Asked** | "What does this rule say?" | "Which rules does this change put at risk, and which regression tests cover them?" |
| **RCA** | Ranks against rules and schemas | Ranks against precedent: this symptom, this corridor, this system, three times before |
| **Stories and tests** | Drafted from a rule | Drafted from a rule *and* the defects that rule has already caused |
| **Review** | Mandatory fields and contradictions | Compared against the mappings this institution has approved before |
| **Specialist's role** | Authors everything | Confirms, arbitrates contradictions, governs — the scarce input is spent on judgement, not transcription |

The specialist is not being replaced; their reach is. They stop re-deriving the same
answer for the fourth programme, and the answer stops leaving when they do.

---

## 5. What is deliberately not the plan

- **No autonomous promotion.** SwiftSage never decides its own inference is policy.
- **No replacement of ISO 20022 specialists.** Governance, edge cases and contradictions
  are theirs.
- **No external knowledge service.** The graph is a local SQLite file; the run log is a
  local JSONL file. The demo works with no network and no second key.
- **No ingestion of real bank artefacts in this POC.** The seeded rules are mocked.
- **No production JIRA or test-management integration yet.** Stories and test packs export
  as Markdown and CSV; wiring them into a tracker is a later step, not a missing one.

---

## 6. Where to read more

| Document | What it covers |
|---|---|
| [`../README.md`](../README.md) | What the product does today, how to run it, task-by-task usage |
| [`DESIGN.md`](DESIGN.md) §6b | The knowledge graph and RCA as built — schema, invariants, evidence sources |
| [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) | The built-in scenarios and what their output means |
| [`../approach.md`](../approach.md) | The original problem statement, personas and POC scope |
