from fastapi import APIRouter, Request
from ..database import connect
from fastapi.templating import Jinja2Templates
templates=Jinja2Templates(directory="templates"); router=APIRouter()
@router.get("/")
def home(request: Request):
    with connect() as db:
        stats=db.execute("SELECT COUNT(*) books, COALESCE(SUM(page_count),0) pages FROM books").fetchone()
        recent=db.execute("SELECT * FROM books ORDER BY created_at DESC LIMIT 5").fetchall()
    return templates.TemplateResponse(request=request, name="home.html", context={"stats":stats,"recent":recent})
