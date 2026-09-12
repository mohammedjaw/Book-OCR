import sqlite3
from pathlib import Path
from .secrets import load_secrets, save_secrets

DB = Path(__file__).parent.parent / "data" / "library.db"

def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    DB.parent.mkdir(exist_ok=True)
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS books (id INTEGER PRIMARY KEY, book_uuid TEXT UNIQUE NOT NULL,
          title TEXT NOT NULL, original_filename TEXT NOT NULL, stored_filename TEXT NOT NULL,
          file_path TEXT NOT NULL, file_hash TEXT UNIQUE NOT NULL, page_count INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'جاهز', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '');
        INSERT OR IGNORE INTO settings(key,value) VALUES ('gemini_model','gemini-3.1-flash-lite'),('thinking_level','minimal');
        """)
        legacy = db.execute("SELECT value FROM settings WHERE key='gemini_api_key'").fetchone()
        if legacy and legacy[0] and not load_secrets().get('gemini_api_key'):
            save_secrets({'gemini_api_key': legacy[0]})
        db.execute("DELETE FROM settings WHERE key='gemini_api_key'")
