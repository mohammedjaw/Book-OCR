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
        CREATE TABLE IF NOT EXISTS book_pages (id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL, page_number INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', extracted_text TEXT, line_count INTEGER, model TEXT, thinking_level TEXT, error_message TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(book_id,page_number));
        INSERT OR IGNORE INTO settings(key,value) VALUES ('gemini_model','gemini-3.1-flash-lite'),('thinking_level','minimal'),('max_concurrent_pages','3');
        """)
        legacy = db.execute("SELECT value FROM settings WHERE key='gemini_api_key'").fetchone()
        if legacy and legacy[0] and not load_secrets().get('gemini_api_key'):
            save_secrets({'gemini_api_key': legacy[0]})
        db.execute("DELETE FROM settings WHERE key='gemini_api_key'")
        for book in db.execute("SELECT id,page_count FROM books"):
            db.executemany("INSERT OR IGNORE INTO book_pages(book_id,page_number,status,created_at,updated_at) VALUES(?,?,?,?,?)", [(book['id'], n, 'pending', '', '') for n in range(1, book['page_count'] + 1)])
