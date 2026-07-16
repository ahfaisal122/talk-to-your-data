"""Load the Olist Brazilian E-Commerce dataset (Kaggle) into DuckDB."""

import duckdb
import kagglehub

DB_PATH = "ecommerce.duckdb"

TABLES = {
    "customers": "olist_customers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}


def seed_database():
    data_dir = kagglehub.dataset_download("olistbr/brazilian-ecommerce")
    con = duckdb.connect(DB_PATH)

    for table_name, filename in TABLES.items():
        con.execute(f"DROP TABLE IF EXISTS {table_name}")
        csv_path = f"{data_dir}/{filename}"
        con.execute(
            f"CREATE TABLE {table_name} AS SELECT * FROM read_csv_auto('{csv_path}', sample_size=-1)"
        )
        count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        print(f"Loaded {table_name}: {count} rows")

    con.close()


if __name__ == "__main__":
    seed_database()
