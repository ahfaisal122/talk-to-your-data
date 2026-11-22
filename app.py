import html
import json
import os
import time

import duckdb
import streamlit as st
from google.genai import errors as genai_errors

from query_engine import (
    auto_chart,
    execute_query,
    format_sql,
    generate_sql,
    get_table_columns,
    get_table_names,
    get_table_preview,
)


class OutOfScopeQuestion(Exception):
    pass


SAMPLE_CACHE_PATH = "sample_cache.json"
MAX_QUERIES_PER_SESSION = 5
SESSION_TTL_SECONDS = 30 * 60

TAB_PRACTICE = ":material/extension: Practice"
TAB_WORKSPACE = ":material/terminal: Workspace"
TAB_DATASET = ":material/database: Dataset"

LEVEL_COLORS = {"Easy": "green", "Medium": "orange", "Hard": "red"}

# Practice problems: every question here has a pre-generated answer in
# sample_cache.json, so they run instantly and without an API key.
PROBLEMS = [
    {
        "q": "How many orders were delivered vs canceled?",
        "level": "Easy",
        "concepts": ["WHERE … IN", "GROUP BY", "COUNT"],
        "tables": ["orders"],
    },
    {
        "q": "Revenue breakdown by payment type",
        "level": "Easy",
        "concepts": ["SUM", "GROUP BY", "ORDER BY"],
        "tables": ["order_payments"],
    },
    {
        "q": "Top 10 sellers by total sales",
        "level": "Easy",
        "concepts": ["SUM", "GROUP BY", "LIMIT"],
        "tables": ["order_items"],
    },
    {
        "q": "Show monthly order volume trend for 2017",
        "level": "Medium",
        "concepts": ["STRFTIME", "Date ranges", "GROUP BY"],
        "tables": ["orders"],
    },
    {
        "q": "Which state has the highest average freight value?",
        "level": "Medium",
        "concepts": ["JOIN", "AVG", "LIMIT 1"],
        "tables": ["order_items", "orders", "customers"],
    },
    {
        "q": "What are the top 10 product categories by revenue?",
        "level": "Medium",
        "concepts": ["Multi-JOIN", "SUM", "ORDER BY"],
        "tables": ["order_items", "products", "category_translation"],
    },
    {
        "q": "Average delivery time in days by state",
        "level": "Hard",
        "concepts": ["date_diff", "IS NOT NULL", "JOIN"],
        "tables": ["orders", "customers"],
    },
    {
        "q": "What's the average review score by product category?",
        "level": "Hard",
        "concepts": ["3× JOIN", "AVG", "GROUP BY"],
        "tables": ["order_reviews", "order_items", "products", "category_translation"],
    },
]
PROBLEM_INDEX = {p["q"]: i for i, p in enumerate(PROBLEMS)}

HINT_INTRO = (
    "Before jumping to the query itself, it helps to think about the question in three parts: "
    "which tables hold the data you need, how those tables connect to each other, and what "
    "filtering, grouping, or ordering turns the raw rows into the answer."
)

st.set_page_config(
    page_title="Talk to Your Data · SQL Playground",
    page_icon=":material/database:",
    layout="wide",
    initial_sidebar_state="auto",
)

# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

st.html(
    """
    <style>
    :root {
        --ink: #0F172A;
        --ink-2: #475569;
        --ink-3: #64748B;
        --line: #E2E8F0;
        --brand: #4F46E5;
        --brand-soft: #EEF2FF;
        --cyan: #06B6D4;
        --surface: #FFFFFF;
    }

    [data-testid="stHeader"] { background: transparent; }
    [data-testid="stMainBlockContainer"] {
        padding-top: 2.2rem;
        padding-bottom: 8rem;
        max-width: 1240px;
    }

    /* Keep the sidebar's collapse button hidden on desktop/tablet, but not on mobile. */
    @media (min-width: 768px) {
        [data-testid="stSidebarCollapseButton"] { display: none; }
    }

    /* ---------- Hero ---------- */
    .hero {
        position: relative;
        overflow: hidden;
        display: grid;
        grid-template-columns: 1.3fr 1fr;
        gap: 36px;
        align-items: center;
        padding: 40px 44px;
        border-radius: 22px;
        border: 1px solid var(--line);
        background:
            radial-gradient(900px 380px at -10% -20%, #E0E7FF 0%, transparent 60%),
            radial-gradient(700px 360px at 110% 120%, #CFFAFE 0%, transparent 60%),
            var(--surface);
        box-shadow: 0 1px 2px rgba(15,23,42,.04), 0 18px 40px -24px rgba(79,70,229,.35);
    }
    .hero::before {
        content: "";
        position: absolute;
        inset: 0;
        background-image:
            linear-gradient(rgba(148,163,184,.18) 1px, transparent 1px),
            linear-gradient(90deg, rgba(148,163,184,.18) 1px, transparent 1px);
        background-size: 28px 28px;
        -webkit-mask-image: radial-gradient(ellipse at 20% 0%, #000 0%, transparent 65%);
        mask-image: radial-gradient(ellipse at 20% 0%, #000 0%, transparent 65%);
        pointer-events: none;
    }
    .hero > * { position: relative; }
    .eyebrow {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 7px 13px;
        border-radius: 999px;
        border: 1px solid #E0E7FF;
        background: rgba(238,242,255,.85);
        color: var(--brand);
        font: 600 11.5px/1 Inter, sans-serif;
        letter-spacing: .09em;
        text-transform: uppercase;
    }
    .eyebrow .dot {
        width: 7px; height: 7px; border-radius: 50%;
        background: #10B981;
        box-shadow: 0 0 0 3px rgba(16,185,129,.22);
    }
    .hero h1 {
        margin: 18px 0 14px;
        padding: 0;
        font-family: "Plus Jakarta Sans", Inter, sans-serif;
        font-size: clamp(2rem, 3.5vw, 3rem);
        font-weight: 800;
        line-height: 1.07;
        letter-spacing: -.035em;
        color: var(--ink);
    }
    .hero h1 .grad {
        background: linear-gradient(92deg, #4F46E5 10%, #06B6D4 90%);
        -webkit-background-clip: text;
        background-clip: text;
        color: transparent;
    }
    .hero .lead {
        margin: 0;
        max-width: 540px;
        color: var(--ink-2);
        font: 400 1.05rem/1.65 Inter, sans-serif;
    }
    .stats { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 26px; }
    .stat {
        display: flex; flex-direction: column; gap: 2px;
        padding: 9px 14px;
        border-radius: 12px;
        border: 1px solid var(--line);
        background: rgba(255,255,255,.8);
        backdrop-filter: blur(6px);
    }
    .stat b { font: 700 1.15rem/1.2 "Plus Jakarta Sans", sans-serif; color: var(--ink); }
    .stat span { font: 500 .76rem/1.2 Inter, sans-serif; color: var(--ink-3); }

    .codewin {
        border-radius: 16px;
        overflow: hidden;
        background: #0B1020;
        border: 1px solid #1E2642;
        box-shadow: 0 30px 60px -28px rgba(11,16,32,.6);
        transform: perspective(1200px) rotateY(-4deg) rotateX(2deg);
    }
    .codewin .bar {
        display: flex; align-items: center; gap: 7px;
        padding: 12px 16px;
        background: #10162C;
        border-bottom: 1px solid #1E2642;
    }
    .codewin .bar i { width: 11px; height: 11px; border-radius: 50%; display: inline-block; }
    .codewin .fname { margin-left: 10px; font: 500 12px "JetBrains Mono", monospace; color: #94A3B8; }
    .codewin .run {
        margin-left: auto;
        padding: 4px 10px; border-radius: 6px;
        background: #34D399; color: #052E1C;
        font: 700 11px/1.4 Inter, sans-serif;
    }
    .codewin pre {
        margin: 0; padding: 18px 22px;
        background: transparent;
        color: #E2E8F0;
        font: 13.5px/1.8 "JetBrains Mono", monospace;
        white-space: pre; overflow-x: auto;
    }
    .codewin .ln { color: #334155; user-select: none; display: inline-block; width: 22px; }
    .tk-k { color: #C4B5FD; } .tk-f { color: #67E8F9; } .tk-n { color: #FDA4AF; }
    .tk-c { color: #64748B; font-style: italic; } .tk-i { color: #F8FAFC; }
    .codewin .out {
        display: flex; gap: 14px; align-items: center;
        padding: 10px 22px;
        border-top: 1px solid #1E2642;
        font: 500 12px "JetBrains Mono", monospace;
        color: #34D399;
    }
    .codewin .out span { color: #64748B; }

    @media (max-width: 900px) {
        .hero { grid-template-columns: 1fr; padding: 28px 22px; gap: 28px; }
        .codewin { transform: none; }
    }

    /* ---------- Section headings ---------- */
    .sec { margin: 6px 0 4px; }
    .sec h3 {
        margin: 0; padding: 0;
        font: 700 1.35rem/1.3 "Plus Jakarta Sans", sans-serif;
        letter-spacing: -.02em;
        color: var(--ink);
    }
    .sec p { margin: 4px 0 0; color: var(--ink-3); font: 400 .95rem/1.5 Inter, sans-serif; }

    /* ---------- Main navigation (segmented control) ---------- */
    .st-key-nav [role="radiogroup"] {
        gap: 4px;
        padding: 5px;
        border-radius: 14px;
        border: 1px solid var(--line);
        background: var(--surface);
        box-shadow: 0 1px 2px rgba(15,23,42,.04);
    }
    .st-key-nav button[role="radio"] {
        height: 40px;
        padding: 0 18px;
        border: none !important;
        border-radius: 10px !important;
        background: transparent;
        color: var(--ink-2);
        transition: background .15s ease, color .15s ease;
    }
    .st-key-nav button[role="radio"] p { font-weight: 600; font-size: .95rem; }
    .st-key-nav button[role="radio"]:hover { background: #F1F3F9; color: var(--ink); }
    .st-key-nav button[role="radio"][aria-checked="true"] {
        background: var(--brand);
        color: #fff;
        box-shadow: 0 6px 16px -6px rgba(79,70,229,.65);
    }

    /* Result tabs inside answers: compact pills. */
    div[class*="st-key-res_tabs"] [role="tablist"] {
        gap: 4px;
        width: fit-content;
        max-width: 100%;
        padding: 4px;
        border-radius: 11px;
        background: #F1F3F9;
    }
    div[class*="st-key-res_tabs"] [role="tab"] {
        height: 32px;
        padding: 0 14px;
        border-radius: 8px;
        transition: background .15s ease;
    }
    div[class*="st-key-res_tabs"] [role="tab"] p { font-size: .85rem; font-weight: 600; color: var(--ink-3); }
    div[class*="st-key-res_tabs"] [role="tab"]:hover { background: rgba(255,255,255,.7); }
    div[class*="st-key-res_tabs"] [role="tab"][aria-selected="true"] {
        background: var(--surface);
        box-shadow: 0 1px 3px rgba(15,23,42,.14);
    }
    div[class*="st-key-res_tabs"] [role="tab"][aria-selected="true"] p { color: var(--brand); }

    /* ---------- Practice cards ---------- */
    /* Equal-height cards across a row. */
    [data-testid="stHorizontalBlock"]:has([class*="st-key-pcard_"]) { align-items: stretch; }
    [data-testid="stColumn"]:has([class*="st-key-pcard_"]) > [data-testid="stVerticalBlock"],
    [data-testid="stLayoutWrapper"]:has(> [class*="st-key-pcard_"]) { height: 100%; }
    div[class*="st-key-pcard_"] {
        height: 100%;
        justify-content: space-between;
        background: var(--surface);
        border-radius: 16px !important;
        transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
    }
    div[class*="st-key-pcard_"]:hover {
        transform: translateY(-3px);
        border-color: #C7D2FE !important;
        box-shadow: 0 16px 32px -18px rgba(79,70,229,.45);
    }
    .ptitle {
        font: 650 1.02rem/1.4 "Plus Jakarta Sans", Inter, sans-serif;
        color: var(--ink);
        letter-spacing: -.01em;
    }
    div[class*="st-key-pcard_"] code { font-size: .74rem; }

    /* ---------- Workspace ---------- */
    .empty {
        text-align: center;
        padding: 48px 24px 28px;
        border: 1.5px dashed #CBD5E1;
        border-radius: 18px;
        background:
            radial-gradient(500px 200px at 50% 0%, #EEF2FF 0%, transparent 70%),
            var(--surface);
    }
    .empty .icon {
        width: 56px; height: 56px; margin: 0 auto 14px;
        display: grid; place-items: center;
        border-radius: 16px;
        background: linear-gradient(135deg, #4F46E5, #06B6D4);
        color: #fff; font: 700 20px "JetBrains Mono", monospace;
        box-shadow: 0 12px 24px -10px rgba(79,70,229,.6);
    }
    .empty h4 { margin: 0 0 6px; padding: 0; font: 700 1.2rem "Plus Jakarta Sans", sans-serif; color: var(--ink); }
    .empty p { margin: 0 auto; max-width: 460px; color: var(--ink-3); font: 400 .95rem/1.55 Inter, sans-serif; }

    [data-testid="stChatMessage"] {
        padding: 18px 20px;
        border-radius: 16px;
        border: 1px solid var(--line);
        background: var(--surface);
        box-shadow: 0 1px 2px rgba(15,23,42,.04);
        margin-bottom: 4px;
    }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
        background: linear-gradient(180deg, #F5F7FF, #EEF2FF);
        border-color: #E0E7FF;
    }
    [data-testid="stChatMessageAvatarUser"],
    [data-testid="stChatMessageAvatarAssistant"] {
        border-radius: 10px;
        color: #fff;
    }
    [data-testid="stChatMessageAvatarUser"] { background: #4F46E5; }
    [data-testid="stChatMessageAvatarAssistant"] { background: linear-gradient(135deg, #0B1020, #1E2A55); }

    /* Editor chrome above SQL solutions. */
    .editorbar {
        display: flex; align-items: center; gap: 7px;
        padding: 10px 14px;
        border: 1px solid var(--line);
        border-bottom: none;
        border-radius: 12px 12px 0 0;
        background: #F1F3F9;
    }
    .editorbar i { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
    .editorbar span { margin-left: 8px; font: 500 12px "JetBrains Mono", monospace; color: var(--ink-3); }
    div[class*="st-key-sqlwin_"] [data-testid="stCode"],
    div[class*="st-key-sqlwin_"] [data-testid="stCode"] pre {
        margin-top: 0;
        border-radius: 0 0 12px 12px;
    }
    div[class*="st-key-sqlwin_"] [data-testid="stCode"] pre { border: 1px solid var(--line); }

    .hintbox {
        padding: 14px 16px;
        border-radius: 12px;
        border: 1px solid #FDE68A;
        background: #FFFBEB;
        color: #78350F;
        font: 400 .92rem/1.6 Inter, sans-serif;
        margin-bottom: 6px;
    }
    .hintbox b { color: #92400E; }

    /* ---------- Dataset ---------- */
    [data-testid="stMetric"] {
        padding: 14px 18px;
        border-radius: 14px;
        border: 1px solid var(--line);
        background: var(--surface);
    }
    [data-testid="stMetricLabel"] p { color: var(--ink-3); font-weight: 500; }

    /* ---------- Chat input ---------- */
    [data-testid="stBottom"] { bottom: 18px; }
    [data-testid="stChatInput"] {
        border-radius: 16px;
        box-shadow: 0 18px 40px -18px rgba(15,23,42,.35);
    }

    /* ---------- Sidebar ---------- */
    .brand { display: flex; align-items: center; gap: 12px; padding: 4px 0 6px; }
    .brand .logo {
        width: 40px; height: 40px; border-radius: 12px;
        display: grid; place-items: center;
        background: linear-gradient(135deg, #6366F1, #06B6D4);
        color: #fff; font: 700 15px "JetBrains Mono", monospace;
        box-shadow: 0 8px 20px -8px rgba(99,102,241,.8);
    }
    .brand b { display: block; font: 700 1.02rem/1.2 "Plus Jakarta Sans", sans-serif; color: #F8FAFC; }
    .brand span { font: 500 .75rem/1.2 Inter, sans-serif; color: #64748B; }
    .side-label {
        margin: 14px 0 2px;
        font: 600 .7rem/1 Inter, sans-serif;
        letter-spacing: .12em;
        text-transform: uppercase;
        color: #64748B;
    }
    .cols { list-style: none; margin: 0; padding: 0; }
    .cols li {
        display: flex; justify-content: space-between; gap: 10px;
        padding: 5px 2px;
        border-bottom: 1px dashed #1E2642;
        font: 400 12px/1.4 "JetBrains Mono", monospace;
    }
    .cols li:last-child { border-bottom: none; }
    .cols .cn { color: #E2E8F0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .cols .ct { color: #818CF8; font-size: 10.5px; white-space: nowrap; }
    .side-foot { margin-top: 18px; font: 400 .75rem/1.5 Inter, sans-serif; color: #475569; }
    </style>
    """
)


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def get_api_key():
    try:
        if "GOOGLE_API_KEY" in st.secrets:
            return st.secrets["GOOGLE_API_KEY"]
    except FileNotFoundError:
        pass
    return os.environ.get("GOOGLE_API_KEY", "")


@st.cache_data
def load_sample_cache():
    try:
        with open(SAMPLE_CACHE_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


@st.cache_data(show_spinner=False)
def cached_table_columns():
    return get_table_columns()


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


def reset_session():
    st.session_state.session_start = time.time()
    st.session_state.query_count = 0
    st.session_state.messages = []
    st.session_state.solved = set()


if "session_start" not in st.session_state:
    reset_session()
elif time.time() - st.session_state.session_start > SESSION_TTL_SECONDS:
    reset_session()

st.session_state.setdefault("nav", TAB_PRACTICE)
st.session_state.setdefault("level_filter", "All")
# Re-assigning keeps these widgets' values when their section isn't rendered
# (Streamlit drops state for widgets that disappear from a run).
for _key in ("nav", "level_filter", "table_pick"):
    if _key in st.session_state:
        st.session_state[_key] = st.session_state[_key]

session_elapsed = time.time() - st.session_state.session_start
minutes_left = max(0, int((SESSION_TTL_SECONDS - session_elapsed) // 60))
queries_left = MAX_QUERIES_PER_SESSION - st.session_state.query_count

pending_toast = st.session_state.pop("pending_toast", None)
if pending_toast:
    st.toast(pending_toast[0], icon=pending_toast[1])


def queue_question(question):
    st.session_state.prefill_question = question
    st.session_state.nav = TAB_WORKSPACE


def clear_history():
    st.session_state.messages = []


table_names = get_table_names()
sample_cache = load_sample_cache()
server_api_key = get_api_key()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.html(
        """
        <div class="brand">
            <div class="logo">&gt;_</div>
            <div><b>Talk to Your Data</b><span>SQL playground · DuckDB + Gemini</span></div>
        </div>
        """
    )

    st.html('<div class="side-label">Your session</div>')
    used = st.session_state.query_count
    st.progress(min(used / MAX_QUERIES_PER_SESSION, 1.0), text=f"**{used}/{MAX_QUERIES_PER_SESSION}** queries used")
    solved_count = len(st.session_state.solved)
    st.progress(solved_count / len(PROBLEMS), text=f"**{solved_count}/{len(PROBLEMS)}** practice problems solved")
    if queries_left > 0:
        st.caption(f":material/schedule: Session resets in {minutes_left} min")
    else:
        st.caption(f":material/lock: Limit reached · resets in {minutes_left} min")

    st.html('<div class="side-label">Gemini API</div>')
    if server_api_key:
        api_key = server_api_key
        st.badge("API key configured", icon=":material/check_circle:", color="green")
    else:
        api_key = st.text_input("Google API Key", type="password", placeholder="Paste your key…")
        if not api_key:
            st.caption("Needed for your own questions. Practice problems run without it.")

    st.html('<div class="side-label">Schema</div>')
    for table, cols in cached_table_columns().items():
        with st.expander(table, icon=":material/table_chart:"):
            rows = "".join(
                f'<li><span class="cn">{html.escape(name)}</span><span class="ct">{html.escape(str(dtype))}</span></li>'
                for name, dtype in cols
            )
            st.html(f'<ul class="cols">{rows}</ul>')

    st.html('<div class="side-foot">Data: Olist Brazilian E-Commerce (Kaggle) · 2016–2018</div>')


# ---------------------------------------------------------------------------
# Hero
# ---------------------------------------------------------------------------

st.html(
    f"""
    <section class="hero">
        <div>
            <span class="eyebrow"><span class="dot"></span>Interactive SQL playground</span>
            <h1>Learn SQL by <span class="grad">asking questions</span></h1>
            <p class="lead">
                Ask anything in plain English. Get the DuckDB query that answers it, step-by-step
                hints that explain the logic, and the result as a table and chart, all on a
                real e-commerce dataset.
            </p>
            <div class="stats">
                <div class="stat"><b>{len(table_names)}</b><span>tables</span></div>
                <div class="stat"><b>~100K</b><span>real orders</span></div>
                <div class="stat"><b>{len(PROBLEMS)}</b><span>problems</span></div>
                <div class="stat"><b>{MAX_QUERIES_PER_SESSION}</b><span>queries/session</span></div>
            </div>
        </div>
        <div class="codewin">
            <div class="bar">
                <i style="background:#FF5F57"></i><i style="background:#FEBC2E"></i><i style="background:#28C840"></i>
                <span class="fname">top_sellers.sql</span>
                <span class="run">▶ RUN</span>
            </div>
<pre><span class="ln">1</span><span class="tk-c">-- "Top 10 sellers by total sales"</span>
<span class="ln">2</span><span class="tk-k">SELECT</span> <span class="tk-i">seller_id</span>,
<span class="ln">3</span>       <span class="tk-f">SUM</span>(<span class="tk-i">price</span>) <span class="tk-k">AS</span> <span class="tk-i">total_sales</span>
<span class="ln">4</span><span class="tk-k">FROM</span>   <span class="tk-i">order_items</span>
<span class="ln">5</span><span class="tk-k">GROUP BY</span> <span class="tk-i">seller_id</span>
<span class="ln">6</span><span class="tk-k">ORDER BY</span> <span class="tk-i">total_sales</span> <span class="tk-k">DESC</span>
<span class="ln">7</span><span class="tk-k">LIMIT</span>  <span class="tk-n">10</span>;</pre>
            <div class="out">✓ 10 rows <span>· DuckDB · in-process</span></div>
        </div>
    </section>
    """
)


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def section(title, subtitle):
    st.html(f'<div class="sec"><h3>{title}</h3><p>{subtitle}</p></div>')


def render_message(idx, msg):
    if msg["role"] == "user":
        with st.chat_message("user"):
            st.markdown(msg["content"])
        return

    with st.chat_message("assistant"):
        level = msg.get("level")
        if level == "error":
            st.error(msg["content"], icon=":material/error:")
            return
        if level == "warning":
            st.warning(msg["content"], icon=":material/info:")
            return
        if "df" not in msg:
            st.markdown(msg["content"])
            return

        df = msg["df"]
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.badge(f"{len(df):,} rows", icon=":material/table_rows:", color="primary")
            st.badge(f"{len(df.columns)} columns", icon=":material/view_column:", color="gray")
            if msg.get("cached"):
                st.badge("Instant · practice answer", icon=":material/bolt:", color="green")

        labels = [":material/table: Result"]
        if msg.get("chart") is not None:
            labels.append(":material/bar_chart: Chart")
        if msg.get("explanation"):
            labels.append(":material/lightbulb: Hints")
        labels.append(":material/code: SQL")

        tabs = dict(zip(labels, st.tabs(labels, key=f"res_tabs_{idx}")))

        with tabs[":material/table: Result"]:
            st.dataframe(df, hide_index=True)

        if ":material/bar_chart: Chart" in tabs:
            with tabs[":material/bar_chart: Chart"]:
                st.plotly_chart(msg["chart"], key=f"chart_{idx}")

        if ":material/lightbulb: Hints" in tabs:
            with tabs[":material/lightbulb: Hints"]:
                st.html(f'<div class="hintbox"><b>Think first.</b> {html.escape(HINT_INTRO)}</div>')
                st.markdown(msg["explanation"])

        with tabs[":material/code: SQL"]:
            with st.container(key=f"sqlwin_{idx}", gap=None):
                st.html(
                    '<div class="editorbar"><i style="background:#FF5F57"></i>'
                    '<i style="background:#FEBC2E"></i><i style="background:#28C840"></i>'
                    "<span>solution.sql</span></div>"
                )
                st.code(msg["sql"], language="sql", line_numbers=True)


def style_chart(fig):
    # Bars colored by their own category get a legend that just repeats the x-axis.
    if fig.data and all(t.type == "bar" and len(t.x) == 1 for t in fig.data):
        fig.update_layout(showlegend=False)
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=8, t=48, b=8),
        legend_title_text="",
        title_font=dict(size=15),
    )
    return fig


def answer_question(question, api_key):
    """Generate + run SQL for a question and return the assistant message to store."""
    cached = sample_cache.get(question)
    if not api_key and not cached:
        return {
            "role": "assistant",
            "content": "Add your Google API key in the sidebar to ask your own questions. "
            "Practice problems work without one.",
            "level": "warning",
        }

    st.session_state.query_count += 1
    try:
        if cached:
            sql = cached["sql"]
            explanation = cached.get("explanation", "")
        else:
            result = generate_sql(question, api_key)
            sql = result["sql"]
            explanation = result.get("explanation", "")

        if not sql.strip() or not any(t.lower() in sql.lower() for t in table_names):
            raise OutOfScopeQuestion(
                "I can only answer questions about this e-commerce dataset — "
                "try asking about orders, products, customers, sellers, payments, or reviews."
            )

        forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]
        sql_upper = sql.upper().strip()
        if any(sql_upper.startswith(kw) for kw in forbidden):
            raise ValueError("Only SELECT queries are allowed.")

        df = execute_query(sql)
        chart = auto_chart(df, question)

        if question in PROBLEM_INDEX:
            st.session_state.solved.add(question)

        msg = {
            "role": "assistant",
            "content": f"Found **{len(df)}** rows.",
            "sql": format_sql(sql),
            "df": df,
            "explanation": explanation,
            "cached": bool(cached),
        }
        if chart:
            msg["chart"] = style_chart(chart)
        return msg

    except OutOfScopeQuestion as e:
        return {"role": "assistant", "content": str(e), "level": "warning"}
    except json.JSONDecodeError:
        err = "Sorry, I couldn't parse the response. Please try rephrasing your question."
    except duckdb.Error as e:
        err = f"SQL Error: {e}"
    except genai_errors.APIError as e:
        err = f"API Error: {e.message}"
    except Exception as e:
        err = f"Error: {e}"
    return {"role": "assistant", "content": err, "level": "error"}


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

nav = st.segmented_control(
    "Section",
    [TAB_PRACTICE, TAB_WORKSPACE, TAB_DATASET],
    key="nav",
    required=True,
    label_visibility="collapsed",
)


def render_practice():
    with st.container(horizontal=True, vertical_alignment="bottom"):
        section(
            "Practice problems",
            "Each problem comes with a worked solution and hints. They run instantly, no API key needed.",
        )
        level_filter = st.segmented_control(
            "Difficulty",
            ["All", "Easy", "Medium", "Hard"],
            key="level_filter",
            label_visibility="collapsed",
        )

    visible = [
        (i, p) for i, p in enumerate(PROBLEMS) if level_filter in (None, "All") or p["level"] == level_filter
    ]
    per_row = 4
    for start in range(0, len(visible), per_row):
        cols = st.columns(per_row, gap="medium")
        for col, (i, p) in zip(cols, visible[start : start + per_row]):
            solved = p["q"] in st.session_state.solved
            with col, st.container(border=True, key=f"pcard_{i}"):
                with st.container(gap="small"):
                    badges = f":{LEVEL_COLORS[p['level']]}-badge[{p['level']}] :gray-badge[#{i + 1:02d}]"
                    if solved:
                        badges += " :violet-badge[:material/check: Solved]"
                    st.markdown(badges)
                    st.html(f'<div class="ptitle">{html.escape(p["q"])}</div>')
                    st.markdown(" ".join(f"`{c}`" for c in p["concepts"]))
                    st.caption(":material/table_chart: " + " · ".join(p["tables"]))
                st.button(
                    "Solve again" if solved else "Solve",
                    key=f"solve_{i}",
                    icon=":material/replay:" if solved else ":material/play_arrow:",
                    type="secondary" if solved else "primary",
                    width="stretch",
                    disabled=queries_left <= 0,
                    on_click=queue_question,
                    args=(p["q"],),
                )


def render_dataset():
    section(
        "Explore the dataset",
        "Browse a random sample from any table. Column types are listed in the sidebar schema.",
    )
    default_table = "customers" if "customers" in table_names else table_names[0]
    st.session_state.setdefault("table_pick", default_table)
    picked = st.pills("Table", table_names, key="table_pick", label_visibility="collapsed")
    selected_table = picked or default_table

    preview_cache_key = f"table_preview::{selected_table}"
    if preview_cache_key not in st.session_state:
        st.session_state[preview_cache_key] = get_table_preview(selected_table, limit=10)
    preview_df, total_rows = st.session_state[preview_cache_key]

    m1, m2, m3 = st.columns(3)
    m1.metric("Total rows", f"{total_rows:,}")
    m2.metric("Columns", len(preview_df.columns))
    m3.metric("Sample size", f"{len(preview_df)} rows")
    st.dataframe(preview_df, hide_index=True)


def render_workspace():
    with st.container(horizontal=True, vertical_alignment="bottom"):
        section(
            "Workspace",
            "Type a question below. Each answer has the result, a chart, hints and the SQL behind it.",
        )
        if st.session_state.messages:
            st.button("Clear", icon=":material/delete_sweep:", type="tertiary", on_click=clear_history)

    prefill = st.session_state.pop("prefill_question", None)

    if not st.session_state.messages and not prefill:
        st.html(
            """
            <div class="empty">
                <div class="icon">&gt;_</div>
                <h4>Your workspace is empty</h4>
                <p>Pick a problem from <b>Practice</b>, or type your own question in the box below.
                Try one of these to get started:</p>
            </div>
            """
        )
        with st.container(horizontal=True, horizontal_alignment="center", gap="small"):
            for p in PROBLEMS[:3]:
                st.button(
                    p["q"],
                    key=f"quick_{p['q']}",
                    icon=":material/bolt:",
                    disabled=queries_left <= 0,
                    on_click=queue_question,
                    args=(p["q"],),
                )

    for idx, msg in enumerate(st.session_state.messages):
        render_message(idx, msg)

    if queries_left <= 0:
        st.info(
            f"You've used all {MAX_QUERIES_PER_SESSION} queries for this session. "
            f"It resets automatically in {minutes_left} min.",
            icon=":material/lock:",
        )

    question = st.chat_input(
        "Ask a question about the data, e.g. “Which city has the most customers?”",
        key="chat_input",
        disabled=queries_left <= 0,
    )
    if prefill and not question:
        question = prefill

    if not question or queries_left <= 0:
        return

    st.session_state.messages.append({"role": "user", "content": question})
    count_before = st.session_state.query_count
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Writing and running your SQL…"):
            reply = answer_question(question, api_key)
    st.session_state.messages.append(reply)

    if st.session_state.query_count > count_before:
        remaining_after = MAX_QUERIES_PER_SESSION - st.session_state.query_count
        if remaining_after > 0:
            unit = "query" if remaining_after == 1 else "queries"
            st.session_state.pending_toast = (
                f"You have **{remaining_after}** {unit} left in this session.",
                ":material/hourglass_top:",
            )
        else:
            st.session_state.pending_toast = (
                "That was your last query for this session — it resets automatically in 30 min.",
                ":material/lock:",
            )

    # Rerun so the sidebar's counters and disabled states update immediately.
    st.rerun()


if nav == TAB_WORKSPACE:
    render_workspace()
elif nav == TAB_DATASET:
    render_dataset()
else:
    render_practice()
