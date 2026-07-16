import streamlit as st
import duckdb
import pandas as pd
import plotly.express as px
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
import json
import os
from seed_data import seed_database, TABLES

DB_PATH = "ecommerce.duckdb"

st.set_page_config(page_title="Talk to Your Data", page_icon="💬", layout="wide")


def get_api_key():
    try:
        if "GOOGLE_API_KEY" in st.secrets:
            return st.secrets["GOOGLE_API_KEY"]
    except FileNotFoundError:
        pass
    return os.environ.get("GOOGLE_API_KEY", "")


def _has_expected_tables() -> bool:
    try:
        con = duckdb.connect(DB_PATH, read_only=True)
    except duckdb.Error:
        return False
    try:
        existing = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    except duckdb.Error:
        return False
    finally:
        con.close()
    return set(TABLES.keys()).issubset(existing)


def get_db():
    if not os.path.exists(DB_PATH) or not _has_expected_tables():
        seed_database()
    return duckdb.connect(DB_PATH, read_only=True)


def get_schema_description():
    con = get_db()
    tables = con.execute("SHOW TABLES").fetchall()
    schema_parts = []
    for (table_name,) in tables:
        cols = con.execute(f"DESCRIBE {table_name}").fetchall()
        col_descriptions = [f"  - {col[0]} ({col[1]})" for col in cols]
        sample = con.execute(f"SELECT * FROM {table_name} LIMIT 3").fetchdf()
        schema_parts.append(
            f"Table: {table_name}\nColumns:\n" + "\n".join(col_descriptions)
            + f"\nSample rows:\n{sample.to_string(index=False)}"
        )
    con.close()
    return "\n\n".join(schema_parts)


SYSTEM_PROMPT = """You are a SQL expert assistant. You convert natural language questions into SQL queries for a DuckDB database.

Here is the database schema:

{schema}

Rules:
1. Return ONLY a JSON object with two keys: "sql" (the SQL query string) and "explanation" (a brief explanation of what the query does).
2. Use DuckDB SQL syntax.
3. Always use table and column names exactly as shown in the schema.
4. For date filtering, base ranges on the actual values shown in the sample rows above. Treat {reference_date} as "today" when interpreting relative time phrases like "last quarter" or "this year".
5. There is no total-amount column on `orders`. For revenue/sales amounts, sum `order_items.price` (add `freight_value` for shipping revenue too) or sum `order_payments.payment_value`, joining via `order_id` as needed — pick whichever matches the question.
6. Product categories in `products.product_category_name` are in Portuguese; join `category_translation` on that column to get English names when relevant.
7. Always limit results to at most 50 rows unless the user asks for more.
8. Do NOT use any DML statements (INSERT, UPDATE, DELETE, DROP, etc.) — only SELECT queries.
9. Return valid JSON only, no markdown code fences."""


def get_reference_date() -> str:
    try:
        con = get_db()
        result = con.execute("SELECT MAX(order_purchase_timestamp) FROM orders").fetchone()
        con.close()
        if result and result[0]:
            return str(result[0])[:10]
    except duckdb.Error:
        pass
    return "today"


def generate_sql(question: str, api_key: str) -> dict:
    client = genai.Client(api_key=api_key)
    schema = get_schema_description()
    reference_date = get_reference_date()

    response = client.models.generate_content(
        model="gemini-flash-latest",
        contents=question,
        config=genai_types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT.format(schema=schema, reference_date=reference_date),
            response_mime_type="application/json",
        ),
    )

    response_text = (response.text or "").strip()
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    return json.loads(response_text)


def execute_query(sql: str) -> pd.DataFrame:
    con = get_db()
    df = con.execute(sql).fetchdf()
    con.close()
    return df


def get_table_names() -> list:
    con = get_db()
    tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]
    con.close()
    return tables


def get_table_preview(table_name: str, limit: int = 15):
    con = get_db()
    df = con.execute(f"SELECT * FROM {table_name} LIMIT {limit}").fetchdf()
    total_rows = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    con.close()
    return df, total_rows


def auto_chart(df: pd.DataFrame, question: str):
    if len(df) == 0 or len(df.columns) < 2:
        return None

    num_cols = df.select_dtypes(include="number").columns.tolist()
    cat_cols = [c for c in df.columns if c not in num_cols]
    date_cols = [c for c in df.columns if any(k in c.lower() for k in ["date", "month", "year", "quarter", "week"])]

    # Prefer measure columns (e.g. revenue, count) over id-like columns (e.g. product_id)
    # when picking the default numeric axis.
    id_cols = [c for c in num_cols if c.lower() == "id" or c.lower().endswith("_id")]
    metric_cols = [c for c in num_cols if c not in id_cols]
    ranked_num_cols = metric_cols + id_cols

    if date_cols and ranked_num_cols:
        x_col = date_cols[0]
        y_col = ranked_num_cols[0]
        color_col = cat_cols[0] if cat_cols and cat_cols[0] != x_col else None
        if len(df) > 20:
            return px.line(df, x=x_col, y=y_col, color=color_col, title="Trend")
        return px.bar(df, x=x_col, y=y_col, color=color_col, title="Results")

    if cat_cols and ranked_num_cols:
        x_col = cat_cols[0]
        y_col = ranked_num_cols[0]
        if len(df) <= 8 and "percent" not in question.lower():
            return px.bar(df, x=x_col, y=y_col, color=x_col, title="Results")
        if "percent" in question.lower() or "share" in question.lower() or "proportion" in question.lower():
            return px.pie(df, names=x_col, values=y_col, title="Distribution")
        return px.bar(df, x=x_col, y=y_col, color=x_col, title="Results")

    if len(ranked_num_cols) >= 2:
        return px.scatter(df, x=ranked_num_cols[0], y=ranked_num_cols[1], title="Scatter")

    return None


# --- UI ---

st.title("💬 Talk to Your Data")
st.caption("Ask questions about your e-commerce data in plain English")

with st.container(border=True):
    table_names = get_table_names()
    default_index = table_names.index("customers") if "customers" in table_names else 0
    selected_table = st.selectbox("Select table", table_names, index=default_index)

    preview_df, total_rows = get_table_preview(selected_table, limit=15)
    st.dataframe(preview_df, width="stretch")

    if total_rows > len(preview_df):
        st.caption(f"more — showing {len(preview_df)} of {total_rows:,} rows")

st.divider()

with st.sidebar:
    st.header("⚙️ Settings")
    server_api_key = get_api_key()
    if server_api_key:
        api_key = server_api_key
        st.success("Google API key configured.")
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
        if st.button(q, key=q):
            st.session_state["prefill_question"] = q

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "df" in msg:
            st.dataframe(msg["df"], width="stretch")
        if "chart" in msg:
            st.plotly_chart(msg["chart"], width="stretch")
        if "sql" in msg:
            with st.expander("View SQL"):
                st.code(msg["sql"], language="sql")

prefill = st.session_state.pop("prefill_question", None)
question = st.chat_input("Ask a question about your data...", key="chat_input")
if prefill and not question:
    question = prefill

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    if not api_key:
        err_msg = "Please enter your Google API key in the sidebar."
        st.session_state.messages.append({"role": "assistant", "content": err_msg})
        with st.chat_message("assistant"):
            st.warning(err_msg)
    else:
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    result = generate_sql(question, api_key)
                    sql = result["sql"]
                    explanation = result.get("explanation", "")

                    forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]
                    sql_upper = sql.upper().strip()
                    if any(sql_upper.startswith(kw) for kw in forbidden):
                        raise ValueError("Only SELECT queries are allowed.")

                    df = execute_query(sql)

                    response_text = f"**{explanation}**\n\nFound **{len(df)}** rows."
                    st.markdown(response_text)
                    st.dataframe(df, width="stretch")

                    chart = auto_chart(df, question)
                    if chart:
                        st.plotly_chart(chart, width="stretch")

                    with st.expander("View SQL"):
                        st.code(sql, language="sql")

                    msg_data = {"role": "assistant", "content": response_text, "sql": sql, "df": df}
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
