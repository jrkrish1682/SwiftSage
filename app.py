"""
SwiftSage — ISO 20022 Expert Agent for Business Analysts & Product Owners.

Layout
------
  Sidebar  : Configuration, file uploader, quick actions
  Main area: Tabbed interface
    • Chat              — Conversational agent (streaming, BA/PO persona)
    • Transform Advisor — Internal message → ISO 20022 mapping + requirements doc
    • XML Diff          — Direct semantic comparison tool
    • Library           — Browse downloaded schemas
    • Help              — Quick start guide
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from src.utils.helpers import get_logger

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

# ── Global CSS — Claude Code style, light-blue theme ──────────────────────────
st.markdown("""
<style>
/* ── App shell ──────────────────────────────────────────────────────────────── */
.stApp {
    background-color: #EBF5FB;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
}

/* ── Sidebar ─────────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: #D6EAF8 !important;
}
[data-testid="stSidebar"] * {
    color: #1F4E79 !important;
}
[data-testid="stSidebar"] .stTextInput input {
    background-color: #FFFFFF !important;
    color: #1a2936 !important;
    border: 1px solid #85C1E9 !important;
    border-radius: 8px !important;
}
[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] {
    background-color: #FFFFFF !important;
    border: 1px solid #85C1E9 !important;
    border-radius: 8px !important;
    color: #1a2936 !important;
}
[data-testid="stSidebar"] .stButton button {
    background-color: #2E75B6 !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 500 !important;
    transition: background-color 0.2s !important;
}
[data-testid="stSidebar"] .stButton button:hover {
    background-color: #1F4E79 !important;
}
[data-testid="stSidebar"] hr {
    border-color: #85C1E9 !important;
}

/* ── Main content area ───────────────────────────────────────────────────────── */
.main .block-container {
    padding-top: 1.5rem !important;
    padding-bottom: 1rem !important;
}

/* ── Tabs ────────────────────────────────────────────────────────────────────── */
[data-testid="stTabs"] [role="tablist"] {
    background-color: #D6EAF8;
    border-radius: 10px;
    padding: 4px;
    gap: 4px;
    border-bottom: none !important;
}
[data-testid="stTabs"] [role="tab"] {
    border-radius: 8px !important;
    color: #1F4E79 !important;
    font-weight: 500 !important;
    padding: 6px 16px !important;
    border: none !important;
    background-color: transparent !important;
    transition: background-color 0.2s !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    background-color: #1F4E79 !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    box-shadow: 0 1px 4px rgba(31,78,121,0.3) !important;
}
[data-testid="stTabs"] [role="tab"]:hover:not([aria-selected="true"]) {
    background-color: #AED6F1 !important;
}

/* ── Chat messages ───────────────────────────────────────────────────────────── */
[data-testid="stChatMessage"] {
    border-radius: 14px !important;
    margin: 10px 0 !important;
    padding: 14px 18px !important;
    box-shadow: 0 1px 4px rgba(31, 78, 121, 0.10) !important;
    border: 1px solid #AED6F1 !important;
    background-color: #FFFFFF !important;
    animation: fadeIn 0.18s ease-in !important;
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(6px); }
    to   { opacity: 1; transform: translateY(0); }
}

/* User message — light blue tint */
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
    background-color: #D6EAF8 !important;
    border-color: #85C1E9 !important;
    margin-left: 8% !important;
}

/* Assistant message — white card */
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
    background-color: #FFFFFF !important;
    border-color: #AED6F1 !important;
    margin-right: 8% !important;
}

/* Avatar icons */
[data-testid="chatAvatarIcon-user"] {
    background-color: #1F4E79 !important;
    color: #FFFFFF !important;
    border-radius: 50% !important;
}
[data-testid="chatAvatarIcon-assistant"] {
    background-color: #2E75B6 !important;
    color: #FFFFFF !important;
    border-radius: 50% !important;
}

/* Message text */
[data-testid="stChatMessage"] p,
[data-testid="stChatMessage"] li,
[data-testid="stChatMessage"] span {
    color: #1a2936 !important;
    font-size: 0.95rem !important;
    line-height: 1.65 !important;
}

/* Inline code */
[data-testid="stChatMessage"] code {
    background-color: #D6EAF8 !important;
    color: #1F4E79 !important;
    border-radius: 5px !important;
    padding: 2px 6px !important;
    font-size: 0.87em !important;
    font-family: "SF Mono", "Fira Code", "Cascadia Code", monospace !important;
    border: 1px solid #AED6F1 !important;
}

/* Code blocks (tool output, pre) */
[data-testid="stChatMessage"] pre {
    background-color: #EBF5FB !important;
    border: 1px solid #AED6F1 !important;
    border-radius: 10px !important;
    padding: 14px 16px !important;
    overflow-x: auto !important;
}
[data-testid="stChatMessage"] pre code {
    background-color: transparent !important;
    border: none !important;
    color: #1F4E79 !important;
    font-size: 0.85em !important;
}

/* Bold text in messages */
[data-testid="stChatMessage"] strong {
    color: #1F4E79 !important;
    font-weight: 600 !important;
}

/* Tables in chat */
[data-testid="stChatMessage"] table {
    border-collapse: collapse !important;
    width: 100% !important;
    margin: 8px 0 !important;
}
[data-testid="stChatMessage"] th {
    background-color: #1F4E79 !important;
    color: #FFFFFF !important;
    padding: 8px 12px !important;
    font-size: 0.87rem !important;
}
[data-testid="stChatMessage"] td {
    padding: 7px 12px !important;
    border: 1px solid #AED6F1 !important;
    font-size: 0.88rem !important;
}
[data-testid="stChatMessage"] tr:nth-child(even) td {
    background-color: #EBF5FB !important;
}

/* Horizontal rule in chat */
[data-testid="stChatMessage"] hr {
    border-color: #AED6F1 !important;
    margin: 10px 0 !important;
}

/* ── Chat input ───────────────────────────────────────────────────────────────── */
[data-testid="stChatInput"] {
    background-color: #FFFFFF !important;
    border: 2px solid #2E75B6 !important;
    border-radius: 24px !important;
    box-shadow: 0 2px 12px rgba(46,117,182,0.15) !important;
    padding: 4px 8px !important;
}
[data-testid="stChatInput"]:focus-within {
    border-color: #1F4E79 !important;
    box-shadow: 0 2px 16px rgba(31,78,121,0.25) !important;
}
[data-testid="stChatInput"] textarea {
    color: #1a2936 !important;
    font-size: 0.95rem !important;
    background-color: transparent !important;
}
[data-testid="stChatInput"] textarea::placeholder {
    color: #85C1E9 !important;
}

/* ── Demo question chips ─────────────────────────────────────────────────────── */
.stButton button[kind="secondary"] {
    background-color: #EBF5FB !important;
    color: #1F4E79 !important;
    border: 1px solid #AED6F1 !important;
    border-radius: 20px !important;
    font-size: 0.83rem !important;
    padding: 6px 14px !important;
    transition: all 0.2s !important;
    white-space: normal !important;
    height: auto !important;
}
.stButton button[kind="secondary"]:hover {
    background-color: #D6EAF8 !important;
    border-color: #2E75B6 !important;
}

/* ── Primary buttons ─────────────────────────────────────────────────────────── */
.stButton button[kind="primary"] {
    background-color: #1F4E79 !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    letter-spacing: 0.01em !important;
    transition: background-color 0.2s !important;
}
.stButton button[kind="primary"]:hover {
    background-color: #2E75B6 !important;
}

/* ── Info / success / warning banners ───────────────────────────────────────── */
[data-testid="stAlert"] {
    border-radius: 10px !important;
    border-left-width: 4px !important;
}

/* ── Chat tab padding — ensure last message isn't hidden behind sticky input ── */
.main .block-container {
    padding-bottom: 100px !important;
}
</style>
""", unsafe_allow_html=True)

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


# ── Session state ──────────────────────────────────────────────────────────────
if "messages"            not in st.session_state: st.session_state.messages = []
if "agent"               not in st.session_state: st.session_state.agent = None
if "uploaded_files"      not in st.session_state: st.session_state.uploaded_files = {}
if "transform_mappings"  not in st.session_state: st.session_state.transform_mappings = None
if "transform_gaps"      not in st.session_state: st.session_state.transform_gaps = None
if "transform_target"    not in st.session_state: st.session_state.transform_target = None
if "transform_doc_bytes" not in st.session_state: st.session_state.transform_doc_bytes = None


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚡ SwiftSage")
    st.caption("ISO 20022 Expert Agent for Business Analysts & Product Owners")
    st.divider()

    api_key = st.text_input(
        "Anthropic API Key",
        value=st.session_state.get("api_key", ""),
        type="password",
        help="Enter your API key for this session. Never stored on disk.",
        placeholder="sk-ant-...",
    )
    if api_key:
        st.session_state["api_key"] = api_key
        os.environ["ANTHROPIC_API_KEY"] = api_key

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
                f"Sync complete: {result.get('artifacts_added', 0)} added, "
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
tab_chat, tab_transform, tab_diff, tab_library, tab_help = st.tabs([
    "💬 Chat",
    "🔄 Transform Advisor",
    "🔍 XML Diff",
    "📚 Library",
    "ℹ️ Help",
])


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Chat
# ═══════════════════════════════════════════════════════════════════════════════
with tab_chat:
    st.header("SwiftSage — ISO 20022 Expert")
    st.caption(
        "Ask anything about SWIFT / ISO 20022 in plain English. "
        "SwiftSage answers in business terms and can validate, compare, map, and explain messages."
    )

    if st.session_state.uploaded_files:
        names = ", ".join(f"`{n}`" for n in st.session_state.uploaded_files)
        st.info(f"📂 Uploaded files available: {names}")

    # Demo question chips
    st.markdown("**Try asking:**")
    demo_cols = st.columns(3)
    demo_questions = [
        "What is pain.001 used for in business terms?",
        "What changed between pain.001 v3 and v9 and what is the business impact?",
        "Explain the end-to-end flow of a cross-border SWIFT GPI payment",
    ]
    for col, q in zip(demo_cols, demo_questions):
        if col.button(q, use_container_width=True, key=f"demo_{q[:20]}"):
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

    pending = st.session_state.pop("_pending_chat", None)
    prompt = st.chat_input("Ask about ISO 20022, transformation requirements, or message flows...") or pending

    if prompt:
        if not api_key:
            st.error("Please enter your Anthropic API Key in the sidebar.")
            st.stop()

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
    st.header("🔄 Transformation Advisor")
    st.caption(
        "Upload your bank's internal payment message. SwiftSage will map every field to its "
        "ISO 20022 equivalent, identify gaps, and generate a Transformation Requirements "
        "Document ready for your development team."
    )

    st.info(
        "**How it works:** SwiftSage parses your internal message → maps each field to "
        "ISO 20022 (DIRECT / DERIVED / SPLIT / UNMAPPED) → identifies BLOCKING and ENRICHMENT "
        "gaps → generates a structured requirements document. This will take few minutes.",
        icon="💡",
    )

    # ── Inputs ─────────────────────────────────────────────────────────────────
    col_upload, col_target = st.columns([3, 1])
    with col_upload:
        internal_file = st.file_uploader(
            "Upload Internal Bank Message (XML)",
            type=["xml"],
            key="internal_xml_uploader",
            help="Your bank's proprietary payment XML format — not an ISO 20022 file.",
        )
    with col_target:
        target_msg = st.selectbox(
            "Target ISO 20022 Message",
            ["pain.001.001.09", "pacs.008.001.10", "camt.053.001.10"],
            key="target_msg_type",
            help="The ISO 20022 message type you are migrating to.",
        )

    SAMPLES = {
        "None — I'll upload my own": None,
        "pain.001 — Meridian Bank payment initiation (46 fields)": Path("data/samples/internal/sample_bank_payment.xml"),
        "pacs.008 — Meridian Bank FI credit transfer (3 transactions)": Path("data/samples/internal/sample_bank_fi_transfer.xml"),
    }

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
                st.code(selected_sample_path.read_text(), language="xml")
        else:
            st.warning(f"Sample file not found: {selected_sample_path}")

    st.divider()

    if st.button("🔍 Analyse & Map", type="primary", use_container_width=True, key="btn_analyse"):
        if not api_key:
            st.error("Please enter your Anthropic API Key in the sidebar.")
            st.stop()

        xml_content = None
        if selected_sample_path is not None:
            if selected_sample_path.exists():
                xml_content = selected_sample_path.read_text(encoding="utf-8")
            else:
                st.error(f"Sample file not found: {selected_sample_path}")
                st.stop()
        elif internal_file:
            xml_content = internal_file.read().decode("utf-8")
        else:
            st.error("Please upload an internal message or select a sample.")
            st.stop()

        with st.spinner("SwiftSage is analysing your internal message — this take few minutes..."):
            try:
                from src.transformer.message_parser import parse_xml_fields
                from src.transformer.field_mapper import FieldMapper
                from src.transformer import gap_analyzer
                from src.transformer.requirements_generator import generate_requirements_doc

                fields   = parse_xml_fields(xml_content)
                mapper   = FieldMapper()
                mappings = mapper.map(fields, target_msg)
                gaps     = gap_analyzer.analyze(mappings, target_msg)
                doc_bytes = generate_requirements_doc(mappings, gaps, target_msg)

                st.session_state.transform_mappings  = mappings
                st.session_state.transform_gaps      = gaps
                st.session_state.transform_target    = target_msg
                st.session_state.transform_doc_bytes = doc_bytes

            except Exception as exc:
                log.exception("Transform Advisor analysis failed")
                st.error(f"Analysis failed: {exc}")
                st.stop()

        st.success(
            f"Analysis complete — {len(mappings)} fields mapped, "
            f"{len([g for g in gaps if not g.is_resolved])} open gaps identified."
        )

    # ── Results ─────────────────────────────────────────────────────────────────
    if st.session_state.transform_mappings is not None:
        import pandas as pd

        mappings  = st.session_state.transform_mappings
        gaps      = st.session_state.transform_gaps
        target    = st.session_state.transform_target
        doc_bytes = st.session_state.transform_doc_bytes

        # Summary metrics
        direct   = sum(1 for m in mappings if m.mapping_type == "DIRECT")
        derived  = sum(1 for m in mappings if m.mapping_type == "DERIVED")
        unmapped = sum(1 for m in mappings if m.mapping_type == "UNMAPPED")
        blocking = sum(1 for g in gaps if g.gap_type == "BLOCKING" and not g.is_resolved)
        enrichmt = sum(1 for g in gaps if g.gap_type == "ENRICHMENT" and not g.is_resolved)

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("✅ DIRECT",    direct)
        c2.metric("🔧 DERIVED",   derived)
        c3.metric("➖ UNMAPPED",  unmapped)
        c4.metric("🔴 BLOCKING",  blocking, delta="gaps" if blocking else None,
                  delta_color="inverse")
        c5.metric("🟠 ENRICHMENT", enrichmt)

        st.divider()

        # Field mapping table
        st.subheader("Field Mapping Table")

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
                "Business Rule":     m.business_rule,
            }
            for m in mappings
        ])
        st.dataframe(
            map_df.style.apply(_highlight_map, axis=1),
            use_container_width=True,
            height=380,
        )

        st.divider()

        # Gap register
        st.subheader("Gap Register")

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

        st.divider()

        # Download
        st.subheader("Download Requirements Document")
        st.caption(
            "The Word document includes: executive summary, complete field mapping table, "
            "gap register, unmapped fields register, open questions, and next steps."
        )
        if doc_bytes:
            st.download_button(
                label="📥 Download Transformation Requirements Document (.docx)",
                data=doc_bytes,
                file_name=f"SwiftSage_Transform_Requirements_{target}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
                type="primary",
            )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — XML Diff
# ═══════════════════════════════════════════════════════════════════════════════
with tab_diff:
    st.header("XML Semantic Comparator")
    st.caption(
        "Compare two ISO 20022 XML versions. Changes are classified as "
        "BREAKING / WARNING / BENIGN / INFO with a 0–100 business impact score."
    )

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Baseline (A)")
        xml_a_option = st.radio(
            "Source A", ["Use sample (pain.001 v1)", "From uploaded files", "Paste XML"],
            key="src_a", horizontal=True,
        )
        if xml_a_option == "Use sample (pain.001 v1)":
            xml_a_path = "data/samples/pain001_v1.xml"
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
        st.subheader("Revised (B)")
        xml_b_option = st.radio(
            "Source B", ["Use sample (pain.001 v2)", "From uploaded files", "Paste XML"],
            key="src_b", horizontal=True,
        )
        if xml_b_option == "Use sample (pain.001 v2)":
            xml_b_path = "data/samples/pain001_v2.xml"
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

    if st.button("🔍 Compare", type="primary", use_container_width=True):
        if not xml_a_path or not xml_b_path:
            st.error("Please select both XML files.")
        else:
            with st.spinner("Comparing..."):
                from src.comparator.xml_comparator import XMLComparator
                cmp = XMLComparator(ignore_tags=ignore_tags)
                result = cmp.compare(xml_a_path, xml_b_path)

            score = result.breaking_score
            color = "🔴" if score >= 60 else "🟠" if score >= 30 else "🟢"
            st.metric(
                label="Breaking-Change Score",
                value=f"{score}/100",
                delta=f"{color} {'HIGH RISK' if score >= 60 else 'MEDIUM RISK' if score >= 30 else 'LOW RISK'}",
            )

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Diffs",   len(result.diffs))
            col2.metric("🔴 BREAKING",   len(result.breaking))
            col3.metric("🟠 WARNING",    len(result.warnings))
            col4.metric("🟢 BENIGN",     len(result.benign))

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
                col_dl1, col_dl2 = st.columns(2)
                col_dl1.download_button(
                    "📥 Download JSON Report", data=result.to_json(),
                    file_name="diff_report.json", mime="application/json",
                )
                col_dl2.download_button(
                    "📥 Download Text Report", data=result.human_report(),
                    file_name="diff_report.txt", mime="text/plain",
                )
            else:
                st.success("No differences found after applying ignore rules.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Standards Library
# ═══════════════════════════════════════════════════════════════════════════════
with tab_library:
    st.header("Local Standards Library")
    st.caption("Downloaded ISO 20022 schemas and artefacts.")

    col_filter1, col_filter2 = st.columns(2)
    with col_filter1:
        ms_filter = st.selectbox(
            "Filter by message set",
            ["All", "pain", "pacs", "camt", "acmt", "auth", "reda"],
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
# TAB 5 — Help
# ═══════════════════════════════════════════════════════════════════════════════
with tab_help:
    st.header("SwiftSage — Quick Start Guide")
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
- A 0–100 breaking-change score
- Classification of every difference: BREAKING / WARNING / BENIGN / INFO
- Downloadable report (JSON or text)

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
