import hashlib
import json
import tempfile
import zipfile
import uuid
import shutil
from pathlib import Path, PureWindowsPath
from datetime import datetime
import pymupdf
from .database import connect
from .search_service import normalize_arabic
from .export_service import filename

MAX_PDF_BYTES = 2 * 1024**3
MAX_TEXT_BYTES = 256 * 1024**2
MAX_COLLECTION_BOOKS = 1000

def digest_file(path):
    with open(path, 'rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()

def export_package(uid):
    with connect() as db:
        book = db.execute('SELECT * FROM books WHERE book_uuid=?', (uid,)).fetchone()
        if not book: raise ValueError('Book not found')
        pages = db.execute('SELECT * FROM book_pages WHERE book_id=? ORDER BY page_number', (book['id'],)).fetchall()
    if len(pages) != book['page_count'] or any(p['status'] != 'completed' or p['extracted_text'] is None for p in pages):
        raise ValueError('Complete every page before exporting a portable book.')
    pdf = Path(book['file_path'])
    manifest = {'format':'Book-OCR-Package','format_version':1,'book_uuid':book['book_uuid'],
                'title':book['title'],'original_filename':PureWindowsPath(book['original_filename']).name,
                'page_count':book['page_count'],'sha256':digest_file(pdf),'created_at':book['created_at']}
    data = [{'page_number':p['page_number'],'status':'completed','extracted_text':p['extracted_text'],
             'line_count':p['line_count'],'model':p['model'],'thinking_level':p['thinking_level']} for p in pages]
    with tempfile.NamedTemporaryFile(suffix='.bookocr.zip', delete=False) as temp: path = temp.name
    try:
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
            archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,separators=(',',':')))
            archive.writestr('pages.json',json.dumps(data,ensure_ascii=False,separators=(',',':')))
            archive.write(pdf,'original.pdf')
        return path,filename(book['title'],'.bookocr.zip')
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise

def import_package(upload):
    from .book_manager import BOOKS
    target = None
    committed = False
    try:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)/'original.pdf'
            with zipfile.ZipFile(upload,'r') as archive:
                infos = archive.infolist()
                # An exact allowlist rejects traversal, drive paths, duplicates and hidden extras.
                if len(infos) != 3 or {i.filename for i in infos} != {'manifest.json','pages.json','original.pdf'}:
                    raise ValueError('Invalid package members')
                for info in infos:
                    maximum = MAX_PDF_BYTES if info.filename == 'original.pdf' else MAX_TEXT_BYTES if info.filename == 'pages.json' else 1024**2
                    if info.file_size > maximum or info.flag_bits & 1 or (info.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError('Unsupported or oversized package member')
                manifest = json.loads(archive.read('manifest.json'))
                pages = json.loads(archive.read('pages.json'))
                with archive.open('original.pdf') as incoming, source.open('wb') as out:
                    shutil.copyfileobj(incoming,out)
            if not isinstance(manifest,dict) or manifest.get('format') != 'Book-OCR-Package' or type(manifest.get('format_version')) is not int or manifest['format_version'] != 1:
                raise ValueError('Unsupported package format or version')
            uid = str(uuid.UUID(manifest['book_uuid']))
            if uid != manifest['book_uuid']: raise ValueError('Invalid book identifier')
            count = manifest.get('page_count')
            if type(count) is not int or not 1 <= count <= 100000: raise ValueError('Invalid page count')
            if not isinstance(pages,list) or len(pages) != count: raise ValueError('Invalid page count')
            for number,page in enumerate(pages,1):
                if not isinstance(page,dict) or type(page.get('page_number')) is not int or page['page_number'] != number or page.get('status') != 'completed' or not isinstance(page.get('extracted_text'),str):
                    raise ValueError('Invalid page order, status or text')
                if any(page.get(k) is not None and not isinstance(page[k],str) for k in ('model','thinking_level')):
                    raise ValueError('Invalid page metadata')
            if not isinstance(manifest.get('title'),str) or not manifest['title'].strip(): raise ValueError('Invalid book title')
            original = manifest.get('original_filename')
            if not isinstance(original,str) or not original or PureWindowsPath(original).name != original or '/' in original:
                raise ValueError('Invalid original filename')
            digest = digest_file(source)
            if digest != manifest.get('sha256'): raise ValueError('PDF hash validation failed')
            from .ocr_service import _render_lock
            with _render_lock, pymupdf.open(source) as pdf:
                if pdf.needs_pass or len(pdf) != count: raise ValueError('PDF page count mismatch or encrypted PDF')
            BOOKS.mkdir(parents=True,exist_ok=True)
            now = datetime.now().isoformat()
            with connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT 1 FROM books WHERE file_hash=? OR book_uuid=?',(digest,uid)).fetchone():
                    raise ValueError('This book already exists')
                target = BOOKS/(uid + '_' + uuid.uuid4().hex + '.pdf')
                with source.open('rb') as incoming, target.open('xb') as out: shutil.copyfileobj(incoming,out)
                book_id = db.execute('INSERT INTO books(book_uuid,title,original_filename,stored_filename,file_path,file_hash,page_count,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)', (uid,manifest['title'],original,target.name,str(target),digest,count,'completed',now,now)).lastrowid
                for page in pages:
                    text = page['extracted_text']
                    page_id = db.execute("INSERT INTO book_pages(book_id,page_number,status,extracted_text,line_count,model,thinking_level,created_at,updated_at) VALUES(?,?,'completed',?,?,?,?,?,?)", (book_id,page['page_number'],text,len(text.splitlines()),page.get('model'),page.get('thinking_level'),now,now)).lastrowid
                    db.execute('INSERT INTO page_search VALUES(?,?,?)',(page_id,text,normalize_arabic(text)))
            committed = True
            return uid
    except (ValueError,KeyError,TypeError,zipfile.BadZipFile,UnicodeError,RuntimeError) as exc:
        raise ValueError('Invalid or damaged Book-OCR package. No book was imported.') from None
    finally:
        if target is not None and not committed: target.unlink(missing_ok=True)


def _complete_pages(book_id, page_count):
    with connect() as db:
        pages = db.execute('SELECT * FROM book_pages WHERE book_id=? ORDER BY page_number', (book_id,)).fetchall()
    if len(pages) != page_count or any(p['status'] != 'completed' or p['extracted_text'] is None for p in pages):
        raise ValueError('Every volume must be fully completed before a collection can be exported.')
    return pages


def _book_members(book, pages):
    manifest = {'format':'Book-OCR-Package','format_version':1,'book_uuid':book['book_uuid'],
                'title':book['title'],'original_filename':PureWindowsPath(book['original_filename']).name,
                'page_count':book['page_count'],'sha256':digest_file(Path(book['file_path'])),'created_at':book['created_at']}
    page_data = [{'page_number':p['page_number'],'status':'completed','extracted_text':p['extracted_text'],
                  'line_count':p['line_count'],'model':p['model'],'thinking_level':p['thinking_level']} for p in pages]
    return manifest, page_data


def export_collection_package(collection_uuid):
    with connect() as db:
        collection = db.execute('SELECT * FROM collections WHERE uuid=?', (collection_uuid,)).fetchone()
        if not collection: raise ValueError('Collection not found')
        books = db.execute('SELECT * FROM books WHERE collection_id=? ORDER BY volume_number IS NULL,volume_number,id', (collection['id'],)).fetchall()
    if not books: raise ValueError('A collection needs at least one completed volume before export.')
    members = []
    for book in books:
        pages = _complete_pages(book['id'], book['page_count'])
        manifest, page_data = _book_members(book, pages)
        members.append((book, manifest, page_data))
    with tempfile.NamedTemporaryFile(suffix='.bookocr-collection.zip', delete=False) as temp: path = temp.name
    try:
        metadata = {'uuid':collection['uuid'],'title':collection['title'],'created_at':collection['created_at'],
                    'books':[{'book_uuid':book['book_uuid'],'volume_number':book['volume_number']} for book,_,_ in members]}
        top = {'format':'Book-OCR-Collection','format_version':1,'collection_uuid':collection['uuid'],'member_count':len(members)}
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            archive.writestr('manifest.json', json.dumps(top, ensure_ascii=False, separators=(',',':')))
            archive.writestr('collection.json', json.dumps(metadata, ensure_ascii=False, separators=(',',':')))
            for book, manifest, pages in members:
                prefix = f"books/{book['book_uuid']}/"
                archive.writestr(prefix+'manifest.json', json.dumps(manifest, ensure_ascii=False, separators=(',',':')))
                archive.writestr(prefix+'pages.json', json.dumps(pages, ensure_ascii=False, separators=(',',':')))
                archive.write(book['file_path'], prefix+'original.pdf')
        return path, filename(collection['title'], '.bookocr-collection.zip')
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise


def _uuid(value, label):
    try:
        parsed = str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f'Invalid {label}') from None
    if parsed != value: raise ValueError(f'Invalid {label}')
    return parsed


def _validate_collection_book(manifest, pages, pdf, expected_uuid):
    if not isinstance(manifest,dict) or manifest.get('format') != 'Book-OCR-Package' or manifest.get('format_version') != 1:
        raise ValueError('Invalid member book manifest')
    uid = _uuid(manifest.get('book_uuid'), 'book identifier')
    if uid != expected_uuid: raise ValueError('Collection member identifier mismatch')
    count = manifest.get('page_count')
    if type(count) is not int or not 1 <= count <= 100000: raise ValueError('Invalid member page count')
    if not isinstance(manifest.get('title'), str) or not manifest['title'].strip(): raise ValueError('Invalid member title')
    original = manifest.get('original_filename')
    if not isinstance(original,str) or not original or PureWindowsPath(original).name != original or '/' in original: raise ValueError('Invalid original filename')
    if not isinstance(pages,list) or len(pages) != count: raise ValueError('Invalid member pages')
    for number, page in enumerate(pages, 1):
        if not isinstance(page,dict) or page.get('page_number') != number or page.get('status') != 'completed' or not isinstance(page.get('extracted_text'),str):
            raise ValueError('Collection packages require complete ordered OCR pages')
        if any(page.get(k) is not None and not isinstance(page[k],str) for k in ('model','thinking_level')): raise ValueError('Invalid page metadata')
    if hashlib.sha256(pdf).hexdigest() != manifest.get('sha256'): raise ValueError('PDF hash validation failed')
    with pymupdf.open(stream=pdf, filetype='pdf') as document:
        if document.needs_pass or len(document) != count: raise ValueError('PDF page count mismatch or encrypted PDF')
    return uid, count, original


def import_collection_package(upload):
    """Validate the complete archive first, then atomically create collection and volumes."""
    created = []
    try:
        with zipfile.ZipFile(upload, 'r') as archive:
            infos = archive.infolist(); names = [info.filename for info in infos]
            if len(names) != len(set(names)) or any(name.startswith('/') or '\\' in name or '..' in PureWindowsPath(name).parts for name in names): raise ValueError('Invalid archive paths')
            if any(info.flag_bits & 1 or (info.external_attr >> 16) & 0o170000 == 0o120000 for info in infos): raise ValueError('Unsupported archive member')
            if any(info.file_size > (MAX_PDF_BYTES if info.filename.endswith('original.pdf') else MAX_TEXT_BYTES) for info in infos): raise ValueError('Oversized archive member')
            top = json.loads(archive.read('manifest.json')); collection = json.loads(archive.read('collection.json'))
            if not isinstance(top,dict) or top.get('format') != 'Book-OCR-Collection' or top.get('format_version') != 1: raise ValueError('Unsupported collection package')
            collection_uuid = _uuid(top.get('collection_uuid'), 'collection identifier')
            if not isinstance(collection,dict) or _uuid(collection.get('uuid'), 'collection identifier') != collection_uuid: raise ValueError('Invalid collection metadata')
            members = collection.get('books')
            if not isinstance(members,list) or not 1 <= len(members) <= MAX_COLLECTION_BOOKS or top.get('member_count') != len(members): raise ValueError('Invalid collection members')
            if not isinstance(collection.get('title'),str) or not collection['title'].strip() or len(collection['title']) > 500: raise ValueError('Invalid collection title')
            expected = {'manifest.json','collection.json'}; validated = []
            for member in members:
                uid = _uuid(member.get('book_uuid') if isinstance(member,dict) else None, 'book identifier')
                volume = member.get('volume_number')
                if volume is not None and (type(volume) is not int or not 1 <= volume <= 2147483647): raise ValueError('Invalid volume number')
                prefix = f'books/{uid}/'; expected.update({prefix+'manifest.json',prefix+'pages.json',prefix+'original.pdf'})
                manifest = json.loads(archive.read(prefix+'manifest.json')); pages = json.loads(archive.read(prefix+'pages.json')); pdf = archive.read(prefix+'original.pdf')
                if len(pdf) > MAX_PDF_BYTES: raise ValueError('Oversized PDF')
                _, count, original = _validate_collection_book(manifest, pages, pdf, uid)
                validated.append((uid, volume, manifest, pages, pdf, count, original))
            if set(names) != expected: raise ValueError('Invalid or incomplete collection archive structure')
        if len({item[0] for item in validated}) != len(validated): raise ValueError('Duplicate collection member')
        from .book_manager import BOOKS
        BOOKS.mkdir(parents=True, exist_ok=True)
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM collections WHERE uuid=?',(collection_uuid,)).fetchone(): raise ValueError('Collection already exists')
            if any(db.execute('SELECT 1 FROM books WHERE book_uuid=? OR file_hash=?',(uid,hashlib.sha256(pdf).hexdigest())).fetchone() for uid,_,_,_,pdf,_,_ in validated): raise ValueError('A collection book already exists')
            collection_id = db.execute('INSERT INTO collections(uuid,title,created_at) VALUES(?,?,?)',(collection_uuid,collection['title'],collection.get('created_at') or datetime.now().isoformat())).lastrowid
            for uid, volume, manifest, pages, pdf, count, original in validated:
                target = BOOKS / f'{uid}_{uuid.uuid4().hex}.pdf'
                target.write_bytes(pdf); created.append(target)
                now = datetime.now().isoformat()
                book_id = db.execute('INSERT INTO books(book_uuid,title,original_filename,stored_filename,file_path,file_hash,page_count,status,created_at,updated_at,collection_id,volume_number) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (uid,manifest['title'],original,target.name,str(target),hashlib.sha256(pdf).hexdigest(),count,'completed',manifest.get('created_at') or now,now,collection_id,volume)).lastrowid
                for page in pages:
                    text=page['extracted_text']; page_id=db.execute("INSERT INTO book_pages(book_id,page_number,status,extracted_text,line_count,model,thinking_level,created_at,updated_at) VALUES(?,?,'completed',?,?,?,?,?,?)",(book_id,page['page_number'],text,len(text.splitlines()),page.get('model'),page.get('thinking_level'),now,now)).lastrowid
                    db.execute('INSERT INTO page_search VALUES(?,?,?)',(page_id,text,normalize_arabic(text)))
        return collection_uuid
    except (ValueError, KeyError, TypeError, zipfile.BadZipFile, UnicodeError, RuntimeError):
        for path in created: path.unlink(missing_ok=True)
        raise ValueError('Invalid or conflicting Book-OCR collection package. No collection was imported.') from None
