"""SQLite storage. Set DB_PATH to a persistent volume in production."""
import os
import sqlite3

DB_PATH = os.getenv("DB_PATH", "leadforge.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, company TEXT, email TEXT,
  created TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY, client_id INTEGER, title TEXT, icp_json TEXT,
  target_count INTEGER, price_usd REAL DEFAULT 0, plan TEXT DEFAULT 'one_time',
  status TEXT DEFAULT 'draft', paid INTEGER DEFAULT 0, active INTEGER DEFAULT 1,
  cost_usd REAL DEFAULT 0, review_minutes REAL DEFAULT 0,
  created TEXT DEFAULT (datetime('now')), delivered_at TEXT);
CREATE TABLE IF NOT EXISTS leads(
  id INTEGER PRIMARY KEY, order_id INTEGER, company TEXT, website TEXT, domain TEXT,
  contact_name TEXT, title TEXT, email TEXT, country TEXT, source_url TEXT,
  confidence INTEGER DEFAULT 0, status TEXT DEFAULT 'new', flags TEXT, notes TEXT,
  created TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS suppression(
  id INTEGER PRIMARY KEY, value TEXT UNIQUE, reason TEXT,
  created TEXT DEFAULT (datetime('now')));
"""


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with conn() as c:
        c.executescript(SCHEMA)


def q(sql, args=()):
    with conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def x(sql, args=()):
    with conn() as c:
        return c.execute(sql, args).lastrowid
