from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import RedirectResponse, FileResponse
from starlette.background import BackgroundTask
import os
from fastapi.templating import Jinja2Templates
from ..database import connect
from ..book_manager import add_book
from ..ocr_service import extract_page
from ..ocr_worker import start, pause, active, recover_stale
from ..search_service import highlight_text, count_matches, search_pages
from ..package_service import export_package
from ..export_service import make_json, make_docx, book_data
from fastapi.responses import FileResponse
templates=Jinja2Templates(directory="templates"); router=APIRouter()
@router.get("/books")
def books(request:Request):
    with connect() as db: rows=db.execute("SELECT * FROM books ORDER BY created_at DESC").fetchall()
    return templates.TemplateResponse(request=request, name="books.html", context={"books":rows})
@router.get("/books/new")
def upload(request:Request): return templates.TemplateResponse(request=request, name="upload.html", context={"error":None})
@router.post("/books/new")
def upload_post(request:Request, file:UploadFile=File(...), title:str=Form("")):
    try: uid=add_book(file,title); return RedirectResponse(f"/books/{uid}",303)
    except ValueError as e: return templates.TemplateResponse(request=request, name="upload.html", context={"error":str(e)},status_code=400)
@router.get("/books/{uid}")
def detail(request:Request,uid:str):
    return render_detail(request, uid)
@router.post("/books/{uid}/ocr")
def ocr(request:Request,uid:str,page_number:int=Form(...)):
    with connect() as db: book=db.execute("SELECT id FROM books WHERE book_uuid=?",(uid,)).fetchone()
    if book:
        try: extract_page(book['id'],page_number)
        except ValueError as error:
            return render_detail(request,uid,error=str(error))
    return render_detail(request,uid,success='تم استخراج الصفحة بنجاح')
@router.get('/books/{uid}/ocr/status')
def ocr_status(uid:str):
    with connect() as db:
        book=db.execute('SELECT id,page_count FROM books WHERE book_uuid=?',(uid,)).fetchone()
        rows=db.execute('SELECT status,COUNT(*) count FROM book_pages WHERE book_id=? GROUP BY status',(book['id'],)).fetchall()
    return {'total':book['page_count'],'counts':{r['status']:r['count'] for r in rows},'active':active(book['id'])}

def render_detail(request:Request,uid:str,error=None,success=None):
    with connect() as db:
        book=db.execute("SELECT * FROM books WHERE book_uuid=?",(uid,)).fetchone()
        stats=db.execute("SELECT status,COUNT(*) count FROM book_pages WHERE book_id=? GROUP BY status",(book['id'],)).fetchall() if book else []
        pages=db.execute("SELECT * FROM book_pages WHERE book_id=? ORDER BY page_number",(book['id'],)).fetchall() if book else []
    return templates.TemplateResponse(request=request,name="book_detail.html",context={"book":book,"counts":{r['status']:r['count'] for r in stats},"pages":pages,"error":error,"success":success,"active":active(book['id']) if book else False})

@router.post("/books/{uid}/ocr/start")
def start_ocr(request:Request,uid:str):
    recover_stale()
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
@router.get("/books/{uid}/pages")
def pages(request:Request,uid:str,status:str='all'):
    with connect() as db:
        book=db.execute("SELECT * FROM books WHERE book_uuid=?",(uid,)).fetchone()
        query="SELECT * FROM book_pages WHERE book_id=?"; args=[book['id']]
        if status in ('completed','failed','pending'): query += " AND status=?"; args.append(status)
        rows=db.execute(query+" ORDER BY page_number",args).fetchall()
    return templates.TemplateResponse(request=request,name="pages.html",context={"book":book,"pages":rows,"status":status})
@router.get("/books/{uid}/pages/{page_number}")
def page_detail(request:Request,uid:str,page_number:int,q:str='',mode:str='exact',book_id:str|None=None):
    with connect() as db:
        book=db.execute("SELECT * FROM books WHERE book_uuid=?",(uid,)).fetchone(); page=db.execute("SELECT * FROM book_pages WHERE book_id=? AND page_number=?",(book['id'],page_number)).fetchone()
    with connect() as db: settings={r['key']:r['value'] for r in db.execute('SELECT * FROM settings')}
    result_pages=search_pages(q,mode,int(book_id) if book_id and book_id!='all' else None,10000,0) if q else []
    ids=[(r['book_uuid'],r['page_number']) for r in result_pages]; current=(uid,page_number); pos=ids.index(current) if current in ids else -1
    prev_result=ids[pos-1] if pos>0 else None; next_result=ids[pos+1] if pos>=0 and pos+1<len(ids) else None
    return templates.TemplateResponse(request=request,name="page_detail.html",context={"book":book,"page":page,"q":q,"mode":mode,"book_id":book_id or 'all',"highlighted":highlight_text(page['extracted_text'],q,mode) if page and q else (page['extracted_text'] if page else ''),"matches":count_matches(page['extracted_text'],q,mode) if page and q else 0,"settings":settings,"prev_result":prev_result,"next_result":next_result,"next_href":f'/books/{next_result[0]}/pages/{next_result[1]}' if next_result else '#'})
@router.get('/books/{uid}/reader')
def reader(request:Request,uid:str,page:int=1): return page_detail(request,uid,page)
@router.get('/books/{uid}/export/json')
def export_json(uid:str):
    path,name=make_json(uid); return FileResponse(path,media_type='application/json',filename=name,background=BackgroundTask(os.unlink,path))
@router.get('/books/{uid}/export/docx')
def export_docx(uid:str):
    path,name=make_docx(uid); return FileResponse(path,media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',filename=name,background=BackgroundTask(os.unlink,path))
@router.get('/books/{uid}/export/package')
def export_package_route(uid:str):
    path,name=export_package(uid); return FileResponse(path,media_type='application/zip',filename=name,background=BackgroundTask(os.unlink,path))
@router.get('/books/{uid}/download/pdf')
def download_pdf(uid:str):
    with connect() as db: book=db.execute('SELECT file_path,original_filename FROM books WHERE book_uuid=?',(uid,)).fetchone()
    return FileResponse(book['file_path'],media_type='application/pdf',filename=book['original_filename'])
@router.get("/books/{uid}/view")
def view(request:Request,uid:str,page:int=1):
    with connect() as db: book=db.execute("SELECT * FROM books WHERE book_uuid=?",(uid,)).fetchone()
    return templates.TemplateResponse(request=request, name="viewer.html", context={"book":book,"page":page})
@router.get("/books/{uid}/file")
def file(uid:str):
    with connect() as db: book=db.execute("SELECT file_path FROM books WHERE book_uuid=?",(uid,)).fetchone()
    return FileResponse(book["file_path"],media_type="application/pdf")
@router.post('/books/{uid}/delete')
def delete_book(uid:str):
    with connect() as db: book=db.execute('SELECT id,file_path FROM books WHERE book_uuid=?',(uid,)).fetchone()
    if not book: return RedirectResponse('/books',303)
    pause(book['id'])
    with connect() as db:
        db.execute('BEGIN'); db.execute('DELETE FROM page_search WHERE page_id IN (SELECT id FROM book_pages WHERE book_id=?)',(book['id'],)); db.execute('DELETE FROM book_pages WHERE book_id=?',(book['id'],)); db.execute('DELETE FROM books WHERE id=?',(book['id'],)); db.commit()
    from pathlib import Path
    Path(book['file_path']).unlink(missing_ok=True)
    return RedirectResponse('/books?message=تم+حذف+الكتاب+بنجاح',303)
