from fastapi import APIRouter,Request
from fastapi.templating import Jinja2Templates
templates=Jinja2Templates(directory="templates"); router=APIRouter()
@router.get("/search")
def search(request:Request): return templates.TemplateResponse(request=request, name="search.html", context={})
