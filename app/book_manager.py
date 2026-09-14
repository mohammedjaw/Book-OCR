import hashlib, re, shutil, uuid
from datetime import datetime
from pathlib import Path
import pymupdf
from .database import connect

BOOKS = Path(__file__).parent.parent / "books"
def safe_name(name):
    return re.sub(r"[^\w .-]", "_", Path(name).stem)[:100] + ".pdf"
def add_book(upload, title=None):
    data = upload.file.read()
    if not data.startswith(b"%PDF"):
        raise ValueError("الملف ليس PDF صالحًا")
    digest = hashlib.sha256(data).hexdigest()
    title = (title or Path(upload.filename).stem).strip()
    if not title: raise ValueError("اسم الكتاب لا يمكن أن يكون فارغًا")
    with connect() as db:
        if db.execute("SELECT 1 FROM books WHERE file_hash=?", (digest,)).fetchone():
            raise ValueError("هذا الكتاب موجود مسبقًا في المكتبة")
    book_uuid = str(uuid.uuid4()); filename = f"{book_uuid}_{safe_name(upload.filename)}"
    BOOKS.mkdir(parents=True,exist_ok=True)
    target = BOOKS / filename; target.write_bytes(data)
    try:
        from .ocr_service import _render_lock
        with _render_lock, pymupdf.open(target) as document:
            if document.needs_pass: raise ValueError('Encrypted PDF')
            pages = len(document)
            if not pages: raise ValueError('Empty PDF')
    except Exception:
        target.unlink(missing_ok=True); raise ValueError("تعذر قراءة ملف PDF")
    now = datetime.now().isoformat(timespec="seconds")
    try:
        with connect() as db:
            cur = db.execute("INSERT INTO books(book_uuid,title,original_filename,stored_filename,file_path,file_hash,page_count,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (book_uuid, title, upload.filename, filename, str(target), digest, pages, "جاهز", now, now))
            db.executemany("INSERT INTO book_pages(book_id,page_number,status,created_at,updated_at) VALUES(?,?,?,?,?)", [(cur.lastrowid, n, 'pending', now, now) for n in range(1, pages + 1)])
    except Exception:
        target.unlink(missing_ok=True)
        raise ValueError('Could not store the book; no partial book was added.') from None
    return book_uuid


def recover_interrupted_deletions():
    # Restore an original if a crash interrupted deletion before its DB commit.
    with connect() as db: paths = [Path(r[0]) for r in db.execute('SELECT file_path FROM books')]
    for original in paths:
        original = original.resolve()
        if original.parent != BOOKS.resolve(): continue
        parked = original.with_name(original.name + '.deleting')
        if not original.exists() and parked.is_file(): parked.rename(original)
