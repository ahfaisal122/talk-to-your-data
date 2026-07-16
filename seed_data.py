"""Generate a realistic e-commerce dataset and seed it into DuckDB."""

import duckdb
import random
from datetime import datetime, timedelta

DB_PATH = "ecommerce.duckdb"

CATEGORIES = ["Electronics", "Clothing", "Home & Kitchen", "Books", "Sports", "Beauty", "Toys", "Food & Grocery"]

PRODUCTS = {
    "Electronics": [
        ("Wireless Earbuds", 49.99), ("Bluetooth Speaker", 79.99), ("USB-C Hub", 34.99),
        ("Mechanical Keyboard", 129.99), ("Webcam HD", 59.99), ("Portable Charger", 29.99),
        ("Smart Watch", 199.99), ("Noise Cancelling Headphones", 249.99),
    ],
    "Clothing": [
        ("Cotton T-Shirt", 19.99), ("Denim Jeans", 49.99), ("Running Shoes", 89.99),
        ("Winter Jacket", 129.99), ("Casual Hoodie", 39.99), ("Formal Shirt", 44.99),
    ],
    "Home & Kitchen": [
        ("Coffee Maker", 69.99), ("Air Fryer", 99.99), ("Blender", 44.99),
        ("Instant Pot", 89.99), ("Knife Set", 59.99), ("Water Filter", 29.99),
    ],
    "Books": [
        ("Python Programming", 39.99), ("Data Science Handbook", 44.99), ("AI Fundamentals", 34.99),
        ("SQL Mastery", 29.99), ("Cloud Architecture", 49.99), ("Machine Learning Guide", 54.99),
    ],
    "Sports": [
        ("Yoga Mat", 24.99), ("Dumbbells Set", 79.99), ("Resistance Bands", 14.99),
        ("Running Watch", 149.99), ("Protein Shaker", 12.99), ("Jump Rope", 9.99),
    ],
    "Beauty": [
        ("Moisturizer", 24.99), ("Sunscreen SPF 50", 14.99), ("Hair Dryer", 49.99),
        ("Face Wash", 12.99), ("Vitamin C Serum", 29.99), ("Lip Balm Set", 9.99),
    ],
    "Toys": [
        ("LEGO Set", 59.99), ("Board Game", 29.99), ("Puzzle 1000pc", 19.99),
        ("RC Car", 44.99), ("Stuffed Animal", 14.99), ("Art Kit", 24.99),
    ],
    "Food & Grocery": [
        ("Organic Coffee Beans", 18.99), ("Granola Mix", 8.99), ("Protein Bars Pack", 24.99),
        ("Green Tea Box", 12.99), ("Dark Chocolate Set", 15.99), ("Mixed Nuts", 14.99),
    ],
}

REGIONS = ["North America", "Europe", "Asia Pacific", "Latin America", "Middle East"]
COUNTRIES = {
    "North America": ["United States", "Canada", "Mexico"],
    "Europe": ["United Kingdom", "Germany", "France", "Spain", "Italy"],
    "Asia Pacific": ["Japan", "Australia", "India", "South Korea", "Singapore"],
    "Latin America": ["Brazil", "Argentina", "Colombia"],
    "Middle East": ["UAE", "Saudi Arabia", "Israel"],
}
PAYMENT_METHODS = ["Credit Card", "Debit Card", "PayPal", "Apple Pay", "Google Pay"]
STATUSES = ["Completed", "Completed", "Completed", "Completed", "Shipped", "Processing", "Returned", "Cancelled"]


def seed_database():
    con = duckdb.connect(DB_PATH)

    con.execute("DROP TABLE IF EXISTS orders")
    con.execute("DROP TABLE IF EXISTS products")
    con.execute("DROP TABLE IF EXISTS customers")

    con.execute("""
        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY,
            name VARCHAR,
            email VARCHAR,
            region VARCHAR,
            country VARCHAR,
            signup_date DATE
        )
    """)

    con.execute("""
        CREATE TABLE products (
            product_id INTEGER PRIMARY KEY,
            name VARCHAR,
            category VARCHAR,
            price DECIMAL(10, 2)
        )
    """)

    con.execute("""
        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY,
            customer_id INTEGER,
            product_id INTEGER,
            quantity INTEGER,
            total_amount DECIMAL(10, 2),
            order_date DATE,
            status VARCHAR,
            payment_method VARCHAR,
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
            FOREIGN KEY (product_id) REFERENCES products(product_id)
        )
    """)

    random.seed(42)

    first_names = ["Emma", "Liam", "Olivia", "Noah", "Ava", "Elijah", "Sophia", "James",
                   "Isabella", "William", "Mia", "Benjamin", "Charlotte", "Lucas", "Amelia",
                   "Henry", "Harper", "Alexander", "Evelyn", "Daniel", "Yuki", "Raj", "Fatima",
                   "Carlos", "Aisha", "Mohammed", "Priya", "Luis", "Chen", "Maria"]
    last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
                  "Rodriguez", "Martinez", "Anderson", "Taylor", "Thomas", "Hernandez", "Moore",
                  "Martin", "Lee", "Clark", "Lewis", "Walker", "Tanaka", "Kumar", "Hassan",
                  "Silva", "Kim", "Nakamura", "Patel", "Santos", "Wang", "Lopez"]

    customers = []
    for i in range(1, 501):
        region = random.choice(REGIONS)
        country = random.choice(COUNTRIES[region])
        signup = datetime(2023, 1, 1) + timedelta(days=random.randint(0, 730))
        name = f"{random.choice(first_names)} {random.choice(last_names)}"
        email = f"{name.lower().replace(' ', '.')}+{i}@example.com"
        customers.append((i, name, email, region, country, signup.date()))

    con.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?)", customers)

    products = []
    pid = 1
    for category, items in PRODUCTS.items():
        for name, price in items:
            products.append((pid, name, category, price))
            pid += 1
    con.executemany("INSERT INTO products VALUES (?, ?, ?, ?)", products)

    orders = []
    for i in range(1, 5001):
        cust = random.choice(customers)
        prod = random.choice(products)
        qty = random.choices([1, 2, 3, 4, 5], weights=[50, 25, 15, 7, 3])[0]
        total = round(prod[3] * qty * random.uniform(0.85, 1.15), 2)
        cust_signup = datetime.combine(cust[5], datetime.min.time())
        earliest = max(cust_signup, datetime(2023, 6, 1))
        order_date = earliest + timedelta(days=random.randint(0, (datetime(2025, 6, 30) - earliest).days))
        status = random.choice(STATUSES)
        payment = random.choice(PAYMENT_METHODS)
        orders.append((i, cust[0], prod[0], qty, total, order_date.date(), status, payment))

    con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)", orders)

    print(f"Seeded {len(customers)} customers, {len(products)} products, {len(orders)} orders")

    result = con.execute("SELECT COUNT(*) FROM orders").fetchone()
    print(f"Verification — orders in DB: {result[0]}")

    con.close()


if __name__ == "__main__":
    seed_database()
