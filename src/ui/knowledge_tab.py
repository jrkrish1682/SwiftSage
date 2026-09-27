"""
The SME Knowledge tab — the institution's own knowledge, and what it is for.

One tab with sub-modes rather than a tab each, because they are all views of the
same graph: Knowledge browses it, RCA consumes it, and later modes (stories,
tests, mapping review) generate from it. A BA should never have to work out
which of five tabs holds the rule they just read.

Kept out of `app.py` deliberately: this is the largest single surface in the app
and the rest of the file is already long. Rendering is pure Streamlit against
`KnowledgeStore` and `rca` — no model call, so every mode below works with no
API key applied.
"""
from __future__ import annotations

from typing import Optional

import streamlit as st

from src.knowledge import graph as kgraph
from src.knowledge import rca
from src.knowledge import store as ks
from src.observability import run_log
from src.ui.theme import hero, section

MODES = ("Knowledge", "Stories", "Tests", "Review", "RCA")

_STATUS_BADGE = {
    ks.SEEDED: "🔵 seeded (mocked policy)",
    ks.CONFIRMED: "🟢 confirmed",
    ks.CANDIDATE: "🟡 candidate — unconfirmed",
    ks.RETIRED: "⚪ retired",
}

_SEVERITY_ICON = {"HIGH": "🔴", "MEDIUM": "🟠", "LOW": "🟡"}


@st.cache_resource(show_spinner=False)
def _store() -> ks.KnowledgeStore:
    """One store per app process; SQLite handles the concurrency we have."""
    return ks.KnowledgeStore.open()


def counts_snapshot() -> dict[str, int]:
    """Flat counters for the Observability growth panel."""
    counts = _store().counts()
    by_kind = counts["by_kind"]
    return {
        "nodes": counts["nodes"],
        "edges": counts["edges"],
        "rules": by_kind.get(ks.RULE, 0),
        "defects": by_kind.get(ks.DEFECT, 0),
        "candidates": counts["candidates"],
        "confirmed": counts["confirmed"],
    }


def render() -> None:
    """Draw the whole tab."""
    store = _store()
    counts = store.counts()

    hero(
        "SwiftSage as your organisation's SME",
        "The standard says what ISO 20022 permits. This holds what your "
        "institution decided — the rules, mappings and failures that normally "
        "live in one specialist's head — and uses them to explain, generate and "
        "diagnose.",
        [
            f"{counts['nodes']} facts",
            f"{counts['edges']} relationships",
            f"{counts['candidates']} awaiting review",
            "No API key needed",
        ],
    )

    st.info(
        "The rules shipped here are **mocked demo policy for a fictional bank "
        "(Meridian Bank)** — they are not published ISO 20022 requirements and "
        "not any real institution's standards. Everything SwiftSage infers by "
        "itself stays a *candidate* until a specialist confirms it.",
        icon="🧠",
    )

    mode = st.radio(
        "Mode",
        MODES,
        horizontal=True,
        label_visibility="collapsed",
        key="knowledge_mode",
    )

    if mode == "Knowledge":
        _knowledge_mode(store, counts)
    elif mode == "RCA":
        _rca_mode(store)
    else:
        st.info(
            f"**{mode}** is the next increment on this store — "
            "the Knowledge and RCA modes are live now.",
            icon="🚧",
        )


# ── Knowledge mode ────────────────────────────────────────────────────────────

def _knowledge_mode(store: ks.KnowledgeStore, counts: dict) -> None:
    section(
        "What SwiftSage knows",
        "Search the graph, open a rule to see the ISO elements it governs, the "
        "systems that own it and the incidents it caused.",
    )

    metric_cols = st.columns(4)
    by_kind = counts["by_kind"]
    metric_cols[0].metric("Business rules", by_kind.get(ks.RULE, 0))
    metric_cols[1].metric("ISO elements linked", by_kind.get(ks.ISO_ELEMENT, 0))
    metric_cols[2].metric("Past incidents", by_kind.get(ks.DEFECT, 0))
    metric_cols[3].metric("Awaiting review", counts["candidates"])

    domain_bits = " · ".join(
        f"**{domain}** {count}" for domain, count in sorted(counts["by_domain"].items())
    )
    if domain_bits:
        st.caption("Coverage by domain: " + domain_bits)

    filter_cols = st.columns([2, 1, 1])
    query = filter_cols[0].text_input(
        "Search",
        placeholder="IBAN, closing balance, expiry extension, BR-004…",
        key="knowledge_query",
    )
    domain = filter_cols[1].selectbox(
        "Domain", ("All", *ks.DOMAINS), key="knowledge_domain"
    )
    include_candidates = filter_cols[2].toggle(
        "Include candidates",
        value=False,
        key="knowledge_include_candidates",
        help="Unconfirmed knowledge SwiftSage inferred but no specialist has "
             "approved. Off by default so the list reads as policy.",
    )

    statuses = (
        (ks.SEEDED, ks.CONFIRMED, ks.CANDIDATE)
        if include_candidates
        else ks.AUTHORITATIVE
    )
    selected_domain = "" if domain == "All" else domain

    if query.strip():
        rules = store.search_rules(
            query, domain=selected_domain, statuses=statuses, limit=25
        )
    else:
        rules = store.rules(domain=selected_domain, statuses=statuses)

    if not rules:
        st.warning(
            "Nothing matches. Broaden the search, or switch on candidates to "
            "see unconfirmed knowledge."
        )
        return

    st.caption(f"{len(rules)} rule(s)")
    for rule in rules:
        _rule_card(store, rule)

    other = [
        node
        for node in store.nodes(kind=ks.DEFECT, statuses=statuses)
        if not selected_domain or node.domain == selected_domain
    ]
    if other:
        with st.expander(f"📓 Incident history ({len(other)})"):
            for node in other:
                caused = [e.dst for e in store.edges(node.id, relation=ks.CAUSED)]
                st.markdown(
                    f"**{node.id} — {node.name}**  \n"
                    f"{_STATUS_BADGE.get(node.status, node.status)} · "
                    f"{node.domain} · {node.detail.get('message_type', '—')}  \n"
                    f"{node.summary}"
                    + (f"  \nAttributed to: {', '.join(caused)}" if caused else "")
                )
                st.divider()

    with st.expander("⚙️ Reset the knowledge graph"):
        st.caption(
            "Drops everything, including anything confirmed this session, and "
            "re-seeds the mocked rules. Useful before a rehearsed demo."
        )
        if st.button("Reset to seeded state", key="knowledge_reset"):
            store.reset()
            run_log.record(
                run_log.KNOWLEDGE, "reset", nodes=store.counts()["nodes"]
            )
            st.cache_resource.clear()
            st.rerun()


def _rule_card(store: ks.KnowledgeStore, rule: ks.Rule) -> None:
    icon = _SEVERITY_ICON.get(rule.severity, "⚪")
    with st.container(border=True):
        st.markdown(f"#### {icon} {rule.id} — {rule.name}")
        st.caption(
            f"{rule.domain} · severity {rule.severity} · "
            f"{_STATUS_BADGE.get(rule.node.status, rule.node.status)} · "
            f"confidence {rule.node.confidence}%"
        )
        st.markdown(f"**When** {rule.condition}")
        st.markdown(f"**Then** {rule.action}")

        if rule.message_types:
            st.markdown("**Applies to** " + ", ".join(f"`{m}`" for m in rule.message_types))

        elements = [
            store.node(edge.dst)
            for edge in store.edges(rule.id, relation=ks.GOVERNS)
        ]
        linked = sorted({n.name for n in elements if n is not None})
        if linked:
            st.markdown(
                "**Governs ISO elements** " + ", ".join(f"`{n}`" for n in linked)
            )
        unresolved = rule.node.detail.get("unresolved_elements") or []
        if unresolved:
            st.caption(
                "Not linked to a schema — no XSD is vendored for "
                f"{', '.join(rule.message_types) or 'this message set'}: "
                + ", ".join(f"`{e}`" for e in unresolved)
            )

        with st.expander("Evidence, systems and neighbourhood"):
            evidence = store.evidence(rule.id)
            if evidence:
                st.markdown("**Evidence**")
                for citation, run_id in evidence:
                    st.markdown(f"- {citation}" + (f" _(run {run_id})_" if run_id else ""))
            systems = [
                store.node(edge.dst)
                for edge in store.edges(rule.id, relation=ks.OWNED_BY)
            ]
            owners = [n.name for n in systems if n is not None]
            if owners:
                st.markdown("**Owned by** " + ", ".join(owners))

            neighbourhood = store.neighbourhood(rule.id, hops=1)
            if neighbourhood is not None and neighbourhood.edges:
                st.graphviz_chart(kgraph.to_dot(neighbourhood), use_container_width=True)


# ── RCA mode ──────────────────────────────────────────────────────────────────

def _rca_mode(store: ks.KnowledgeStore) -> None:
    section(
        "Why did this fail in production?",
        "Paste the reject reason, and the payload if you have it. SwiftSage "
        "ranks probable causes against the bank's own rules, its incident "
        "history and the vendored schemas — no model call, so every cause "
        "shows the evidence it came from.",
    )

    with st.form("rca_form"):
        symptom = st.text_area(
            "Reject reason / error text",
            placeholder="Rejected by beneficiary bank: invalid account "
                        "identifier — IBAN missing for cross-border payment",
            height=90,
            key="rca_symptom",
        )
        col_type, col_upload = st.columns([1, 2])
        message_type = col_type.text_input(
            "Message version (optional)",
            placeholder="pacs.008.001.10",
            key="rca_message_type",
            help="Detected from the payload namespace when one is supplied.",
        )
        upload = col_upload.file_uploader(
            "Failing message (optional XML)", type=["xml"], key="rca_upload"
        )
        payload = st.text_area(
            "…or paste the payload",
            height=120,
            key="rca_payload",
            placeholder="<Document xmlns=\"urn:iso:std:iso:20022:tech:xsd:pacs.008.001.10\">…",
        )
        submitted = st.form_submit_button("🔎 Analyse", type="primary")

    if submitted:
        text = payload
        if upload is not None:
            text = upload.getvalue().decode("utf-8", errors="replace")
        if not symptom.strip() and not text.strip():
            st.error("Give at least a reject reason or a payload.")
        else:
            with st.spinner("Checking rules, incidents and schemas…"), \
                    run_log.track(
                        run_log.RCA, message_type or "unidentified"
                    ) as detail:
                report = rca.analyse(
                    store,
                    payload=text,
                    symptom=symptom,
                    message_type=message_type,
                )
                detail.update(
                    findings=len(report.findings),
                    top_score=report.top.score if report.top else 0,
                    missing_mandatory=len(report.missing_mandatory),
                    message_type=report.message_type,
                    domain=report.domain,
                )
            st.session_state.rca_report = report

    report: Optional[rca.RcaReport] = st.session_state.get("rca_report")
    if report is None:
        st.caption(
            "No analysis yet. The seeded incidents make three symptoms "
            "explainable out of the box: a non-IBAN account identifier on a "
            "cross-border payment, a statement that does not reconcile, and a "
            "guarantee amendment with no original undertaking reference."
        )
        return

    _rca_results(store, report)


def _rca_results(store: ks.KnowledgeStore, report: rca.RcaReport) -> None:
    cols = st.columns(4)
    cols[0].metric("Probable causes", len(report.findings))
    cols[1].metric("Message version", report.message_type or "—")
    cols[2].metric("Domain", report.domain or "—")
    cols[3].metric("Payload elements", report.elements_present)

    if report.checks:
        st.caption("Checked: " + ", ".join(report.checks))
    for note in report.notes:
        st.caption(f"ℹ️ {note}")

    if not report.findings:
        st.warning(
            "No cause could be derived from the schema or the knowledge graph. "
            "Nothing is guessed — add the rule in Knowledge mode once the cause "
            "is understood, and the next occurrence will be explained."
        )
        return

    st.download_button(
        "⬇️ Download analysis (Markdown)",
        report.as_markdown(),
        file_name="swiftsage_rca.md",
        mime="text/markdown",
    )

    for finding in report.findings:
        badge = {"HIGH": "🔴", "MEDIUM": "🟠", "LOW": "🟡"}[finding.likelihood]
        with st.container(border=True):
            st.markdown(f"#### {badge} {finding.title}")
            st.caption(
                f"{finding.category} · likelihood **{finding.likelihood}** "
                f"(score {finding.score}) · {finding.id}"
            )
            st.markdown(finding.explanation)
            if finding.citations:
                with st.expander("Evidence"):
                    for citation in finding.citations:
                        st.markdown(f"- {citation}")
            if finding.rule_ids:
                _confirm_cause(store, report, finding)

    st.caption(
        "These are **probable** causes ranked by evidence, not a confirmed "
        "diagnosis. Confirming one writes the incident back into the graph so "
        "the same symptom is explained faster next time."
    )


def _confirm_cause(
    store: ks.KnowledgeStore, report: rca.RcaReport, finding: rca.Finding
) -> None:
    with st.expander("✅ This was the cause — record it"):
        st.caption(
            "Records a confirmed incident linked to "
            + ", ".join(finding.rule_ids)
            + ". Only a human can do this: SwiftSage never promotes its own "
              "ranking to a confirmed cause."
        )
        title = st.text_input(
            "Incident title", value=finding.title, key=f"rca_title_{finding.id}"
        )
        note = st.text_area(
            "What actually happened",
            key=f"rca_note_{finding.id}",
            placeholder="Channel sent sort code and account number in Othr/Id; "
                        "IBAN derivation was not enabled for the Spain corridor.",
            height=80,
        )
        if st.button("Record confirmed cause", key=f"rca_confirm_{finding.id}"):
            defect_id = rca.record_cause(
                store, report, finding, title=title, note=note
            )
            run_log.record(
                run_log.KNOWLEDGE,
                "confirm_cause",
                defect=defect_id,
                rules=len(finding.rule_ids),
            )
            st.success(
                f"Recorded as **{defect_id}**, linked to "
                f"{', '.join(finding.rule_ids)}. It now appears in Knowledge "
                "mode and will rank against future symptoms."
            )
