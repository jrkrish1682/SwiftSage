"""Visual theme for the SwiftSage Streamlit app.

Exposes:
    inject_css()   — global stylesheet, call once right after set_page_config()
    hero()         — gradient page banner
    section()      — section heading with optional caption
    stat_cards()   — row of KPI cards
    badge()        — inline coloured pill (returns HTML)
"""
from __future__ import annotations

from html import escape

import streamlit as st

INDIGO = "#4F46E5"
INDIGO_DARK = "#3730A3"
TEAL = "#0EA5A4"
INK = "#0F1B2D"
MUTED = "#5B6B84"
LINE = "#E3E9F2"
SURFACE = "#FFFFFF"
CANVAS = "#E6F1FA"

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {{
    --ss-indigo: {INDIGO};
    --ss-indigo-dark: {INDIGO_DARK};
    --ss-teal: {TEAL};
    --ss-ink: {INK};
    --ss-muted: {MUTED};
    --ss-line: {LINE};
    --ss-surface: {SURFACE};
    --ss-canvas: {CANVAS};
    --ss-radius: 14px;
    --ss-shadow: 0 1px 2px rgba(15,27,45,.04), 0 8px 24px rgba(15,27,45,.06);
}}

/* ── Shell ─────────────────────────────────────────────────────────────── */
html, body, .stApp, [class*="css"] {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}}
.stApp {{
    background:
        radial-gradient(1100px 520px at 12% -8%, #DCEAFB 0%, rgba(220,234,251,0) 60%),
        radial-gradient(900px 480px at 92% 0%, #D8F2F7 0%, rgba(216,242,247,0) 55%),
        var(--ss-canvas);
    color: var(--ss-ink);
}}
[data-testid="stHeader"] {{ background: transparent !important; }}
[data-testid="stMain"] .block-container {{
    padding-top: 4.6rem !important;
    padding-bottom: 6rem !important;
    max-width: 1320px;
}}
#MainMenu, footer {{ visibility: hidden; }}
h1, h2, h3, h4 {{ color: var(--ss-ink); letter-spacing: -.015em; font-weight: 700; }}

/* ── Hero banner ───────────────────────────────────────────────────────── */
.ss-hero {{
    position: relative;
    overflow: hidden;
    border-radius: 20px;
    padding: 26px 30px;
    margin-bottom: 18px;
    color: #FFFFFF;
    background: linear-gradient(120deg, #312E81 0%, {INDIGO} 46%, {TEAL} 100%);
    box-shadow: 0 12px 34px rgba(49,46,129,.28);
}}
.ss-hero::after {{
    content: "";
    position: absolute;
    inset: -60% -20% auto auto;
    width: 380px; height: 380px;
    background: radial-gradient(circle, rgba(255,255,255,.22) 0%, rgba(255,255,255,0) 65%);
}}
.ss-hero h1 {{
    color: #FFFFFF !important;
    font-size: 1.9rem;
    margin: 0 0 6px 0;
    font-weight: 700;
    letter-spacing: -.02em;
}}
.ss-hero p {{
    margin: 0;
    font-size: .97rem;
    color: rgba(255,255,255,.88);
    max-width: 760px;
    line-height: 1.55;
}}
.ss-hero-tags {{ margin-top: 14px; display: flex; gap: 8px; flex-wrap: wrap; }}
.ss-hero-tags span {{
    background: rgba(255,255,255,.16);
    border: 1px solid rgba(255,255,255,.28);
    color: #FFFFFF;
    border-radius: 999px;
    padding: 4px 12px;
    font-size: .78rem;
    font-weight: 500;
    backdrop-filter: blur(6px);
}}

/* ── Section heading ───────────────────────────────────────────────────── */
.ss-section {{ margin: 6px 0 12px 0; }}
.ss-section h3 {{
    margin: 0;
    font-size: 1.12rem;
    display: flex; align-items: center; gap: 9px;
}}
.ss-section h3::before {{
    content: "";
    width: 4px; height: 19px; border-radius: 3px;
    background: linear-gradient(180deg, {INDIGO} 0%, {TEAL} 100%);
}}
.ss-section p {{ margin: 5px 0 0 13px; color: var(--ss-muted); font-size: .88rem; }}

/* ── KPI cards ─────────────────────────────────────────────────────────── */
.ss-stats {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 2px 0 6px 0; }}
.ss-stat {{
    flex: 1 1 150px;
    background: var(--ss-surface);
    border: 1px solid var(--ss-line);
    border-radius: var(--ss-radius);
    padding: 14px 16px;
    box-shadow: var(--ss-shadow);
    border-top: 3px solid var(--ss-accent, {INDIGO});
}}
.ss-stat .ss-stat-label {{
    font-size: .72rem; font-weight: 600; letter-spacing: .07em;
    text-transform: uppercase; color: var(--ss-muted);
}}
.ss-stat .ss-stat-value {{
    font-size: 1.85rem; font-weight: 700; line-height: 1.15;
    margin-top: 4px; color: var(--ss-ink);
}}
.ss-stat .ss-stat-hint {{ font-size: .78rem; color: var(--ss-muted); margin-top: 2px; }}

.ss-badge {{
    display: inline-block; border-radius: 999px; padding: 2px 10px;
    font-size: .75rem; font-weight: 600;
}}

/* ── Sidebar ───────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {{
    background: linear-gradient(185deg, #0F1B2D 0%, #16233B 62%, #1B2C49 100%) !important;
    border-right: 1px solid rgba(255,255,255,.06);
}}
[data-testid="stSidebar"] * {{ color: #E7ECF5 !important; }}
[data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{ color: #FFFFFF !important; }}
[data-testid="stSidebar"] .ss-brand {{
    display: flex; align-items: center; gap: 11px; padding: 4px 0 2px 0;
}}
[data-testid="stSidebar"] .ss-brand .ss-logo {{
    width: 38px; height: 38px; border-radius: 11px;
    background: linear-gradient(135deg, {INDIGO} 0%, {TEAL} 100%);
    display: flex; align-items: center; justify-content: center;
    font-size: 1.15rem; box-shadow: 0 6px 16px rgba(79,70,229,.4);
}}
[data-testid="stSidebar"] .ss-brand .ss-name {{
    font-size: 1.18rem; font-weight: 700; letter-spacing: -.01em; line-height: 1.1;
}}
[data-testid="stSidebar"] .ss-brand .ss-tag {{
    font-size: .74rem; color: #93A4BF !important;
}}
[data-testid="stSidebar"] [data-testid="stTextInputRootElement"],
[data-testid="stSidebar"] .react-aria-ComboBox > div {{
    background-color: rgba(255,255,255,.07) !important;
    border: 1px solid rgba(255,255,255,.16) !important;
    border-radius: 10px !important;
}}
[data-testid="stSidebar"] [data-testid="stTextInputRootElement"]:focus-within,
[data-testid="stSidebar"] .react-aria-ComboBox > div:focus-within {{
    border-color: {TEAL} !important;
}}
[data-testid="stSidebar"] input {{
    background-color: transparent !important;
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}}
[data-testid="stSidebar"] svg {{ fill: #C3D0E4 !important; }}
[data-testid="stSidebar"] .stButton button {{
    background: rgba(255,255,255,.08) !important;
    color: #FFFFFF !important;
    border: 1px solid rgba(255,255,255,.16) !important;
    border-radius: 10px !important;
    font-weight: 500 !important;
    transition: all .18s ease !important;
}}
[data-testid="stSidebar"] [data-testid="stFormSubmitButton"] button,
[data-testid="stSidebar"] button[data-testid*="FormSubmit"] {{
    background: linear-gradient(120deg, {INDIGO} 0%, {TEAL} 130%) !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    box-shadow: 0 6px 16px rgba(79,70,229,.35) !important;
}}
[data-testid="stSidebar"] [data-testid="stFormSubmitButton"] button,
[data-testid="stSidebar"] [data-testid="stFormSubmitButton"] button *,
[data-testid="stSidebar"] button[data-testid*="FormSubmit"],
[data-testid="stSidebar"] button[data-testid*="FormSubmit"] * {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}}
[data-testid="stSidebar"] [data-testid="stFormSubmitButton"] button:hover,
[data-testid="stSidebar"] button[data-testid*="FormSubmit"]:hover {{
    filter: brightness(1.08);
    transform: translateY(-1px);
}}
[data-testid="stSidebar"] .stButton button:hover {{
    background: linear-gradient(120deg, {INDIGO} 0%, {TEAL} 130%) !important;
    border-color: transparent !important;
    transform: translateY(-1px);
}}
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {{
    background: rgba(255,255,255,.05) !important;
    border: 1px dashed rgba(255,255,255,.22) !important;
    border-radius: 12px !important;
}}
[data-testid="stSidebar"] hr {{ border-color: rgba(255,255,255,.1) !important; }}
[data-testid="stSidebar"] a {{ color: {TEAL} !important; }}

/* ── Tabs ──────────────────────────────────────────────────────────────── */
[data-testid="stTabs"] {{ margin-bottom: 6px; }}
[data-testid="stTabs"] [role="tablist"] {{
    background: var(--ss-surface);
    border: 1px solid var(--ss-line);
    border-radius: 14px;
    padding: 6px 8px;
    gap: 4px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    row-gap: 4px;
    overflow: visible !important;
    box-shadow: var(--ss-shadow);
    border-bottom: 1px solid var(--ss-line) !important;
}}
[data-testid="stTabs"] [role="tab"] {{
    border-radius: 10px !important;
    color: var(--ss-muted) !important;
    font-weight: 600 !important;
    font-size: .9rem !important;
    padding: 8px 16px !important;
    height: auto !important;
    min-height: 38px !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    white-space: nowrap !important;
    flex: 0 0 auto !important;
    border: none !important;
    background: transparent !important;
    transition: all .18s ease !important;
}}
[data-testid="stTabs"] [role="tab"]:hover:not([aria-selected="true"]) {{
    background: #F1F4FA !important; color: var(--ss-ink) !important;
}}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {{
    background: linear-gradient(120deg, {INDIGO} 0%, {INDIGO_DARK} 100%) !important;
    color: #FFFFFF !important;
    box-shadow: 0 6px 16px rgba(79,70,229,.32) !important;
}}
[data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-border"] {{ display: none !important; }}

/* ── Surfaces: expander, alerts, dataframe, metrics ───────────────────── */
[data-testid="stExpander"] {{
    background: var(--ss-surface);
    border: 1px solid var(--ss-line) !important;
    border-radius: var(--ss-radius) !important;
    box-shadow: var(--ss-shadow);
}}
[data-testid="stAlert"] {{
    border-radius: 12px !important;
    border: 1px solid var(--ss-line) !important;
    border-left: 4px solid {INDIGO} !important;
    box-shadow: var(--ss-shadow);
}}
[data-testid="stDataFrame"], [data-testid="stTable"] {{
    border: 1px solid var(--ss-line) !important;
    border-radius: var(--ss-radius) !important;
    overflow: hidden;
    box-shadow: var(--ss-shadow);
}}
[data-testid="stMetric"] {{
    background: var(--ss-surface);
    border: 1px solid var(--ss-line);
    border-radius: var(--ss-radius);
    padding: 14px 16px;
    box-shadow: var(--ss-shadow);
}}
[data-testid="stMetricLabel"] {{ color: var(--ss-muted) !important; font-weight: 600 !important; }}

/* ── Buttons ───────────────────────────────────────────────────────────── */
.stButton button[kind="primary"], .stDownloadButton button {{
    background: linear-gradient(120deg, {INDIGO} 0%, {INDIGO_DARK} 100%) !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 11px !important;
    font-weight: 600 !important;
    padding: 9px 20px !important;
    box-shadow: 0 8px 20px rgba(79,70,229,.26) !important;
    transition: transform .16s ease, box-shadow .16s ease !important;
}}
.stButton button[kind="primary"]:hover, .stDownloadButton button:hover {{
    transform: translateY(-1px);
    box-shadow: 0 12px 26px rgba(79,70,229,.34) !important;
}}
.stButton button[kind="secondary"] {{
    background: var(--ss-surface) !important;
    color: var(--ss-ink) !important;
    border: 1px solid var(--ss-line) !important;
    border-radius: 12px !important;
    font-size: .85rem !important;
    font-weight: 500 !important;
    padding: 9px 15px !important;
    text-align: left !important;
    white-space: normal !important;
    height: auto !important;
    box-shadow: var(--ss-shadow);
    transition: all .18s ease !important;
}}
.stButton button[kind="secondary"]:hover {{
    border-color: {INDIGO} !important;
    color: {INDIGO} !important;
    transform: translateY(-1px);
}}

/* ── Chat ──────────────────────────────────────────────────────────────── */
[data-testid="stChatMessage"] {{
    background: var(--ss-surface) !important;
    border: 1px solid var(--ss-line) !important;
    border-radius: 16px !important;
    padding: 15px 19px !important;
    margin: 11px 0 !important;
    box-shadow: var(--ss-shadow) !important;
    animation: ssFade .2s ease-in !important;
}}
@keyframes ssFade {{ from {{ opacity:0; transform: translateY(6px); }} to {{ opacity:1; transform:none; }} }}
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {{
    background: linear-gradient(120deg, #EEF1FF 0%, #F4F7FF 100%) !important;
    border-color: #D9DEFB !important;
    margin-left: 10% !important;
}}
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {{ margin-right: 10% !important; }}
[data-testid="chatAvatarIcon-user"] {{ background: {INK} !important; color: #FFF !important; }}
[data-testid="chatAvatarIcon-assistant"] {{
    background: linear-gradient(135deg, {INDIGO} 0%, {TEAL} 100%) !important; color: #FFF !important;
}}
[data-testid="stChatMessage"] p, [data-testid="stChatMessage"] li {{
    color: var(--ss-ink) !important; font-size: .95rem !important; line-height: 1.68 !important;
}}
[data-testid="stChatMessage"] code {{
    font-family: 'JetBrains Mono', monospace !important;
    background: #EEF1FF !important; color: {INDIGO_DARK} !important;
    border: 1px solid #DDE3FA !important; border-radius: 6px !important; padding: 1px 6px !important;
}}
[data-testid="stChatMessage"] pre {{
    background: #0F1B2D !important; border-radius: 12px !important; padding: 15px 17px !important;
}}
[data-testid="stChatMessage"] pre code {{ color: #D8E2F5 !important; border: none !important; background: transparent !important; }}
[data-testid="stChatMessage"] th {{ background: {INK} !important; color: #FFF !important; padding: 9px 12px !important; }}
[data-testid="stChatMessage"] td {{ border: 1px solid var(--ss-line) !important; padding: 8px 12px !important; }}
[data-testid="stChatMessage"] tr:nth-child(even) td {{ background: #F7F9FC !important; }}

[data-testid="stChatInput"] {{
    background: var(--ss-surface) !important;
    border: 1px solid var(--ss-line) !important;
    border-radius: 16px !important;
    box-shadow: 0 10px 30px rgba(15,27,45,.10) !important;
}}
[data-testid="stChatInput"]:focus-within {{
    border-color: {INDIGO} !important;
    box-shadow: 0 0 0 4px rgba(79,70,229,.12), 0 10px 30px rgba(15,27,45,.10) !important;
}}
[data-testid="stChatInput"] textarea {{ color: var(--ss-ink) !important; font-size: .95rem !important; }}

/* ── Markdown tables on the main canvas ────────────────────────────────── */
[data-testid="stMain"] [data-testid="stMarkdownContainer"] table {{
    border-collapse: separate !important;
    border-spacing: 0 !important;
    width: 100% !important;
    background: var(--ss-surface);
    border: 1px solid var(--ss-line);
    border-radius: var(--ss-radius);
    overflow: hidden;
    box-shadow: var(--ss-shadow);
    margin: 6px 0 14px 0;
}}
[data-testid="stMain"] [data-testid="stMarkdownContainer"] th {{
    background: {INK} !important;
    color: #FFFFFF !important;
    text-align: left !important;
    padding: 10px 14px !important;
    font-size: .86rem !important;
}}
[data-testid="stMain"] [data-testid="stMarkdownContainer"] td {{
    padding: 9px 14px !important;
    border-top: 1px solid var(--ss-line) !important;
    font-size: .89rem !important;
}}
[data-testid="stMain"] [data-testid="stMarkdownContainer"] tr:nth-child(even) td {{
    background: #F7F9FC !important;
}}

/* ── Sidebar overrides (must outrank the main-canvas rules above) ──────── */
[data-testid="stSidebar"] .stButton button[kind="secondary"],
[data-testid="stSidebar"] .stButton button[kind="primary"],
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button {{
    background: rgba(255,255,255,.08) !important;
    color: #FFFFFF !important;
    border: 1px solid rgba(255,255,255,.18) !important;
    border-radius: 10px !important;
    box-shadow: none !important;
    text-align: center !important;
}}
[data-testid="stSidebar"] .stButton button[kind="secondary"]:hover,
[data-testid="stSidebar"] .stButton button[kind="primary"]:hover,
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button:hover {{
    background: linear-gradient(120deg, {INDIGO} 0%, {TEAL} 130%) !important;
    border-color: transparent !important;
    color: #FFFFFF !important;
}}
[data-testid="stSidebar"] input::placeholder {{ color: #8497B3 !important; }}
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] span {{ color: #B9C6DB !important; }}

/* ── Inputs on the main canvas ─────────────────────────────────────────── */
[data-testid="stMain"] [data-testid="stTextInputRootElement"],
[data-testid="stMain"] [data-testid="stTextAreaRootElement"],
[data-testid="stMain"] .react-aria-ComboBox > div {{
    border-radius: 10px !important;
    border-color: var(--ss-line) !important;
}}
[data-testid="stMain"] [data-testid="stFileUploaderDropzone"] {{
    background: var(--ss-surface) !important;
    border: 1.5px dashed #C3CEE2 !important;
    border-radius: var(--ss-radius) !important;
}}
</style>
"""


def inject_css() -> None:
    """Inject the global stylesheet. Call once, immediately after set_page_config()."""
    st.markdown(_CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str, tags: list[str] | None = None) -> None:
    """Render the gradient page banner."""
    chips = "".join(f"<span>{escape(t)}</span>" for t in (tags or []))
    st.markdown(
        f"""<div class="ss-hero">
            <h1>{escape(title)}</h1>
            <p>{escape(subtitle)}</p>
            {f'<div class="ss-hero-tags">{chips}</div>' if chips else ''}
        </div>""",
        unsafe_allow_html=True,
    )


def section(title: str, caption: str = "") -> None:
    """Render a section heading with an accent bar and optional caption."""
    cap = f"<p>{escape(caption)}</p>" if caption else ""
    st.markdown(
        f'<div class="ss-section"><h3>{escape(title)}</h3>{cap}</div>',
        unsafe_allow_html=True,
    )


def stat_cards(cards: list[tuple[str, object, str, str]]) -> None:
    """Render a row of KPI cards from (label, value, hint, accent_colour) tuples."""
    html = "".join(
        f'<div class="ss-stat" style="--ss-accent:{accent}">'
        f'<div class="ss-stat-label">{escape(label)}</div>'
        f'<div class="ss-stat-value">{escape(str(value))}</div>'
        f'<div class="ss-stat-hint">{escape(hint)}</div>'
        f"</div>"
        for label, value, hint, accent in cards
    )
    st.markdown(f'<div class="ss-stats">{html}</div>', unsafe_allow_html=True)


def badge(text: str, colour: str = INDIGO) -> str:
    """Return an inline coloured pill as HTML."""
    return (
        f'<span class="ss-badge" style="background:{colour}1A;color:{colour};">'
        f"{escape(text)}</span>"
    )
