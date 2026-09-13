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
    target = BOOKS / filename; target.write_bytes(data)
    try: pages = len(pymupdf.open(target))
    except Exception:
        target.unlink(missing_ok=True); raise ValueError("تعذر قراءة ملف PDF")
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as db:
        cur = db.execute("INSERT INTO books(book_uuid,title,original_filename,stored_filename,file_path,file_hash,page_count,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
          (book_uuid, title, upload.filename, filename, str(target), digest, pages, "جاهز", now, now))
        db.executemany("INSERT INTO book_pages(book_id,page_number,status,created_at,updated_at) VALUES(?,?,?,?,?)", [(cur.lastrowid, n, 'pending', now, now) for n in range(1, pages + 1)])
    return book_uuid
