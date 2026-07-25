"""SQLite persistence layer for NCLAT cause list data."""

import sqlite3
import json
import os
from datetime import datetime
from typing import Optional, List, Dict

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "cause_lists.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cause_lists (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date        TEXT NOT NULL,
                court_key   TEXT NOT NULL,
                list_type   TEXT NOT NULL CHECK(list_type IN ('main', 'supplementary')),
                pdf_url     TEXT,
                items       TEXT NOT NULL,  -- JSON array
                scraped_at  TEXT NOT NULL,
                UNIQUE(date, court_key, list_type)
            );

            CREATE TABLE IF NOT EXISTS available_dates (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date        TEXT NOT NULL UNIQUE,
                label       TEXT,
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS scrape_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at  TEXT NOT NULL,
                finished_at TEXT,
                status      TEXT,
                message     TEXT
            );
        """)


def upsert_cause_list(date: str, court_key: str, list_type: str,
                      pdf_url: str, items: list) -> None:
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO cause_lists (date, court_key, list_type, pdf_url, items, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(date, court_key, list_type)
            DO UPDATE SET pdf_url=excluded.pdf_url,
                          items=excluded.items,
                          scraped_at=excluded.scraped_at
        """, (date, court_key, list_type, pdf_url, json.dumps(items), now))


def upsert_dates(dates: list) -> None:
    """dates = [{'date': 'YYYY-MM-DD', 'label': 'Today'}, ...]"""
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        # Clear old entries so stale dates don't persist
        conn.execute("DELETE FROM available_dates")
        conn.executemany(
            "INSERT OR REPLACE INTO available_dates (date, label, updated_at) VALUES (?,?,?)",
            [(d["date"], d.get("label", ""), now) for d in dates]
        )


def get_available_dates() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, label FROM available_dates ORDER BY date"
        ).fetchall()
    return [dict(r) for r in rows]


def get_cause_list(date: str, court_key: str) -> dict:
    """Returns {'supplementary': [...], 'main': [...]} for a date+court."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT list_type, items, pdf_url, scraped_at FROM cause_lists "
            "WHERE date=? AND court_key=?",
            (date, court_key)
        ).fetchall()

    result = {"supplementary": [], "main": [], "pdf_urls": {}}
    for row in rows:
        result[row["list_type"]] = json.loads(row["items"])
        result["pdf_urls"][row["list_type"]] = row["pdf_url"]
    return result


def log_scrape(started_at: str, status: str, message: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO scrape_log (started_at, finished_at, status, message) "
            "VALUES (?, ?, ?, ?)",
            (started_at, datetime.utcnow().isoformat(), status, message)
        )


def get_last_scrape() -> Optional[Dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM scrape_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None
