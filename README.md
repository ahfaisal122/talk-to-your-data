# Talk to Your Data 💬

Ask questions about an e-commerce dataset in plain English and get back SQL, results, and an auto-generated chart. Built with Streamlit, DuckDB, and Google's Gemini API.

## How it works

1. You ask a question (e.g. "What are the top 5 products by revenue?")
2. Gemini converts it into a DuckDB SQL query based on the schema
3. The query runs against a local DuckDB database
4. Results are shown as a table and an auto-picked chart



## Tech stack

- [Streamlit](https://streamlit.io) — UI
- [DuckDB](https://duckdb.org) — local analytical database
- [Google Gemini](https://ai.google.dev) — natural language → SQL
- [Plotly](https://plotly.com/python/) — charts
