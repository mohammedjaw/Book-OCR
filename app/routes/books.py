from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import RedirectResponse, FileResponse
from starlette.background import BackgroundTask
import os
from fastapi.templating import Jinja2Templates
from ..database import connect
from ..book_manager import add_book
from ..ocr_service import extract_page
from ..ocr_worker import start, pause, active, state, rerender_failed_page, RETRYABLE, _lock as worker_lock
from ..search_service import highlight_text, count_matches, search_pages, parse_scope
from ..package_service import export_package
from ..export_service import make_json, make_docx, book_data
from fastapi.responses import FileResponse
from ..ui import templates; router=APIRouter()
@router.get("/books")
def books(request:Request):
    with connect() as db:
        rows=db.execute("SELECT * FROM books WHERE collection_id IS NULL ORDER BY created_at DESC").fetchall()
        collections=db.execute('SELECT c.*,COUNT(b.id) volume_count,COALESCE(SUM(b.page_count),0) page_count FROM collections c LEFT JOIN books b ON b.collection_id=c.id GROUP BY c.id ORDER BY c.created_at DESC,c.id DESC').fetchall()
    return templates.TemplateResponse(request=request, name="books.html", context={"books":rows,"collections":collections})
@router.get("/books/new")
def upload(request:Request): return templates.TemplateResponse(request=request, name="upload.html", context={"error":None})
@router.post("/books/new")
def upload_post(request:Request, file:UploadFile=File(...), title:str=Form("")):
    try: uid=add_book(file,title); return RedirectResponse(f"/books/{uid}",303)
    except ValueError as e: return templates.TemplateResponse(request=request, name="upload.html", context={"error":str(e)},status_code=400)
@router.get("/books/{uid}")
def detail(request:Request,uid:str):
    return render_detail(request, uid)
def require_book(uid):
    with connect() as db: book = db.execute('SELECT * FROM books WHERE book_uuid=?',(uid,)).fetchone()
    if not book: raise HTTPException(404, 'Book not found')
    return book

@router.post("/books/{uid}/ocr")
def ocr(request:Request,uid:str,page_number:int=Form(...)):
    book = require_book(uid)
    if not 1 <= page_number <= book['page_count']: raise HTTPException(404, 'Page not found')
    start(book['id'], page_number=page_number)
    return RedirectResponse(f'/books/{uid}',303)

@router.get('/books/{uid}/ocr/status')
def ocr_status(uid:str):
    book = require_book(uid)
    with connect() as db:
        rows = db.execute('SELECT status,COUNT(*) count FROM book_pages WHERE book_id=? GROUP BY status',(book['id'],)).fetchall()
        eligible = db.execute(f"SELECT COUNT(*) FROM book_pages WHERE book_id=? AND status='failed' AND {RETRYABLE}",(book['id'],)).fetchone()[0]
    counts = dict.fromkeys(('completed','pending','processing','failed'),0)
    counts.update({r['status']:r['count'] for r in rows})
    live_state = state(book['id'])
    current = live_state or ('completed' if counts['completed'] == book['page_count'] else book['status'])
    if current not in ('running','pausing','paused','completed','keys_unavailable','application_error'): current = 'stopped'
    return {'total':book['page_count'], 'counts':counts, 'active':live_state is not None,
            'state':current, 'retryable_failed':eligible, 'complete':counts['completed']==book['page_count']}

def render_detail(request:Request,uid:str,error=None,success=None):
    require_book(uid)
    with connect() as db:
        book=db.execute("SELECT * FROM books WHERE book_uuid=?",(uid,)).fetchone()
        stats=db.execute("SELECT status,COUNT(*) count FROM book_pages WHERE book_id=? GROUP BY status",(book['id'],)).fetchall() if book else []
        collections=db.execute('SELECT * FROM collections ORDER BY title,id').fetchall()
    return templates.TemplateResponse(request=request,name="book_detail.html",context={"book":book,"collections":collections,"counts":{r['status']:r['count'] for r in stats},"error":error,"success":success,"active":active(book['id']) if book else False})

@router.post("/books/{uid}/ocr/start")
def start_ocr(request:Request,uid:str):
    with connect() as db: book=db.execute("SELECT id FROM books WHERE book_uuid=?",(uid,)).fetchone()
    if book: start(book['id'])
    return RedirectResponse(f"/books/{uid}",303)
@router.post("/books/{uid}/ocr/pause")
def pause_ocr(uid:str):
    with connect() as db: book=db.execute("SELECT id FROM books WHERE book_uuid=?",(uid,)).fetchone()
    if book: pause(book['id'])
    return RedirectResponse(f"/books/{uid}",303)
@router.post("/books/{uid}/ocr/resume")
def resume_ocr(request:Request,uid:str): return start_ocr(request,uid)
@router.post("/books/{uid}/ocr/retry")
def retry_ocr(request:Request,uid:str):
    with connect() as db: book=db.execute("SELECT id FROM books WHERE book_uuid=?",(uid,)).fetchone()
    if book: start(book['id'],retry_failed=True)
    return RedirectResponse(f"/books/{uid}",303)
@router.post("/books/{uid}/pages/{page_number}/rerender-retry")
def rerender_retry(uid:str,page_number:int):
    book = require_book(uid)
    with connect() as db:
        page = db.execute("SELECT status FROM book_pages WHERE book_id=? AND page_number=?", (book['id'], page_number)).fetchone()
    if not page: raise HTTPException(404, 'Page not found')
    if page['status'] != 'failed': raise HTTPException(409, 'Only failed pages can be re-rendered')
    if not rerender_failed_page(book['id'], page_number): raise HTTPException(409, 'OCR is already active for this book')
    return RedirectResponse(f"/books/{uid}/pages/{page_number}",303)
@router.get("/books/{uid}/pages")
def pages(request:Request,uid:str,status:str='all'):
    require_book(uid)
    with connect() as db:
        book=db.execute("SELECT * FROM books WHERE book_uuid=?",(uid,)).fetchone()
        query="SELECT page_number,status,line_count,error_message,error_kind FROM book_pages WHERE book_id=?"; args=[book['id']]
        if status in ('completed','failed','pending','processing'): query += " AND status=?"; args.append(status)
        rows=db.execute(query+" ORDER BY page_number",args).fetchall()
    return templates.TemplateResponse(request=request,name="pages.html",context={"book":book,"pages":rows,"status":status})
@router.get("/books/{uid}/pages/{page_number}")
def page_detail(request:Request,uid:str,page_number:int,q:str='',mode:str='exact',book_id:str|None=None):
    require_book(uid)
    with connect() as db:
        book=db.execute("SELECT * FROM books WHERE book_uuid=?",(uid,)).fetchone(); page=db.execute("SELECT * FROM book_pages WHERE book_id=? AND page_number=?",(book['id'],page_number)).fetchone()
    if not page: raise HTTPException(404, 'Page not found')
    with connect() as db: settings={r['key']:r['value'] for r in db.execute('SELECT * FROM settings')}
    with connect() as db: word_ready = db.execute("SELECT COUNT(*)=b.page_count FROM book_pages p JOIN books b ON b.id=p.book_id WHERE b.id=? AND p.status='completed' AND p.extracted_text IS NOT NULL", (book['id'],)).fetchone()[0]
    selected_book, selected_collection = parse_scope(book_id)
    result_pages=search_pages(q,mode,selected_book,10000,0,identifiers_only=True,collection_id=selected_collection) if q else []
    ids=[(r['book_uuid'],r['page_number']) for r in result_pages]; current=(uid,page_number); pos=ids.index(current) if current in ids else -1
    prev_result=ids[pos-1] if pos>0 else None; next_result=ids[pos+1] if pos>=0 and pos+1<len(ids) else None
    return templates.TemplateResponse(request=request,name="page_detail.html",context={"book":book,"page":page,"q":q,"mode":mode,"book_id":book_id or 'all',"highlighted":highlight_text(page['extracted_text'],q,mode) if page and q else (page['extracted_text'] if page else ''),"matches":count_matches(page['extracted_text'],q,mode) if page and q else 0,"settings":settings,"word_ready":bool(word_ready),"prev_result":prev_result,"next_result":next_result,"next_href":f'/books/{next_result[0]}/pages/{next_result[1]}' if next_result else '#'})
@router.get('/books/{uid}/reader')
def reader(request:Request,uid:str,page:int=1): return page_detail(request,uid,page)
@router.get('/books/{uid}/export/json')
def export_json(uid:str):
    ensure_complete(uid)
    path,name=make_json(uid); return FileResponse(path,media_type='application/json',filename=name,background=BackgroundTask(os.unlink,path))
@router.get('/books/{uid}/export/docx')
def export_docx(uid:str):
    ensure_complete(uid)
    path,name=make_docx(uid); return FileResponse(path,media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',filename=name,background=BackgroundTask(os.unlink,path))
@router.get('/books/{uid}/export/package')
def export_package_route(uid:str):
    ensure_complete(uid); path,name=export_package(uid); return FileResponse(path,media_type='application/zip',filename=name,background=BackgroundTask(os.unlink,path))
def ensure_complete(uid):
    with connect() as db: row=db.execute("SELECT b.page_count,COALESCE(SUM(p.status='completed'),0) completed,COALESCE(SUM(p.status!='completed'),0) unfinished FROM books b LEFT JOIN book_pages p ON p.book_id=b.id WHERE b.book_uuid=? GROUP BY b.id",(uid,)).fetchone()
    if not row or row['completed']!=row['page_count'] or row['unfinished']: raise HTTPException(409,'خيارات التصدير متاحة بعد اكتمال استخراج جميع صفحات الكتاب بنجاح.')
@router.get('/books/{uid}/download/pdf')
def download_pdf(uid:str):
    with connect() as db: book=db.execute('SELECT file_path,original_filename FROM books WHERE book_uuid=?',(uid,)).fetchone()
    if not book: raise HTTPException(404, 'Book not found')
    return FileResponse(book['file_path'],media_type='application/pdf',filename=book['original_filename'])
@router.get("/books/{uid}/view")
def view(request:Request,uid:str,page:int=1):
    book = require_book(uid)
    if not 1 <= page <= book["page_count"]: raise HTTPException(404,"Page not found")
    with connect() as db: book=db.execute("SELECT * FROM books WHERE book_uuid=?",(uid,)).fetchone()
    return templates.TemplateResponse(request=request, name="viewer.html", context={"book":book,"page":page})
@router.get("/books/{uid}/file")
def file(uid:str):
    with connect() as db: book=db.execute("SELECT file_path FROM books WHERE book_uuid=?",(uid,)).fetchone()
    if not book: raise HTTPException(404, "Book not found")
    return FileResponse(book["file_path"],media_type="application/pdf")
@router.get('/books/{uid}/text')
def full_text(request:Request,uid:str,page:int=1):
    book = require_book(uid)
    page = max(1,min(page,book['page_count']))
    with connect() as db:
        rows = db.execute('SELECT page_number,extracted_text,status FROM book_pages WHERE book_id=? AND page_number>=? ORDER BY page_number LIMIT 20',(book['id'],page)).fetchall()
    return templates.TemplateResponse(request=request,name='full_text.html',context={'book':book,'pages':rows,'start_page':page,'end_page':rows[-1]['page_number'] if rows else page})

@router.get('/books/{uid}/delete')
def confirm_delete(request:Request,uid:str):
    return templates.TemplateResponse(request=request,name='delete_book.html',context={'book':require_book(uid)})

@router.post('/books/{uid}/delete')
def delete_book(request:Request,uid:str,confirm:str=Form('')):
    from pathlib import Path
    from ..book_manager import BOOKS
    if confirm != uid: raise HTTPException(400,'Deletion confirmation required')
    # Holding the scheduler lock prevents a Start/Delete race; active jobs must drain first.
    with worker_lock:
        book = require_book(uid)
        if active(book['id']):
            pause(book['id'])
            return templates.TemplateResponse(request=request,name='delete_book.html',context={'book':book,'busy':True},status_code=409)
        target = Path(book['file_path']).resolve()
        root = BOOKS.resolve()
        if target.parent != root or target.suffix.lower() != '.pdf':
            raise HTTPException(409,'Book PDF path is outside managed storage; deletion refused.')
        with connect() as db:
            if any(Path(row[0]).resolve() == target for row in db.execute('SELECT file_path FROM books WHERE id!=?',(book['id'],))):
                raise HTTPException(409,'Another book references this PDF; deletion refused.')
        quarantine = target.with_name(target.name + '.deleting')
        if quarantine.exists(): raise HTTPException(409,'A previous deletion needs storage recovery.')
        moved = False
        try:
            if target.exists(): target.rename(quarantine); moved = True
            with connect() as db:
                db.execute('DELETE FROM page_search WHERE page_id IN (SELECT id FROM book_pages WHERE book_id=?)',(book['id'],))
                db.execute('DELETE FROM book_pages WHERE book_id=?',(book['id'],))
                db.execute('DELETE FROM books WHERE id=?',(book['id'],))
        except Exception:
            if moved: quarantine.rename(target)
            raise
        if moved: quarantine.unlink()
    return RedirectResponse('/books',303)
