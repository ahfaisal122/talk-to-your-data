import streamlit as st
import duckdb
import json
import os
import time
from google.genai import errors as genai_errors
from query_engine import (
    generate_sql,
    format_sql,
    execute_query,
    get_table_names,
    get_table_preview,
    get_schema_description,
    auto_chart,
)

SAMPLE_CACHE_PATH = "sample_cache.json"
MAX_QUERIES_PER_SESSION = 5
SESSION_TTL_SECONDS = 30 * 60

st.set_page_config(page_title="Talk to Your Data", page_icon="💬", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
    <style>
    /* Keep the sidebar permanently open on desktop/tablet widths.
       Below 768px, leave Streamlit's default collapsible behavior
       alone so mobile users can still hide it to see the main content. */
    @media (min-width: 768px) {
        [data-testid="stSidebarCollapseButton"] {
            display: none;
        }
    }

    /* Lift the chat input a little off the very bottom edge. */
    [data-testid="stBottom"] {
        bottom: 18px;
    }

    /* Colorful gradient underline beneath the page title. */
    h1 {
        padding-bottom: 0.3rem;
        border-bottom: 4px solid transparent;
        border-image: linear-gradient(90deg, #E8523F, #F5A623, #16A394, #7C5CFC) 1;
    }

    /* Highlight the "View Hints" expander (indigo) and "View SQL" expander (teal)
       so the two toggles stand out from the rest of the response. Targeted via
       st.expander(key=...), which Streamlit renders as a "st-key-<key>" class on
       the expander's wrapper div (not the expander itself, hence the descendant selector). */
    div[class*="st-key-hints"] [data-testid="stExpander"] {
        background-color: #F1EEFF;
        border: 1px solid #7C5CFC;
        border-left: 5px solid #7C5CFC;
        border-radius: 10px;
    }
    div[class*="st-key-sql"] [data-testid="stExpander"] {
        background-color: #E8FBF6;
        border: 1px solid #16A394;
        border-left: 5px solid #16A394;
        border-radius: 10px;
    }

    /* Colorful top accent on the table preview panel. */
    div[class*="st-key-table_preview"] {
        border-top: 4px solid #E8523F !important;
        border-radius: 10px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


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


HINT_INTRO = (
    "Before jumping to the query itself, it helps to think about the question in three parts: "
    "which tables hold the data you need, how those tables connect to each other, and what "
    "filtering, grouping, or ordering turns the raw rows into the answer."
)


def reset_session():
    st.session_state.session_start = time.time()
    st.session_state.query_count = 0
    st.session_state.messages = []


if "session_start" not in st.session_state:
    reset_session()
elif time.time() - st.session_state.session_start > SESSION_TTL_SECONDS:
    reset_session()

session_elapsed = time.time() - st.session_state.session_start
minutes_left = max(0, int((SESSION_TTL_SECONDS - session_elapsed) // 60))
queries_left = MAX_QUERIES_PER_SESSION - st.session_state.query_count

pending_toast = st.session_state.pop("pending_toast", None)
if pending_toast:
    st.toast(pending_toast[0], icon=pending_toast[1])

# --- UI ---

st.title("💬 Talk to Your Data")
st.caption("Ask questions about your e-commerce data in plain English")

with st.container(border=True, key="table_preview"):
    table_names = get_table_names()
    default_index = table_names.index("customers") if "customers" in table_names else 0
    selected_table = st.selectbox("Select table to explore data", table_names, index=default_index)

    preview_cache_key = f"table_preview::{selected_table}"
    if preview_cache_key not in st.session_state:
        st.session_state[preview_cache_key] = get_table_preview(selected_table, limit=10)
    preview_df, total_rows = st.session_state[preview_cache_key]
    st.dataframe(preview_df, width="stretch")

    if total_rows > len(preview_df):
        st.caption(f"more — showing {len(preview_df)} of {total_rows:,} rows")

st.divider()

with st.sidebar:
    if queries_left > 0:
        st.caption(f"🔢 {queries_left}/{MAX_QUERIES_PER_SESSION} queries left this session · resets in {minutes_left} min")
    else:
        st.caption(f"🔢 Session limit reached · resets in {minutes_left} min")

    st.header("⚙️ Settings")
    server_api_key = get_api_key()
    if server_api_key:
        api_key = server_api_key
        st.success("Api Key configured.")
    else:
        api_key = st.text_input("Google API Key", type="password")
        if not api_key:
            st.warning("Enter your Google API key to get started.")

    st.divider()
    st.header("📊 Database Info")
    if st.button("Show Schema"):
        st.code(get_schema_description(), language="sql")

    st.divider()
    st.markdown("**Sample questions:**")
    sample_questions = [
        "What are the top 10 product categories by revenue?",
        "Show monthly order volume trend for 2017",
        "What's the average review score by product category?",
        "Which state has the highest average freight value?",
        "Top 10 sellers by total sales",
        "Revenue breakdown by payment type",
        "How many orders were delivered vs canceled?",
        "Average delivery time in days by state",
    ]
    for q in sample_questions:
        if st.button(q, key=q, disabled=queries_left <= 0):
            st.session_state["prefill_question"] = q

for idx, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "df" in msg:
            st.dataframe(msg["df"], width="stretch")
        if msg.get("explanation"):
            st.markdown(HINT_INTRO)
            with st.expander("View Hints", key=f"hints_{idx}", icon="💡"):
                st.markdown(msg["explanation"])
        if "sql" in msg:
            with st.expander("View SQL", key=f"sql_{idx}", icon="🗄️"):
                st.code(msg["sql"], language="sql")
        if "chart" in msg:
            st.plotly_chart(msg["chart"], width="stretch")

sample_cache = load_sample_cache()

if queries_left <= 0:
    st.info(f"You've used all {MAX_QUERIES_PER_SESSION} queries for this session. It resets automatically in {minutes_left} min.")

prefill = st.session_state.pop("prefill_question", None)
question = st.chat_input("Ask a question about your e-commerce data...", key="chat_input", disabled=queries_left <= 0)
if prefill and not question:
    question = prefill

if question and queries_left <= 0:
    question = None

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    cached = sample_cache.get(question)

    if not api_key and not cached:
        err_msg = "Please enter your Google API key in the sidebar."
        st.session_state.messages.append({"role": "assistant", "content": err_msg})
        with st.chat_message("assistant"):
            st.warning(err_msg)
    else:
        st.session_state.query_count += 1
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    if cached:
                        sql = cached["sql"]
                        explanation = cached.get("explanation", "")
                    else:
                        result = generate_sql(question, api_key)
                        sql = result["sql"]
                        explanation = result.get("explanation", "")

                    forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]
                    sql_upper = sql.upper().strip()
                    if any(sql_upper.startswith(kw) for kw in forbidden):
                        raise ValueError("Only SELECT queries are allowed.")

                    df = execute_query(sql)
                    formatted_sql = format_sql(sql)

                    response_text = f"Found **{len(df)}** rows."
                    st.markdown(response_text)
                    st.dataframe(df, width="stretch")

                    if explanation:
                        st.markdown(HINT_INTRO)
                        with st.expander("View Hints", key="hints_live", icon="💡"):
                            st.markdown(explanation)

                    with st.expander("View SQL", key="sql_live", icon="🗄️"):
                        st.code(formatted_sql, language="sql")

                    chart = auto_chart(df, question)
                    if chart:
                        st.plotly_chart(chart, width="stretch")

                    msg_data = {
                        "role": "assistant",
                        "content": response_text,
                        "sql": formatted_sql,
                        "df": df,
                        "explanation": explanation,
                    }
                    if chart:
                        msg_data["chart"] = chart
                    st.session_state.messages.append(msg_data)

                except json.JSONDecodeError:
                    err = "Sorry, I couldn't parse the response. Please try rephrasing your question."
                    st.error(err)
                    st.session_state.messages.append({"role": "assistant", "content": err})
                except duckdb.Error as e:
                    err = f"SQL Error: {e}"
                    st.error(err)
                    st.session_state.messages.append({"role": "assistant", "content": err})
                except genai_errors.APIError as e:
                    err = f"API Error: {e.message}"
                    st.error(err)
                    st.session_state.messages.append({"role": "assistant", "content": err})
                except Exception as e:
                    err = f"Error: {e}"
                    st.error(err)
                    st.session_state.messages.append({"role": "assistant", "content": err})

        remaining_after = MAX_QUERIES_PER_SESSION - st.session_state.query_count
        if remaining_after > 0:
            unit = "query" if remaining_after == 1 else "queries"
            st.session_state.pending_toast = (f"You have only **{remaining_after}** {unit} left in this session.", "⏳")
        else:
            st.session_state.pending_toast = ("That was your last query for this session — it resets automatically in 30 min.", "🔒")

    # Rerun so the sidebar's query count/disabled states reflect this turn immediately,
    # instead of lagging one interaction behind (the sidebar renders before this block).
    st.rerun()
