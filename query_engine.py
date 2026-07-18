import os
import duckdb
import pandas as pd
import plotly.express as px
import sqlparse
from google import genai
from google.genai import types as genai_types
import json
from seed_data import seed_database, TABLES

DB_PATH = "ecommerce.duckdb"


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
1. Return ONLY a JSON object with two keys: "sql" (the SQL query string) and "explanation" (a short, numbered, step-by-step breakdown, in plain English, of how the query answers the question — e.g. "1. Start from the `orders` table...", "2. Join `order_items` to get...", "3. Group by ... and average ...". Keep each step to one short sentence, 3-5 steps total.).
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


def format_sql(sql: str) -> str:
    return sqlparse.format(sql, reindent=True, keyword_case="upper", indent_width=4)


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
    df = con.execute(f"SELECT * FROM {table_name} USING SAMPLE {limit} ROWS").fetchdf()
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
