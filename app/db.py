import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv("CLAVEL_DB", Path(__file__).resolve().parent.parent / "clavel.db"))


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            email TEXT UNIQUE, age INTEGER, occupation TEXT, budget REAL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            category TEXT NOT NULL, price REAL NOT NULL CHECK(price >= 0),
            cost REAL NOT NULL DEFAULT 0 CHECK(cost >= 0), stock INTEGER NOT NULL DEFAULT 0 CHECK(stock >= 0),
            specs TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(customer_id) REFERENCES customers(id)
        );
        CREATE TABLE IF NOT EXISTS transaction_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, transaction_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL, quantity INTEGER NOT NULL CHECK(quantity > 0),
            unit_price REAL NOT NULL, FOREIGN KEY(transaction_id) REFERENCES transactions(id),
            FOREIGN KEY(product_id) REFERENCES products(id)
        );
        CREATE TABLE IF NOT EXISTS segments (
            customer_id INTEGER PRIMARY KEY, label INTEGER NOT NULL, model_version TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(customer_id) REFERENCES customers(id)
        );
        CREATE TABLE IF NOT EXISTS model_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, model_version TEXT NOT NULL,
            customer_count INTEGER NOT NULL, segment_count INTEGER NOT NULL,
            details TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)


def rows(query, params=()):
    with connect() as db:
        return [dict(r) for r in db.execute(query, params).fetchall()]


def one(query, params=()):
    with connect() as db:
        row = db.execute(query, params).fetchone()
        return dict(row) if row else None
