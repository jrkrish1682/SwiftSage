"""
SwiftSage — ISO 20022 Expert Agent for Business Analysts & Product Owners.

Layout
------
  Sidebar  : Configuration, file uploader, quick actions
  Main area: Tabbed interface
    • Demo              — One-click rehearsed scenarios with talking points
    • Chat              — Conversational agent (streaming, BA/PO persona)
    • Transform Advisor — Internal message → ISO 20022 mapping + requirements doc
    • XML Diff          — Direct semantic comparison tool
    • Library           — Browse downloaded schemas
    • Observability     — Local run log: durations, tool calls, effort saved
    • Help              — Quick start guide
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from src.observability import metrics, run_log
from src.ui import demo_scenarios, prompt_packs
from src.ui.theme import hero, inject_css, section, stat_cards
from src.utils.helpers import ISO20022_MESSAGE_SETS, get_logger

log = get_logger(__name__)

# ── Bootstrap environment ──────────────────────────────────────────────────────
load_dotenv(override=False)
if "ANTHROPIC_API_KEY" in os.environ:
    del os.environ["ANTHROPIC_API_KEY"]

# ── Page config (must be first Streamlit call) ─────────────────────────────────
st.set_page_config(
    page_title="SwiftSage — ISO 20022 Expert",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global theme ─────────────────────────────────────────────────────────────
inject_css()

# ── Lazy loaders ───────────────────────────────────────────────────────────────
def _load_agent():
    from src.agent.swift_agent import SWIFTAgent
    return SWIFTAgent()

def _load_comparator():
    from src.comparator.xml_comparator import XMLComparator
    from config.settings import settings
    return XMLComparator(ignore_tags=settings.benign_patterns)

def _load_library():
    from src.storage.standards_library import StandardsLibrary
    from config.settings import settings
    return StandardsLibrary(settings.standards_library_path)


# ── Shared actions ─────────────────────────────────────────────────────────────
def _compare_and_record(xml_a: str, xml_b: str, schema: str | None,
                        ignore_tags: list[str]) -> None:
    """Run one comparison, store it in session state and log the run.

    Shared by the Compare button and the one-click demo scenarios so both
    produce identical results and identical telemetry.
    """
    from src.comparator.xml_comparator import XMLComparator

    cmp = XMLComparator(ignore_tags=ignore_tags)
    with run_log.track(
        run_log.DIFF,
        f"{Path(xml_a).name} → {Path(xml_b).name}",
        schema=Path(schema).stem if schema else "none",
    ) as detail:
        # Kept in session state so the download buttons below — each of which
        # reruns the script — do not wipe the result panel.
        result = cmp.compare(xml_a, xml_b, schema_path=schema)
        st.session_state.diff_result = result
        st.session_state.diff_schema = schema
        detail.update(
            message_type_a=result.message_type_a or "unknown",
            message_type_b=result.message_type_b or "unknown",
            diffs=len(result.diffs),
            breaking=len(result.breaking),
            warnings=len(result.warnings),
            benign=len(result.benign),
            breaking_score=result.breaking_score,
            parse_error=bool(result.parse_error),
        )
        # The comparator returns unreadable XML as a result rather than
        # raising, so grade it here or it counts as a success.
        if result.parse_error:
            detail["status"] = "error"


# ── Session state ──────────────────────────────────────────────────────────────
if "messages"            not in st.session_state: st.session_state.messages = []
if "agent"               not in st.session_state: st.session_state.agent = None
if "uploaded_files"      not in st.session_state: st.session_state.uploaded_files = {}
if "transform_mappings"  not in st.session_state: st.session_state.transform_mappings = None
if "transform_gaps"      not in st.session_state: st.session_state.transform_gaps = None
if "transform_target"    not in st.session_state: st.session_state.transform_target = None
if "transform_doc_bytes" not in st.session_state: st.session_state.transform_doc_bytes = None
if "transform_provenance" not in st.session_state: st.session_state.transform_provenance = None
if "transform_family_note" not in st.session_state: st.session_state.transform_family_note = ""


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        """<div class="ss-brand">
            <div class="ss-logo">⚡</div>
            <div>
                <div class="ss-name">SwiftSage</div>
                <div class="ss-tag">ISO 20022 Expert Agent</div>
            </div>
        </div>""",
        unsafe_allow_html=True,
    )
    st.divider()

    st.subheader("Configuration")
    with st.form("api_key_form", clear_on_submit=False):
        key_input = st.text_input(
            "Anthropic API Key",
            value=st.session_state.get("api_key", ""),
            type="password",
            help="Enter your API key for this session, then press Apply. "
                 "Never stored on disk.",
            placeholder="sk-ant-...",
        )
        applied = st.form_submit_button("Apply key", use_container_width=True)

    if applied:
        if key_input != st.session_state.get("api_key", ""):
            st.session_state.agent = None          # rebuild with the new key
        st.session_state["api_key"] = key_input

    api_key = st.session_state.get("api_key", "")
    if api_key:
        os.environ["ANTHROPIC_API_KEY"] = api_key
        st.caption("✅ Key applied for this session.")
    else:
        os.environ.pop("ANTHROPIC_API_KEY", None)
        st.caption("Key not applied — Chat and Transform Advisor are disabled.")

    model = st.selectbox(
        "Model",
        ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"],
        index=0,
    )
    os.environ["AGENT_MODEL"] = model

    st.divider()

    st.subheader("Upload Files")
    uploaded = st.file_uploader(
        "Upload ISO 20022 XML / XSD files",
        type=["xml", "xsd"],
        accept_multiple_files=True,
        help="Files are saved to a temp directory and referenced by name in chat.",
    )
    if uploaded:
        tmp_dir = Path(tempfile.mkdtemp())
        for f in uploaded:
            dest = tmp_dir / f.name
            dest.write_bytes(f.read())
            st.session_state.uploaded_files[f.name] = str(dest)
        if st.session_state.uploaded_files:
            st.success(f"{len(st.session_state.uploaded_files)} file(s) ready")
            for name in st.session_state.uploaded_files:
                st.caption(f"📄 `{name}`")

    st.divider()

    st.subheader("Quick Actions")
    if st.button("🔄 Sync ISO 20022 Schemas", use_container_width=True):
        st.info("Syncing schemas from ISO 20022 GitHub repo...")
        try:
            from src.connectors.iso20022_connector import ISO20022Connector
            lib = _load_library()
            conn = ISO20022Connector(library=lib)
            result = conn.sync(message_sets=["pain", "pacs", "camt"])
            st.success(
                f"Sync complete from {result.get('source', 'unknown source')}: "
                f"{result.get('artifacts_added', 0)} added, "
                f"{result.get('artifacts_skipped', 0)} skipped"
            )
        except Exception as e:
            st.error(f"Sync failed: {e}")

    if st.button("📚 Show Library Summary", use_container_width=True):
        try:
            lib = _load_library()
            st.info(lib.summary())
        except Exception as e:
            st.error(str(e))

    if st.button("🗑️ Clear Chat History", use_container_width=True):
        st.session_state.messages = []
        if st.session_state.agent:
            st.session_state.agent.clear_history()
        st.rerun()

    st.divider()
    st.caption("📖 [ISO 20022 Definitions](https://www.iso20022.org/iso-20022-message-definitions)")
    st.caption("📖 [SWIFT MyStandards](https://www.swift.com/our-solutions/standards/swift-mystandards)")


# ── Tabs ───────────────────────────────────────────────────────────────────────
(tab_demo, tab_chat, tab_transform, tab_diff, tab_library, tab_obs,
 tab_help) = st.tabs([
    "🎬 Demo",
    "💬 Chat",
    "🔄 Transform Advisor",
    "🔍 XML Diff",
    "📚 Library",
    "📈 Observability",
    "ℹ️ Help",
])


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 0 — Demo
# ═══════════════════════════════════════════════════════════════════════════════
with tab_demo:
    hero(
        "Rehearsed demo scenarios",
        "Four business questions a migration programme actually asks. Each one "
        "loads its own inputs, runs where no credentials are needed, and tells "
        "you what to point at.",
        ["One click", "Payments + Trade", "Offline-safe"],
    )

    st.info(
        "**How to run the demo:** press *Run* or *Load*, then switch to the tab "
        "named on the card. Scenarios 1 and 2 need no API key — they work "
        "entirely from the vendored XSDs, so a failed conference Wi-Fi cannot "
        "stop the demo. Scenarios 3 and 4 call Claude and need a key applied in "
        "the sidebar.",
        icon="🎬",
    )

    for scenario in demo_scenarios.SCENARIOS:
        missing = demo_scenarios.missing_assets(scenario)
        with st.container(border=True):
            st.markdown(f"#### {scenario.title}")
            st.caption(
                f"Opens in **{scenario.tab}** · "
                + ("needs an API key" if scenario.needs_key
                   else "runs offline, no key needed")
            )
            st.markdown(f"> {scenario.question}")

            col_run, col_notes = st.columns([1, 2])
            with col_run:
                label = ("▶️ Run scenario" if scenario.diff is not None
                         else "📋 Load scenario")
                if missing:
                    st.error(
                        "Missing demo asset(s): "
                        + ", ".join(p.name for p in missing)
                    )
                elif st.button(
                    label,
                    key=f"demo_run_{scenario.id}",
                    use_container_width=True,
                    type="primary",
                ):
                    for key, value in scenario.presets.items():
                        st.session_state[key] = value
                    if scenario.diff is not None:
                        from config.settings import settings as _s
                        baseline, revised, schema = scenario.diff.paths()
                        with st.spinner("Comparing..."):
                            _compare_and_record(
                                str(baseline), str(revised), str(schema),
                                list(_s.benign_patterns),
                            )
                    if scenario.chat_prompt:
                        st.session_state._pending_chat = scenario.chat_prompt
                    st.session_state.demo_loaded = scenario.id
                    st.rerun()

                if st.session_state.get("demo_loaded") == scenario.id:
                    st.success(f"Loaded — open the **{scenario.tab}** tab.")

            with col_notes:
                with st.expander("🎙️ Current Use case"):
                    for point in scenario.talking_points:
                        st.markdown(f"- {point}")
                with st.expander("👀 What the tool does"):
                    for point in scenario.watch_for:
                        st.markdown(f"- {point}")
        st.write("")

    st.caption(
        "Timings for everything you run are recorded locally and rolled up in "
        "the **📈 Observability** tab — that is where the weeks-to-minutes "
        "number comes from."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Chat
# ═══════════════════════════════════════════════════════════════════════════════
with tab_chat:
    hero(
        "Your ISO 20022 expert, on call",
        "Ask anything about SWIFT and ISO 20022 in plain English. SwiftSage answers in "
        "business terms and can validate, compare, map, and explain payment messages.",
        ["pain.001", "pacs.008", "camt.053", "tsrv.001", "Claude-powered", "BA / PO ready"],
    )

    if st.session_state.uploaded_files:
        names = ", ".join(f"`{n}`" for n in st.session_state.uploaded_files)
        st.info(f"📂 Uploaded files available: {names}")

    # Demo question chips, grouped by business domain
    section(
        "Start a conversation",
        "Pick a domain for starter questions, or type your own below. Answers about "
        "specific fields are looked up in the vendored schemas and cite the message version.",
    )
    pack = st.radio(
        "Domain",
        prompt_packs.pack_names(),
        horizontal=True,
        label_visibility="collapsed",
        key="chat_prompt_pack",
    )
    demo_questions = prompt_packs.prompts_for(pack)
    for col, q in zip(st.columns(len(demo_questions)), demo_questions):
        if col.button(q, use_container_width=True, key=f"demo_{pack}_{q[:24]}"):
            st.session_state._pending_chat = q

    st.divider()

    # Render all prior messages directly on the page (no fixed-height container)
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Anchor + auto-scroll so new messages are visible above the sticky input
    st.markdown('<div id="swiftsage-bottom"></div>', unsafe_allow_html=True)
    if st.session_state.messages:
        import streamlit.components.v1 as _components
        _components.html(
            "<script>"
            "window.parent.document.querySelector('[data-testid=\"stAppViewBlockContainer\"]')"
            ".scrollTo(0, 999999);"
            "</script>",
            height=0,
        )

    # A demo question stays queued until it actually runs: popping it before the
    # key check would discard the scenario the presenter just loaded, so the
    # question would never appear once they applied a key.
    pending = st.session_state.get("_pending_chat")
    prompt = st.chat_input("Ask about ISO 20022, transformation requirements, or message flows...") or pending

    if prompt and not api_key:
        st.error("Please enter your Anthropic API Key in the sidebar and press Apply.")
        prompt = None
    elif prompt:
        st.session_state.pop("_pending_chat", None)

    if prompt:
        enriched_prompt = prompt
        if st.session_state.uploaded_files:
            file_context = "\n".join(
                f"  - {name}: {path}"
                for name, path in st.session_state.uploaded_files.items()
            )
            enriched_prompt = f"{prompt}\n\n[Available uploaded files]\n{file_context}"

        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            try:
                if st.session_state.agent is None:
                    with st.spinner("Initialising SwiftSage..."):
                        st.session_state.agent = _load_agent()

                response_container = st.empty()
                full_response = []
                for chunk in st.session_state.agent.stream(enriched_prompt):
                    full_response.append(chunk)
                    response_container.markdown("".join(full_response))

                final = "".join(full_response)
                st.session_state.messages.append({"role": "assistant", "content": final})

            except ValueError as e:
                err = f"⚠️ {e}"
                st.warning(err)
                st.session_state.agent = None
                st.session_state.messages.append({"role": "assistant", "content": err})
            except Exception as e:
                err = f"❌ Agent error: {e}"
                st.error(err)
                st.session_state.messages.append({"role": "assistant", "content": err})


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Transform Advisor
# ═══════════════════════════════════════════════════════════════════════════════
with tab_transform:
    hero(
        "Transformation Advisor",
        "Upload your bank's internal payment or trade finance message. SwiftSage maps every field to its "
        "ISO 20022 equivalent, identifies gaps, and generates a Transformation Requirements "
        "Document ready for your development team.",
        ["Field mapping", "Gap register", "Word export"],
    )

    st.info(
        "**How it works:** SwiftSage parses your internal message or field specification "
        "(XML, JSON, CSV or XLSX) → maps each field to ISO 20022 (DIRECT / DERIVED / SPLIT / "
        "UNMAPPED) → checks every proposed path against the target XSD → identifies BLOCKING "
        "and ENRICHMENT gaps → generates a structured requirements document. "
        "This will take few minutes.",
        icon="💡",
    )

    # ── Inputs ─────────────────────────────────────────────────────────────────
    section("1. Choose your source message")
    col_upload, col_target = st.columns([3, 1])
    with col_upload:
        internal_file = st.file_uploader(
            "Upload Internal Bank Message or Field Specification",
            type=["xml", "json", "csv", "xlsx"],
            key="internal_xml_uploader",
            help="Your bank's proprietary message (XML or JSON) or a field "
                 "specification (CSV / XLSX with a field-name column) — "
                 "not an ISO 20022 file.",
        )
    with col_target:
        target_msg = st.selectbox(
            "Target ISO 20022 Message",
            ["pain.001.001.09", "pacs.008.001.10", "camt.053.001.10", "tsrv.001.001.01"],
            key="target_msg_type",
            help="The ISO 20022 message type you are migrating to.",
        )

    SAMPLES = {
        "None — I'll upload my own": None,
        "pain.001 — Meridian Bank payment initiation (XML, 46 fields)": Path("data/samples/internal/sample_bank_payment.xml"),
        "pacs.008 — Meridian Bank FI credit transfer (XML, 3 transactions)": Path("data/samples/internal/sample_bank_fi_transfer.xml"),
        "pacs.008 — Meridian Bank FI transfer field specification (CSV)": Path("data/samples/internal/sample_bank_fi_transfer_spec.csv"),
        "camt.053 — Meridian Bank statement feed (JSON)": Path("data/samples/internal/sample_bank_statement.json"),
        "tsrv.001 — Meridian Bank guarantee application (XML, trade finance)": Path("data/samples/internal/sample_bank_guarantee.xml"),
    }

    _PREVIEW_LANGUAGE = {".xml": "xml", ".json": "json", ".csv": "text"}

    sample_choice = st.selectbox(
        "Or use a built-in sample",
        list(SAMPLES.keys()),
        key="sample_choice",
        help="Select a pre-loaded demo file to try SwiftSage without uploading your own XML.",
    )

    selected_sample_path = SAMPLES[sample_choice]
    if selected_sample_path is not None:
        if selected_sample_path.exists():
            with st.expander("👁️ Preview sample internal message"):
                st.code(
                    selected_sample_path.read_text(encoding="utf-8"),
                    language=_PREVIEW_LANGUAGE.get(selected_sample_path.suffix.lower(), "text"),
                )
        else:
            st.warning(f"Sample file not found: {selected_sample_path}")

    st.divider()

    analysis_input: tuple[bytes, str] | None = None
    if st.button("🔍 Analyse & Map", type="primary", use_container_width=True, key="btn_analyse"):
        if not api_key:
            st.error("Please enter your Anthropic API Key in the sidebar and press Apply.")
        elif selected_sample_path is not None:
            if selected_sample_path.exists():
                analysis_input = (
                    selected_sample_path.read_bytes(), selected_sample_path.name
                )
            else:
                st.error(f"Sample file not found: {selected_sample_path}")
        elif internal_file:
            analysis_input = (internal_file.read(), internal_file.name)
        else:
            st.error("Please upload an internal message or select a sample.")

    if analysis_input is not None:
        source_bytes, source_name = analysis_input
        analysis_ok = False
        run_started = time.perf_counter()
        run_detail: dict = {
            "source_name": source_name,
            "source_format": Path(source_name).suffix.lstrip(".").upper() or "unknown",
            "source_bytes": len(source_bytes),
        }
        run_status = "ok"

        with st.spinner("SwiftSage is analysing your internal message — this take few minutes..."):
            try:
                from src.transformer.message_parser import parse_fields
                from src.transformer.field_mapper import (
                    MAX_MAPPED_FIELDS, FieldMapper, select_fields,
                )
                from src.transformer import gap_analyzer
                from src.transformer.requirements_generator import (
                    Provenance, generate_requirements_doc,
                )
                from src.transformer.source_classifier import (
                    detect_family, mismatch_warning,
                )
                from src.transformer.target_schema import TargetSchema

                fields   = parse_fields(source_bytes, source_name)
                source_family, family_evidence = detect_family(fields)
                family_note = mismatch_warning(
                    source_family, target_msg, family_evidence
                )
                mapper   = FieldMapper()
                selected, deferred = select_fields(fields)
                mappings = mapper.map(selected, target_msg)
                gaps     = gap_analyzer.analyze(mappings, target_msg)

                schema = TargetSchema.for_message_type(target_msg)
                provenance = Provenance(
                    model=os.environ.get("AGENT_MODEL", "claude-sonnet-4-6"),
                    source_name=source_name,
                    source_format=Path(source_name).suffix.lstrip(".").upper() or "unknown",
                    input_hash=Provenance.hash_input(source_bytes),
                    schema_source=(
                        f"vendored XSD, {len(schema)} paths" if schema
                        else "no vendored XSD for this target"
                    ),
                    source_family=source_family or "",
                    gap_table_origin=gaps[0].origin if gaps else "expert",
                    field_count=len(fields),
                    fields_mapped=len(selected),
                )
                doc_bytes = generate_requirements_doc(
                    mappings, gaps, target_msg,
                    source_label=f"Internal message {source_name}",
                    provenance=provenance,
                )

                st.session_state.transform_mappings   = mappings
                st.session_state.transform_gaps       = gaps
                st.session_state.transform_target     = target_msg
                st.session_state.transform_doc_bytes  = doc_bytes
                st.session_state.transform_provenance = provenance
                st.session_state.transform_family_note = family_note
                analysis_ok = True

                from src.transformer import mapping_validator as _validator
                run_detail.update(
                    fields_parsed=len(fields),
                    fields_mapped=len(selected),
                    fields_deferred=len(deferred),
                    source_family=source_family or "unknown",
                    family_mismatch=bool(family_note),
                    gaps_open=len([g for g in gaps if not g.is_resolved]),
                    gaps_blocking=len([
                        g for g in gaps
                        if g.gap_type == "BLOCKING" and not g.is_resolved
                    ]),
                    gap_table_origin=provenance.gap_table_origin,
                    path_checks=_validator.summarise(mappings),
                    doc_bytes=len(doc_bytes or b""),
                    **mapper.last_usage.as_detail(mapper.last_system_prompt),
                )

            except Exception as exc:
                log.exception("Transform Advisor analysis failed")
                st.error(f"Analysis failed: {exc}")
                run_status = "error"
                run_detail["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                run_log.record(
                    run_log.TRANSFORM,
                    target_msg,
                    status=run_status,
                    duration_ms=int((time.perf_counter() - run_started) * 1000),
                    **run_detail,
                )

        if analysis_ok:
            st.success(
                f"Analysis complete — {len(mappings)} fields mapped, "
                f"{len([g for g in gaps if not g.is_resolved])} open gaps identified."
            )
            if deferred:
                st.info(
                    f"To keep the run within budget, only the {MAX_MAPPED_FIELDS} most "
                    f"business-significant fields were sent to the model. "
                    f"{len(deferred)} of {len(fields)} source fields were deferred — "
                    "repeated occurrences of a structure already mapped, and internal "
                    "control fields. Map them in a follow-up run if the demo needs them.",
                    icon="💡",
                )
                with st.expander(f"Fields deferred from this run ({len(deferred)})"):
                    st.code("\n".join(f.xpath for f in deferred), language="text")

    # ── Results ─────────────────────────────────────────────────────────────────
    if st.session_state.transform_mappings is not None:
        import pandas as pd

        from src.transformer import mapping_validator
        from src.transformer.target_schema import RENAMED, RESOLVED, UNRESOLVED

        mappings   = st.session_state.transform_mappings
        gaps       = st.session_state.transform_gaps
        target     = st.session_state.transform_target
        doc_bytes  = st.session_state.transform_doc_bytes
        provenance = st.session_state.transform_provenance

        # Summary metrics
        direct   = sum(1 for m in mappings if m.mapping_type == "DIRECT")
        derived  = sum(1 for m in mappings if m.mapping_type == "DERIVED")
        unmapped = sum(1 for m in mappings if m.mapping_type == "UNMAPPED")
        blocking = sum(1 for g in gaps if g.gap_type == "BLOCKING" and not g.is_resolved)
        enrichmt = sum(1 for g in gaps if g.gap_type == "ENRICHMENT" and not g.is_resolved)
        checks   = mapping_validator.summarise(mappings)

        section("2. Analysis summary", f"Target message: {target}")
        if st.session_state.transform_family_note:
            st.error(
                "**Source and target belong to different message families.** "
                + st.session_state.transform_family_note,
                icon="🚨",
            )
        stat_cards([
            ("Direct",     direct,   "1:1 field matches",        "#10B981"),
            ("Derived",    derived,  "needs computation",        "#F59E0B"),
            ("Unmapped",   unmapped, "no ISO equivalent",        "#94A3B8"),
            ("Blocking",   blocking, "business decision needed", "#EF4444"),
            ("Enrichment", enrichmt, "reference data needed",    "#4F46E5"),
        ])

        st.write("")
        stat_cards([
            ("Schema-confirmed", checks.get(RESOLVED, 0),
             f"paths verified in {target}", "#10B981"),
            ("Path differs", checks.get(RENAMED, 0),
             "element sits elsewhere", "#F59E0B"),
            ("Not in schema", checks.get(UNRESOLVED, 0),
             "downgraded to LOW confidence", "#EF4444"),
        ])
        if checks.get(UNRESOLVED, 0) or checks.get(RENAMED, 0):
            st.warning(
                "Some proposed ISO 20022 paths could not be confirmed against the "
                f"{target} schema. They are flagged in the mapping table and in the "
                "requirements document, and their confidence has been downgraded.",
                icon="⚠️",
            )

        st.write("")

        # Field mapping table
        section("3. Field mapping table", "Colour-coded by mapping type.")

        _MAP_BG = {
            "DIRECT":   "#d4edda",
            "DERIVED":  "#fff3cd",
            "SPLIT":    "#cce5ff",
            "COMBINED": "#e2d9f3",
            "UNMAPPED": "#e2e3e5",
        }

        def _highlight_map(row):
            colour = _MAP_BG.get(row.get("Mapping Type", ""), "")
            return [f"background-color: {colour}"] * len(row)

        map_df = pd.DataFrame([
            {
                "Source Field":      m.source_field,
                "Sample Value":      (m.source_value or "")[:40],
                "Mapping Type":      m.mapping_type,
                "ISO 20022 Target":  m.iso20022_element or m.iso20022_xpath or "—",
                "Confidence":        m.confidence,
                "Schema Check":      m.validation,
                "Business Rule":     " | ".join(
                    p for p in (m.business_rule, m.validation_note) if p
                ),
            }
            for m in mappings
        ])
        st.dataframe(
            map_df.style.apply(_highlight_map, axis=1),
            use_container_width=True,
            height=380,
        )

        st.write("")

        # Gap register
        section("4. Gap register", "Open gaps that must be resolved before go-live.")

        _GAP_BG = {
            "BLOCKING":    "#f8d7da",
            "ENRICHMENT":  "#fff3cd",
            "CONDITIONAL": "#cce5ff",
            "OUT_OF_SCOPE":"#e2e3e5",
        }

        def _highlight_gap(row):
            colour = _GAP_BG.get(row.get("Gap Type", ""), "")
            return [f"background-color: {colour}"] * len(row)

        open_gaps = [g for g in gaps if not g.is_resolved]
        if open_gaps:
            gap_df = pd.DataFrame([
                {
                    "ISO 20022 Field":  g.iso_xpath,
                    "Business Label":   g.business_label,
                    "Gap Type":         g.gap_type,
                    "Severity":         g.severity,
                    "Recommended Resolution": g.recommendation,
                }
                for g in open_gaps
            ])
            st.dataframe(
                gap_df.style.apply(_highlight_gap, axis=1),
                use_container_width=True,
                height=360,
            )
        else:
            st.success("No open gaps — all mandatory fields have a source mapping.")

        st.write("")

        # Download
        section(
            "5. Requirements document",
            "Includes executive summary, full field mapping table with schema "
            "checks, gap register, unmapped fields, assumptions, open questions, "
            "next steps, and a provenance record.",
        )
        if doc_bytes:
            st.download_button(
                label="📥 Download Transformation Requirements Document (.docx)",
                data=doc_bytes,
                file_name=(
                    f"SwiftSage_Transform_Requirements_{target}"
                    + (f"_{Path(provenance.source_name).stem}" if provenance else "")
                    + ".docx"
                ),
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
                type="primary",
            )

        if provenance is not None:
            with st.expander("🧾 Provenance — inputs, schema and model behind this run"):
                st.table(
                    pd.DataFrame(
                        provenance.rows(target), columns=["Item", "Value"]
                    ).set_index("Item")
                )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — XML Diff
# ═══════════════════════════════════════════════════════════════════════════════
with tab_diff:
    hero(
        "XML Semantic Comparator",
        "Compare two ISO 20022 XML versions. Every change is classified as "
        "BREAKING / WARNING / BENIGN / INFO with a 0–100 business impact score.",
        ["Semantic diff", "Impact score", "Word / Markdown assessment"],
    )

    # Demo pairs: payments (pain.001) and trade finance (tsrv undertaking
    # amendment, tsmt baseline-report version upgrade).
    _DIFF_SAMPLES_A = {
        "Payment sample (pain.001.001.09)": "data/samples/pain001_v1.xml",
        "Trade sample (tsrv.001.001.01 guarantee)": "data/samples/trade/tsrv001_guarantee_v1.xml",
        "Trade sample (tsmt.011.001.03 baseline report)": "data/samples/trade/tsmt011_baseline_v3.xml",
    }
    _DIFF_SAMPLES_B = {
        "Payment sample (amended pain.001.001.09)": "data/samples/pain001_v2.xml",
        "Payment sample (upgrade to pain.001.001.12)": "data/samples/pain001_v12_upgrade.xml",
        "Trade sample (amended guarantee)": "data/samples/trade/tsrv001_guarantee_v2.xml",
        "Trade sample (upgrade to tsmt.011.001.04)": "data/samples/trade/tsmt011_baseline_v4.xml",
    }

    col_a, col_b = st.columns(2)
    with col_a:
        section("Baseline (A)")
        xml_a_option = st.radio(
            "Source A",
            [
                "Payment sample (pain.001.001.09)",
                "Trade sample (tsrv.001.001.01 guarantee)",
                "Trade sample (tsmt.011.001.03 baseline report)",
                "From uploaded files",
                "Paste XML",
            ],
            key="src_a", horizontal=True,
        )
        if xml_a_option in _DIFF_SAMPLES_A:
            xml_a_path = _DIFF_SAMPLES_A[xml_a_option]
        elif xml_a_option == "From uploaded files":
            if st.session_state.uploaded_files:
                sel_a = st.selectbox("File A", list(st.session_state.uploaded_files.keys()), key="sel_a")
                xml_a_path = st.session_state.uploaded_files[sel_a]
            else:
                st.warning("No uploaded files yet.")
                xml_a_path = None
        else:
            pasted_a = st.text_area("Paste XML A", height=200, key="paste_a")
            if pasted_a:
                tmp_a = tempfile.NamedTemporaryFile(delete=False, suffix=".xml")
                tmp_a.write(pasted_a.encode()); tmp_a.close()
                xml_a_path = tmp_a.name
            else:
                xml_a_path = None

    with col_b:
        section("Revised (B)")
        xml_b_option = st.radio(
            "Source B",
            [
                "Payment sample (amended pain.001.001.09)",
                "Payment sample (upgrade to pain.001.001.12)",
                "Trade sample (amended guarantee)",
                "Trade sample (upgrade to tsmt.011.001.04)",
                "From uploaded files",
                "Paste XML",
            ],
            key="src_b", horizontal=True,
        )
        if xml_b_option in _DIFF_SAMPLES_B:
            xml_b_path = _DIFF_SAMPLES_B[xml_b_option]
        elif xml_b_option == "From uploaded files":
            if st.session_state.uploaded_files:
                sel_b = st.selectbox("File B", list(st.session_state.uploaded_files.keys()), key="sel_b")
                xml_b_path = st.session_state.uploaded_files[sel_b]
            else:
                st.warning("No uploaded files yet.")
                xml_b_path = None
        else:
            pasted_b = st.text_area("Paste XML B", height=200, key="paste_b")
            if pasted_b:
                tmp_b = tempfile.NamedTemporaryFile(delete=False, suffix=".xml")
                tmp_b.write(pasted_b.encode()); tmp_b.close()
                xml_b_path = tmp_b.name
            else:
                xml_b_path = None

    with st.expander("⚙️ Ignore patterns (benign fields)"):
        from config.settings import settings as _cfg
        default_ignores = ", ".join(_cfg.benign_patterns)
        ignore_input = st.text_input(
            "Comma-separated tag names to treat as benign", value=default_ignores,
        )
        ignore_tags = [t.strip() for t in ignore_input.split(",") if t.strip()]

    with st.expander("📐 Schema-aware classification (optional XSD)"):
        from src.connectors.schema_bundle import bundle_files
        schema_choices = {"None — rule-based classification only": None}
        schema_choices.update(
            {f"{p.stem} ({p.parent.name})": str(p) for p in bundle_files()}
        )
        schema_label = st.selectbox(
            "Validate and classify against", list(schema_choices.keys()),
            key="diff_schema_choice",
            help="With an XSD, newly added mandatory fields are graded BREAKING "
                 "rather than informational, and both messages are validated.",
        )
        schema_path = schema_choices[schema_label]

    if st.button("🔍 Compare", type="primary", use_container_width=True):
        if not xml_a_path or not xml_b_path:
            st.error("Please select both XML files.")
            st.session_state.diff_result = None
        else:
            with st.spinner("Comparing..."):
                _compare_and_record(
                    xml_a_path, xml_b_path, schema_path, ignore_tags
                )

    result = st.session_state.get("diff_result")
    if result is not None:
        from src.comparator.impact_report import (
            markdown_impact_report, risk_rating, word_impact_report,
        )
        schema_used = st.session_state.get("diff_schema")

        if result.parse_error:
            st.error(result.parse_error)
        else:
            if result.message_type_a != result.message_type_b:
                st.info(
                    f"Version upgrade detected: **{result.message_type_a} → "
                    f"{result.message_type_b}**. Differences below exclude the "
                    "namespace change on every element, which is reported once."
                )

            if schema_used:
                for label, valid, errors in (
                    ("Baseline (A)", result.is_valid_a, result.validation_errors_a),
                    ("Revised (B)", result.is_valid_b, result.validation_errors_b),
                ):
                    if valid:
                        st.success(f"{label} is valid against {Path(schema_used).stem}.")
                    else:
                        with st.expander(
                            f"⚠️ {label} does not validate against "
                            f"{Path(schema_used).stem} ({len(errors)} finding(s))"
                        ):
                            for err in errors[:20]:
                                st.write(f"- {err}")

            # Same rating the exported impact assessment reports, so the two
            # never disagree.
            score = result.breaking_score
            rating = risk_rating(score, len(result.breaking))
            color = {"HIGH": "🔴", "MEDIUM": "🟠"}.get(rating, "🟡" if rating == "LOW-MEDIUM" else "🟢")
            st.metric(
                label="Breaking-Change Score",
                value=f"{score}/100",
                delta=f"{color} {rating} RISK",
            )

            stat_cards([
                ("Total diffs", len(result.diffs),    "changes detected",   "#4F46E5"),
                ("Breaking",    len(result.breaking), "will reject or fail", "#EF4444"),
                ("Warning",     len(result.warnings), "needs review",        "#F59E0B"),
                ("Benign",      len(result.benign),   "safe to ignore",      "#10B981"),
            ])

            if result.diffs:
                import pandas as pd
                df = pd.DataFrame([d.to_dict() for d in result.diffs])
                df = df[["severity", "change_type", "xpath", "old_value", "new_value", "explanation"]]

                def _highlight(row):
                    c = {
                        "BREAKING": "background-color: #ffcccc",
                        "WARNING":  "background-color: #fff3cd",
                        "INFO":     "background-color: #d4edda",
                        "BENIGN":   "background-color: #f0f0f0",
                    }
                    return [c.get(row["severity"], "")] * len(row)

                st.dataframe(
                    df.style.apply(_highlight, axis=1),
                    use_container_width=True, height=400,
                )
                with st.expander("🧮 How the score was calculated"):
                    st.dataframe(
                        pd.DataFrame(result.score_breakdown),
                        use_container_width=True, hide_index=True,
                    )
                    st.caption(
                        "Score = points awarded ÷ points if every change were "
                        "BREAKING. Weights are configurable per severity."
                        + ("  Classification used the selected XSD."
                           if result.schema_aware else
                           "  No XSD selected — rule-based classification only.")
                    )

                section("Business impact assessment")
                col_dl1, col_dl2 = st.columns(2)
                col_dl1.download_button(
                    "📥 Impact Assessment (.docx)",
                    data=word_impact_report(result),
                    file_name="SwiftSage_Impact_Assessment.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                )
                col_dl2.download_button(
                    "📥 Impact Assessment (.md)",
                    data=markdown_impact_report(result),
                    file_name="SwiftSage_Impact_Assessment.md",
                    mime="text/markdown",
                    use_container_width=True,
                )
                col_dl3, col_dl4 = st.columns(2)
                col_dl3.download_button(
                    "📥 Technical JSON Report", data=result.to_json(),
                    file_name="diff_report.json", mime="application/json",
                    use_container_width=True,
                )
                col_dl4.download_button(
                    "📥 Technical Text Report", data=result.human_report(),
                    file_name="diff_report.txt", mime="text/plain",
                    use_container_width=True,
                )
            else:
                st.success("No differences found after applying ignore rules.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Standards Library
# ═══════════════════════════════════════════════════════════════════════════════
with tab_library:
    hero(
        "Standards Library",
        "Every ISO 20022 schema and artefact downloaded to this workspace, "
        "filterable by message set and artefact type.",
        ["XSD", "Samples", "MUG", "MDR"],
    )

    col_filter1, col_filter2 = st.columns(2)
    with col_filter1:
        ms_filter = st.selectbox(
            "Filter by message set",
            ["All", *ISO20022_MESSAGE_SETS],
        )
    with col_filter2:
        type_filter = st.selectbox(
            "Filter by artifact type", ["All", "xsd", "sample", "mug", "mdr"],
        )

    try:
        lib = _load_library()
        ms = None if ms_filter == "All" else ms_filter
        at = None if type_filter == "All" else type_filter
        artifacts = lib.list_artifacts(message_set=ms, artifact_type=at)

        if artifacts:
            import pandas as pd
            df = pd.DataFrame([a.model_dump() for a in artifacts])
            cols = ["artifact_id", "artifact_type", "message_type", "version",
                    "retrieved_at", "source_url"]
            df = df[[c for c in cols if c in df.columns]]
            st.dataframe(df, use_container_width=True)
            st.caption(f"Total: {len(artifacts)} artifacts")
        else:
            st.info("No artifacts yet. Use 'Sync ISO 20022 Schemas' in the sidebar.")
    except Exception as e:
        st.error(f"Library error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5 — Observability
# ═══════════════════════════════════════════════════════════════════════════════
with tab_obs:
    hero(
        "Run observability",
        "Every chat turn, grounding lookup, mapping run and comparison is timed and "
        "recorded to a local JSONL log — no external service, works offline.",
        ["Local only", "Durations", "Tool calls", "Outcomes"],
    )

    col_kinds, col_actions = st.columns([3, 1])
    with col_kinds:
        kind_labels = {
            run_log.CHAT: "Chat turns",
            run_log.TOOL: "Tool calls",
            run_log.TRANSFORM: "Transform runs",
            run_log.DIFF: "XML comparisons",
        }
        chosen = st.multiselect(
            "Show",
            list(kind_labels),
            default=list(kind_labels),
            format_func=lambda k: kind_labels[k],
        )
    with col_actions:
        st.write("")
        if st.button("↻ Refresh", use_container_width=True, key="obs_refresh"):
            st.rerun()

    events = run_log.read_events(limit=500, kinds=chosen)
    stats = run_log.summarise(events)

    if not events:
        st.info(
            "No runs recorded yet. Compare two messages in **XML Diff**, or run the "
            "**Transform Advisor**, and the timings appear here.",
            icon="📈",
        )
    else:
        stat_cards([
            ("Events",          stats["events"],        "recorded units of work", "#4F46E5"),
            ("Chat turns",      stats["chat_turns"],    "agent conversations",    "#0EA5E9"),
            ("Transform runs",  stats["by_kind"].get(run_log.TRANSFORM, {}).get("runs", 0),
             "mapping runs",    "#10B981"),
            ("Comparisons",     stats["by_kind"].get(run_log.DIFF, {}).get("runs", 0),
             "version diffs",   "#F59E0B"),
            ("Errors",          stats["errors"],        "failed runs",            "#EF4444"),
        ])

        st.write("")
        section(
            "Latency by activity",
            "Median and slowest duration per activity — the evidence behind "
            "\"minutes, not weeks\".",
        )
        import pandas as pd

        if stats["by_kind"]:
            st.dataframe(
                pd.DataFrame([
                    {
                        "Activity": kind_labels.get(kind, kind),
                        "Runs": row["runs"],
                        "Median (s)": row["median_s"],
                        "Slowest (s)": row["slowest_s"],
                    }
                    for kind, row in stats["by_kind"].items()
                ]).set_index("Activity"),
                use_container_width=True,
            )

        usage = stats["tokens"]
        if usage.calls:
            st.write("")
            section(
                "Model token usage",
                "Reported by the API for every request and response in the "
                "selected runs. The system prompt is sent as a cached block, so "
                "it is billed once and read back cheaply on later calls.",
            )
            hit_rate = usage.cache_hit_rate
            stat_cards([
                ("Model calls", usage.calls, "requests to Claude", "#4F46E5"),
                ("Request tokens", f"{usage.input_tokens:,}",
                 "prompt, cached included", "#0EA5E9"),
                ("Response tokens", f"{usage.output_tokens:,}",
                 "completions", "#10B981"),
                ("System prompt", f"{usage.cached_prefix_tokens:,}",
                 "cached block per call", "#8B5CF6"),
                ("Cache hit", f"{hit_rate}%" if hit_rate is not None else "—",
                 "of request tokens read from cache", "#F59E0B"),
            ])
            st.dataframe(
                pd.DataFrame([
                    {
                        "Activity": kind_labels.get(kind, kind),
                        "Model calls": row.calls,
                        "Request": row.input_tokens,
                        "— new": row.uncached_input_tokens,
                        "— cache read": row.cache_read_tokens,
                        "— cache written": row.cache_write_tokens,
                        "Response": row.output_tokens,
                        "Total": row.total_tokens,
                    }
                    for kind, row in stats["tokens_by_kind"].items()
                ]).set_index("Activity"),
                use_container_width=True,
            )
            st.caption(
                f"Prompt caching avoided the equivalent of "
                f"**{usage.tokens_saved_by_cache:,}** uncached request tokens "
                "(a cache read is billed at 10% of the input rate, writing the "
                "cache at 125%). The system-prompt figure is the cached prefix "
                "the API reported; where a prompt was too short to cache it is "
                "an estimate from its character count instead. Runs without a "
                "model call — XML Diff, the offline demo scenarios — cost no "
                "tokens and are absent from this table."
            )

        effort = metrics.effort_summary(events)
        if effort["rows"]:
            st.write("")
            section(
                "Effort vs the manual baseline",
                "Measured run time against an estimate of the same deliverable "
                "produced by hand. The estimate is stated, not hidden.",
            )
            stat_cards([
                ("Runs", effort["runs"], "successful deliverables", "#4F46E5"),
                ("SwiftSage", effort["automated_label"],
                 "measured from the run log", "#0EA5E9"),
                ("Manual equivalent", f"{effort['manual_days']} d",
                 f"{effort['manual_hours']} h of BA + SME time", "#F59E0B"),
                ("Effort avoided", f"{effort['hours_saved']} h",
                 "on this session's runs", "#10B981"),
                ("Speed-up", effort["speedup_label"],
                 "manual ÷ measured", "#8B5CF6"),
            ])
            st.dataframe(
                pd.DataFrame([
                    {
                        "Deliverable": row["deliverable"],
                        "Runs": row["runs"],
                        "SwiftSage": row["automated_label"],
                        "Manual (h each)": row["baseline_hours_each"],
                        "Manual (h total)": row["manual_hours"],
                        "Avoided (h)": row["hours_saved"],
                    }
                    for row in effort["rows"]
                ]).set_index("Deliverable"),
                use_container_width=True,
            )
            with st.expander("📐 Assumptions behind these numbers"):
                for line in metrics.assumptions():
                    st.markdown(f"- {line}")
                st.caption(
                    "Override a baseline before a demo with "
                    "`SWIFTSAGE_BASELINE_TRANSFORM_HOURS`, "
                    "`SWIFTSAGE_BASELINE_DIFF_HOURS` or "
                    "`SWIFTSAGE_BASELINE_CHAT_HOURS`."
                )

        if stats["chat_turns"]:
            rate = stats["grounded_rate"]
            st.metric(
                "Grounded chat turns",
                f"{stats['grounded_turns']}/{stats['chat_turns']}",
                delta=f"{rate}% consulted the schemas" if rate is not None else None,
            )
            st.caption(
                "A turn counts as grounded when the agent called "
                "`lookup_iso20022_element` or `compare_element_across_versions` — i.e. "
                "answered from the vendored XSDs rather than model recall."
            )

        if stats["tool_counts"]:
            st.write("")
            section("Tool usage", "Which capabilities the agent actually reached for.")
            st.dataframe(
                pd.DataFrame(
                    sorted(stats["tool_counts"].items(), key=lambda kv: -kv[1]),
                    columns=["Tool", "Calls"],
                ).set_index("Tool"),
                use_container_width=True,
            )

        st.write("")
        section("Recent activity", "Newest first. Detail holds counts and outcomes only.")
        st.dataframe(
            pd.DataFrame([
                {
                    "When (UTC)": e.ts.replace("T", " ").replace("+00:00", ""),
                    "Activity":   kind_labels.get(e.kind, e.kind),
                    "Subject":    e.name,
                    "Status":     e.status,
                    "Seconds":    e.duration_s,
                    "Detail":     json.dumps(e.detail, ensure_ascii=False),
                }
                for e in events[:100]
            ]),
            use_container_width=True,
            height=380,
        )

        col_dl, col_clear = st.columns(2)
        with col_dl:
            log_file = run_log.log_path()
            if log_file.exists():
                st.download_button(
                    "📥 Download run log (.jsonl)",
                    data=log_file.read_bytes(),
                    file_name="swiftsage_runs.jsonl",
                    mime="application/x-ndjson",
                    use_container_width=True,
                )
        with col_clear:
            if st.button(
                "🗑️ Clear run log", use_container_width=True, key="obs_clear"
            ):
                run_log.clear()
                st.rerun()

        st.caption(f"Log file: `{run_log.log_path()}`")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 6 — Help
# ═══════════════════════════════════════════════════════════════════════════════
with tab_help:
    hero(
        "Quick start guide",
        "Everything you need to run your first mapping, comparison, or expert question.",
        ["2 minute setup"],
    )
    st.markdown("""
## Getting Started

### 1. Enter your API Key
Add your **Anthropic API key** in the sidebar (get one at [console.anthropic.com](https://console.anthropic.com)).

### 2. Choose your workflow

---

## 🔄 Transform Advisor — Map Internal Messages to ISO 20022

**Purpose:** Upload your bank's internal payment message and get a complete
field mapping, gap analysis, and downloadable Transformation Requirements Document.

**Steps:**
1. Go to the **Transform Advisor** tab
2. Upload your internal XML message (or use the built-in sample)
3. Select the target ISO 20022 message type (default: pain.001.001.09)
4. Click **Analyse & Map**
5. Review the mapping table and gap register
6. Download the Transformation Requirements Document (.docx)

**What you get:**
- Field mapping table: DIRECT / DERIVED / SPLIT / COMBINED / UNMAPPED
- Gap register: BLOCKING / ENRICHMENT / CONDITIONAL gaps with recommendations
- Word document ready for handoff to your development team

---

## 💬 Chat — Ask the ISO 20022 Expert

Ask anything in plain English:
- *"What is pain.001 used for in business terms?"*
- *"What changed between pain.001 v3 and v9 and what is the impact?"*
- *"Explain the end-to-end flow of a cross-border SWIFT GPI payment"*
- *"Map my internal payment message to pain.001.001.09"*
- *"What are the mandatory fields in pacs.008?"*

---

## 🔍 XML Diff — Compare Two ISO 20022 Messages

Compare any two ISO 20022 XML versions and get:
- A 0–100 breaking-change score, with the per-severity calculation behind it
- Classification of every difference: BREAKING / WARNING / BENIGN / INFO
- Optional schema-aware grading — pick a vendored XSD to validate both messages and
  grade newly added **mandatory** fields as BREAKING
- Version upgrades across message versions (e.g. **pain.001.001.09 → .12**), where the
  namespace change is reported once instead of on every element
- Downloadable business impact assessment (Word or Markdown) plus technical JSON / text

---

## Breaking Change Classification

| Severity | Meaning | Example |
|----------|---------|---------|
| 🔴 **BREAKING** | Will cause payment rejection or STP failure | Amount changed, IBAN changed, mandatory field removed |
| 🟠 **WARNING** | Investigate — may affect settlement or routing | Date changes, reordering |
| ℹ️ **INFO** | Informational — optional field added or removed | New remittance info block |
| ✅ **BENIGN** | Safe to ignore | Message ID, timestamp, correlation ref |

---

## Transformation Mapping Types

| Type | Meaning | Example |
|------|---------|---------|
| ✅ **DIRECT** | 1:1 match, same business meaning | BeneficiaryName → Cdtr/Nm |
| 🔧 **DERIVED** | Target computed from source | SortCode → BIC via reference data |
| ↔️ **SPLIT** | One source → multiple targets | FullName → FrstNm + LastNm |
| ➕ **COMBINED** | Multiple sources → one target | SortCode + AccountNo → IBAN |
| ➖ **UNMAPPED** | No ISO 20022 equivalent | CostCentre, WorkflowId |

---

## Sample Files

| File | Description |
|------|-------------|
| `data/samples/pain001_v1.xml` | pain.001 baseline (2 payments) |
| `data/samples/pain001_v2.xml` | pain.001 with breaking + warning changes |
| `data/samples/pacs008_sample.xml` | pacs.008 interbank transfer |
| `data/samples/internal/sample_bank_payment.xml` | Sample internal bank payment (demo for Transform Advisor) |
    """)
