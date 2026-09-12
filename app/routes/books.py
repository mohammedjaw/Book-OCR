from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from ..database import connect
from ..book_manager import add_book
from ..ocr_service import extract_page
templates=Jinja2Templates(directory="templates"); router=APIRouter()
@router.get("/books")
def books(request:Request):
    with connect() as db: rows=db.execute("SELECT * FROM books ORDER BY created_at DESC").fetchall()
    return templates.TemplateResponse(request=request, name="books.html", context={"books":rows})
@router.get("/books/new")
def upload(request:Request): return templates.TemplateResponse(request=request, name="upload.html", context={"error":None})
@router.post("/books/new")
def upload_post(request:Request, file:UploadFile=File(...)):
    try: uid=add_book(file); return RedirectResponse(f"/books/{uid}",303)
    except ValueError as e: return templates.TemplateResponse(request=request, name="upload.html", context={"error":str(e)},status_code=400)
@router.get("/books/{uid}")
def detail(request:Request,uid:str):
    with connect() as db:
        book=db.execute("SELECT * FROM books WHERE book_uuid=?",(uid,)).fetchone()
        stats=db.execute("SELECT status,COUNT(*) count FROM book_pages WHERE book_id=? GROUP BY status",(book['id'],)).fetchall() if book else []
        pages=db.execute("SELECT * FROM book_pages WHERE book_id=? ORDER BY page_number",(book['id'],)).fetchall() if book else []
    return templates.TemplateResponse(request=request, name="book_detail.html", context={"book":book,"counts":{r['status']:r['count'] for r in stats},"pages":pages,"error":None})
@router.post("/books/{uid}/ocr")
def ocr(request:Request,uid:str,page_number:int=Form(...)):
    with connect() as db: book=db.execute("SELECT id FROM books WHERE book_uuid=?",(uid,)).fetchone()
    if book:
        try: extract_page(book['id'],page_number)
        except ValueError: pass
    return detail(request,uid)
@router.get("/books/{uid}/view")
def view(request:Request,uid:str,page:int=1):
    with connect() as db: book=db.execute("SELECT * FROM books WHERE book_uuid=?",(uid,)).fetchone()
    return templates.TemplateResponse(request=request, name="viewer.html", context={"book":book,"page":page})
@router.get("/books/{uid}/file")
def file(uid:str):
    with connect() as db: book=db.execute("SELECT file_path FROM books WHERE book_uuid=?",(uid,)).fetchone()
    return FileResponse(book["file_path"],media_type="application/pdf")
