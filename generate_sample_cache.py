"""One-time utility: pre-generate SQL + explanation for the sidebar sample
questions and write them to sample_cache.json, so the app can answer those
questions without hitting the Gemini API (and without a user-supplied key).

Run manually whenever the sample question list changes:
    python generate_sample_cache.py
"""
import json
import os
import time

import toml
from google.genai import errors as genai_errors

from query_engine import generate_sql

SAMPLE_QUESTIONS = [
    "What are the top 10 product categories by revenue?",
    "Show monthly order volume trend for 2017",
    "What's the average review score by product category?",
    "Which state has the highest average freight value?",
    "Top 10 sellers by total sales",
    "Revenue breakdown by payment type",
    "How many orders were delivered vs canceled?",
    "Average delivery time in days by state",
]


def load_api_key() -> str:
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if api_key:
        return api_key
    secrets_path = os.path.join(".streamlit", "secrets.toml")
    if os.path.exists(secrets_path):
        return toml.load(secrets_path).get("GOOGLE_API_KEY", "")
    return ""


def load_existing_cache() -> dict:
    if os.path.exists("sample_cache.json"):
        with open("sample_cache.json") as f:
            return json.load(f)
    return {}


def save_cache(cache: dict):
    with open("sample_cache.json", "w") as f:
        json.dump(cache, f, indent=2)


def main():
    api_key = load_api_key()
    if not api_key:
        raise SystemExit("No GOOGLE_API_KEY found in env or .streamlit/secrets.toml")

    cache = load_existing_cache()

    for question in SAMPLE_QUESTIONS:
        if question in cache:
            print(f"Already cached: {question}")
            continue

        print(f"Generating: {question}")
        for attempt in range(6):
            try:
                result = generate_sql(question, api_key)
                cache[question] = {"sql": result["sql"], "explanation": result.get("explanation", "")}
                save_cache(cache)
                break
            except genai_errors.ClientError as e:
                if e.code == 429 and attempt < 5:
                    print("  rate limited, waiting 20s...")
                    time.sleep(20)
                else:
                    raise
        time.sleep(15)

    print(f"Wrote sample_cache.json with {len(cache)} entries.")


if __name__ == "__main__":
    main()
