"""One-off schema migration for the live factoryos.db.

There's no Alembic in this project — models.py + Base.metadata.create_all() only
ever creates missing *tables*, never adds columns to existing ones. This script
brings an existing SQLite file forward to match the current models.py by adding
any missing columns, without touching existing data. Idempotent — safe to run
more than once.

Usage: python3 migrate_schema.py
"""
import sqlite3
from dotenv import load_dotenv

load_dotenv()

from database import DATABASE_URL

if not DATABASE_URL.startswith('sqlite:///'):
    raise SystemExit(f"This migration script only supports SQLite; DATABASE_URL is {DATABASE_URL!r}")

DB_PATH = DATABASE_URL.replace('sqlite:///', '', 1)

# (table, column, sqlite_type, default_sql_or_None)
COLUMNS = [
    ('engagements',  'created_at',        'DATETIME', None),
    ('engagements',  'is_processing',     'INTEGER',  '0'),
    ('engagements',  'processing_error',  'TEXT',     None),
    ('transcripts',  'meeting_date',      'TEXT',     None),
    ('transcripts',  'duration_minutes',  'INTEGER',  None),
    ('transcripts',  'attendees',         'TEXT',     None),
    ('transcripts',  'summary',           'TEXT',     None),
    ('briefs',       'completeness',      'TEXT',     None),
    ('proposals',    'completeness',      'TEXT',     None),
]


def existing_columns(cur, table):
    cur.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def create_new_tables():
    """Base.metadata.create_all() only creates *missing* tables — safe to run against
    the live DB, it won't touch existing ones. Runs (and its SQLAlchemy engine
    connection fully closes) before the raw sqlite3 connection below opens, so the
    two never hold the file open concurrently."""
    from database import Base, engine
    import models  # noqa: F401 — registers models on Base.metadata
    Base.metadata.create_all(bind=engine)
    engine.dispose()


def main():
    create_new_tables()

    print(f"Migrating {DB_PATH} ...")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        added = []
        for table, column, sqltype, default in COLUMNS:
            if column in existing_columns(cur, table):
                continue
            ddl = f"ALTER TABLE {table} ADD COLUMN {column} {sqltype}"
            if default is not None:
                ddl += f" DEFAULT {default}"
            cur.execute(ddl)
            added.append(f"{table}.{column}")
        conn.commit()
        if added:
            print("Added columns:", ", ".join(added))
        else:
            print("Already up to date — no columns added.")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
