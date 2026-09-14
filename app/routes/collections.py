"""Local collection management; all volumes remain ordinary books."""
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from ..database import connect
from ..ui import templates

router = APIRouter()

def require_collection(db, uid):
    row = db.execute('SELECT * FROM collections WHERE uuid=?', (uid,)).fetchone()
    if row is None:
        raise HTTPException(404, 'Collection not found')
    return row

def clean_title(title):
    title = title.strip()
    if not title or len(title) > 500:
        raise HTTPException(400, 'Collection title must contain 1–500 characters')
    return title

@router.post('/collections')
def create(title: str = Form(...)):
    uid = str(uuid4())
    with connect() as db:
        db.execute('INSERT INTO collections(uuid,title,created_at) VALUES(?,?,?)',
                   (uid, clean_title(title), datetime.now(timezone.utc).isoformat()))
    return RedirectResponse(f'/collections/{uid}', 303)

@router.get('/collections/{uid}')
def detail(request: Request, uid: str):
    return render_detail(request, uid)

def render_detail(request, uid, error=None, status_code=200):
    with connect() as db:
        collection = require_collection(db, uid)
        books = db.execute('SELECT * FROM books WHERE collection_id=? ORDER BY volume_number IS NULL,volume_number,id', (collection['id'],)).fetchall()
        available = db.execute('SELECT book_uuid,title FROM books WHERE collection_id IS NULL ORDER BY title,id').fetchall()
    return templates.TemplateResponse(request=request, name='collection_detail.html',
        context={'collection': collection, 'books': books, 'available': available, 'error': error}, status_code=status_code)

@router.post('/collections/{uid}/rename')
def rename(uid: str, title: str = Form(...)):
    with connect() as db:
        require_collection(db, uid)
        db.execute('UPDATE collections SET title=? WHERE uuid=?', (clean_title(title), uid))
    return RedirectResponse(f'/collections/{uid}', 303)

@router.post('/collections/{uid}/delete')
def delete(request: Request, uid: str):
    try:
        with connect() as db:
            require_collection(db, uid)
            db.execute('DELETE FROM collections WHERE uuid=?', (uid,))
    except sqlite3.IntegrityError:
        return render_detail(request, uid, error='collection_not_empty', status_code=409)
    return RedirectResponse('/books', 303)

@router.post('/books/{book_uid}/collection')
def assign(book_uid: str, collection_id: str = Form(''), volume_number: int | None = Form(None)):
    if volume_number is not None and not 1 <= volume_number <= 2147483647:
        raise HTTPException(400, 'Volume number must be between 1 and 2147483647')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        book = db.execute('SELECT id FROM books WHERE book_uuid=?', (book_uid,)).fetchone()
        if book is None:
            raise HTTPException(404, 'Book not found')
        collection = require_collection(db, collection_id) if collection_id else None
        db.execute('UPDATE books SET collection_id=?,volume_number=? WHERE id=?',
                   (collection['id'] if collection else None, volume_number if collection else None, book['id']))
    return RedirectResponse(f"/collections/{collection['uuid']}" if collection else f'/books/{book_uid}', 303)

@router.post('/collections/{uid}/add')
def add(uid: str, book_uid: str = Form(...), volume_number: int | None = Form(None)):
    return assign(book_uid, uid, volume_number)
