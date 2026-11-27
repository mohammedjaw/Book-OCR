import json, re, tempfile
from pathlib import Path
from .database import connect

def filename(title, ext):
    return re.sub(r'[<>:"/\\|?*]', '_', title).strip() + ext

def book_data(uid):
    with connect() as db:
        book=db.execute('SELECT * FROM books WHERE book_uuid=?',(uid,)).fetchone()
        pages=db.execute('SELECT * FROM book_pages WHERE book_id=? ORDER BY page_number',(book['id'],)).fetchall()
    return book,pages

def make_json(uid):
    book,pages=book_data(uid)
    data={'book':{'uuid':book['book_uuid'],'title':book['title'],'original_filename':book['original_filename'],'page_count':book['page_count']},'pages':[{'page_number':p['page_number'],'status':p['status'],'text':p['extracted_text'],'line_count':p['line_count'] or 0,'model':p['model'],'thinking_level':p['thinking_level'],'error_message':p['error_message']} for p in pages]}
    f=tempfile.NamedTemporaryFile(suffix='.json',delete=False); f.close(); Path(f.name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8'); return f.name,filename(book['title'],'.json')

def make_docx(uid):
    from docx import Document
    from docx.enum.text import WD_BREAK
    book,pages=book_data(uid); doc=Document(); doc.core_properties.title=book['title']
    for i,p in enumerate(pages):
        if i: doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        h=doc.add_heading(f"الصفحة {p['page_number']}",level=1); h.paragraph_format.alignment=2
        text=p['extracted_text'] if p['status']=='completed' and p['extracted_text'] is not None else '[فشل استخراج هذه الصفحة]'
        if p['status']=='failed' and p['error_message']: text += '\n'+p['error_message']
        para=doc.add_paragraph(); para.paragraph_format.alignment=2; para.add_run(text)
    f=tempfile.NamedTemporaryFile(suffix='.docx',delete=False); f.close(); doc.save(f.name); return f.name,filename(book['title'],'.docx')


def text_snapshot(uid, collection=False):
    """Materialize metadata and pages in one read-only SQLite transaction."""
    from fastapi import HTTPException
    with connect() as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        if collection:
            parent = db.execute('SELECT * FROM collections WHERE uuid=?', (uid,)).fetchone()
            if parent is None: raise HTTPException(404, 'Collection not found')
            books = db.execute('SELECT * FROM books WHERE collection_id=? ORDER BY volume_number IS NULL,volume_number,id', (parent['id'],)).fetchall()
        else:
            parent = db.execute('SELECT * FROM books WHERE book_uuid=?', (uid,)).fetchone()
            if parent is None: raise HTTPException(404, 'Book not found')
            books = [parent]
        volumes = []
        for book in books:
            rows = {p['page_number']: dict(p) for p in db.execute('SELECT page_number,status,extracted_text FROM book_pages WHERE book_id=? ORDER BY page_number', (book['id'],))}
            pages = [rows.get(n, {'page_number': n, 'status': 'missing', 'extracted_text': None}) for n in range(1, book['page_count'] + 1)]
            counts = {status: sum(p['status'] == status for p in pages) for status in ('completed','failed','pending','processing','missing')}
            counts['text_pages'] = sum(p['status'] == 'completed' and bool(p['extracted_text']) for p in pages)
            counts['text_missing'] = sum(p['status'] == 'completed' and p['extracted_text'] is None for p in pages)
            volumes.append((dict(book), pages, counts))
    if not any(c['text_pages'] for _, _, c in volumes):
        raise HTTPException(409, 'No successfully extracted text is available yet.')
    return parent['title'], volumes


def make_text(uid, ext, collection=False):
    from fastapi import HTTPException
    if ext not in ('md', 'txt'): raise HTTPException(404, 'Unknown text export format')
    title, volumes = text_snapshot(uid, collection)
    total = {key: sum(c[key] for _, _, c in volumes) for key in volumes[0][2]}
    incomplete = any(total[k] for k in ('failed','pending','processing','missing','text_missing'))
    chunks = [title, 'INCOMPLETE / غير مكتمل' if incomplete else 'Complete / مكتمل',
              '; '.join(f'{key}: {value}' for key, value in total.items() if key != 'text_pages')]
    for book, pages, counts in volumes:
        chunks.extend(['', f"Book: {book['title']} (volume: {book.get('volume_number')})",
                       '; '.join(f'{k}: {v}' for k,v in counts.items() if k != 'text_pages')])
        for page in pages:
            n, status, text = page['page_number'], page['status'], page['extracted_text']
            chunks.extend(['', f'## Page {n}' if ext == 'md' else f'Page {n}'])
            chunks.append(text if status == 'completed' and text is not None else f'[Page {n}: extraction status={status}; text unavailable / النص غير متاح]')
    # No stripping, normalization or escaping of original extracted text.
    with tempfile.NamedTemporaryFile(suffix='.' + ext, delete=False) as out:
        out.write('\n\n'.join(chunks).encode('utf-8'))
    return out.name, filename(title + (' - partial' if incomplete else ''), '.' + ext)
