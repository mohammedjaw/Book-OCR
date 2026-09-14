import sqlite3
from pathlib import Path
from .secrets import load_secrets, save_secrets

DB = Path(__file__).parent.parent / "data" / "library.db"

class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()

def connect():
    db = sqlite3.connect(DB, timeout=30, factory=Connection)
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
        CREATE VIRTUAL TABLE IF NOT EXISTS page_search USING fts5(page_id UNINDEXED, exact_text, normalized_text);
        INSERT OR IGNORE INTO settings(key,value) VALUES ('gemini_model','gemini-3.1-flash-lite'),('thinking_level','minimal'),('max_concurrent_pages','2'),('ui_language','ar');
        """)
        init_collections(db)
        columns = {r['name'] for r in db.execute('PRAGMA table_info(book_pages)')}
        if 'error_kind' not in columns:
            db.execute("ALTER TABLE book_pages ADD COLUMN error_kind TEXT")
        db.execute("CREATE INDEX IF NOT EXISTS pages_book_status ON book_pages(book_id,status,page_number)")
        db.execute("INSERT OR IGNORE INTO settings VALUES ('ocr_key_mode','single')")
        db.execute("INSERT OR IGNORE INTO settings VALUES ('ocr_pool_ids','[]')")
        legacy = db.execute("SELECT value FROM settings WHERE key='gemini_api_key'").fetchone()
        if legacy and legacy[0] and not load_secrets().get('gemini_api_key'):
            values = load_secrets(); values['gemini_api_key'] = legacy[0]; save_secrets(values)
        db.execute("DELETE FROM settings WHERE key='gemini_api_key'")
        for book in db.execute("SELECT id,page_count FROM books"):
            db.executemany("INSERT OR IGNORE INTO book_pages(book_id,page_number,status,created_at,updated_at) VALUES(?,?,?,?,?)", [(book['id'], n, 'pending', '', '') for n in range(1, book['page_count'] + 1)])

def init_collections(db):
    """Add local grouping metadata without changing existing book/page values."""
    db.execute("CREATE TABLE IF NOT EXISTS collections (id INTEGER PRIMARY KEY, uuid TEXT UNIQUE NOT NULL, title TEXT NOT NULL, created_at TEXT NOT NULL)")
    columns = {r['name'] for r in db.execute('PRAGMA table_info(books)')}
    if 'collection_id' not in columns:
        db.execute('ALTER TABLE books ADD COLUMN collection_id INTEGER REFERENCES collections(id) ON DELETE RESTRICT')
    if 'volume_number' not in columns:
        db.execute('ALTER TABLE books ADD COLUMN volume_number INTEGER CHECK(volume_number IS NULL OR volume_number > 0)')
    db.execute('CREATE INDEX IF NOT EXISTS books_collection_order ON books(collection_id,volume_number,id)')
    # Enforce integrity even on existing connections that do not enable foreign_keys.
    db.executescript('''
    CREATE TRIGGER IF NOT EXISTS collection_delete_guard BEFORE DELETE ON collections
    WHEN EXISTS(SELECT 1 FROM books WHERE collection_id=OLD.id)
    BEGIN SELECT RAISE(ABORT, 'Collection is not empty'); END;
    CREATE TRIGGER IF NOT EXISTS book_collection_insert BEFORE INSERT ON books
    WHEN NEW.collection_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM collections WHERE id=NEW.collection_id)
    BEGIN SELECT RAISE(ABORT, 'Collection not found'); END;
    CREATE TRIGGER IF NOT EXISTS book_collection_update BEFORE UPDATE OF collection_id ON books
    WHEN NEW.collection_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM collections WHERE id=NEW.collection_id)
    BEGIN SELECT RAISE(ABORT, 'Collection not found'); END;
    ''')
